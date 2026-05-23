"""search_entries write/read helpers."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from . import embedding as emb_mod
from ._common import new_id, now_iso
from .normalize import normalize_chunk_type


RETRIEVAL_SURFACE_MAX_CHARS = 1500


@dataclass
class EntryStats:
    examined: int = 0
    migrated: int = 0
    skipped: int = 0
    embedding_used: bool = False


def stable_text_hash(text: str) -> str:
    normalized = " ".join((text or "").split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def metadata_dict(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def cap_retrieval_text(text: str, max_chars: int = RETRIEVAL_SURFACE_MAX_CHARS) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip()


def build_retrieval_surface(
    *,
    text: str,
    reason: str | None = None,
    files: list[str] | None = None,
    symbols: list[str] | None = None,
    max_chars: int = RETRIEVAL_SURFACE_MAX_CHARS,
) -> str:
    lines = [text.strip()]
    if reason:
        lines.append(f"Reason: {reason.strip()}")
    if files:
        lines.append("Files: " + ", ".join(v.strip() for v in files if v and v.strip()))
    if symbols:
        lines.append("Symbols: " + ", ".join(v.strip() for v in symbols if v and v.strip()))
    return cap_retrieval_text("\n".join(line for line in lines if line), max_chars=max_chars)


def dedup_exists(
    conn: sqlite3.Connection,
    project_id: str,
    *,
    source_uri: str | None,
    evidence_level: str | None,
    text_hash: str,
    source_event_id: str | None = None,
    raw_type: str | None = None,
) -> bool:
    if source_uri and evidence_level:
        row = conn.execute(
            """
            SELECT 1 FROM search_entries
            WHERE project_id = ?
              AND json_extract(metadata_json, '$.source_uri') = ?
              AND json_extract(metadata_json, '$.evidence_level') = ?
              AND json_extract(metadata_json, '$.text_hash') = ?
              AND is_current = 1
            LIMIT 1
            """,
            (project_id, source_uri, evidence_level, text_hash),
        ).fetchone()
        if row is not None:
            return True
    if source_event_id and raw_type:
        row = conn.execute(
            """
            SELECT 1 FROM search_entries
            WHERE project_id = ?
              AND source_event_id = ?
              AND raw_type = ?
              AND json_extract(metadata_json, '$.text_hash') = ?
              AND is_current = 1
            LIMIT 1
            """,
            (project_id, source_event_id, raw_type, text_hash),
        ).fetchone()
        if row is not None:
            return True
    return False


def insert_search_entry(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    origin: str,
    raw_type: str,
    text: str,
    metadata: dict[str, Any] | None = None,
    source_event_id: str | None = None,
    source_document_id: str | None = None,
    chunk_index: int | None = None,
    section_path: str | None = None,
    context_prefix: str | None = None,
    source_created_at: str | None = None,
    source_updated_at: str | None = None,
    pinned: int = 0,
    entry_id: str | None = None,
    embedding: bytes | None = None,
    generate_embedding: bool = False,
    retrieval_text: str | None = None,
) -> str:
    if origin == "source_document" and not source_document_id:
        raise ValueError("origin=source_document requires source_document_id")
    safe_text = text.strip()
    index_text = cap_retrieval_text(retrieval_text) if retrieval_text else (
        f"{context_prefix}\n{safe_text}" if context_prefix else safe_text
    )
    md = dict(metadata or {})
    md.setdefault("text_hash", stable_text_hash(safe_text))
    normalized_type = normalize_chunk_type(raw_type)
    if embedding is None and generate_embedding and emb_mod.is_available():
        embedding = emb_mod.embed_text(index_text)
    eid = entry_id or new_id()
    ts = now_iso()
    conn.execute(
        """
        INSERT INTO search_entries
          (id, project_id, source_document_id, source_event_id, origin,
           raw_type, normalized_type, chunk_index, section_path, text,
           context_prefix, retrieval_text, embedding, plan_key, feature_key,
           source_created_at, source_updated_at, valid_from, valid_to,
           is_current, supersedes_entry_id, pinned, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL,
                1, NULL, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          source_document_id = excluded.source_document_id,
          source_event_id = excluded.source_event_id,
          origin = excluded.origin,
          raw_type = excluded.raw_type,
          normalized_type = excluded.normalized_type,
          chunk_index = excluded.chunk_index,
          section_path = excluded.section_path,
          text = excluded.text,
          context_prefix = excluded.context_prefix,
          retrieval_text = excluded.retrieval_text,
          embedding = COALESCE(excluded.embedding, search_entries.embedding),
          plan_key = excluded.plan_key,
          feature_key = excluded.feature_key,
          source_created_at = excluded.source_created_at,
          source_updated_at = excluded.source_updated_at,
          valid_to = NULL,
          is_current = 1,
          pinned = excluded.pinned,
          metadata_json = excluded.metadata_json
        """,
        (
            eid,
            project_id,
            source_document_id,
            source_event_id,
            origin,
            raw_type,
            normalized_type,
            chunk_index,
            section_path,
            safe_text,
            context_prefix,
            index_text,
            embedding,
            md.get("plan_key"),
            md.get("feature_key"),
            source_created_at,
            source_updated_at,
            source_updated_at or ts,
            int(pinned),
            json.dumps(md, ensure_ascii=False),
            ts,
        ),
    )
    return eid
