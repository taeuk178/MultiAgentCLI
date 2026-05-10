"""검색 결과를 Claude prompt 형식으로 포매팅."""
from __future__ import annotations

from .retrieve import RetrievalResult


def format_for_claude(
    project_name: str,
    result: "RetrievalResult",
    *,
    instructions: str | None = None,
) -> str:
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

    lines.append("[Retrieved Context]")
    if not result.candidates:
        lines.append("(검색 결과 없음)")
    for i, cand in enumerate(result.candidates, 1):
        meta_bits = []
        if cand.source_type:
            meta_bits.append(f"source={cand.source_type}")
        if cand.section_path:
            meta_bits.append(f"section={cand.section_path}")
        meta_bits.append(f"current={'true' if cand.is_current else 'false'}")
        if cand.source_updated_at:
            meta_bits.append(f"updated={cand.source_updated_at}")
        lines.append(f"{i}. {' | '.join(meta_bits)}")
        # chunk_text 본문 (Claude 가 답할 때 핵심으로 쓸 부분).
        for body_line in cand.chunk_text.splitlines():
            lines.append(f"   {body_line}")
        lines.append("")

    lines.append("[Instructions]")
    if instructions:
        lines.append(instructions)
    else:
        lines.append("- 현재 결정(current=true) 을 기준으로 답하세요.")
        lines.append("- 과거 결정은 변화를 설명할 때만 언급하세요.")
        lines.append("- 검색 결과 외 사실은 추론하지 말고 모른다고 답하세요.")
    return "\n".join(lines)
