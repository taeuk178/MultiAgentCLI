"""memory_chunks -> chunks_v2 bridge.

자동 hook memory 는 기존 `memory_chunks` 에 직접 저장된다. 이 모듈은
persistent memory row 를 retrieval v2 의 `documents`/`chunks_v2` 후보로도
보이게 하는 얇은 승격 경로다.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from . import embedding as emb_mod
from ._common import now_iso
from .normalize import normalize_chunk_type

SOURCE_REF_PREFIX = "memory_chunks:"


@dataclass
class BridgeStats:
    examined: int = 0
    bridged: int = 0
    skipped: int = 0
    embedding_used: bool = False


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}-{digest}"


def _row_dict(cur: sqlite3.Cursor, row: sqlite3.Row | tuple[Any, ...] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        return dict(row)
    names = [desc[0] for desc in cur.description or []]
    return dict(zip(names, row))


def _metadata(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _should_bridge(row: dict[str, Any], metadata: dict[str, Any]) -> bool:
    if row.get("chunk_type") == "source_status":
        return False
    if metadata.get("memory_tier") == "working":
        return False
    text = str(row.get("text") or "").strip()
    return bool(text)


def _source_type(metadata: dict[str, Any]) -> str:
    return str(metadata.get("source_type") or metadata.get("source") or "memory")


def _bridge_metadata(row: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    source_type = _source_type(metadata)
    out = dict(metadata)
    out.update({
        "bridged_from": "memory_chunks",
        "memory_chunk_id": row["id"],
        "source_event_id": row.get("source_event_id"),
        "chunk_type": row.get("chunk_type"),
        "source_type": source_type,
        "evidence_level": metadata.get("evidence_level") or "memory",
        "text_hash": metadata.get("text_hash") or _checksum(str(row.get("text") or "")),
        "pinned": bool(row.get("pinned") or 0),
        "bridged_at": now_iso(),
    })
    if metadata.get("source_uri") or metadata.get("url"):
        out["source_uri"] = metadata.get("source_uri") or metadata.get("url")
    return out


def bridge_memory_chunk(
    conn: sqlite3.Connection,
    memory_chunk_id: str,
    *,
    generate_embedding: bool = False,
) -> bool:
    """memory_chunks row 1건을 chunks_v2 로 upsert. skip 이면 False."""
    _ensure_metadata_column(conn)
    cur = conn.execute(
        """
        SELECT id, project_id, source_event_id, chunk_type, text, metadata_json,
               created_at, pinned
        FROM memory_chunks
        WHERE id = ?
        """,
        (memory_chunk_id,),
    )
    row = _row_dict(cur, cur.fetchone())
    if row is None:
        return False

    metadata = _metadata(row.get("metadata_json"))
    if not _should_bridge(row, metadata):
        return False

    now = now_iso()
    text = str(row["text"])
    source_type = _source_type(metadata)
    source_ref = f"{SOURCE_REF_PREFIX}{row['id']}"
    document_id = _stable_id("memdoc", str(row["id"]))
    chunk_id = _stable_id("memchunk", str(row["id"]))
    title = metadata.get("section_title") or metadata.get("memory_kind") or row["chunk_type"]
    checksum = _checksum(text)
    source_created_at = row.get("created_at")
    source_updated_at = metadata.get("fetched_at") or metadata.get("write_ts") or row.get("created_at")
    section_path = metadata.get("section_path") or metadata.get("section_title") or row["chunk_type"]
    bridge_md = _bridge_metadata(row, metadata)
    metadata_json = json.dumps(bridge_md, ensure_ascii=False)
    embedding_blob = None
    if generate_embedding and emb_mod.is_available():
        embedding_blob = emb_mod.embed_text(text)

    conn.execute(
        """
        INSERT INTO documents
          (id, project_id, source_type, source_ref, title, source_created_at,
           source_updated_at, raw_text, checksum, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id, source_type, source_ref) DO UPDATE SET
          title = excluded.title,
          source_created_at = excluded.source_created_at,
          source_updated_at = excluded.source_updated_at,
          raw_text = excluded.raw_text,
          checksum = excluded.checksum,
          updated_at = excluded.updated_at
        """,
        (
            document_id, row["project_id"], source_type, source_ref, str(title),
            source_created_at, source_updated_at, text, checksum, now, now,
        ),
    )
    existing = conn.execute(
        "SELECT id FROM chunks_v2 WHERE document_id = ? AND chunk_index = 0",
        (document_id,),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE chunks_v2
            SET section_path = ?,
                chunk_text = ?,
                context_prefix = NULL,
                retrieval_text = ?,
                embedding = COALESCE(?, embedding),
                raw_chunk_type = ?,
                normalized_chunk_type = ?,
                source_created_at = ?,
                source_updated_at = ?,
                valid_to = NULL,
                is_current = 1,
                metadata_json = ?
            WHERE document_id = ? AND chunk_index = 0
            """,
            (
                str(section_path), text, text, embedding_blob,
                row["chunk_type"], normalize_chunk_type(str(row["chunk_type"])),
                source_created_at, source_updated_at, metadata_json, document_id,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO chunks_v2
              (id, project_id, document_id, chunk_index, section_path,
               chunk_text, context_prefix, retrieval_text, embedding,
               raw_chunk_type, normalized_chunk_type,
               source_created_at, source_updated_at,
               valid_from, is_current, created_at, metadata_json)
            VALUES (?, ?, ?, 0, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                chunk_id, row["project_id"], document_id, str(section_path),
                text, text, embedding_blob,
                row["chunk_type"], normalize_chunk_type(str(row["chunk_type"])),
                source_created_at, source_updated_at, source_updated_at or now, now,
                metadata_json,
            ),
        )
    return True


def _ensure_metadata_column(conn: sqlite3.Connection) -> None:
    has_metadata = conn.execute(
        "SELECT COUNT(*) FROM pragma_table_info('chunks_v2') WHERE name = 'metadata_json'"
    ).fetchone()[0]
    if not has_metadata:
        conn.execute("ALTER TABLE chunks_v2 ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")


def bridge_project_memory(
    project_id: str,
    *,
    limit: int | None = None,
    generate_embedding: bool = False,
    conn: sqlite3.Connection | None = None,
) -> BridgeStats:
    own = conn is None
    if own:
        from ._common import db_connect

        conn = db_connect()
    assert conn is not None
    stats = BridgeStats()
    try:
        sql = """
            SELECT id FROM memory_chunks
            WHERE project_id = ?
              AND chunk_type != 'source_status'
              AND coalesce(json_extract(metadata_json, '$.memory_tier'), '') != 'working'
            ORDER BY created_at ASC
        """
        params: list[Any] = [project_id]
        if limit is not None and limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        ids = [r[0] for r in conn.execute(sql, params).fetchall()]
        stats.examined = len(ids)
        for mid in ids:
            ok = bridge_memory_chunk(conn, str(mid), generate_embedding=generate_embedding)
            if ok:
                stats.bridged += 1
            else:
                stats.skipped += 1
        stats.embedding_used = bool(generate_embedding and emb_mod.is_available())
        if own:
            conn.commit()
        return stats
    finally:
        if own:
            conn.close()
