"""hybrid retrieval 동기 경로.

QN → RES → QEMB → HYB(FTS5 + sqlite-vec) → RRF → BOOST → RG → RR → CTX.
embedding/sqlite-vec 미가용 시 FTS-only path 로 graceful degradation.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from . import embedding as emb_mod
from . import rerank as rerank_mod
from ._common import Span, db_connect, profile_emit
from .entity import resolve_in_query
from .normalize import normalize_alias, normalize_chunk_type, normalize_query

# Hybrid candidate fan-out.
# 각 검색 채널에서 넉넉히 후보를 모은 뒤 RRF/BOOST/RR 단계에서 줄인다.
VECTOR_TOPN = 100
BM25_TOPN = 100
FUSION_CANDIDATES = 200

# 최종 context 로 넘기는 기본 chunk 수. CLI top_k 인자가 없을 때 사용한다.
FINAL_TOPK_DEFAULT = 10

# Reciprocal Rank Fusion 설정.
# RRF_K 는 상위 rank 간 점수 차이를 완만하게 만드는 smoothing 값이고,
# vector/BM25 weight 는 semantic recall 을 더 신뢰하는 현재 정책을 표현한다.
RRF_K = 60
RRF_VECTOR_WEIGHT = 0.8
RRF_BM25_WEIGHT = 0.2

# Candidate boost/penalty weights.
# RRF 뒤에 현재성, entity coverage, recency, pin/기억 역할, query context,
# contradiction 신호를 더한다.
BOOST_CURRENT = 0.15
BOOST_ENTITY = 0.10
BOOST_RECENT = 0.05
# pin/manual 기억과 rollup 근거의 역할 분리 가중치.
# 0.08 묶음(pinned·manual·manual×broad)은 current(0.15)/entity(0.10)를 뒤집지 않는
# 약한 tie-breaker 수준으로 둔다 — "비슷한 후보면 기억을 살짝 위로".
# ROLLUP_IMPLEMENTATION 만 0.20 으로 큰 이유: 구현 질문("왜/어떻게/파일")에서는
# canonical 기억보다 reason/files/symbols 를 가진 rollup 근거가 답에 직접 쓰이므로,
# current+entity 합산도 의도적으로 추월할 수 있게 시스템 내 최대 양수 boost 로 둔다.
# 값 자체는 경험적 튜닝치 — 변경 시 tests/run_tests.py TC-32 의 순서 단정을 함께 확인.
BOOST_PINNED = 0.08
BOOST_MANUAL_MEMORY = 0.08
BOOST_MANUAL_BROAD_QUERY = 0.08
BOOST_ROLLUP_IMPLEMENTATION_QUERY = 0.20

# Working memory 는 retrieved context 가 아니라 query context 이므로 낮은 고정 점수로 soft union.
WORKING_OVERLAY_SCORE = 0.12
WORKING_OVERLAY_LIMIT = 4

# Confirmed contradiction 은 사실상 사용 금지에 가까운 강한 감점, candidate 는 약한 감점.
BOOST_CONTRADICTION_CONFIRMED = -1.0
BOOST_CONTRADICTION_CANDIDATE = -0.20

# top1 이 이 값보다 낮으면 low-confidence trace 로 남긴다. events 자동 fallback 은 열지 않는다.
LOW_CONFIDENCE_TOP1 = 0.13

# Rerank gate thresholds.
# 후보가 충분하고 top1 확신이 낮을 때만 cross-encoder 를 호출해 latency 를 제한한다.
RG_MIN_CANDIDATES = 10
RG_TOP1_THRESHOLD = 0.85


@dataclass
class RetrievalCandidate:
    chunk_id: str
    document_id: str | None
    retrieval_text: str
    chunk_text: str
    section_path: str | None
    source_type: str | None
    source_updated_at: str | None
    is_current: int
    raw_chunk_type: str | None
    normalized_chunk_type: str | None
    bm25_rank: int | None = None
    vector_rank: int | None = None
    rrf_score: float = 0.0
    boost_score: float = 0.0
    final_score: float = 0.0
    matched_entities: list[str] = field(default_factory=list)
    lane: str | None = None
    evidence_level: str | None = None
    grounded: bool | None = None
    source_uri: str | None = None
    text_hash: str | None = None
    penalties: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_event_id: str | None = None
    pinned: int = 0

    @property
    def entry_id(self) -> str:
        return self.chunk_id

    @property
    def source_document_id(self) -> str | None:
        return self.document_id

    @property
    def text(self) -> str:
        return self.chunk_text

    @property
    def raw_type(self) -> str | None:
        return self.raw_chunk_type

    @property
    def normalized_type(self) -> str | None:
        return self.normalized_chunk_type


@dataclass
class RetrievalResult:
    query: str
    normalized_query: str
    resolved_entities: list[dict]
    candidates: list[RetrievalCandidate]
    rerank_used: bool = False
    rerank_timeout: bool = False
    embedding_used: bool = False
    query_surfaces: list[dict[str, str]] = field(default_factory=list)
    fallback_triggered: bool = False
    fallback_reasons: list[str] = field(default_factory=list)
    low_confidence_reasons: list[str] = field(default_factory=list)
    rerank_gate_reason: str = "not_evaluated"


_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")

# LIKE fallback 에서 query intent 단어를 검색 token 으로 쓰지 않기 위한 stopword.
_LIKE_STOPWORDS = {
    "알려줘", "알려주세요", "설명해줘", "설명해주세요",
    "어떻게", "뭐야", "무엇", "동작",
}

# 질문 의도 분류용 키워드 집합. 형태소 분석 없이 substring/token 매칭(_query_has_any).
# 두 집합은 의도적으로 배타가 아니다 — "왜 이 결정을 했어?" 처럼 한 질문이 양쪽에
# 모두 걸릴 수 있다. 겹쳤을 때의 우선순위는 BOOST 단계에서 rollup 쪽으로 기울도록
# 고정한다(아래 BOOST 적용부 주석 참고). 즉 "애매하면 근거 우선" 이 설계 기본값이다.
_IMPLEMENTATION_QUERY_TERMS = {
    "왜", "이유", "근거", "어떻게", "구현", "코드", "로직", "파일", "심볼",
    "테스트", "검증", "수정", "변경", "추가", "삭제", "연결", "적용",
    "why", "how", "implement", "implementation", "code", "logic", "file",
    "symbol", "test", "reason", "because", "change", "fix",
}

_BROAD_MEMORY_QUERY_TERMS = {
    "목적", "원칙", "정책", "결정", "방향", "큰틀", "전체", "요약",
    "기억", "메모", "remember", "decision", "policy", "summary", "overview",
}


def _query_surfaces(query: str, expanded: str) -> list[tuple[str, str]]:
    """원문, entity-expanded, code/action surface 를 병렬 검색용으로 구성."""
    surfaces: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(kind: str, text: str) -> None:
        t = " ".join((text or "").split())
        key = t.lower()
        if t and key not in seen:
            seen.add(key)
            surfaces.append((kind, t))

    add("original", query)
    add("expanded", expanded)
    q = query.lower()
    terms: list[str] = []
    if any(k in q for k in ("버튼", "button", "클릭", "click", "탭", "tap")):
        terms.extend(["button", "click", "handler", "action", "onClick", "onTap", "navigation"])
    if any(k in q for k in ("화면", "view", "screen", "페이지", "page")):
        terms.extend(["screen", "view", "route", "navigation"])
    if any(k in q for k in ("설정", "동기화", "sync", "저장", "save")):
        terms.extend(["settings", "sync", "synchronize", "save", "state"])
    if terms:
        add("code", f"{expanded} {' '.join(terms)}")
    return surfaces[:3]


def _contradiction_penalty_ids(
    conn: sqlite3.Connection,
    project_id: str,
    resolved: list[dict],
) -> tuple[set[str], set[str]]:
    entity_ids = [hit.get("entity_id") for hit in resolved if hit.get("entity_id")]
    if not entity_ids:
        return set(), set()
    placeholders = ",".join("?" * len(entity_ids))
    cur = conn.execute(
        f"""
        SELECT entry_a_id, entry_b_id, status
        FROM contradictions
        WHERE project_id = ?
          AND entity_id IN ({placeholders})
          AND status IN ('confirmed', 'candidate')
        """,
        (project_id, *entity_ids),
    )
    confirmed: set[str] = set()
    candidate: set[str] = set()
    for row in cur.fetchall():
        target = confirmed if row["status"] == "confirmed" else candidate
        target.add(row["entry_a_id"])
        target.add(row["entry_b_id"])
    return confirmed, candidate


def _low_confidence_reasons(
    ordered: list[RetrievalCandidate],
    resolved_terms: set[str],
) -> list[str]:
    reasons: list[str] = []
    if not ordered:
        return ["no_candidates"]
    if ordered[0].final_score < LOW_CONFIDENCE_TOP1:
        reasons.append("top1_below_threshold")
    if ordered and all(c.source_type == "working" for c in ordered[: min(3, len(ordered))]):
        reasons.append("working_only")
    if resolved_terms:
        top = ordered[: min(3, len(ordered))]
        if top and not any(
            any(term and term in normalize_alias(c.retrieval_text) for term in resolved_terms)
            for c in top
        ):
            reasons.append("entity_mismatch")
    return reasons


def _has_low_confidence(
    ordered: list[RetrievalCandidate],
    resolved_terms: set[str],
) -> bool:
    return bool(_low_confidence_reasons(ordered, resolved_terms))


def _candidate_context_section(cand: RetrievalCandidate) -> str:
    if cand.source_type == "working":
        return "query_context"
    if cand.evidence_level == "raw_source" or cand.source_type in {"slack", "notion", "spec", "message", "thread"}:
        return "external_source_context"
    return "retrieved_memory"


def _query_has_any(query: str, terms: set[str]) -> bool:
    normalized = normalize_alias(query)
    tokens = {t.lower() for t in _TOKEN_RE.findall(query)}
    for term in terms:
        t = term.lower()
        if t in tokens or t in normalized:
            return True
    return False


def _is_rollup_candidate(cand: RetrievalCandidate) -> bool:
    return bool(cand.metadata.get("rolled") or cand.metadata.get("rollup"))


def _dedupe_candidates(candidates: list[RetrievalCandidate]) -> list[RetrievalCandidate]:
    """동일 source_uri/text_hash 후보가 반복되면 가장 높은 점수 후보만 남긴다."""
    by_key: dict[tuple[str, str], RetrievalCandidate] = {}
    passthrough: list[RetrievalCandidate] = []
    for cand in candidates:
        key: tuple[str, str] | None = None
        if cand.source_uri:
            key = ("source_uri", cand.source_uri)
        elif cand.text_hash:
            key = ("text_hash", cand.text_hash)
        if key is None:
            passthrough.append(cand)
            continue
        prev = by_key.get(key)
        if prev is None or cand.final_score > prev.final_score:
            by_key[key] = cand
    merged = passthrough + list(by_key.values())
    return sorted(merged, key=lambda c: -c.final_score)


def _build_fts_query(query: str) -> str | None:
    """trigram FTS5 용 OR 검색 표현 생성.

    한국어 phrase 전체를 그대로 MATCH 에 넘기면 trigram 시퀀스가 어긋나 매치 실패.
    토큰 단위로 쪼개고 ≥3 글자만 phrase 로 OR 결합. 모두 짧으면 None.
    """
    tokens = _TOKEN_RE.findall(query)
    parts = [t for t in tokens if len(t) >= 3]
    if not parts:
        return None
    return " OR ".join(f'"{t}"' for t in parts)


def _fts_search(conn: sqlite3.Connection, project_id: str, query: str, top_n: int) -> list[sqlite3.Row]:
    """FTS5 trigram BM25 검색. 3글자 미만 토큰은 trigram 미생성 → 빈 결과."""
    fts_query = _build_fts_query(query)
    if not fts_query:
        return []
    cur = conn.execute(
        """
        SELECT c.id, c.source_document_id AS document_id, c.source_event_id,
               COALESCE(NULLIF(c.retrieval_text, ''), c.text) AS retrieval_text,
               c.text AS chunk_text,
               c.section_path, c.source_updated_at, c.is_current,
               c.raw_type AS raw_chunk_type, c.normalized_type AS normalized_chunk_type,
               c.metadata_json, coalesce(d.source_type, c.origin) AS source_type,
               c.pinned,
               bm25(search_entries_fts) AS bm25_score
        FROM search_entries_fts
        JOIN search_entries c ON c.rowid = search_entries_fts.rowid
        LEFT JOIN source_documents d ON d.id = c.source_document_id
        WHERE search_entries_fts MATCH ?
          AND c.project_id = ?
          AND c.is_current = 1
          AND coalesce(c.raw_type, '') != 'source_status'
        ORDER BY bm25_score
        LIMIT ?
        """,
        (fts_query, project_id, top_n),
    )
    return list(cur.fetchall())


def _like_fallback_search(
    conn: sqlite3.Connection,
    project_id: str,
    raw_query: str,
    normalized_query: str,
    top_n: int,
) -> list[sqlite3.Row]:
    """FTS/vector 가 둘 다 비었을 때 쓰는 짧은 한국어 토큰 fallback.

    FTS5 trigram 은 2글자 한국어 토큰(버튼, 클릭, 동작)을 거의 못 잡는다.
    embedding 미설치 환경에서는 이런 짧은 UI 질의가 빈 결과가 되므로, 원문과
    정규화 질의의 2글자 이상 토큰을 `LIKE` 로 한 번 더 확인한다.
    """
    tokens: list[str] = []
    seen: set[str] = set()
    for source in (raw_query, normalized_query):
        for tok in _TOKEN_RE.findall(source):
            t = tok.strip().lower()
            if len(t) < 2 or t in _LIKE_STOPWORDS or t in seen:
                continue
            seen.add(t)
            tokens.append(t)
    if not tokens:
        return []

    clauses = []
    params: list[str] = []
    for tok in tokens[:8]:
        pat = f"%{tok}%"
        clauses.append("(lower(c.retrieval_text) LIKE ? OR lower(c.text) LIKE ?)")
        params.extend([pat, pat])

    cur = conn.execute(
        f"""
        SELECT c.id, c.source_document_id AS document_id, c.source_event_id,
               COALESCE(NULLIF(c.retrieval_text, ''), c.text) AS retrieval_text,
               c.text AS chunk_text,
               c.section_path, c.source_updated_at, c.is_current,
               c.raw_type AS raw_chunk_type, c.normalized_type AS normalized_chunk_type,
               c.metadata_json, coalesce(d.source_type, c.origin) AS source_type,
               c.pinned
        FROM search_entries c
        LEFT JOIN source_documents d ON d.id = c.source_document_id
        WHERE c.project_id = ?
          AND c.is_current = 1
          AND coalesce(c.raw_type, '') != 'source_status'
          AND ({' OR '.join(clauses)})
        LIMIT ?
        """,
        (project_id, *params, max(top_n * 2, top_n)),
    )
    rows = list(cur.fetchall())

    def hit_count(row: sqlite3.Row) -> int:
        haystack = f"{row['retrieval_text'] or ''}\n{row['chunk_text'] or ''}".lower()
        return sum(1 for tok in tokens if tok in haystack)

    rows.sort(key=lambda r: (-hit_count(r), -(r["is_current"] or 0), r["id"]))
    return rows[:top_n]


def _working_memory_overlay(
    conn: sqlite3.Connection,
    project_id: str,
    raw_query: str,
    normalized_query: str,
    top_n: int = WORKING_OVERLAY_LIMIT,
) -> list[RetrievalCandidate]:
    """현재 세션 user_message event metadata 를 query context 로 soft union."""
    session_id = os.environ.get("IMPRINT_SESSION_ID", "").strip()
    params: list[Any] = [project_id]
    session_clause = ""
    if session_id:
        session_clause = "AND json_extract(e.metadata_json, '$.session_id') = ?"
        params.append(session_id)
    params.append(max(top_n * 3, top_n))
    cur = conn.execute(
        f"""
        SELECT e.id, e.kind AS chunk_type, e.text_clean AS text, e.metadata_json, e.created_at, 0 AS pinned
        FROM events e
        WHERE e.project_id = ?
          AND e.kind = 'user_message'
          AND json_extract(e.metadata_json, '$.memory_tier') = 'working'
          AND json_extract(e.metadata_json, '$.session_visible') = 1
          {session_clause}
        ORDER BY e.created_at DESC
        LIMIT ?;
        """,
        params,
    )
    rows = list(cur.fetchall())

    tokens: list[str] = []
    seen_tokens: set[str] = set()
    for source in (raw_query, normalized_query):
        for tok in _TOKEN_RE.findall(source):
            t = tok.strip().lower()
            if len(t) < 2 or t in _LIKE_STOPWORDS or t in seen_tokens:
                continue
            seen_tokens.add(t)
            tokens.append(t)

    def hit_count(row: sqlite3.Row) -> int:
        if not tokens:
            return 0
        haystack = (row["text"] or "").lower()
        return sum(1 for tok in tokens if tok in haystack)

    scored = [(row, hit_count(row)) for row in rows]
    if not session_id and tokens:
        scored = [(row, hits) for row, hits in scored if hits > 0]
    scored.sort(key=lambda t: (t[1], t[0]["created_at"]), reverse=True)
    selected = [row for row, _hits in scored[:top_n]]

    out: list[RetrievalCandidate] = []
    for row in selected:
        try:
            md = json.loads(row["metadata_json"] or "{}")
            if not isinstance(md, dict):
                md = {}
        except (json.JSONDecodeError, TypeError):
            md = {}
        display_text = (row["text"] or "").split("\n", 1)[0].strip() or row["text"]
        out.append(
            RetrievalCandidate(
                chunk_id=row["id"],
                document_id=None,
                retrieval_text=row["text"],
                chunk_text=display_text,
                section_path=md.get("memory_kind") or "working",
                source_type="working",
                source_updated_at=row["created_at"],
                is_current=0,
                raw_chunk_type="raw_turn",
                normalized_chunk_type=normalize_chunk_type("raw_turn"),
                rrf_score=WORKING_OVERLAY_SCORE,
                boost_score=0.0,
                final_score=WORKING_OVERLAY_SCORE,
                lane="query_context",
                evidence_level=md.get("evidence_level") or "raw_turn",
                grounded=bool(md.get("grounded")) if md.get("grounded") is not None else False,
                source_uri=md.get("source_uri") or md.get("url"),
                text_hash=md.get("text_hash"),
                metadata=md,
            )
        )
    return out


def _vector_search(
    conn: sqlite3.Connection, project_id: str, query_embedding: bytes, top_n: int
) -> list[tuple[sqlite3.Row, float]]:
    """sqlite-vec 미가용 가정 — Python 측에서 cosine 직접 계산.

    search_entries 의 모든 current row 를 가져와 cosine 정렬. 데이터 규모가 커지면
    sqlite-vec extension 로드 path 로 교체.
    """
    cur = conn.execute(
        """
        SELECT c.id, c.source_document_id AS document_id, c.source_event_id,
               COALESCE(NULLIF(c.retrieval_text, ''), c.text) AS retrieval_text,
               c.text AS chunk_text,
               c.section_path, c.source_updated_at, c.is_current,
               c.raw_type AS raw_chunk_type, c.normalized_type AS normalized_chunk_type,
               c.embedding, c.metadata_json, coalesce(d.source_type, c.origin) AS source_type,
               c.pinned
        FROM search_entries c
        LEFT JOIN source_documents d ON d.id = c.source_document_id
        WHERE c.project_id = ?
          AND c.is_current = 1
          AND c.embedding IS NOT NULL
          AND coalesce(c.raw_type, '') != 'source_status'
        """,
        (project_id,),
    )
    scored: list[tuple[sqlite3.Row, float]] = []
    for row in cur.fetchall():
        sim = emb_mod.cosine_similarity_blob(query_embedding, row["embedding"])
        scored.append((row, sim))
    scored.sort(key=lambda t: -t[1])
    return scored[:top_n]


def _row_to_candidate(row: sqlite3.Row) -> RetrievalCandidate:
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
        if not isinstance(metadata, dict):
            metadata = {}
    except (IndexError, KeyError, json.JSONDecodeError, TypeError):
        metadata = {}
    cand = RetrievalCandidate(
        chunk_id=row["id"],
        document_id=row["document_id"],
        retrieval_text=row["retrieval_text"],
        chunk_text=row["chunk_text"],
        section_path=row["section_path"],
        source_type=row["source_type"],
        source_updated_at=row["source_updated_at"],
        is_current=row["is_current"],
        raw_chunk_type=row["raw_chunk_type"],
        normalized_chunk_type=row["normalized_chunk_type"],
    )
    cand.metadata = metadata
    try:
        cand.source_event_id = row["source_event_id"]
    except (IndexError, KeyError):
        cand.source_event_id = None
    try:
        cand.pinned = int(row["pinned"] or 0)
    except (IndexError, KeyError, TypeError, ValueError):
        cand.pinned = 0
    cand.evidence_level = metadata.get("evidence_level")
    if cand.evidence_level is None and cand.source_type in {"slack", "notion"}:
        cand.evidence_level = "raw_source"
    if "grounded" in metadata:
        cand.grounded = bool(metadata.get("grounded"))
    else:
        cand.grounded = True if cand.evidence_level == "raw_source" else None
    source_uri = metadata.get("source_uri") or metadata.get("url")
    text_hash = metadata.get("text_hash")
    cand.source_uri = str(source_uri) if source_uri else None
    cand.text_hash = str(text_hash) if text_hash else None
    cand.lane = _candidate_context_section(cand)
    return cand


def _is_recent(source_updated_at: str | None) -> bool:
    """30일 이내 갱신을 'recent' 로 본다."""
    if not source_updated_at:
        return False
    from datetime import datetime, timedelta, timezone

    try:
        ts = datetime.fromisoformat(source_updated_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts) < timedelta(days=30)


def retrieve(
    query: str,
    project_id: str,
    top_k: int = FINAL_TOPK_DEFAULT,
) -> RetrievalResult:
    """질문에 대한 hybrid retrieval. 결과는 final_score 내림차순."""
    with Span("retrieve_total", project=project_id):
        with Span("QN"):
            normalized = normalize_query(query)

        conn = db_connect()
        try:
            surfaces: list[tuple[str, str]] = []
            fallback_reasons: list[str] = []
            fallback_triggered = False
            low_confidence_reasons: list[str] = []
            rerank_gate_reason = "not_evaluated"
            with Span("RES"):
                resolved = resolve_in_query(project_id, query, conn=conn)
                expanded = normalized
                for hit in resolved:
                    expanded = f"{expanded} {hit['canonical_name']}"

            # QEMB
            embedding_used = False
            query_embedding: bytes | None = None
            with Span("QEMB"):
                if emb_mod.is_available():
                    query_embedding = emb_mod.embed_text(expanded)
                    embedding_used = query_embedding is not None

            # HYB
            with Span("HYB"):
                surfaces = _query_surfaces(query, expanded)
                bm25_batches: list[list[sqlite3.Row]] = []
                for _kind, surface in surfaces:
                    rows = _fts_search(conn, project_id, surface, BM25_TOPN)
                    if rows:
                        bm25_batches.append(rows)
                vector_rows: list[tuple[sqlite3.Row, float]] = []
                if query_embedding is not None:
                    vector_rows = _vector_search(conn, project_id, query_embedding, VECTOR_TOPN)
                if not bm25_batches and not vector_rows:
                    like_rows: list[sqlite3.Row] = []
                    for _kind, surface in surfaces:
                        like_rows.extend(_like_fallback_search(
                            conn, project_id, query, surface, BM25_TOPN,
                        ))
                    if like_rows:
                        dedup_like: dict[str, sqlite3.Row] = {}
                        for row in like_rows:
                            dedup_like.setdefault(row["id"], row)
                        bm25_batches.append(list(dedup_like.values()))

            # RRF
            with Span("RRF"):
                merged: dict[str, RetrievalCandidate] = {}
                for batch in bm25_batches:
                    for rank, row in enumerate(batch):
                        cid = row["id"]
                        cand = merged.get(cid) or _row_to_candidate(row)
                        cand.bm25_rank = rank if cand.bm25_rank is None else min(cand.bm25_rank, rank)
                        cand.rrf_score += RRF_BM25_WEIGHT * (1.0 / (RRF_K + rank))
                        merged[cid] = cand
                for rank, (row, _sim) in enumerate(vector_rows):
                    cid = row["id"]
                    cand = merged.get(cid) or _row_to_candidate(row)
                    cand.vector_rank = rank
                    cand.rrf_score += RRF_VECTOR_WEIGHT * (1.0 / (RRF_K + rank))
                    merged[cid] = cand
                for cand in _working_memory_overlay(conn, project_id, query, expanded):
                    merged.setdefault(cand.chunk_id, cand)

            # BOOST
            with Span("BOOST"):
                resolved_terms = {
                    normalize_alias(term)
                    for hit in resolved
                    for term in (hit.get("canonical_name"), hit.get("matched_alias"))
                    if term
                }
                implementation_query = _query_has_any(query, _IMPLEMENTATION_QUERY_TERMS)
                broad_memory_query = _query_has_any(query, _BROAD_MEMORY_QUERY_TERMS)
                confirmed_penalty, candidate_penalty = _contradiction_penalty_ids(
                    conn, project_id, resolved,
                )
                for cand in merged.values():
                    boost = 0.0
                    if cand.is_current:
                        boost += BOOST_CURRENT
                    if cand.pinned:
                        boost += BOOST_PINNED
                    if cand.source_type == "manual_remember":
                        boost += BOOST_MANUAL_MEMORY
                        # broad 보너스는 "순수하게 넓은 질문"에만 — 구현 신호가 섞이면
                        # 제외한다. 반면 rollup 보너스(아래)는 broad 여부와 무관하게
                        # implementation 신호만으로 붙으므로, 양쪽에 걸친 애매한 질문은
                        # manual 의 broad 보너스가 빠지고 rollup 이 +0.20 을 받아 근거 쪽으로
                        # 기운다. 이 비대칭이 "애매하면 근거 우선" 정책의 구현부다.
                        if broad_memory_query and not implementation_query:
                            boost += BOOST_MANUAL_BROAD_QUERY
                    if implementation_query and _is_rollup_candidate(cand):
                        boost += BOOST_ROLLUP_IMPLEMENTATION_QUERY
                    if cand.normalized_chunk_type and resolved_terms:
                        normalized_text = normalize_alias(cand.retrieval_text)
                        # Phase 7a v1 은 entry_entities 자동 채움 전 단계라 alias/canonical
                        # 본문 매칭을 간이 entity coverage 신호로 사용한다.
                        for hit in resolved:
                            cn = hit["canonical_name"]
                            terms = (
                                normalize_alias(cn),
                                normalize_alias(hit.get("matched_alias") or ""),
                            )
                            if any(term and term in normalized_text for term in terms):
                                boost += BOOST_ENTITY
                                cand.matched_entities.append(cn)
                                break
                    if _is_recent(cand.source_updated_at):
                        boost += BOOST_RECENT
                    if cand.chunk_id in confirmed_penalty:
                        boost += BOOST_CONTRADICTION_CONFIRMED
                        cand.penalties.append("confirmed_contradiction")
                    elif cand.chunk_id in candidate_penalty:
                        boost += BOOST_CONTRADICTION_CANDIDATE
                        cand.penalties.append("candidate_contradiction")
                    cand.boost_score = boost
                    cand.final_score = cand.rrf_score + boost
                    cand.lane = cand.lane or _candidate_context_section(cand)
                ordered = _dedupe_candidates(list(merged.values()))[:FUSION_CANDIDATES]
                low_confidence_reasons = _low_confidence_reasons(ordered, resolved_terms)
                if low_confidence_reasons:
                    fallback_triggered = False
                    fallback_reasons = low_confidence_reasons[:]

            # RG
            rerank_used = False
            rerank_timeout = False
            top1_score = ordered[0].final_score if ordered else 0.0
            if len(ordered) < RG_MIN_CANDIDATES:
                rerank_gate_reason = "too_few_candidates"
            elif top1_score >= RG_TOP1_THRESHOLD:
                rerank_gate_reason = "top1_confident"
            elif not rerank_mod.is_available():
                rerank_gate_reason = "rerank_unavailable"
            else:
                rerank_gate_reason = "eligible"
            rg_pass = (
                len(ordered) >= RG_MIN_CANDIDATES
                and top1_score < RG_TOP1_THRESHOLD
                and rerank_mod.is_available()
            )
            if rg_pass:
                with Span("RR"):
                    rerank_input = [(c.chunk_id, c.retrieval_text) for c in ordered[:30]]
                    new_order = rerank_mod.rerank(
                        query=query, candidates=rerank_input, project_id=project_id
                    )
                    rerank_used = True
                    if new_order == list(range(len(rerank_input))):
                        # 입력 순서 그대로 → timeout 또는 신규 cache miss 의 fallback.
                        rerank_timeout = True
                    reranked_top = [ordered[i] for i in new_order]
                    ordered = reranked_top + ordered[len(rerank_input) :]
                    rerank_gate_reason = "used_timeout" if rerank_timeout else "used"

            # CTX (top-K 자르기 — assembly 는 별도 모듈)
            with Span("CTX"):
                final = ordered[:top_k]

        finally:
            conn.close()

        profile_emit(
            "retrieve_done",
            project=project_id,
            candidates=len(final),
            embedding=embedding_used,
            rerank=rerank_used,
            surfaces=len(surfaces),
            fallback=fallback_triggered,
            fallback_reasons=",".join(fallback_reasons),
            rerank_gate_reason=rerank_gate_reason,
        )
        return RetrievalResult(
            query=query,
            normalized_query=normalized,
            resolved_entities=resolved,
            candidates=final,
            rerank_used=rerank_used,
            rerank_timeout=rerank_timeout,
            embedding_used=embedding_used,
            query_surfaces=[{"kind": kind, "text": text} for kind, text in surfaces],
            fallback_triggered=fallback_triggered,
            fallback_reasons=fallback_reasons,
            low_confidence_reasons=low_confidence_reasons,
            rerank_gate_reason=rerank_gate_reason,
        )
