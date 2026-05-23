"""One-shot migration from memory_chunks/documents/chunks_v2 to search_entries."""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from ._common import IMPRINT_DB, new_id, now_iso
from .entries import stable_text_hash
from .normalize import normalize_chunk_type


SCHEMA = Path(__file__).resolve().parents[1] / "schema.sql"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
        (name,),
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _metadata(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _origin_from_memory(metadata: dict[str, Any]) -> str:
    source = str(metadata.get("source") or metadata.get("source_type") or "")
    if source in {"slack", "notion"}:
        return "source_document"
    if source == "llm_response" or metadata.get("evidence_level") == "assistant_extracted":
        return "assistant_extract"
    return "manual_remember"


def _backup_path(db_path: Path) -> Path:
    stamp = now_iso().replace(":", "").replace("-", "").replace("Z", "")
    return db_path.with_name(f"{db_path.name}.backup-search-entries-{stamp}")


def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))


def migrate(db_path: Path | None = None) -> dict[str, Any]:
    db_path = db_path or IMPRINT_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        backup = _backup_path(db_path)
        shutil.copy2(db_path, backup)
    else:
        backup = None

    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        legacy = {
            "documents": _table_exists(conn, "documents"),
            "chunks_v2": _table_exists(conn, "chunks_v2"),
            "memory_chunks": _table_exists(conn, "memory_chunks"),
            "summaries": _table_exists(conn, "summaries"),
            "chunk_entities": _table_exists(conn, "chunk_entities"),
            "contradictions": _table_exists(conn, "contradictions")
            and "chunk_a_id" in _columns(conn, "contradictions"),
            "summary_links": _table_exists(conn, "summary_links")
            and _table_exists(conn, "summaries"),
        }
        if legacy["contradictions"]:
            conn.execute("ALTER TABLE contradictions RENAME TO contradictions_legacy")
        if legacy["summary_links"]:
            conn.execute("ALTER TABLE summary_links RENAME TO summary_links_legacy")

        _apply_schema(conn)
        conn.execute("PRAGMA foreign_keys = OFF")

        stats: dict[str, Any] = {
            "backup": str(backup) if backup else None,
            "source_documents": 0,
            "entries_from_chunks": 0,
            "entries_from_memory": 0,
            "search_summaries": 0,
            "entry_entities": 0,
            "summary_links": 0,
            "contradictions": 0,
            "dropped_legacy": [],
        }

        if legacy["documents"]:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO source_documents
                  (id, project_id, source_type, source_ref, title, author,
                   source_created_at, source_updated_at, raw_text, checksum,
                   is_deleted, created_at, updated_at)
                SELECT id, project_id, source_type, source_ref, title, author,
                       source_created_at, source_updated_at, raw_text, checksum,
                       is_deleted, created_at, updated_at
                FROM documents
                WHERE source_ref NOT LIKE 'memory_chunks:%'
                """
            )
            stats["source_documents"] = cur.rowcount if cur.rowcount >= 0 else 0

        if legacy["chunks_v2"]:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO search_entries
                  (id, project_id, source_document_id, source_event_id, origin,
                   raw_type, normalized_type, chunk_index, section_path, text,
                   context_prefix, retrieval_text, embedding, plan_key, feature_key,
                   source_created_at, source_updated_at, valid_from, valid_to,
                   is_current, supersedes_entry_id, pinned, metadata_json, created_at)
                SELECT c.id, c.project_id, c.document_id, NULL, 'source_document',
                       c.raw_chunk_type, c.normalized_chunk_type, c.chunk_index,
                       c.section_path, c.chunk_text, c.context_prefix, c.retrieval_text,
                       c.embedding, NULL, NULL, c.source_created_at, c.source_updated_at,
                       c.valid_from, c.valid_to, c.is_current, c.supersedes_chunk_id,
                       0, c.metadata_json, c.created_at
                FROM chunks_v2 c
                JOIN documents d ON d.id = c.document_id
                WHERE d.source_ref NOT LIKE 'memory_chunks:%'
                """
            )
            stats["entries_from_chunks"] = cur.rowcount if cur.rowcount >= 0 else 0

        if legacy["memory_chunks"]:
            rows = conn.execute(
                """
                SELECT id, project_id, source_event_id, chunk_type, text,
                       metadata_json, created_at, pinned
                FROM memory_chunks
                WHERE chunk_type != 'source_status'
                ORDER BY created_at ASC
                """
            ).fetchall()
            migrated_memory = 0
            for row in rows:
                md = _metadata(row["metadata_json"])
                if md.get("memory_tier") == "working":
                    continue
                md.setdefault("text_hash", stable_text_hash(row["text"]))
                md.setdefault("migrated_from", "memory_chunks")
                origin = _origin_from_memory(md)
                source_event_id = row["source_event_id"]
                if source_event_id and _table_exists(conn, "events"):
                    exists = conn.execute("SELECT 1 FROM events WHERE id = ?", (source_event_id,)).fetchone()
                    if exists is None:
                        source_event_id = None
                conn.execute(
                    """
                    INSERT OR IGNORE INTO search_entries
                      (id, project_id, source_document_id, source_event_id, origin,
                       raw_type, normalized_type, chunk_index, section_path, text,
                       context_prefix, retrieval_text, embedding, plan_key, feature_key,
                       source_created_at, source_updated_at, valid_from, valid_to,
                       is_current, supersedes_entry_id, pinned, metadata_json, created_at)
                    VALUES (?, ?, NULL, ?, ?, ?, ?, 0, ?, ?, NULL, ?, NULL, ?, ?,
                            ?, ?, ?, NULL, 1, NULL, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        row["project_id"],
                        source_event_id,
                        origin,
                        row["chunk_type"],
                        normalize_chunk_type(row["chunk_type"]),
                        md.get("section_path") or md.get("section_title") or row["chunk_type"],
                        row["text"],
                        row["text"],
                        md.get("plan_key"),
                        md.get("feature_key"),
                        row["created_at"],
                        md.get("fetched_at") or md.get("write_ts") or row["created_at"],
                        row["created_at"],
                        int(row["pinned"] or 0),
                        json.dumps(md, ensure_ascii=False),
                        row["created_at"],
                    ),
                )
                migrated_memory += 1
            stats["entries_from_memory"] = migrated_memory

        if legacy["summaries"]:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO search_summaries
                SELECT * FROM summaries
                """
            )
            stats["search_summaries"] = cur.rowcount if cur.rowcount >= 0 else 0

        if legacy["chunk_entities"]:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO entry_entities (entry_id, entity_id, mention, confidence)
                SELECT ce.chunk_id, ce.entity_id, ce.mention, ce.confidence
                FROM chunk_entities ce
                JOIN search_entries se ON se.id = ce.chunk_id
                """
            )
            stats["entry_entities"] = cur.rowcount if cur.rowcount >= 0 else 0

        if legacy["summary_links"]:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO summary_links
                  (parent_summary_id, child_kind, child_id, rank_order, weight)
                SELECT parent_summary_id,
                       CASE WHEN child_kind = 'chunk' THEN 'entry' ELSE child_kind END,
                       child_id, rank_order, weight
                FROM summary_links_legacy
                """
            )
            stats["summary_links"] = cur.rowcount if cur.rowcount >= 0 else 0

        if legacy["contradictions"]:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO contradictions
                  (id, project_id, entity_id, scope_key, entry_a_id, entry_b_id,
                   contradiction_score, detector, status, reason, created_at, updated_at)
                SELECT id, project_id, entity_id, scope_key, chunk_a_id, chunk_b_id,
                       contradiction_score, detector, status, reason, created_at, updated_at
                FROM contradictions_legacy
                WHERE chunk_a_id IN (SELECT id FROM search_entries)
                  AND chunk_b_id IN (SELECT id FROM search_entries)
                """
            )
            stats["contradictions"] = cur.rowcount if cur.rowcount >= 0 else 0

        for fts in ("search_entries_fts", "search_summaries_fts"):
            try:
                conn.execute(f"INSERT INTO {fts}({fts}) VALUES ('rebuild')")
            except sqlite3.Error:
                pass

        drops = [
            "events_fts", "memory_chunks_fts", "chunks_v2_fts", "summaries_fts",
            "chunk_entities", "chunks_v2", "documents", "memory_chunks", "summaries",
            "contradictions_legacy", "summary_links_legacy",
        ]
        for name in drops:
            if _table_exists(conn, name):
                conn.execute(f"DROP TABLE {name}")
                stats["dropped_legacy"].append(name)
        conn.commit()
        return stats
    finally:
        conn.close()
