"""쿼리 정규화 · chunk_type 매핑 · supersede 정규식 등 결정적 변환 헬퍼."""
from __future__ import annotations

import re
import unicodedata

# raw_chunk_type → normalized_chunk_type. 락인된 4-category 매핑.
RAW_TO_NORMALIZED: dict[str, str] = {
    "decision": "decision",
    "fix": "decision",
    "todo": "requirement",
    "spec": "requirement",
    "error": "discussion",
    "test_result": "discussion",
    "summary": "discussion",
    "note": "discussion",
    "message": "discussion",
    "thread": "discussion",
    "command": "code_note",
    "code_context": "code_note",
}

NORMALIZED_TYPES = ("requirement", "decision", "discussion", "code_note")


def normalize_chunk_type(raw: str | None) -> str | None:
    if not raw:
        return None
    return RAW_TO_NORMALIZED.get(raw.lower())


# 쿼리 정규화 — 소문자 + NFKC + 도메인 동의어. 형태소 분석은 도입 안 함.
_DOMAIN_SYNONYMS: list[tuple[str, str]] = [
    (r"클릭|탭|터치", "탭"),
    (r"버튼|button", "버튼"),
    (r"화면|screen|page", "화면"),
]


def normalize_query(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"\s+", " ", text).strip()
    for pat, rep in _DOMAIN_SYNONYMS:
        text = re.sub(pat, rep, text, flags=re.IGNORECASE)
    return text


def normalize_alias(text: str) -> str:
    """entity alias 비교용 정규화. 공백·특수문자 제거 + 소문자 + NFKC."""
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[\s\W_]+", "", text)


# supersede 자동 제안 정규식 1단계. 매칭되면 후보 제시만, 자동 적용 X.
_SUPERSEDE_RE = re.compile(
    r"("
    r"변경한다|대체한다|폐기|취소|업데이트|이제는|이제부터|롤백"
    r"|supersede|replace|deprecat\w*|cancel|now use|rollback"
    r")",
    re.IGNORECASE,
)


def detect_supersede_signal(text: str) -> str | None:
    """supersede 가능성을 시사하는 토큰을 반환. 없으면 None."""
    m = _SUPERSEDE_RE.search(text)
    return m.group(1) if m else None
