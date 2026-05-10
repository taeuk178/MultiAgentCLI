"""versioning 헬퍼.

새 청크가 기존 청크를 대체할 때 valid_to / is_current / supersedes_chunk_id 갱신.
자동 supersede 결정은 안 함 — 호출자가 명시적으로 supersedes_chunk_id 지정.
정규식 트리거가 매칭되면 후보를 제시할 뿐 자동 적용은 X.
"""
from __future__ import annotations

import sqlite3
from typing import Iterable

from ._common import db_connect, now_iso
from .normalize import detect_supersede_signal


def mark_superseded(
    chunk_id: str,
    superseded_by: str,
    valid_to: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """chunk_id 를 superseded_by 가 대체하는 것으로 마킹."""
    own = conn is None
    if own:
        conn = db_connect()
    ts = valid_to or now_iso()
    try:
        conn.execute(
            """
            UPDATE chunks_v2
            SET valid_to = ?, is_current = 0
            WHERE id = ?
            """,
            (ts, chunk_id),
        )
        conn.execute(
            "UPDATE chunks_v2 SET supersedes_chunk_id = ?, valid_from = ? WHERE id = ?",
            (chunk_id, ts, superseded_by),
        )
    finally:
        if own:
            conn.close()


def find_supersede_candidates(
    project_id: str,
    new_chunk_text: str,
    section_path: str | None = None,
    conn: sqlite3.Connection | None = None,
    limit: int = 5,
) -> list[sqlite3.Row]:
    """새 청크 text 에 supersede 시그널이 있을 때 같은 section 의 current 청크 후보 조회.

    매칭이 없거나 시그널이 없으면 빈 리스트. 호출자가 사용자에게 후보 제시 후 명시 결정.
    """
    if not detect_supersede_signal(new_chunk_text):
        return []
    own = conn is None
    if own:
        conn = db_connect()
    try:
        if section_path:
            cur = conn.execute(
                """
                SELECT id, chunk_text, section_path, source_updated_at, created_at
                FROM chunks_v2
                WHERE project_id = ? AND is_current = 1 AND section_path = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (project_id, section_path, limit),
            )
        else:
            cur = conn.execute(
                """
                SELECT id, chunk_text, section_path, source_updated_at, created_at
                FROM chunks_v2
                WHERE project_id = ? AND is_current = 1
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (project_id, limit),
            )
        return list(cur.fetchall())
    finally:
        if own:
            conn.close()
