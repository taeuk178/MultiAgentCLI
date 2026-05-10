"""계층 요약 생성기 — feature / document / project.

LLM 가용 시 claude CLI 로 4~8 문장 요약을 생성. 미가용 시 deterministic concat
fallback (원문 청크의 핵심 라인 묶기). 두 경우 모두 generator 컬럼에 기록.
summary_links 로 어느 chunk / summary 가 출처인지 추적.

incremental — `regenerate_for_changed_chunks(...)` 가 영향받는 feature 만 재생성하고,
그 다음 영향받은 document, 마지막으로 project 까지 상향식 전파.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
from dataclasses import dataclass
from typing import Iterable

from . import embedding as emb_mod
from ._common import db_connect, log, new_id, now_iso

CLAUDE_BIN = os.environ.get("IMPRINT_CLAUDE_BIN") or "claude"
SUMMARY_TIMEOUT = int(os.environ.get("IMPRINT_SUMMARY_TIMEOUT") or "30")
SUMMARY_MAX_CHARS = 1200
DETERMINISTIC_MAX_LINES = 8


@dataclass
class SummaryStats:
    feature_summaries: int = 0
    document_summaries: int = 0
    project_summaries: int = 0
    used_llm: int = 0
    used_deterministic: int = 0


def _feature_key_for_chunk(row: sqlite3.Row) -> str | None:
    """feature key 휴리스틱.

    1순위: chunk_entities 의 canonical_name (가장 confidence 높은 entity).
    2순위: section_path 의 leaf node.
    3순위: document title — 거의 fallback.
    """
    if row["entity_canonical"]:
        return f"feature:{row['entity_canonical']}"
    if row["section_path"]:
        leaf = row["section_path"].split(">")[-1].strip()
        if leaf:
            return f"feature:{leaf}"
    if row["document_title"]:
        return f"feature:{row['document_title'].strip()}"
    return None


def _select_chunks_for_feature(conn: sqlite3.Connection, project_id: str, feature_key: str) -> list[sqlite3.Row]:
    """feature_key 와 매칭되는 모든 current chunk 를 회수.

    매칭 룰: chunk_entities.canonical_name 이 feature_key 의 ":" 뒤 부분과 일치하거나,
    section_path leaf 가 같거나, document title 이 같음.
    _feature_key_for_chunk 의 역치환.
    """
    target = feature_key.split(":", 1)[1] if ":" in feature_key else feature_key
    cur = conn.execute(
        """
        SELECT c.id, c.chunk_text, c.retrieval_text, c.section_path, c.normalized_chunk_type,
               c.is_current, c.source_updated_at,
               d.title AS document_title, d.source_type, d.id AS document_id,
               (SELECT e.canonical_name FROM chunk_entities ce
                JOIN entities e ON e.id = ce.entity_id
                WHERE ce.chunk_id = c.id
                ORDER BY ce.confidence DESC LIMIT 1) AS entity_canonical
        FROM chunks_v2 c
        JOIN documents d ON d.id = c.document_id
        WHERE c.project_id = ? AND c.is_current = 1
        """,
        (project_id,),
    )
    out: list[sqlite3.Row] = []
    for row in cur.fetchall():
        if _feature_key_for_chunk(row) == feature_key:
            out.append(row)
    return out


def _llm_summarize(prompt: str) -> str | None:
    if os.environ.get("IMPRINT_DISABLE_SUMMARY_LLM") == "1":
        return None
    try:
        env = os.environ.copy()
        env["IMPRINT_BYPASS_HOOKS"] = "1"
        proc = subprocess.run(
            [CLAUDE_BIN, "-p", "--model", "haiku"],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=SUMMARY_TIMEOUT,
            env=env,
        )
        if proc.returncode != 0:
            log("WARN", f"summary LLM failed rc={proc.returncode} stderr={proc.stderr[:200]!r}")
            return None
        out = proc.stdout.strip()
        return out[:SUMMARY_MAX_CHARS] if out else None
    except Exception as exc:
        log("WARN", f"summary LLM exception: {exc!r}")
        return None


def _deterministic_summarize(chunk_texts: list[str], *, max_lines: int = DETERMINISTIC_MAX_LINES) -> str:
    """LLM 없이 핵심 문장 concat. 청크의 첫 문장만 골라 dedupe."""
    seen: set[str] = set()
    lines: list[str] = []
    for t in chunk_texts:
        first = t.strip().split("\n", 1)[0].strip()
        if not first or first in seen:
            continue
        seen.add(first)
        lines.append(first)
        if len(lines) >= max_lines:
            break
    return " ".join(lines)


def _build_feature_prompt(feature_key: str, chunks: list[sqlite3.Row]) -> str:
    chunk_blob = "\n---\n".join(
        f"[{r['source_type']}] {r['section_path'] or ''}\n{r['chunk_text']}" for r in chunks
    )
    return (
        f"Summarize the following project knowledge for the feature '{feature_key}'.\n"
        "Rules:\n"
        "- 4-8 sentences in Korean.\n"
        "- '현재 기준 동작' 우선, 과거 변경은 1-2 문장으로만 언급.\n"
        "- source 간 합의/불일치 여부 명시.\n"
        "- 구현 세부보다 기능 의미 중심.\n\n"
        f"=== chunks ===\n{chunk_blob}\n\n"
        "Output the summary text only."
    )


def _upsert_summary(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    level: str,
    target_key: str,
    title: str | None,
    summary_text: str,
    generator: str,
) -> str:
    """current summary 를 upsert. 기존 current row 는 valid_to 채우고 obsolete 처리."""
    ts = now_iso()
    retrieval_text = f"[{level}:{target_key}] {summary_text}"
    blob: bytes | None = None
    if emb_mod.is_available():
        blob = emb_mod.embed_text(retrieval_text)

    conn.execute(
        """
        UPDATE summaries SET valid_to = ?, is_current = 0
        WHERE project_id = ? AND level = ? AND target_key = ? AND is_current = 1
        """,
        (ts, project_id, level, target_key),
    )
    sid = new_id()
    conn.execute(
        """
        INSERT INTO summaries
          (id, project_id, level, target_key, title, summary_text, retrieval_text,
           embedding, source_chunk_count, source_summary_count,
           valid_from, is_current, generator, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 1, ?, ?)
        """,
        (sid, project_id, level, target_key, title, summary_text, retrieval_text,
         blob, ts, generator, ts),
    )
    return sid


def _replace_links(
    conn: sqlite3.Connection,
    parent_summary_id: str,
    children: list[tuple[str, str, float]],
) -> None:
    """summary_links 를 parent 에 대해 통째로 갱신."""
    conn.execute(
        "DELETE FROM summary_links WHERE parent_summary_id = ?",
        (parent_summary_id,),
    )
    for rank, (kind, child_id, weight) in enumerate(children):
        conn.execute(
            """
            INSERT INTO summary_links (parent_summary_id, child_kind, child_id, rank_order, weight)
            VALUES (?, ?, ?, ?, ?)
            """,
            (parent_summary_id, kind, child_id, rank, weight),
        )


def regenerate_feature(
    project_id: str,
    feature_key: str,
    *,
    use_llm: bool = True,
    conn: sqlite3.Connection | None = None,
) -> tuple[str | None, bool]:
    """feature_key 를 재생성. (summary_id, used_llm) 반환. chunks 가 비면 (None, False)."""
    own = conn is None
    if own:
        conn = db_connect()
    try:
        chunks = _select_chunks_for_feature(conn, project_id, feature_key)
        if not chunks:
            # 기존 summary 가 있다면 obsolete 처리.
            conn.execute(
                """
                UPDATE summaries SET is_current = 0, valid_to = ?
                WHERE project_id = ? AND level = 'feature' AND target_key = ? AND is_current = 1
                """,
                (now_iso(), project_id, feature_key),
            )
            return None, False

        summary_text: str | None = None
        used_llm = False
        if use_llm:
            summary_text = _llm_summarize(_build_feature_prompt(feature_key, chunks))
            used_llm = summary_text is not None
        if not summary_text:
            summary_text = _deterministic_summarize([r["chunk_text"] for r in chunks])

        sid = _upsert_summary(
            conn,
            project_id=project_id, level="feature", target_key=feature_key,
            title=feature_key.split(":", 1)[-1],
            summary_text=summary_text,
            generator="llm" if used_llm else "deterministic",
        )
        # source_chunk_count 갱신.
        conn.execute(
            "UPDATE summaries SET source_chunk_count = ? WHERE id = ?",
            (len(chunks), sid),
        )
        children = [("chunk", r["id"], 1.0) for r in chunks]
        _replace_links(conn, sid, children)
        return sid, used_llm
    finally:
        if own:
            conn.close()


def _document_feature_keys(conn: sqlite3.Connection, project_id: str, document_id: str) -> list[str]:
    """document 안의 모든 chunk 에서 feature key 집합 도출."""
    cur = conn.execute(
        """
        SELECT c.id, c.section_path,
               d.title AS document_title,
               (SELECT e.canonical_name FROM chunk_entities ce
                JOIN entities e ON e.id = ce.entity_id
                WHERE ce.chunk_id = c.id
                ORDER BY ce.confidence DESC LIMIT 1) AS entity_canonical
        FROM chunks_v2 c
        JOIN documents d ON d.id = c.document_id
        WHERE c.project_id = ? AND c.document_id = ? AND c.is_current = 1
        """,
        (project_id, document_id),
    )
    keys: list[str] = []
    seen: set[str] = set()
    for row in cur.fetchall():
        k = _feature_key_for_chunk(row)
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    return keys


def regenerate_document(
    project_id: str,
    document_id: str,
    *,
    use_llm: bool = True,
    conn: sqlite3.Connection | None = None,
) -> str | None:
    """document summary 재생성. 하위 feature summary id 를 summary_links 로 묶음."""
    own = conn is None
    if own:
        conn = db_connect()
    try:
        feature_keys = _document_feature_keys(conn, project_id, document_id)
        feature_summary_ids: list[str] = []
        for fk in feature_keys:
            cur = conn.execute(
                """
                SELECT id FROM summaries
                WHERE project_id = ? AND level = 'feature' AND target_key = ? AND is_current = 1
                """,
                (project_id, fk),
            )
            row = cur.fetchone()
            if row:
                feature_summary_ids.append(row["id"])

        # feature summary 가 없으면 chunk 를 직접 모음.
        if not feature_summary_ids:
            cur = conn.execute(
                "SELECT id, chunk_text FROM chunks_v2 WHERE project_id = ? AND document_id = ? AND is_current = 1",
                (project_id, document_id),
            )
            chunk_rows = cur.fetchall()
            if not chunk_rows:
                conn.execute(
                    """
                    UPDATE summaries SET is_current = 0, valid_to = ?
                    WHERE project_id = ? AND level = 'document' AND target_key = ? AND is_current = 1
                    """,
                    (now_iso(), project_id, f"document:{document_id}"),
                )
                return None
            text = _deterministic_summarize([r["chunk_text"] for r in chunk_rows])
            sid = _upsert_summary(
                conn, project_id=project_id, level="document",
                target_key=f"document:{document_id}",
                title=None, summary_text=text, generator="deterministic",
            )
            _replace_links(conn, sid, [("chunk", r["id"], 1.0) for r in chunk_rows])
            return sid

        # feature summary 들의 본문을 모아 document summary 작성.
        cur = conn.execute(
            f"SELECT id, summary_text FROM summaries WHERE id IN ({','.join('?' * len(feature_summary_ids))})",
            tuple(feature_summary_ids),
        )
        feat_rows = cur.fetchall()
        prompt = (
            f"Summarize the following feature summaries into a document-level summary in Korean.\n"
            "Rules: 5-10 sentences. PRD 면 기능 정의/예외/조건, 회의록이면 결정/변경 위주. \n\n"
            + "\n---\n".join(r["summary_text"] for r in feat_rows)
            + "\nOutput the summary only."
        )
        text: str | None = None
        used_llm = False
        if use_llm:
            text = _llm_summarize(prompt)
            used_llm = text is not None
        if not text:
            text = _deterministic_summarize([r["summary_text"] for r in feat_rows])

        sid = _upsert_summary(
            conn, project_id=project_id, level="document",
            target_key=f"document:{document_id}",
            title=None, summary_text=text,
            generator="llm" if used_llm else "deterministic",
        )
        conn.execute(
            "UPDATE summaries SET source_summary_count = ? WHERE id = ?",
            (len(feat_rows), sid),
        )
        _replace_links(conn, sid, [("summary", fid, 1.0) for fid in feature_summary_ids])
        return sid
    finally:
        if own:
            conn.close()


def regenerate_project(
    project_id: str,
    *,
    use_llm: bool = True,
    conn: sqlite3.Connection | None = None,
) -> str | None:
    """project summary — 모든 current document summary 를 묶음."""
    own = conn is None
    if own:
        conn = db_connect()
    try:
        cur = conn.execute(
            """
            SELECT id, summary_text FROM summaries
            WHERE project_id = ? AND level = 'document' AND is_current = 1
            ORDER BY updated_at DESC
            """,
            (project_id,),
        )
        doc_rows = cur.fetchall()
        if not doc_rows:
            conn.execute(
                """
                UPDATE summaries SET is_current = 0, valid_to = ?
                WHERE project_id = ? AND level = 'project' AND target_key = ? AND is_current = 1
                """,
                (now_iso(), project_id, f"project:{project_id}"),
            )
            return None

        prompt = (
            "Summarize the following document summaries into a project-level summary in Korean.\n"
            "Rules: 6-12 sentences. 전체 프로젝트 주요 기능 축, 현재 유효 정책 중심,\n"
            "문서 간 변경 흐름은 간단히 언급, 너무 자세한 구현 설명 금지.\n\n"
            + "\n---\n".join(r["summary_text"] for r in doc_rows)
            + "\nOutput the summary only."
        )
        text: str | None = None
        used_llm = False
        if use_llm:
            text = _llm_summarize(prompt)
            used_llm = text is not None
        if not text:
            text = _deterministic_summarize([r["summary_text"] for r in doc_rows])

        sid = _upsert_summary(
            conn, project_id=project_id, level="project",
            target_key=f"project:{project_id}",
            title=None, summary_text=text,
            generator="llm" if used_llm else "deterministic",
        )
        conn.execute(
            "UPDATE summaries SET source_summary_count = ? WHERE id = ?",
            (len(doc_rows), sid),
        )
        _replace_links(conn, sid, [("summary", r["id"], 1.0) for r in doc_rows])
        return sid
    finally:
        if own:
            conn.close()


def regenerate_for_document(
    project_id: str,
    document_id: str,
    *,
    use_llm: bool = True,
    propagate_project: bool = True,
) -> SummaryStats:
    """document 변경 → 영향 feature → document → project 상향식 재생성."""
    stats = SummaryStats()
    conn = db_connect()
    try:
        feature_keys = _document_feature_keys(conn, project_id, document_id)
        for fk in feature_keys:
            sid, used = regenerate_feature(project_id, fk, use_llm=use_llm, conn=conn)
            if sid:
                stats.feature_summaries += 1
                stats.used_llm += int(used)
                stats.used_deterministic += int(not used)
        sid = regenerate_document(project_id, document_id, use_llm=use_llm, conn=conn)
        if sid:
            stats.document_summaries += 1
        if propagate_project:
            sid = regenerate_project(project_id, use_llm=use_llm, conn=conn)
            if sid:
                stats.project_summaries += 1
    finally:
        conn.close()
    return stats


def list_drilldown_chunks(
    parent_summary_id: str,
    limit: int = 3,
    conn: sqlite3.Connection | None = None,
) -> list[sqlite3.Row]:
    """summary 의 child_kind=chunk link 1~3개 조회 — GROUND 단계 grounding."""
    own = conn is None
    if own:
        conn = db_connect()
    try:
        cur = conn.execute(
            """
            SELECT c.id, c.chunk_text, c.section_path, c.is_current, c.source_updated_at,
                   d.source_type, d.title AS document_title
            FROM summary_links sl
            JOIN chunks_v2 c ON c.id = sl.child_id
            JOIN documents d ON d.id = c.document_id
            WHERE sl.parent_summary_id = ? AND sl.child_kind = 'chunk'
            ORDER BY sl.rank_order
            LIMIT ?
            """,
            (parent_summary_id, limit),
        )
        return list(cur.fetchall())
    finally:
        if own:
            conn.close()
