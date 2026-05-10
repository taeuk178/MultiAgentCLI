"""문서를 청크로 분할.

문단(빈 줄로 구분) 및 markdown heading(`#`/`##`/`###`) 을 우선 분할 단위로 사용.
target token 범위 안에 들 때까지 인접 문단을 누적, 넘치면 다음 청크로 split.
overlap 은 token 단위로 마지막 ~10% 를 다음 청크 앞에 붙인다.

token 추정은 정확한 BPE 가 아니라 "공백 + CJK 문자 단위 휴리스틱" — 측정 인프라가
들어와 정확도 측정이 필요해지면 tokenizer 라이브러리를 도입한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator

# heading 1~6. line start 에서만 매치.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_BLANK_LINE_RE = re.compile(r"\n\s*\n")
_CJK_RE = re.compile(r"[㐀-鿿가-힯]")


def estimate_tokens(text: str) -> int:
    """간단 휴리스틱: ASCII 단어 1 토큰 + CJK 문자 1 글자 ≒ 1 토큰.

    실측 값보다 살짝 over-estimate 되는 경향이 있어, 청크가 너무 커지지 않게
    안전쪽으로 동작. 정확도 부족이 측정으로 드러나면 tokenizer 로 교체.
    """
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    non_cjk = _CJK_RE.sub(" ", text)
    words = len(non_cjk.split())
    return cjk + words


@dataclass
class ChunkSpec:
    """저장 직전의 청크 명세. embedding/context_prefix 는 다른 단계에서 채운다."""

    chunk_index: int
    section_path: str
    chunk_text: str
    raw_chunk_type: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class ChunkConfig:
    target_tokens: int = 600        # 300~800 권장 범위 중간값
    max_tokens: int = 1200          # hard cap — 단일 문단이 거대할 때 강제 split
    min_tokens: int = 80            # 너무 짧은 꼬리 청크는 직전 청크에 흡수
    overlap_ratio: float = 0.12     # 10~15% 사이


def _split_by_paragraph(text: str) -> list[str]:
    """빈 줄로 paragraph 분할. paragraph 첫 줄이 markdown heading 이면 그 줄을
    별도 paragraph 로 분리 — heading 직후 빈 줄이 없는 입력도 정상 인식.
    """
    parts = _BLANK_LINE_RE.split(text.strip())
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        first, sep, rest = p.partition("\n")
        if _HEADING_RE.match(first):
            out.append(first)
            if rest.strip():
                out.append(rest.strip())
        else:
            out.append(p)
    return out


def _hard_split(text: str, max_tokens: int) -> list[str]:
    """단일 문단이 max_tokens 를 넘으면 문장 단위 → 그래도 넘으면 길이 단위로 자른다."""
    if estimate_tokens(text) <= max_tokens:
        return [text]
    sentences = re.split(r"(?<=[.!?。！？])\s+|\n", text)
    out: list[str] = []
    buf: list[str] = []
    buf_tok = 0
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        st = estimate_tokens(s)
        if buf and buf_tok + st > max_tokens:
            out.append(" ".join(buf))
            buf, buf_tok = [], 0
        buf.append(s)
        buf_tok += st
    if buf:
        out.append(" ".join(buf))
    # 문장이 없는 경우 (코드 블록 등): 길이 단위 fallback.
    final: list[str] = []
    for chunk in out or [text]:
        if estimate_tokens(chunk) <= max_tokens:
            final.append(chunk)
            continue
        # max_tokens 가 단어/CJK 추정이라, 문자 수 기반으로 거칠게 자른다.
        approx_chars = max_tokens * 4
        i = 0
        while i < len(chunk):
            final.append(chunk[i : i + approx_chars])
            i += approx_chars
    return final


def _section_path_for(section_stack: list[str]) -> str:
    return " > ".join(section_stack) if section_stack else ""


def _take_overlap(text: str, ratio: float) -> str:
    """청크 끝부분 ratio 만큼을 단어 경계에서 잘라 다음 청크 prefix 로 사용."""
    if ratio <= 0:
        return ""
    total = estimate_tokens(text)
    target = max(1, int(total * ratio))
    # 단어 단위로 뒤에서 take.
    words = text.split()
    if not words:
        return ""
    acc: list[str] = []
    acc_tok = 0
    for w in reversed(words):
        wt = estimate_tokens(w)
        if acc_tok + wt > target and acc:
            break
        acc.append(w)
        acc_tok += wt
    acc.reverse()
    return " ".join(acc)


def split_document(text: str, config: ChunkConfig | None = None) -> Iterator[ChunkSpec]:
    """문서 raw_text 를 ChunkSpec 시퀀스로 분할.

    markdown heading 으로 section 트래킹, 문단 단위 누적, target_tokens 도달 시 emit.
    overlap 은 직전 청크 끝의 일부를 다음 청크 앞에 prepend.
    """
    cfg = config or ChunkConfig()
    section_stack: list[str] = []
    chunk_idx = 0
    buf_paragraphs: list[str] = []
    buf_tokens = 0
    pending_overlap = ""
    last_section_path = ""

    def flush() -> Iterator[ChunkSpec]:
        nonlocal chunk_idx, buf_paragraphs, buf_tokens, pending_overlap
        if not buf_paragraphs:
            return
        body = "\n\n".join(buf_paragraphs)
        full = f"{pending_overlap}\n\n{body}".strip() if pending_overlap else body
        yield ChunkSpec(
            chunk_index=chunk_idx,
            section_path=last_section_path,
            chunk_text=full,
        )
        chunk_idx += 1
        pending_overlap = _take_overlap(body, cfg.overlap_ratio)
        buf_paragraphs = []
        buf_tokens = 0

    for paragraph in _split_by_paragraph(text):
        # heading 처리: paragraph 가 단일 heading 라인이면 section_stack 갱신.
        m = _HEADING_RE.match(paragraph)
        if m and "\n" not in paragraph:
            # 이전 section 의 buf 를 먼저 flush — 새 section_path 로 잘못 태깅 방지.
            yield from flush()
            level = len(m.group(1))
            title = m.group(2).strip()
            section_stack = section_stack[: level - 1]
            section_stack.append(title)
            last_section_path = _section_path_for(section_stack)
            # heading 자체는 청크 본문에 포함하지 않고 다음 문단부터 새 section.
            continue

        # 단일 문단이 max 초과면 미리 hard split.
        for piece in _hard_split(paragraph, cfg.max_tokens):
            piece_tok = estimate_tokens(piece)
            if buf_tokens and buf_tokens + piece_tok > cfg.target_tokens:
                yield from flush()
            last_section_path = _section_path_for(section_stack)
            buf_paragraphs.append(piece)
            buf_tokens += piece_tok
            if buf_tokens >= cfg.target_tokens:
                yield from flush()

    # 꼬리 청크 — 너무 짧으면 직전 청크에 흡수하기 위해 호출자가 처리하기 어려우므로
    # 여기서는 그대로 emit. 호출자가 필요하면 후처리.
    if buf_paragraphs:
        if buf_tokens < cfg.min_tokens and chunk_idx > 0:
            # 마지막 청크와 합쳐서 재emit.
            tail = "\n\n".join(buf_paragraphs)
            yield ChunkSpec(
                chunk_index=chunk_idx,
                section_path=last_section_path,
                chunk_text=tail,
                extra={"short_tail": True},
            )
        else:
            yield from flush()
