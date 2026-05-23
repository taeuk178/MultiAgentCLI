"""Session delta/rollup extraction.

Rollup processes bounded event batches and advances an extract_state cursor in
the same transaction as search entry inserts. This keeps repeated runs from
creating near-duplicate rich memories without relying on text dedup.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ._common import db_connect, now_iso


DEFAULT_BATCH_EVENTS = int(os.environ.get("IMPRINT_ROLLUP_BATCH_EVENTS") or "24")
DEFAULT_MAX_CHARS = int(os.environ.get("IMPRINT_ROLLUP_MAX_CHARS") or "12000")
DEFAULT_STALE_MINUTES = int(os.environ.get("IMPRINT_ROLLUP_STALE_MINUTES") or "30")
DEFAULT_MAX_STALE_SESSIONS = int(os.environ.get("IMPRINT_ROLLUP_MAX_STALE_SESSIONS") or "3")


@dataclass
class RollupStats:
    project_id: str
    session_id: str = ""
    batches: int = 0
    events_examined: int = 0
    events_processed: int = 0
    chunks_extracted: int = 0
    entries_inserted: int = 0
    cursor_created_at: str | None = None
    cursor_event_id: str | None = None
    remaining: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "session_id": self.session_id,
            "batches": self.batches,
            "events_examined": self.events_examined,
            "events_processed": self.events_processed,
            "chunks_extracted": self.chunks_extracted,
            "entries_inserted": self.entries_inserted,
            "cursor_created_at": self.cursor_created_at,
            "cursor_event_id": self.cursor_event_id,
            "remaining": self.remaining,
        }


def _cursor(conn: sqlite3.Connection, project_id: str, session_id: str) -> tuple[str | None, str | None]:
    row = conn.execute(
        """
        SELECT last_created_at, last_event_id
        FROM extract_state
        WHERE project_id = ? AND session_id = ?
        """,
        (project_id, session_id),
    ).fetchone()
    if not row:
        return None, None
    return row["last_created_at"], row["last_event_id"]


def _event_rows(
    conn: sqlite3.Connection,
    project_id: str,
    session_id: str,
    *,
    batch_events: int,
) -> list[sqlite3.Row]:
    last_created_at, last_event_id = _cursor(conn, project_id, session_id)
    params: list[Any] = [project_id, session_id]
    cursor_clause = ""
    if last_created_at and last_event_id:
        cursor_clause = """
          AND (
            e.created_at > ?
            OR (e.created_at = ? AND e.id > ?)
          )
        """
        params.extend([last_created_at, last_created_at, last_event_id])
    params.append(batch_events)
    return conn.execute(
        f"""
        SELECT e.id, e.kind, e.text_clean, e.created_at
        FROM events e
        WHERE e.project_id = ?
          AND json_extract(e.metadata_json, '$.session_id') = ?
          AND e.noise = 0
          {cursor_clause}
        ORDER BY e.created_at ASC, e.id ASC
        LIMIT ?
        """,
        params,
    ).fetchall()


def _bounded_rows(rows: list[sqlite3.Row], max_chars: int) -> list[sqlite3.Row]:
    selected: list[sqlite3.Row] = []
    total = 0
    for row in rows:
        text = row["text_clean"] or ""
        next_total = total + len(text)
        if selected and next_total > max_chars:
            break
        selected.append(row)
        total = next_total
    return selected


def _transcript(rows: list[sqlite3.Row]) -> str:
    lines: list[str] = []
    for row in rows:
        role = "assistant" if row["kind"] == "llm_response" else "user"
        text = (row["text_clean"] or "").strip()
        if not text:
            continue
        lines.append(f"[{role} {row['created_at']} {row['id']}]\n{text}")
    return "\n\n".join(lines)


def _last_assistant_id(rows: list[sqlite3.Row]) -> str | None:
    for row in reversed(rows):
        if row["kind"] == "llm_response":
            return row["id"]
    return rows[-1]["id"] if rows else None


def _advance_cursor(
    conn: sqlite3.Connection,
    project_id: str,
    session_id: str,
    row: sqlite3.Row,
) -> None:
    conn.execute(
        """
        INSERT INTO extract_state
          (project_id, session_id, last_created_at, last_event_id, last_rolled_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(project_id, session_id) DO UPDATE SET
          last_created_at = excluded.last_created_at,
          last_event_id = excluded.last_event_id,
          last_rolled_at = excluded.last_rolled_at
        """,
        (project_id, session_id, row["created_at"], row["id"], now_iso()),
    )


def rollup_session_once(
    project_id: str,
    session_id: str,
    *,
    batch_events: int = DEFAULT_BATCH_EVENTS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> RollupStats:
    from ingestion import extract_chunks_from_response, insert_extracted_chunk

    stats = RollupStats(project_id=project_id, session_id=session_id)
    conn = db_connect()
    try:
        rows = _event_rows(conn, project_id, session_id, batch_events=batch_events)
        stats.events_examined = len(rows)
        rows = _bounded_rows(rows, max_chars)
    finally:
        conn.close()

    if not rows:
        return stats

    transcript = _transcript(rows)
    chunks = extract_chunks_from_response(transcript, mode="rich")
    stats.chunks_extracted = len(chunks)
    source_event_id = _last_assistant_id(rows)
    first_id = rows[0]["id"]
    last = rows[-1]
    last_id = last["id"]
    last_created_at = last["created_at"]

    conn = db_connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        expected_rows = _event_rows(conn, project_id, session_id, batch_events=batch_events)
        expected_rows = _bounded_rows(expected_rows, max_chars)
        if [r["id"] for r in expected_rows] != [r["id"] for r in rows]:
            conn.rollback()
            return stats
        for chunk in chunks:
            inserted = insert_extracted_chunk(
                conn,
                project_id,
                source_event_id,
                chunk["chunk_type"],
                chunk["text"],
                chunk.get("keywords") or [],
                reason=chunk.get("reason"),
                files=chunk.get("files"),
                symbols=chunk.get("symbols"),
                alternatives=chunk.get("alternatives"),
                tests=chunk.get("tests"),
                metadata_extra={
                    "rolled": True,
                    "rollup": True,
                    "session_id": session_id,
                    "event_range": [first_id, last_id],
                    "event_range_created_at": [rows[0]["created_at"], last_created_at],
                },
            )
            if inserted:
                stats.entries_inserted += 1
        _advance_cursor(conn, project_id, session_id, last)
        conn.commit()
        stats.batches = 1
        stats.events_processed = len(rows)
        stats.cursor_created_at = last_created_at
        stats.cursor_event_id = last_id
        stats.remaining = len(rows) < stats.events_examined
        return stats
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def merge_stats(left: RollupStats, right: RollupStats) -> RollupStats:
    left.batches += right.batches
    left.events_examined += right.events_examined
    left.events_processed += right.events_processed
    left.chunks_extracted += right.chunks_extracted
    left.entries_inserted += right.entries_inserted
    left.cursor_created_at = right.cursor_created_at or left.cursor_created_at
    left.cursor_event_id = right.cursor_event_id or left.cursor_event_id
    left.remaining = right.remaining
    return left


def rollup_session(
    project_id: str,
    session_id: str,
    *,
    all_batches: bool = False,
    batch_events: int = DEFAULT_BATCH_EVENTS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> RollupStats:
    total = RollupStats(project_id=project_id, session_id=session_id)
    while True:
        stats = rollup_session_once(
            project_id,
            session_id,
            batch_events=batch_events,
            max_chars=max_chars,
        )
        merge_stats(total, stats)
        if not all_batches or stats.events_processed == 0:
            break
    return total


def latest_session(project_id: str) -> str:
    conn = db_connect()
    try:
        row = conn.execute(
            """
            SELECT json_extract(metadata_json, '$.session_id') AS session_id
            FROM events
            WHERE project_id = ?
              AND COALESCE(json_extract(metadata_json, '$.session_id'), '') != ''
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        return str(row["session_id"] or "") if row else ""
    finally:
        conn.close()


def stale_sessions(
    project_id: str,
    *,
    exclude_session: str = "",
    stale_minutes: int = DEFAULT_STALE_MINUTES,
    max_sessions: int = DEFAULT_MAX_STALE_SESSIONS,
) -> list[str]:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = db_connect()
    try:
        params: list[Any] = [project_id, cutoff]
        exclude_clause = ""
        if exclude_session:
            exclude_clause = "AND s.session_id != ?"
            params.append(exclude_session)
        params.append(max_sessions)
        rows = conn.execute(
            f"""
            WITH session_events AS (
              SELECT
                json_extract(e.metadata_json, '$.session_id') AS session_id,
                e.id AS last_event_id,
                e.created_at AS last_created_at,
                ROW_NUMBER() OVER (
                  PARTITION BY json_extract(e.metadata_json, '$.session_id')
                  ORDER BY e.created_at DESC, e.id DESC
                ) AS rn
              FROM events e
              WHERE e.project_id = ?
                AND e.noise = 0
                AND COALESCE(json_extract(e.metadata_json, '$.session_id'), '') != ''
            )
            SELECT s.session_id
            FROM session_events s
            LEFT JOIN extract_state x
              ON x.project_id = ?
             AND x.session_id = s.session_id
            WHERE s.rn = 1
              AND s.last_created_at <= ?
              {exclude_clause}
              AND (
                x.last_created_at IS NULL
                OR s.last_created_at > x.last_created_at
                OR (s.last_created_at = x.last_created_at AND s.last_event_id > x.last_event_id)
              )
            ORDER BY s.last_created_at ASC
            LIMIT ?
            """,
            [project_id, *params],
        ).fetchall()
        return [str(r["session_id"]) for r in rows if r["session_id"]]
    finally:
        conn.close()


def rollup_stale(
    project_id: str,
    *,
    exclude_session: str = "",
    max_sessions: int = DEFAULT_MAX_STALE_SESSIONS,
    all_batches: bool = False,
) -> dict[str, Any]:
    sessions = stale_sessions(
        project_id,
        exclude_session=exclude_session,
        max_sessions=max_sessions,
    )
    results = [
        rollup_session(project_id, sid, all_batches=all_batches).to_dict()
        for sid in sessions
    ]
    return {
        "project_id": project_id,
        "sessions": sessions,
        "results": results,
        "entries_inserted": sum(int(r.get("entries_inserted") or 0) for r in results),
    }
