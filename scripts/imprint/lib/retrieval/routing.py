"""scope 별 retrieval 라우팅 — local / feature / global.

- local: 7a hybrid retrieve 그대로.
- feature: feature summary 검색 (최대 5) + summary_links drill-down chunk (최대 8).
- global: project summary 1 + document summary 3 + feature summary 5 + 대표 chunk 6.

각 결과에 GROUND drill-down (summary_links → chunk 1~3) 첨부.
CCHECK — resolved entity 의 confirmed contradiction read-only 조회.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from . import contradiction as cd_mod
from . import embedding as emb_mod
from ._common import Span, db_connect
from .entity import resolve_in_query
from .normalize import normalize_query
from .retrieve import RetrievalCandidate, retrieve as chunk_retrieve
from .scope import classify, ScopeDecision

# Routed retrieval depth limits.
# scope 별로 summary/chunk fan-out 을 제한해 context 폭과 latency 를 예측 가능하게 둔다.
FEATURE_SUMMARY_LIMIT = 5
FEATURE_CHUNK_LIMIT = 8
GLOBAL_PROJECT_LIMIT = 1
GLOBAL_DOCUMENT_LIMIT = 3
GLOBAL_FEATURE_LIMIT = 5
GLOBAL_CHUNK_LIMIT = 6
GROUND_DRILLDOWN_LIMIT = 3

# FTS query builder 에서 한국어/영문/숫자 token 을 뽑는 최소 tokenizer.
_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")


@dataclass
class SummaryHit:
    summary_id: str
    level: str
    target_key: str
    title: str | None
    summary_text: str
    is_current: int
    bm25_rank: int | None = None
    vector_rank: int | None = None
    score: float = 0.0


@dataclass
class RoutedResult:
    query: str
    scope: ScopeDecision
    resolved_entities: list[dict]
    summaries: list[SummaryHit] = field(default_factory=list)
    chunks: list[RetrievalCandidate] = field(default_factory=list)
    ground_chunks: list[dict] = field(default_factory=list)
    contradictions: list[dict] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


def _build_fts_query(query: str) -> str | None:
    tokens = _TOKEN_RE.findall(query)
    parts = [t for t in tokens if len(t) >= 3]
    if not parts:
        return None
    return " OR ".join(f'"{t}"' for t in parts)


def _summary_fts(
    conn: sqlite3.Connection, project_id: str, query: str, level: str | None, top_n: int
) -> list[sqlite3.Row]:
    fts_query = _build_fts_query(query)
    if not fts_query:
        return []
    if level:
        cur = conn.execute(
            """
            SELECT s.id, s.level, s.target_key, s.title, s.summary_text,
                   s.is_current, s.embedding, bm25(summaries_fts) AS bm25_score
            FROM summaries_fts
            JOIN summaries s ON s.rowid = summaries_fts.rowid
            WHERE summaries_fts MATCH ?
              AND s.project_id = ? AND s.level = ? AND s.is_current = 1
            ORDER BY bm25_score
            LIMIT ?
            """,
            (fts_query, project_id, level, top_n),
        )
    else:
        cur = conn.execute(
            """
            SELECT s.id, s.level, s.target_key, s.title, s.summary_text,
                   s.is_current, s.embedding, bm25(summaries_fts) AS bm25_score
            FROM summaries_fts
            JOIN summaries s ON s.rowid = summaries_fts.rowid
            WHERE summaries_fts MATCH ?
              AND s.project_id = ? AND s.is_current = 1
            ORDER BY bm25_score
            LIMIT ?
            """,
            (fts_query, project_id, top_n),
        )
    return list(cur.fetchall())


def _summary_vector(
    conn: sqlite3.Connection, project_id: str, level: str | None,
    query_embedding: bytes, top_n: int,
) -> list[tuple[sqlite3.Row, float]]:
    if level:
        cur = conn.execute(
            """
            SELECT id, level, target_key, title, summary_text, is_current, embedding
            FROM summaries
            WHERE project_id = ? AND level = ? AND is_current = 1 AND embedding IS NOT NULL
            """,
            (project_id, level),
        )
    else:
        cur = conn.execute(
            """
            SELECT id, level, target_key, title, summary_text, is_current, embedding
            FROM summaries
            WHERE project_id = ? AND is_current = 1 AND embedding IS NOT NULL
            """,
            (project_id,),
        )
    scored: list[tuple[sqlite3.Row, float]] = []
    for row in cur.fetchall():
        sim = emb_mod.cosine_similarity_blob(query_embedding, row["embedding"])
        scored.append((row, sim))
    scored.sort(key=lambda t: -t[1])
    return scored[:top_n]


def _retrieve_summaries(
    conn: sqlite3.Connection, project_id: str, query: str, level: str | None, top_n: int,
) -> list[SummaryHit]:
    """summary level 별 hybrid retrieve. RRF 재사용 — chunks_v2 와 동일 패턴."""
    bm25_rows = _summary_fts(conn, project_id, query, level, top_n)
    vector_rows: list[tuple[sqlite3.Row, float]] = []
    if emb_mod.is_available():
        emb = emb_mod.embed_text(query)
        if emb is not None:
            vector_rows = _summary_vector(conn, project_id, level, emb, top_n)

    merged: dict[str, SummaryHit] = {}
    K = 60
    for rank, row in enumerate(bm25_rows):
        sid = row["id"]
        h = merged.get(sid) or SummaryHit(
            summary_id=sid, level=row["level"], target_key=row["target_key"],
            title=row["title"], summary_text=row["summary_text"],
            is_current=row["is_current"],
        )
        h.bm25_rank = rank
        h.score += 0.2 * (1.0 / (K + rank))
        merged[sid] = h
    for rank, (row, _sim) in enumerate(vector_rows):
        sid = row["id"]
        h = merged.get(sid) or SummaryHit(
            summary_id=sid, level=row["level"], target_key=row["target_key"],
            title=row["title"], summary_text=row["summary_text"],
            is_current=row["is_current"],
        )
        h.vector_rank = rank
        h.score += 0.8 * (1.0 / (K + rank))
        merged[sid] = h
    return sorted(merged.values(), key=lambda x: -x.score)[:top_n]


def _ground_drilldown(
    conn: sqlite3.Connection, summary_ids: list[str], existing_chunk_ids: set[str], limit: int,
) -> list[dict]:
    """summary_links 따라 child_kind=chunk 1~3개 추가 회수. 중복 제거."""
    out: list[dict] = []
    if not summary_ids:
        return out
    placeholders = ",".join("?" * len(summary_ids))
    cur = conn.execute(
        f"""
        SELECT sl.parent_summary_id, sl.rank_order,
               c.id AS chunk_id, c.chunk_text, c.section_path, c.is_current,
               c.source_updated_at, d.source_type, d.title AS document_title
        FROM summary_links sl
        JOIN chunks_v2 c ON c.id = sl.child_id
        JOIN documents d ON d.id = c.document_id
        WHERE sl.parent_summary_id IN ({placeholders})
          AND sl.child_kind = 'chunk'
        ORDER BY sl.parent_summary_id, sl.rank_order
        """,
        tuple(summary_ids),
    )
    per_parent: dict[str, int] = {}
    for row in cur.fetchall():
        if row["chunk_id"] in existing_chunk_ids:
            continue
        parent = row["parent_summary_id"]
        if per_parent.get(parent, 0) >= limit:
            continue
        per_parent[parent] = per_parent.get(parent, 0) + 1
        out.append({
            "parent_summary_id": parent,
            "chunk_id": row["chunk_id"],
            "chunk_text": row["chunk_text"],
            "section_path": row["section_path"],
            "source_type": row["source_type"],
            "document_title": row["document_title"],
            "is_current": bool(row["is_current"]),
            "source_updated_at": row["source_updated_at"],
        })
    return out


def _ccheck(
    conn: sqlite3.Connection, project_id: str, resolved: list[dict],
) -> list[dict]:
    """resolved entity 의 confirmed contradiction read-only 조회."""
    out: list[dict] = []
    seen: set[str] = set()
    for hit in resolved:
        eid = hit.get("entity_id")
        if not eid or eid in seen:
            continue
        seen.add(eid)
        for row in cd_mod.confirmed_for_entity(project_id, eid, conn=conn):
            out.append({
                "id": row["id"],
                "entity_id": eid,
                "canonical_name": hit.get("canonical_name"),
                "scope_key": row["scope_key"],
                "chunk_a_id": row["chunk_a_id"],
                "chunk_b_id": row["chunk_b_id"],
                "score": row["contradiction_score"],
                "reason": row["reason"],
            })
    return out


def routed_retrieve(query: str, project_id: str) -> RoutedResult:
    """scope 분류 → 라우팅된 검색 + GROUND + CCHECK."""
    with Span("routed_total", project=project_id):
        with Span("RES_pre"):
            resolved_entities = []
            conn = db_connect()
            try:
                resolved_entities = resolve_in_query(project_id, query, conn=conn)
            finally:
                conn.close()

        with Span("SC"):
            scope = classify(query, has_resolved_entity=bool(resolved_entities))

        if scope.scope == "local":
            with Span("HYB1"):
                base = chunk_retrieve(query, project_id, top_k=10)
            existing_ids = {c.chunk_id for c in base.candidates}
            conn = db_connect()
            try:
                with Span("CCHECK"):
                    contradictions = _ccheck(conn, project_id, resolved_entities)
            finally:
                conn.close()
            return RoutedResult(
                query=query, scope=scope,
                resolved_entities=resolved_entities,
                chunks=base.candidates,
                contradictions=contradictions,
                trace={
                    "query_surfaces": base.query_surfaces,
                    "fallback_triggered": base.fallback_triggered,
                    "fallback_reasons": base.fallback_reasons,
                    "low_confidence_reasons": base.low_confidence_reasons,
                    "rerank_gate_reason": base.rerank_gate_reason,
                },
            )

        # feature / global 은 summary retrieval 동반.
        conn = db_connect()
        try:
            if scope.scope == "feature":
                with Span("HYB2_summary"):
                    summaries = _retrieve_summaries(
                        conn, project_id, query, level="feature", top_n=FEATURE_SUMMARY_LIMIT,
                    )
                with Span("HYB2_chunks"):
                    base = chunk_retrieve(query, project_id, top_k=FEATURE_CHUNK_LIMIT)
                with Span("GROUND"):
                    existing_ids = {c.chunk_id for c in base.candidates}
                    ground = _ground_drilldown(
                        conn, [s.summary_id for s in summaries],
                        existing_ids, GROUND_DRILLDOWN_LIMIT,
                    )
                with Span("CCHECK"):
                    contradictions = _ccheck(conn, project_id, resolved_entities)
                return RoutedResult(
                    query=query, scope=scope,
                    resolved_entities=resolved_entities,
                    summaries=summaries,
                    chunks=base.candidates,
                    ground_chunks=ground,
                    contradictions=contradictions,
                    trace={
                        "query_surfaces": base.query_surfaces,
                        "fallback_triggered": base.fallback_triggered,
                        "fallback_reasons": base.fallback_reasons,
                        "low_confidence_reasons": base.low_confidence_reasons,
                        "rerank_gate_reason": base.rerank_gate_reason,
                    },
                )

            # global
            with Span("HYB3"):
                proj_summaries = _retrieve_summaries(
                    conn, project_id, query, level="project", top_n=GLOBAL_PROJECT_LIMIT,
                )
                doc_summaries = _retrieve_summaries(
                    conn, project_id, query, level="document", top_n=GLOBAL_DOCUMENT_LIMIT,
                )
                feat_summaries = _retrieve_summaries(
                    conn, project_id, query, level="feature", top_n=GLOBAL_FEATURE_LIMIT,
                )
            with Span("HYB3_chunks"):
                base = chunk_retrieve(query, project_id, top_k=GLOBAL_CHUNK_LIMIT)
            with Span("GROUND"):
                existing_ids = {c.chunk_id for c in base.candidates}
                all_summary_ids = (
                    [s.summary_id for s in proj_summaries]
                    + [s.summary_id for s in doc_summaries]
                    + [s.summary_id for s in feat_summaries]
                )
                ground = _ground_drilldown(
                    conn, all_summary_ids, existing_ids, GROUND_DRILLDOWN_LIMIT,
                )
            with Span("CCHECK"):
                contradictions = _ccheck(conn, project_id, resolved_entities)
            return RoutedResult(
                query=query, scope=scope,
                resolved_entities=resolved_entities,
                summaries=proj_summaries + doc_summaries + feat_summaries,
                chunks=base.candidates,
                ground_chunks=ground,
                contradictions=contradictions,
                trace={
                    "query_surfaces": base.query_surfaces,
                    "fallback_triggered": base.fallback_triggered,
                    "fallback_reasons": base.fallback_reasons,
                    "low_confidence_reasons": base.low_confidence_reasons,
                    "rerank_gate_reason": base.rerank_gate_reason,
                },
            )
        finally:
            conn.close()
