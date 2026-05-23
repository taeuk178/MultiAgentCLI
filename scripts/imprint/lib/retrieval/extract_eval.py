"""Offline extraction eval harness.

The harness is intentionally extractor-agnostic: callers pass a function that
turns assistant text into chunk dictionaries. This lets us compare the current
flat extractor with future decision-rich extractors against the same fixtures.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .retrieve import retrieve


Extractor = Callable[[str], list[dict[str, Any]]]


@dataclass
class EvalHit:
    query: str
    expected_terms: list[str]
    matched: bool
    candidate_ids: list[str]


def _insert_event(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    project_id: str,
    kind: str,
    text: str,
    created_at: str,
    session_id: str = "",
) -> None:
    metadata = {"session_id": session_id} if session_id else {}
    conn.execute(
        """
        INSERT OR REPLACE INTO events
          (id, project_id, source, kind, text_clean, metadata_json, noise, created_at)
        VALUES (?, ?, 'eval', ?, ?, ?, 0, ?)
        """,
        (event_id, project_id, kind, text, json.dumps(metadata, ensure_ascii=False), created_at),
    )


def seed_events_and_extract(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    fixture: dict[str, Any],
    extractor: Extractor,
) -> dict[str, int]:
    """Seed synthetic events, run extractor on assistant turns, and store chunks."""
    from ingestion import insert_extracted_chunk

    inserted = 0
    assistant_turns = 0
    session_id = str(fixture.get("session_id") or fixture.get("id") or "eval-session")
    for idx, turn in enumerate(fixture.get("turns") or []):
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "")
        text = str(turn.get("text") or "")
        if role not in {"user", "assistant"} or not text:
            continue
        event_id = f"{fixture.get('id', 'fixture')}-{idx}-{role}"
        _insert_event(
            conn,
            event_id=event_id,
            project_id=project_id,
            kind="user_message" if role == "user" else "llm_response",
            text=text,
            created_at=f"2026-05-24T00:{idx:02d}:00Z",
            session_id=session_id,
        )
        if role != "assistant":
            continue
        assistant_turns += 1
        for chunk in extractor(text):
            if not isinstance(chunk, dict):
                continue
            chunk_type = str(chunk.get("chunk_type") or "")
            chunk_text = str(chunk.get("text") or "").strip()
            keywords = chunk.get("keywords") if isinstance(chunk.get("keywords"), list) else []
            if not chunk_type or not chunk_text:
                continue
            if insert_extracted_chunk(
                conn,
                project_id,
                event_id,
                chunk_type,
                chunk_text,
                [str(k) for k in keywords],
                reason=chunk.get("reason"),
                files=chunk.get("files"),
                symbols=chunk.get("symbols"),
                alternatives=chunk.get("alternatives"),
                tests=chunk.get("tests"),
            ):
                inserted += 1
    return {"assistant_turns": assistant_turns, "inserted": inserted}


def score_questions(
    *,
    project_id: str,
    questions: list[dict[str, Any]],
    top_k: int = 5,
) -> list[EvalHit]:
    hits: list[EvalHit] = []
    for question in questions:
        query = str(question.get("query") or "")
        expected_terms = [str(t) for t in (question.get("expected_terms") or []) if str(t)]
        result = retrieve(query, project_id, top_k=top_k)
        haystack = "\n".join(
            [c.text or "" for c in result.candidates]
            + [c.retrieval_text or "" for c in result.candidates]
            + [
                json.dumps(getattr(c, "metadata", {}) or {}, ensure_ascii=False)
                for c in result.candidates
            ]
        )
        matched = bool(expected_terms) and all(term in haystack for term in expected_terms)
        hits.append(
            EvalHit(
                query=query,
                expected_terms=expected_terms,
                matched=matched,
                candidate_ids=[c.entry_id for c in result.candidates],
            )
        )
    return hits


def run_eval(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    fixture: dict[str, Any],
    extractor: Extractor,
    top_k: int = 5,
) -> dict[str, Any]:
    stats = seed_events_and_extract(
        conn,
        project_id=project_id,
        fixture=fixture,
        extractor=extractor,
    )
    conn.commit()
    hits = score_questions(
        project_id=project_id,
        questions=list(fixture.get("questions") or []),
        top_k=top_k,
    )
    return {
        "fixture_id": fixture.get("id"),
        "assistant_turns": stats["assistant_turns"],
        "inserted": stats["inserted"],
        "questions": [
            {
                "query": hit.query,
                "expected_terms": hit.expected_terms,
                "matched": hit.matched,
                "candidate_ids": hit.candidate_ids,
            }
            for hit in hits
        ],
        "matched": sum(1 for hit in hits if hit.matched),
        "total": len(hits),
    }
