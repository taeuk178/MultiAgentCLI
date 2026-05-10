"""entity alias canonicalization.

자동 추출(LLM 기반) 은 별도 skill 책임 — 이 모듈은 alias 등록·정규화·query 시 매칭만 담당.
"""
from __future__ import annotations

import sqlite3

from ._common import db_connect, new_id, now_iso
from .normalize import normalize_alias


def upsert_entity(
    project_id: str,
    entity_type: str,
    canonical_name: str,
    display_name: str,
    conn: sqlite3.Connection | None = None,
) -> str:
    """canonical entity 를 만들거나 기존 row id 를 반환."""
    own = conn is None
    if own:
        conn = db_connect()
    try:
        cur = conn.execute(
            """
            SELECT id FROM entities
            WHERE project_id = ? AND entity_type = ? AND canonical_name = ?
            """,
            (project_id, entity_type, canonical_name),
        )
        row = cur.fetchone()
        if row:
            return row["id"]
        eid = new_id()
        conn.execute(
            """
            INSERT INTO entities (id, project_id, entity_type, canonical_name, display_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (eid, project_id, entity_type, canonical_name, display_name, now_iso()),
        )
        return eid
    finally:
        if own:
            conn.close()


def add_alias(
    entity_id: str,
    alias: str,
    status: str = "pending",
    confidence: float = 0.7,
    conn: sqlite3.Connection | None = None,
) -> str | None:
    """alias 를 등록. 이미 있으면 None 반환 (중복 INSERT 방지)."""
    if not alias.strip():
        return None
    own = conn is None
    if own:
        conn = db_connect()
    try:
        normalized = normalize_alias(alias)
        if not normalized:
            return None
        cur = conn.execute(
            "SELECT id FROM entity_aliases WHERE entity_id = ? AND normalized_alias = ?",
            (entity_id, normalized),
        )
        if cur.fetchone():
            return None
        aid = new_id()
        conn.execute(
            """
            INSERT INTO entity_aliases (id, entity_id, alias, normalized_alias, status, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (aid, entity_id, alias, normalized, status, confidence, now_iso()),
        )
        return aid
    finally:
        if own:
            conn.close()


def confirm_alias(alias_id: str, conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    if own:
        conn = db_connect()
    try:
        conn.execute("UPDATE entity_aliases SET status = 'confirmed' WHERE id = ?", (alias_id,))
    finally:
        if own:
            conn.close()


def reject_alias(alias_id: str, conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    if own:
        conn = db_connect()
    try:
        conn.execute("UPDATE entity_aliases SET status = 'rejected' WHERE id = ?", (alias_id,))
    finally:
        if own:
            conn.close()


def resolve_in_query(
    project_id: str,
    query_text: str,
    conn: sqlite3.Connection | None = None,
) -> list[dict]:
    """쿼리 안에 등장하는 alias → canonical entity 매칭.

    confirmed alias 만 사용. pending 은 review 통과 전이라 검색 정확도 오염 위험.
    매칭은 정규화된 alias 부분문자열 검사로 시작 — 정확도 부족이 측정으로 드러나면
    형태소/Aho-Corasick 같은 스캐너로 교체.
    """
    own = conn is None
    if own:
        conn = db_connect()
    try:
        cur = conn.execute(
            """
            SELECT a.alias, a.normalized_alias, e.id AS entity_id, e.canonical_name, e.entity_type
            FROM entity_aliases a
            JOIN entities e ON a.entity_id = e.id
            WHERE e.project_id = ? AND a.status = 'confirmed'
            """,
            (project_id,),
        )
        candidates = cur.fetchall()
        normalized_q = normalize_alias(query_text)
        hits: list[dict] = []
        seen: set[str] = set()
        for row in candidates:
            na = row["normalized_alias"]
            if na and na in normalized_q and row["entity_id"] not in seen:
                hits.append(
                    {
                        "matched_alias": row["alias"],
                        "entity_id": row["entity_id"],
                        "canonical_name": row["canonical_name"],
                        "entity_type": row["entity_type"],
                    }
                )
                seen.add(row["entity_id"])
        return hits
    finally:
        if own:
            conn.close()
