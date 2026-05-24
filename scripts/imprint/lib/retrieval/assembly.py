"""검색 결과를 host prompt context 형식으로 포매팅.

local: 7a 그대로 (chunk 중심).
feature: feature summary 서두 + chunk 근거 + drill-down + conflict.
global: project / document / feature summary 구조 + 대표 chunk + conflict 분리 섹션.

grounding 규칙: summary 만 단독 사용 금지 — 항상 1~3개 current chunk 근거 필수.
"""
from __future__ import annotations

from typing import Any

from .retrieve import RetrievalResult
from .routing import RoutedResult


def _short_list(value: Any, *, limit: int = 4) -> list[str]:
    if not isinstance(value, list):
        return []
    out = [str(v).strip() for v in value if str(v).strip()]
    return out[:limit]


def _metadata_detail_lines(metadata: dict[str, Any] | None, *, source_event_id: str | None = None) -> list[str]:
    if not isinstance(metadata, dict):
        metadata = {}
    lines: list[str] = []
    reason = str(metadata.get("reason") or "").strip()
    if reason:
        lines.append(f"   reason: {reason[:240]}")
    files = _short_list(metadata.get("files"))
    if files:
        lines.append(f"   files: {', '.join(files)}")
    symbols = _short_list(metadata.get("symbols"))
    if symbols:
        lines.append(f"   symbols: {', '.join(symbols)}")
    tests = _short_list(metadata.get("tests"))
    if tests:
        lines.append(f"   tests: {', '.join(tests)}")
    event_range = metadata.get("event_range")
    if isinstance(event_range, list) and len(event_range) >= 2:
        lines.append(f"   event_range: {event_range[0]}..{event_range[-1]}")
    elif source_event_id:
        lines.append(f"   source_event: {source_event_id}")
    if metadata.get("rolled") or metadata.get("rollup"):
        session_id = str(metadata.get("session_id") or "").strip()
        lines.append(f"   rollup: true{f' session={session_id}' if session_id else ''}")
    return lines


def _role_label(source_type: str | None, metadata: dict[str, Any] | None) -> str | None:
    if source_type == "manual_remember":
        return "canonical_memory"
    if isinstance(metadata, dict) and (metadata.get("rolled") or metadata.get("rollup")):
        return "rollup_evidence"
    return None


def _format_chunk_block(idx: int, *, source_type: str | None, section_path: str | None,
                       is_current: Any, source_updated_at: str | None, chunk_text: str,
                       metadata: dict[str, Any] | None = None,
                       source_event_id: str | None = None) -> list[str]:
    meta_bits: list[str] = []
    if source_type:
        meta_bits.append(f"source={source_type}")
    role = _role_label(source_type, metadata)
    if role:
        meta_bits.append(f"role={role}")
    if section_path:
        meta_bits.append(f"section={section_path}")
    meta_bits.append(f"current={'true' if is_current else 'false'}")
    if source_updated_at:
        meta_bits.append(f"updated={source_updated_at}")
    out = [f"{idx}. {' | '.join(meta_bits)}"]
    for body_line in chunk_text.splitlines():
        out.append(f"   {body_line}")
    out.extend(_metadata_detail_lines(metadata, source_event_id=source_event_id))
    return out


def format_for_claude(
    project_name: str,
    result: "RetrievalResult",
    *,
    instructions: str | None = None,
) -> str:
    """7a chunk-only retrieve 결과 포맷 (local 시나리오와 동일)."""
    lines: list[str] = []
    lines.append("[Project]")
    lines.append(f"프로젝트명: {project_name}")
    lines.append("")
    lines.append("[User Question]")
    lines.append(result.query)
    lines.append("")

    if result.resolved_entities:
        lines.append("[Resolved Entity]")
        for hit in result.resolved_entities:
            lines.append(
                f"canonical: {hit['canonical_name']} ({hit['entity_type']})"
                f" | matched alias: {hit['matched_alias']}"
            )
        lines.append("")

    query_context = [c for c in result.candidates if c.source_type == "working"]
    retrieved_context = [c for c in result.candidates if c.source_type != "working"]

    if query_context:
        lines.append("[Query Context]")
        for i, cand in enumerate(query_context, 1):
            lines.extend(_format_chunk_block(
                i, source_type=cand.source_type, section_path=cand.section_path,
                is_current=cand.is_current, source_updated_at=cand.source_updated_at,
                chunk_text=cand.chunk_text, metadata=cand.metadata,
                source_event_id=cand.source_event_id,
            ))
            lines.append("")

    lines.append("[Retrieved Context]")
    if not retrieved_context:
        lines.append("(검색 결과 없음)")
    for i, cand in enumerate(retrieved_context, 1):
        lines.extend(_format_chunk_block(
            i, source_type=cand.source_type, section_path=cand.section_path,
            is_current=cand.is_current, source_updated_at=cand.source_updated_at,
            chunk_text=cand.chunk_text, metadata=cand.metadata,
            source_event_id=cand.source_event_id,
        ))
        lines.append("")

    lines.append("[Instructions]")
    if instructions:
        lines.append(instructions)
    else:
        lines.append("- 현재 결정(current=true) 을 기준으로 답하세요.")
        lines.append("- 과거 결정은 변화를 설명할 때만 언급하세요.")
        lines.append("- 검색 결과 외 사실은 추론하지 말고 모른다고 답하세요.")
    return "\n".join(lines)


def format_routed_for_claude(
    project_name: str,
    result: "RoutedResult",
    *,
    instructions: str | None = None,
) -> str:
    """scope 별 포맷. summary + chunk grounding + conflict 표시."""
    lines: list[str] = []
    lines.append("[Project]")
    lines.append(f"프로젝트명: {project_name}")
    lines.append(f"scope={result.scope.scope} reason={result.scope.reason}")
    lines.append("")
    lines.append("[User Question]")
    lines.append(result.query)
    lines.append("")

    if result.resolved_entities:
        lines.append("[Resolved Entity]")
        for hit in result.resolved_entities:
            lines.append(
                f"canonical: {hit['canonical_name']} ({hit['entity_type']})"
                f" | matched alias: {hit['matched_alias']}"
            )
        lines.append("")

    if result.scope.scope == "global":
        # project → document → feature 순으로 분리 출력.
        for label in ("project", "document", "feature"):
            level_summaries = [s for s in result.summaries if s.level == label]
            if not level_summaries:
                continue
            lines.append(f"[{label.capitalize()} Summary]")
            for s in level_summaries:
                lines.append(f"- {s.target_key} (score={s.score:.4f})")
                for body_line in s.summary_text.splitlines():
                    lines.append(f"  {body_line}")
            lines.append("")
    elif result.scope.scope == "feature":
        if result.summaries:
            lines.append("[Feature Summary]")
            for s in result.summaries:
                lines.append(f"- {s.target_key} (score={s.score:.4f})")
                for body_line in s.summary_text.splitlines():
                    lines.append(f"  {body_line}")
            lines.append("")

    # grounding chunks — summary 별 drill-down + 본 검색 chunk 합쳐 보여줌.
    query_context = [c for c in result.chunks if c.source_type == "working"]
    chunks = [c for c in result.chunks if c.source_type != "working"]

    if query_context:
        lines.append("[Query Context]")
        for i, cand in enumerate(query_context, 1):
            lines.extend(_format_chunk_block(
                i, source_type=cand.source_type, section_path=cand.section_path,
                is_current=cand.is_current, source_updated_at=cand.source_updated_at,
                chunk_text=cand.chunk_text, metadata=cand.metadata,
                source_event_id=cand.source_event_id,
            ))
        lines.append("")

    if chunks or result.ground_chunks:
        lines.append("[Grounding Chunks]")
        i = 1
        for cand in chunks:
            lines.extend(_format_chunk_block(
                i, source_type=cand.source_type, section_path=cand.section_path,
                is_current=cand.is_current, source_updated_at=cand.source_updated_at,
                chunk_text=cand.chunk_text, metadata=cand.metadata,
                source_event_id=cand.source_event_id,
            ))
            i += 1
        for g in result.ground_chunks:
            lines.append(f"{i}. (drill-down) source={g.get('source_type')} | "
                         f"section={g.get('section_path')} | "
                         f"current={'true' if g.get('is_current') else 'false'}")
            for body_line in (g.get("chunk_text") or "").splitlines():
                lines.append(f"   {body_line}")
            i += 1
        lines.append("")

    if result.contradictions:
        lines.append("[Conflicts — confirmed contradictions]")
        for c in result.contradictions:
            lines.append(
                f"- entity={c.get('canonical_name')} score={c['score']:.2f}"
                f" reason={c.get('reason') or ''}"
            )
        lines.append("")

    lines.append("[Instructions]")
    if instructions:
        lines.append(instructions)
        return "\n".join(lines)

    if result.scope.scope == "global":
        lines.append("- project summary 로 전체 구조 → document/feature summary 로 세부 분기 → 대표 chunk 로 근거.")
        lines.append("- conflict 가 있으면 답 마지막에 별도 섹션으로 분리해 표시하세요.")
    elif result.scope.scope == "feature":
        lines.append("- feature summary 로 서두를 잡고 chunk 근거 2~4개를 인용하세요.")
        lines.append("- conflict 가 있으면 답 중간에 별도 문장으로 명시하세요.")
    else:
        lines.append("- 현재 결정(current=true) 을 기준으로 답하세요.")
        lines.append("- 과거 결정은 변화를 설명할 때만 언급하세요.")
    lines.append("- summary 만 단독으로 답하지 말고 반드시 chunk 근거 1개 이상을 인용하세요.")
    lines.append("- 검색 결과 외 사실은 추론하지 말고 모른다고 답하세요.")
    return "\n".join(lines)
