"""문서 → 청크 → DB 저장 파이프라인.

순서:
  1) documents upsert (checksum 비교, 동일하면 skip)
  2) chunking
  3) context_prefix 생성 (LLM 호출 — 옵션)
  4) retrieval_text 합성 (context_prefix + chunk_text)
  5) embedding 생성 (옵션, BGE-M3)
  6) chunks_v2 저장 (UNIQUE(document_id, chunk_index) 로 dedupe)

LLM/embedding 미가용 시 그 단계만 skip — 검색은 FTS-only 로 동작.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from typing import Any

from . import embedding as emb_mod
from ._common import db_connect, log, new_id, now_iso
from .chunking import ChunkConfig, ChunkSpec, split_document
from .model_runtime import run_background_model
from .normalize import normalize_chunk_type

# Optional context-prefix generation settings.
# The prefix enriches retrieval_text but must be bounded because ingest can run on long docs.
CONTEXT_PREFIX_TIMEOUT = int(os.environ.get("IMPRINT_CONTEXT_PREFIX_TIMEOUT") or "20")
CONTEXT_PREFIX_MAX_CHARS = 400


@dataclass
class IngestStats:
    document_inserted: bool
    document_updated: bool
    chunks_inserted: int
    chunks_updated: int
    chunks_skipped: int
    embedding_used: bool


def _checksum(raw_text: str) -> str:
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def upsert_document(
    *,
    project_id: str,
    source_type: str,
    source_ref: str,
    raw_text: str,
    title: str | None = None,
    author: str | None = None,
    source_created_at: str | None = None,
    source_updated_at: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> tuple[str, bool, bool]:
    """document upsert. (document_id, inserted, updated) 반환.

    같은 (project_id, source_type, source_ref) 가 있으면 checksum 비교 — 동일하면 skip.
    """
    own = conn is None
    if own:
        conn = db_connect()
    cs = _checksum(raw_text)
    ts = now_iso()
    try:
        cur = conn.execute(
            """
            SELECT id, checksum FROM documents
            WHERE project_id = ? AND source_type = ? AND source_ref = ?
            """,
            (project_id, source_type, source_ref),
        )
        row = cur.fetchone()
        if row:
            if row["checksum"] == cs:
                return row["id"], False, False
            conn.execute(
                """
                UPDATE documents
                SET title = ?, author = ?, raw_text = ?, checksum = ?,
                    source_created_at = ?, source_updated_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (title, author, raw_text, cs, source_created_at, source_updated_at, ts, row["id"]),
            )
            return row["id"], False, True
        did = new_id()
        conn.execute(
            """
            INSERT INTO documents (id, project_id, source_type, source_ref,
                                   title, author, source_created_at, source_updated_at,
                                   raw_text, checksum, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (did, project_id, source_type, source_ref, title, author,
             source_created_at, source_updated_at, raw_text, cs, ts, ts),
        )
        return did, True, False
    finally:
        if own:
            conn.close()


def _generate_context_prefix(
    *,
    project_name: str,
    document_title: str | None,
    section_path: str,
    chunk_text: str,
) -> str | None:
    """Codex 로 1~2 문장 context_prefix 생성. 실패 시 None.

    동기 경로에서 직접 호출하지 말 것 — ingest 는 BG side. UPS hook 의 latency
    budget 과 무관.
    """
    if os.environ.get("IMPRINT_DISABLE_CONTEXT_PREFIX") == "1":
        return None
    prompt = (
        "You are generating retrieval context for a chunk.\n"
        f"Project: {project_name}\n"
        f"Document title: {document_title or '(unknown)'}\n"
        f"Section: {section_path or '(top)'}\n"
        f"Chunk:\n{chunk_text}\n\n"
        "Write 1-2 sentences (Korean) that explain what this chunk is about in the context of the document.\n"
        "Be concrete and factual. Output only the context text, no preamble."
    )
    out = run_background_model(prompt, timeout=CONTEXT_PREFIX_TIMEOUT, task="context_prefix")
    if out is None:
        log("WARN", "context_prefix LLM failed")
        return None
    out = out.strip()
    return out[:CONTEXT_PREFIX_MAX_CHARS] if out else None


def ingest_document(
    *,
    project_id: str,
    project_name: str,
    source_type: str,
    source_ref: str,
    raw_text: str,
    title: str | None = None,
    author: str | None = None,
    source_created_at: str | None = None,
    source_updated_at: str | None = None,
    raw_chunk_type: str | None = None,
    chunk_config: ChunkConfig | None = None,
    generate_context_prefix: bool = False,
    generate_embedding: bool = True,
    dispatch: bool = True,
) -> IngestStats:
    """문서 한 건을 청크화해 저장. 호출자(scheduler) 가 source 별 raw_chunk_type 지정."""
    conn = db_connect()
    try:
        document_id, inserted, updated = upsert_document(
            project_id=project_id,
            source_type=source_type,
            source_ref=source_ref,
            raw_text=raw_text,
            title=title,
            author=author,
            source_created_at=source_created_at,
            source_updated_at=source_updated_at,
            conn=conn,
        )
        if not inserted and not updated:
            return IngestStats(False, False, 0, 0, 0, False)

        write_ts = now_iso()
        chunks = list(split_document(raw_text, chunk_config))
        retrieval_texts: list[str] = []
        for spec in chunks:
            prefix: str | None = None
            if generate_context_prefix:
                prefix = _generate_context_prefix(
                    project_name=project_name,
                    document_title=title,
                    section_path=spec.section_path,
                    chunk_text=spec.chunk_text,
                )
            spec.extra["context_prefix"] = prefix
            spec.extra["retrieval_text"] = (
                f"{prefix}\n{spec.chunk_text}" if prefix else spec.chunk_text
            )
            retrieval_texts.append(spec.extra["retrieval_text"])

        embeddings: list[bytes] | None = None
        if generate_embedding and emb_mod.is_available() and retrieval_texts:
            embeddings = emb_mod.embed_texts(retrieval_texts)

        embedding_used = embeddings is not None
        normalized_type = normalize_chunk_type(raw_chunk_type)

        inserted_count = 0
        updated_count = 0
        skipped = 0
        seen_indexes: set[int] = set()
        for i, spec in enumerate(chunks):
            seen_indexes.add(spec.chunk_index)
            cid = new_id()
            blob = embeddings[i] if embeddings else None
            existing = conn.execute(
                """
                SELECT id, chunk_text, retrieval_text FROM chunks_v2
                WHERE document_id = ? AND chunk_index = ?
                """,
                (document_id, spec.chunk_index),
            ).fetchone()
            if existing:
                changed = (
                    existing["chunk_text"] != spec.chunk_text
                    or existing["retrieval_text"] != spec.extra.get("retrieval_text")
                )
                conn.execute(
                    """
                    UPDATE chunks_v2
                    SET section_path = ?,
                        chunk_text = ?,
                        context_prefix = ?,
                        retrieval_text = ?,
                        embedding = ?,
                        raw_chunk_type = ?,
                        normalized_chunk_type = ?,
                        source_created_at = ?,
                        source_updated_at = ?,
                        valid_from = CASE WHEN ? THEN ? ELSE valid_from END,
                        valid_to = NULL,
                        is_current = 1,
                        supersedes_chunk_id = NULL
                    WHERE id = ?
                    """,
                    (
                        spec.section_path,
                        spec.chunk_text,
                        spec.extra.get("context_prefix"),
                        spec.extra.get("retrieval_text"),
                        blob,
                        raw_chunk_type, normalized_type,
                        source_created_at, source_updated_at,
                        1 if changed else 0, write_ts,
                        existing["id"],
                    ),
                )
                updated_count += 1 if changed else 0
                continue
            try:
                conn.execute(
                    """
                    INSERT INTO chunks_v2
                      (id, project_id, document_id, chunk_index, section_path,
                       chunk_text, context_prefix, retrieval_text, embedding,
                       raw_chunk_type, normalized_chunk_type,
                       source_created_at, source_updated_at,
                       valid_from, is_current, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        cid, project_id, document_id, spec.chunk_index, spec.section_path,
                        spec.chunk_text,
                        spec.extra.get("context_prefix"),
                        spec.extra.get("retrieval_text"),
                        blob,
                        raw_chunk_type, normalized_type,
                        source_created_at, source_updated_at,
                        now_iso(), now_iso(),
                    ),
                )
                inserted_count += 1
            except sqlite3.IntegrityError:
                skipped += 1

        if updated:
            # 새 문서에는 더 이상 존재하지 않는 꼬리 청크는 검색 기본 경로에서 제외한다.
            if seen_indexes:
                placeholders = ",".join("?" for _ in seen_indexes)
                conn.execute(
                    f"""
                    UPDATE chunks_v2
                    SET is_current = 0, valid_to = ?
                    WHERE document_id = ?
                      AND chunk_index NOT IN ({placeholders})
                      AND is_current = 1
                    """,
                    (write_ts, document_id, *sorted(seen_indexes)),
                )
            else:
                conn.execute(
                    """
                    UPDATE chunks_v2
                    SET is_current = 0, valid_to = ?
                    WHERE document_id = ? AND is_current = 1
                    """,
                    (write_ts, document_id),
                )
        stats = IngestStats(
            document_inserted=inserted,
            document_updated=updated,
            chunks_inserted=inserted_count,
            chunks_updated=updated_count,
            chunks_skipped=skipped,
            embedding_used=embedding_used,
        )
    finally:
        conn.close()

    # W1 commit dispatcher — 변경 분석 결과를 ingest_queue 에 enqueue.
    if dispatch and (inserted or updated):
        from . import dispatch as dispatch_mod

        dispatch_mod.dispatch_commit(dispatch_mod.CommitChangeSet(
            project_id=project_id,
            changed_document_ids=[document_id],
            decision_chunk_inserted=(normalized_type == "decision" and stats.chunks_inserted > 0),
            entity_link_changed=False,
            supersede_changed=False,
            new_chunk_inserted=stats.chunks_inserted > 0,
        ))
    return stats
