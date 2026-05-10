"""query scope classifier — global / feature / local 분류 (rule-based).

LLM 분류기는 동기 경로 budget 위반 위험으로 보류. 명세 시드 키워드 + entity 매칭
+ 길이 휴리스틱 만으로 ~90% 케이스 커버.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .normalize import normalize_query

GLOBAL_KEYWORDS = (
    "전체", "전반", "프로젝트", "정리", "흐름 전체",
    "overall", "summarize", "everything", "all features",
)
FEATURE_KEYWORDS = (
    "기능", "플로우", "과정", "ux", "시나리오", "흐름", "어떻게 동작",
    "flow", "scenario", "walkthrough",
)

# local 신호 — 짧은 질문 + entity / "누르면" 같은 동작 어휘.
LOCAL_HINTS = (
    "누르면", "탭하면", "클릭하면", "어떻게 돼", "뭐 돼", "뭐야", "어떤 동작",
)

LOCAL_LENGTH_LIMIT = 30  # 정규화 후 글자 수 — 이보다 짧으면 local 가능성 ↑


@dataclass
class ScopeDecision:
    scope: str                # "local" | "feature" | "global"
    matched_keyword: str | None
    fallback: list[str]       # 분류 실패 시 fallback 순서. 다이어그램 SCOPE 분기.
    reason: str               # 판정 근거


def _has_any(text: str, keywords: tuple[str, ...]) -> str | None:
    for kw in keywords:
        if kw in text:
            return kw
    return None


def classify(query: str, *, has_resolved_entity: bool = False) -> ScopeDecision:
    """rule-based 분류. has_resolved_entity 는 entity alias resolve 결과 후에 호출."""
    normalized = normalize_query(query)

    # 1) global 키워드 우선 — 가장 강한 신호.
    g = _has_any(normalized, GLOBAL_KEYWORDS)
    if g:
        return ScopeDecision(
            scope="global", matched_keyword=g,
            fallback=["feature", "local"],
            reason=f"global keyword: {g!r}",
        )

    # 2) feature 키워드.
    f = _has_any(normalized, FEATURE_KEYWORDS)
    if f:
        return ScopeDecision(
            scope="feature", matched_keyword=f,
            fallback=["local", "global"],
            reason=f"feature keyword: {f!r}",
        )

    # 3) entity 매칭 + 짧은 질문 → local.
    if has_resolved_entity and len(normalized) <= LOCAL_LENGTH_LIMIT:
        return ScopeDecision(
            scope="local", matched_keyword=None,
            fallback=["feature", "global"],
            reason=f"entity matched + short query (≤{LOCAL_LENGTH_LIMIT})",
        )

    # 4) local hint 어휘 (짧은 동작 질의 — 누르면/탭하면 등).
    h = _has_any(normalized, LOCAL_HINTS)
    if h:
        return ScopeDecision(
            scope="local", matched_keyword=h,
            fallback=["feature", "global"],
            reason=f"local hint: {h!r}",
        )

    # 5) fallback — 짧으면 local, 그 외 feature.
    if len(normalized) <= LOCAL_LENGTH_LIMIT:
        return ScopeDecision(
            scope="local", matched_keyword=None,
            fallback=["feature", "global"],
            reason="default short → local",
        )
    return ScopeDecision(
        scope="feature", matched_keyword=None,
        fallback=["local", "global"],
        reason="default long → feature",
    )
