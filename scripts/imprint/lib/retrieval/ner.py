"""LLM-driven entity mention 추출 + alias candidate mining.

명세 다이어그램의 `ENT1/ENT2` (chunk → entity mention) 와 `EA` (J4 alias mining)
의 결정적 부분을 채운다. claude CLI haiku 호출이 BG side 전제이므로 동기 경로
budget 과 무관.

추출 결과는 `entity_aliases.status='pending'` + `chunk_entities` link 로 저장 —
`/memory entities` 류 review queue skill 이 confirm/reject 까지 가져가는 경로.
auto-link 는 confidence ≥ AUTO_CONFIRM_THRESHOLD 인 경우에만 status='confirmed'
로 자동 승격.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass

from ._common import db_connect, log, new_id, now_iso
from .entity import upsert_entity, add_alias

CLAUDE_BIN = os.environ.get("IMPRINT_CLAUDE_BIN") or "claude"
NER_TIMEOUT_MS = int(os.environ.get("IMPRINT_NER_TIMEOUT_MS") or "25000")
AUTO_CONFIRM_THRESHOLD = float(os.environ.get("IMPRINT_NER_AUTO_CONFIRM") or "0.9")
NER_MAX_CHARS = 1500

# canonical_name 정규화 — 영문 식별자 스타일로 강제. 공백/특수문자 → _.
_CANON_RE = re.compile(r"[^\w가-힣]+", re.UNICODE)


@dataclass
class ExtractedMention:
    entity_type: str       # ui_element | screen | feature | api | state | experiment_flag
    canonical_name: str    # snake_case 식별자
    display_name: str      # 사람용 표시 이름 (한국어 가능)
    mention: str           # 청크 안에 등장한 실제 표현
    confidence: float


@dataclass
class NerStats:
    chunks_examined: int = 0
    chunks_skipped: int = 0     # LLM 호출 실패한 청크
    mentions_extracted: int = 0
    entities_created: int = 0
    aliases_added: int = 0
    aliases_auto_confirmed: int = 0


_PROMPT = """You are an entity extractor for Korean engineering decisions.

Given a chunk of text, extract entities (UI elements, screens, features, APIs,
states, experiment flags) that are mentioned. Output a JSON array on one line.
For each entity:
  - "entity_type": one of "ui_element"|"screen"|"feature"|"api"|"state"|"experiment_flag"
  - "canonical_name": snake_case English identifier (e.g. "test_button")
  - "display_name": Korean or original-language label (e.g. "Test 버튼")
  - "mention": the exact substring from the chunk that mentions this entity
  - "confidence": 0.0~1.0 (높을수록 확신)

Rules:
- Skip generic terms ("버튼", "기능") — only specific named entities.
- If unsure, omit. Empty array [] is acceptable.
- Output ONLY the JSON array, no prose.

Chunk:
{chunk}

JSON:"""


def _canonicalize(name: str) -> str:
    s = _CANON_RE.sub("_", name.strip().lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "entity"


def _llm_extract(chunk_text: str) -> list[ExtractedMention] | None:
    """청크에서 entity mention 추출. None 이면 LLM 호출 실패 — 호출자가 재시도 결정."""
    if os.environ.get("IMPRINT_DISABLE_NER_LLM") == "1":
        return None
    truncated = chunk_text[:NER_MAX_CHARS]
    prompt = _PROMPT.replace("{chunk}", truncated)
    try:
        env = os.environ.copy()
        env["IMPRINT_BYPASS_HOOKS"] = "1"
        proc = subprocess.run(
            [CLAUDE_BIN, "-p", "--model", "haiku"],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=NER_TIMEOUT_MS / 1000.0,
            env=env,
        )
        if proc.returncode != 0:
            log("WARN", f"NER LLM failed rc={proc.returncode} stderr={proc.stderr[:200]!r}")
            return None
    except subprocess.TimeoutExpired:
        log("WARN", "NER LLM timeout")
        return None
    except Exception as exc:
        log("WARN", f"NER LLM exception: {exc!r}")
        return None

    out = (proc.stdout or "").strip()
    if not out:
        return []
    # JSON 배열 추출 — 코드펜스나 prose 가 둘러싸도 매치.
    m = re.search(r"\[[\s\S]*\]", out)
    if not m:
        log("WARN", f"NER LLM non-JSON output: {out[:200]!r}")
        return None
    try:
        items = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        log("WARN", f"NER LLM parse failed: {exc!r} raw={out[:200]!r}")
        return None
    if not isinstance(items, list):
        return None

    valid: list[ExtractedMention] = []
    valid_types = {"ui_element", "screen", "feature", "api", "state", "experiment_flag"}
    for it in items:
        if not isinstance(it, dict):
            continue
        et = (it.get("entity_type") or "").lower()
        if et not in valid_types:
            continue
        canonical = _canonicalize(it.get("canonical_name") or it.get("display_name") or "")
        display = (it.get("display_name") or canonical).strip()
        mention = (it.get("mention") or display).strip()
        try:
            confidence = float(it.get("confidence") or 0.5)
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        if not canonical or not mention:
            continue
        valid.append(ExtractedMention(
            entity_type=et,
            canonical_name=canonical,
            display_name=display,
            mention=mention,
            confidence=confidence,
        ))
    return valid


def extract_for_chunk(
    project_id: str,
    chunk_id: str,
    *,
    use_llm: bool = True,
    conn: sqlite3.Connection | None = None,
) -> NerStats:
    """단일 chunk 의 mention 추출 → entities/entity_aliases/chunk_entities upsert.

    이미 같은 chunk_id 가 처리됐는지는 chunk_entities row 존재로 판단 — 있으면 skip.
    """
    stats = NerStats()
    own = conn is None
    if own:
        conn = db_connect()
    try:
        cur = conn.execute(
            "SELECT id, chunk_text FROM chunks_v2 WHERE id = ? AND project_id = ?",
            (chunk_id, project_id),
        )
        row = cur.fetchone()
        if not row:
            return stats

        existing = conn.execute(
            "SELECT 1 FROM chunk_entities WHERE chunk_id = ? LIMIT 1",
            (chunk_id,),
        ).fetchone()
        if existing:
            return stats  # 이미 처리됨 (다이어그램상 idempotent 보장).

        stats.chunks_examined += 1
        if not use_llm:
            return stats

        mentions = _llm_extract(row["chunk_text"])
        if mentions is None:
            stats.chunks_skipped += 1
            return stats

        for m in mentions:
            # entity upsert.
            eid_before = conn.execute(
                "SELECT id FROM entities WHERE project_id = ? AND entity_type = ? AND canonical_name = ?",
                (project_id, m.entity_type, m.canonical_name),
            ).fetchone()
            eid = upsert_entity(
                project_id=project_id,
                entity_type=m.entity_type,
                canonical_name=m.canonical_name,
                display_name=m.display_name,
                conn=conn,
            )
            if not eid_before:
                stats.entities_created += 1

            # alias upsert. confidence 가 임계 넘으면 자동 confirm — auto-link.
            status = "confirmed" if m.confidence >= AUTO_CONFIRM_THRESHOLD else "pending"
            aid = add_alias(eid, m.mention, status=status, confidence=m.confidence, conn=conn)
            if aid:
                stats.aliases_added += 1
                if status == "confirmed":
                    stats.aliases_auto_confirmed += 1

            # chunk_entities link (UNIQUE PK 라 중복 INSERT 무시).
            try:
                conn.execute(
                    "INSERT INTO chunk_entities (chunk_id, entity_id, mention, confidence) VALUES (?, ?, ?, ?)",
                    (chunk_id, eid, m.mention, m.confidence),
                )
            except sqlite3.IntegrityError:
                pass
            stats.mentions_extracted += 1
        return stats
    finally:
        if own:
            conn.close()


def extract_for_document(
    project_id: str,
    document_id: str,
    *,
    use_llm: bool = True,
    max_chunks: int = 20,
) -> NerStats:
    """document 의 모든 current chunk 에 대해 NER 수행. 누적 stats 반환."""
    aggregate = NerStats()
    conn = db_connect()
    try:
        cur = conn.execute(
            """
            SELECT id FROM chunks_v2
            WHERE project_id = ? AND document_id = ? AND is_current = 1
            ORDER BY chunk_index
            LIMIT ?
            """,
            (project_id, document_id, max_chunks),
        )
        chunk_ids = [r["id"] for r in cur.fetchall()]
        for cid in chunk_ids:
            s = extract_for_chunk(project_id, cid, use_llm=use_llm, conn=conn)
            aggregate.chunks_examined += s.chunks_examined
            aggregate.chunks_skipped += s.chunks_skipped
            aggregate.mentions_extracted += s.mentions_extracted
            aggregate.entities_created += s.entities_created
            aggregate.aliases_added += s.aliases_added
            aggregate.aliases_auto_confirmed += s.aliases_auto_confirmed
        return aggregate
    finally:
        conn.close()


def refresh_aliases(project_id: str, conn: sqlite3.Connection | None = None) -> int:
    """`EA` 노드 — 같은 entity 의 pending alias 들이 confirmed 와 합쳐질 만한지 점검.

    현재 단계는 alias 사전을 키우는 것만 — pending alias 가 confirmed alias 와
    유사 (normalized 동일) 하면 자동 confirm. 그 외엔 사용자 검토 대기.
    """
    own = conn is None
    if own:
        conn = db_connect()
    promoted = 0
    try:
        cur = conn.execute(
            """
            SELECT a.id AS pending_id, a.entity_id, a.normalized_alias
            FROM entity_aliases a
            JOIN entities e ON e.id = a.entity_id
            WHERE e.project_id = ? AND a.status = 'pending'
            """,
            (project_id,),
        )
        for row in cur.fetchall():
            same = conn.execute(
                """
                SELECT 1 FROM entity_aliases
                WHERE entity_id = ? AND normalized_alias = ? AND status = 'confirmed' LIMIT 1
                """,
                (row["entity_id"], row["normalized_alias"]),
            ).fetchone()
            if same:
                conn.execute(
                    "UPDATE entity_aliases SET status = 'confirmed' WHERE id = ?",
                    (row["pending_id"],),
                )
                promoted += 1
        return promoted
    finally:
        if own:
            conn.close()
