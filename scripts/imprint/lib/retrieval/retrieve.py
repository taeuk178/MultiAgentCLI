"""hybrid retrieval 동기 경로.

QN → RES → QEMB → HYB(FTS5 + sqlite-vec) → RRF → BOOST → RG → RR → CTX.
embedding/sqlite-vec 미가용 시 FTS-only path 로 graceful degradation.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from . import embedding as emb_mod
from . import rerank as rerank_mod
from ._common import Span, db_connect, profile_emit
from .entity import resolve_in_query
from .normalize import normalize_alias, normalize_chunk_type, normalize_query

# Hybrid search defaults — 명세 권장 값.
VECTOR_TOPN = 100
BM25_TOPN = 100
FUSION_CANDIDATES = 200
FINAL_TOPK_DEFAULT = 10

# RRF 가중치 (semantic 80 / BM25 20).
RRF_K = 60
RRF_VECTOR_WEIGHT = 0.8
RRF_BM25_WEIGHT = 0.2

# BOOST 가중치.
BOOST_CURRENT = 0.15
BOOST_ENTITY = 0.10
BOOST_RECENT = 0.05

# RG 게이트 임계.
RG_MIN_CANDIDATES = 10
RG_TOP1_THRESHOLD = 0.85


@dataclass
class RetrievalCandidate:
    chunk_id: str
    document_id: str
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


@dataclass
class RetrievalResult:
    query: str
    normalized_query: str
    resolved_entities: list[dict]
    candidates: list[RetrievalCandidate]
    rerank_used: bool = False
    rerank_timeout: bool = False
    embedding_used: bool = False


_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")
_LIKE_STOPWORDS = {
    "알려줘", "알려주세요", "설명해줘", "설명해주세요",
    "어떻게", "뭐야", "무엇", "동작",
}


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
        SELECT c.id, c.document_id, c.retrieval_text, c.chunk_text, c.section_path,
               c.source_updated_at, c.is_current, c.raw_chunk_type, c.normalized_chunk_type,
               d.source_type,
               bm25(chunks_v2_fts) AS bm25_score
        FROM chunks_v2_fts
        JOIN chunks_v2 c ON c.rowid = chunks_v2_fts.rowid
        JOIN documents d ON d.id = c.document_id
        WHERE chunks_v2_fts MATCH ?
          AND c.project_id = ?
          AND c.is_current = 1
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
        clauses.append("(lower(c.retrieval_text) LIKE ? OR lower(c.chunk_text) LIKE ?)")
        params.extend([pat, pat])

    cur = conn.execute(
        f"""
        SELECT c.id, c.document_id, c.retrieval_text, c.chunk_text, c.section_path,
               c.source_updated_at, c.is_current, c.raw_chunk_type, c.normalized_chunk_type,
               d.source_type
        FROM chunks_v2 c
        JOIN documents d ON d.id = c.document_id
        WHERE c.project_id = ?
          AND c.is_current = 1
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


def _memory_chunks_fallback_search(
    conn: sqlite3.Connection,
    project_id: str,
    raw_query: str,
    normalized_query: str,
    top_n: int,
) -> list[RetrievalCandidate]:
    """문서 retrieval 결과가 없을 때 legacy memory_chunks 를 read-only 후보로 사용.

    자동 hook 과 `/memory remember` 는 아직 `memory_chunks` 에 직접 저장한다.
    bridge 로 데이터를 복제하기 전까지는 `/retrieve` 가 빈 결과일 때만 이 fallback 을
    타게 해, 기본 RAG 기억을 명시 조회에서도 확인할 수 있게 한다.
    """
    fts_query = _build_fts_query(f"{raw_query} {normalized_query}")
    rows: list[sqlite3.Row] = []
    if fts_query:
        cur = conn.execute(
            """
            SELECT m.id, m.chunk_type, m.text, m.metadata_json, m.created_at, m.pinned,
                   bm25(memory_chunks_fts) AS bm25_score
            FROM memory_chunks_fts
            JOIN memory_chunks m ON m.rowid = memory_chunks_fts.rowid
            WHERE memory_chunks_fts MATCH ?
              AND m.project_id = ?
              AND m.chunk_type != 'source_status'
            ORDER BY m.pinned DESC, bm25_score, m.created_at DESC
            LIMIT ?
            """,
            (fts_query, project_id, top_n),
        )
        rows = list(cur.fetchall())

    tokens: list[str] = []
    seen: set[str] = set()
    for source in (raw_query, normalized_query):
        for tok in _TOKEN_RE.findall(source):
            t = tok.strip().lower()
            if len(t) < 2 or t in _LIKE_STOPWORDS or t in seen:
                continue
            seen.add(t)
            tokens.append(t)

    if not rows and tokens:
        clauses = []
        params: list[str] = []
        for tok in tokens[:8]:
            clauses.append("lower(m.text) LIKE ?")
            params.append(f"%{tok}%")
        cur = conn.execute(
            f"""
            SELECT m.id, m.chunk_type, m.text, m.metadata_json, m.created_at, m.pinned
            FROM memory_chunks m
            WHERE m.project_id = ?
              AND m.chunk_type != 'source_status'
              AND ({' OR '.join(clauses)})
            ORDER BY m.created_at DESC
            LIMIT ?
            """,
            (project_id, *params, max(top_n * 2, top_n)),
        )
        rows = list(cur.fetchall())

        def hit_count(row: sqlite3.Row) -> int:
            haystack = (row["text"] or "").lower()
            return sum(1 for tok in tokens if tok in haystack)

        rows.sort(key=lambda r: (-hit_count(r), -(r["pinned"] or 0)))
        rows = rows[:top_n]

    candidates: list[RetrievalCandidate] = []
    for rank, row in enumerate(rows):
        metadata: dict[str, Any]
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
            if not isinstance(metadata, dict):
                metadata = {}
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        source_type = metadata.get("source") or "memory"
        section_path = metadata.get("section_title") or metadata.get("section_path")
        hits = 0
        if tokens:
            haystack = (row["text"] or "").lower()
            hits = sum(1 for tok in tokens if tok in haystack)
        rrf_score = RRF_BM25_WEIGHT * (1.0 / (RRF_K + rank))
        boost = BOOST_CURRENT
        if row["pinned"]:
            boost += BOOST_RECENT
        if hits:
            boost += min(0.08, hits * 0.02)
        candidates.append(
            RetrievalCandidate(
                chunk_id=row["id"],
                document_id="memory_chunks",
                retrieval_text=row["text"],
                chunk_text=row["text"],
                section_path=section_path,
                source_type=str(source_type),
                source_updated_at=row["created_at"],
                is_current=1,
                raw_chunk_type=row["chunk_type"],
                normalized_chunk_type=normalize_chunk_type(row["chunk_type"]),
                bm25_rank=rank,
                vector_rank=None,
                rrf_score=rrf_score,
                boost_score=boost,
                final_score=rrf_score + boost,
            )
        )
    return sorted(candidates, key=lambda c: -c.final_score)


def _vector_search(
    conn: sqlite3.Connection, project_id: str, query_embedding: bytes, top_n: int
) -> list[tuple[sqlite3.Row, float]]:
    """sqlite-vec 미가용 가정 — Python 측에서 cosine 직접 계산.

    chunks_v2 의 모든 current row 를 가져와 cosine 정렬. 데이터 규모가 커지면
    sqlite-vec extension 로드 path 로 교체.
    """
    cur = conn.execute(
        """
        SELECT c.id, c.document_id, c.retrieval_text, c.chunk_text, c.section_path,
               c.source_updated_at, c.is_current, c.raw_chunk_type, c.normalized_chunk_type,
               c.embedding, d.source_type
        FROM chunks_v2 c
        JOIN documents d ON d.id = c.document_id
        WHERE c.project_id = ? AND c.is_current = 1 AND c.embedding IS NOT NULL
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
    return RetrievalCandidate(
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
                bm25_rows = _fts_search(conn, project_id, expanded, BM25_TOPN)
                vector_rows: list[tuple[sqlite3.Row, float]] = []
                if query_embedding is not None:
                    vector_rows = _vector_search(conn, project_id, query_embedding, VECTOR_TOPN)
                if not bm25_rows and not vector_rows:
                    bm25_rows = _like_fallback_search(
                        conn, project_id, query, expanded, BM25_TOPN,
                    )

            # RRF
            with Span("RRF"):
                merged: dict[str, RetrievalCandidate] = {}
                for rank, row in enumerate(bm25_rows):
                    cid = row["id"]
                    cand = merged.get(cid) or _row_to_candidate(row)
                    cand.bm25_rank = rank
                    cand.rrf_score += RRF_BM25_WEIGHT * (1.0 / (RRF_K + rank))
                    merged[cid] = cand
                for rank, (row, _sim) in enumerate(vector_rows):
                    cid = row["id"]
                    cand = merged.get(cid) or _row_to_candidate(row)
                    cand.vector_rank = rank
                    cand.rrf_score += RRF_VECTOR_WEIGHT * (1.0 / (RRF_K + rank))
                    merged[cid] = cand

            # BOOST
            with Span("BOOST"):
                resolved_terms = {
                    normalize_alias(term)
                    for hit in resolved
                    for term in (hit.get("canonical_name"), hit.get("matched_alias"))
                    if term
                }
                for cand in merged.values():
                    boost = 0.0
                    if cand.is_current:
                        boost += BOOST_CURRENT
                    if cand.normalized_chunk_type and resolved_terms:
                        normalized_text = normalize_alias(cand.retrieval_text)
                        # Phase 7a v1 은 chunk_entities 자동 채움 전 단계라 alias/canonical
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
                    cand.boost_score = boost
                    cand.final_score = cand.rrf_score + boost
                ordered = sorted(merged.values(), key=lambda c: -c.final_score)[
                    :FUSION_CANDIDATES
                ]
                if not ordered:
                    with Span("MEMFB"):
                        ordered = _memory_chunks_fallback_search(
                            conn, project_id, query, expanded, FUSION_CANDIDATES,
                        )

            # RG
            rerank_used = False
            rerank_timeout = False
            top1_score = ordered[0].final_score if ordered else 0.0
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
        )
        return RetrievalResult(
            query=query,
            normalized_query=normalized,
            resolved_entities=resolved,
            candidates=final,
            rerank_used=rerank_used,
            rerank_timeout=rerank_timeout,
            embedding_used=embedding_used,
        )
