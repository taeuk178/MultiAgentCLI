"""append-only ingest queue. enqueue / claim / complete / drain.

queue payload 는 JSON. status: pending → claimed → done | failed.
priority: 낮을수록 먼저 처리 (1=높음, 5=중간 기본, 9=낮음).
attempt_count 는 retry 시 increment, 일정 횟수 초과 시 호출자가 dead-letter 처리.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable

from ._common import db_connect, log, new_id, now_iso

# Async job priority map. Lower number drains first.
# J1/J2 are reserved/high-priority ingestion phases; active dispatch currently enqueues J4/J5/J6.
PRIORITY_J2_EXTRACT = 1
PRIORITY_J1_FETCH = 1
PRIORITY_J5_SUMMARY = 5
PRIORITY_J6_CONTRADICTION = 5
PRIORITY_J4_ENTITY = 9
PRIORITY_J3_WARM = 9


def enqueue(
    project_id: str,
    payload: dict[str, Any],
    *,
    priority: int = 5,
    conn: sqlite3.Connection | None = None,
) -> str:
    own = conn is None
    if own:
        conn = db_connect()
    qid = new_id()
    try:
        conn.execute(
            """
            INSERT INTO ingest_queue (id, project_id, payload_json, status, priority, created_at)
            VALUES (?, ?, ?, 'pending', ?, ?)
            """,
            (qid, project_id, json.dumps(payload, ensure_ascii=False), priority, now_iso()),
        )
    finally:
        if own:
            conn.close()
    return qid


def _claim_one(conn: sqlite3.Connection, project_id: str | None) -> sqlite3.Row | None:
    """priority 낮은 순 → 같은 priority 면 오래된 순으로 한 건 claim.

    UPDATE ... WHERE id = (SELECT ...) 단일 SQL 로 race 회피.
    polling worker 다중일 때도 같은 row 를 두 번 claim 안 함.
    """
    where_extra = " AND project_id = ?" if project_id else ""
    params: tuple = (now_iso(),)
    select_params: tuple = (project_id,) if project_id else ()
    cur = conn.execute(
        f"""
        UPDATE ingest_queue
        SET status = 'claimed', claimed_at = ?, attempt_count = attempt_count + 1
        WHERE id = (
            SELECT id FROM ingest_queue
            WHERE status = 'pending'{where_extra}
            ORDER BY priority, created_at
            LIMIT 1
        )
        RETURNING id, project_id, payload_json, attempt_count
        """,
        params + select_params,
    )
    row = cur.fetchone()
    return row


def complete(qid: str, conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    if own:
        conn = db_connect()
    try:
        conn.execute(
            "UPDATE ingest_queue SET status = 'done', completed_at = ? WHERE id = ?",
            (now_iso(), qid),
        )
    finally:
        if own:
            conn.close()


def fail(qid: str, error: str, conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    if own:
        conn = db_connect()
    try:
        conn.execute(
            "UPDATE ingest_queue SET status = 'failed', last_error = ?, completed_at = ? WHERE id = ?",
            (error[:500], now_iso(), qid),
        )
    finally:
        if own:
            conn.close()


def drain(
    handler: Callable[[dict[str, Any]], None],
    project_id: str | None = None,
    max_items: int = 100,
) -> dict[str, int]:
    """pending 항목을 순차적으로 claim → handler 호출 → complete/fail.

    handler 가 raise 하면 fail 로 마킹하고 다음 항목 진행. 한 번 호출에 max_items 처리.
    inline 모드(hook 종료 직전 호출) 에서 무한 루프 방지를 위해 cap 필수.
    """
    stats = {"done": 0, "failed": 0, "claimed": 0}
    conn = db_connect()
    try:
        for _ in range(max_items):
            row = _claim_one(conn, project_id)
            if row is None:
                break
            stats["claimed"] += 1
            qid = row["id"]
            try:
                payload = json.loads(row["payload_json"])
                handler(payload)
                complete(qid, conn=conn)
                stats["done"] += 1
            except Exception as exc:  # 호출자가 던지는 모든 에러 흡수
                log("ERROR", f"ingest drain failed qid={qid} err={exc!r}")
                fail(qid, repr(exc), conn=conn)
                stats["failed"] += 1
    finally:
        conn.close()
    return stats
