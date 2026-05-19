#!/usr/bin/env python3
"""Imprint context-ingestion helper.

Subcommands:
  analyze-prompt                 stdin=prompt,  stdout=JSON {ambiguity_score, keywords, refined_prompt}
  prefill   <project_id>         stdin=prompt,  stdout=context block to prepend
  extract   <project_id>         stdin=response, side-effect: insert chunks
  refresh   <project_id> <spec>  spec = "<url>" | "source slack" | "source notion" | "project"

Design constraints:
- Hook scripts must NEVER block the user session. Every LLM call has a hard
  timeout; every JSON parse is wrapped; every failure path returns silently.
- External-source chunks (slack/notion) bypass the events table and are
  inserted directly into memory_chunks with source_event_id NULL (D11, AC7).
- Dedup key = source_uri/url + evidence_level + text_hash where possible.
  Legacy URL/page-level dedup remains for broad external refresh avoidance.
- Background model calls go through retrieval.model_runtime and use the detected host CLI.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from retrieval.model_runtime import run_background_model
from retrieval._common import migrate_legacy_claude_db_if_needed

# Runtime paths. IMPRINT_HOME 으로 테스트/실사용 DB 를 쉽게 격리한다.
IMPRINT_HOME = Path(os.environ.get("IMPRINT_HOME") or (Path.home() / ".imprint"))
IMPRINT_DB = IMPRINT_HOME / "app.sqlite"
IMPRINT_LOG = IMPRINT_HOME / "plugin.log"
DEFAULT_REDACT_RULES = Path(__file__).with_name("redact-rules.default.json")

# Prompt 분석 결과가 이 값보다 애매하면 refined prompt 를 더 보수적으로 다룬다.
AMBIGUITY_THRESHOLD = float(os.environ.get("IMPRINT_AMBIGUITY_THRESHOLD") or "0.5")
# Host model subprocesses can load user/project rules and MCP config, so even simple
# prompts may take seconds. Fetch has extra MCP RTT and gets a longer timeout.
MODEL_TIMEOUT_PREFILL = int(
    os.environ.get("IMPRINT_MODEL_TIMEOUT_PREFILL")
    or "25"
)
MODEL_TIMEOUT_FETCH = int(
    os.environ.get("IMPRINT_MODEL_TIMEOUT_FETCH")
    or "45"
)
MODEL_TIMEOUT_EXTRACT = int(
    os.environ.get("IMPRINT_MODEL_TIMEOUT_EXTRACT")
    or "30"
)

# LLM이 응답에서 추출하도록 허용된 chunk_type. 외부 source 전용 타입
# (spec/message/thread)은 ingestion 경로에서만 직접 INSERT한다.
CHUNK_TYPES = (
    "decision", "error", "fix", "command", "test_result",
    "summary", "todo", "code_context", "note",
)
EXTERNAL_CHUNK_TYPES = ("spec", "message", "thread")

# External lazy-fetch trigger patterns.
# prompt 안의 직접 URL 은 sources.json keyword mode 보다 우선 처리된다.
SLACK_PERMALINK_RE = re.compile(
    r"https://[a-z0-9\-]+\.slack\.com/archives/[A-Z0-9]+/p\d+(?:\?[^\s]*)?",
    re.IGNORECASE,
)
NOTION_URL_RE = re.compile(
    r"https://(?:www\.)?notion\.so/(?:[^\s/]+/)?[^\s?]+(?:\?[^\s]*)?",
    re.IGNORECASE,
)

# Tokenizer shared by deterministic gate/rewrite/prefill search.
TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9_]+")

# Foreground prefill limits. Hook latency 를 위해 query/session/retrieved context 크기를 제한한다.
WORKING_CONTEXT_LIMIT = int(os.environ.get("IMPRINT_WORKING_CONTEXT_LIMIT") or "4")
PREFILL_CONTEXT_LIMIT = int(os.environ.get("IMPRINT_PREFILL_LIMIT") or "8")

# Working memory retention policy.
# raw_turn 은 query context 용도라 오래 보관하지 않고 session 당 최신 N개만 유지한다.
WORKING_TTL_HOURS = int(os.environ.get("IMPRINT_WORKING_TTL_HOURS") or "24")
WORKING_MAX_PER_SESSION = int(os.environ.get("IMPRINT_WORKING_MAX_PER_SESSION") or "20")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(level: str, msg: str) -> None:
    try:
        IMPRINT_HOME.mkdir(parents=True, exist_ok=True)
        with IMPRINT_LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{now_iso()}] {level}: {msg}\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Profile (env-gated): IMPRINT_PROFILE=1 → profile.jsonl 1줄 추가.
# 기본 OFF — hook 차단 비용은 env 검사 한 번. 분석 hook lifecycle = env_gated.
# ---------------------------------------------------------------------------

PROFILE_ENABLED = os.environ.get("IMPRINT_PROFILE") == "1"
PROFILE_LOG = IMPRINT_HOME / "profile.jsonl"


def _profile_emit(stage: str, **fields: Any) -> None:
    if not PROFILE_ENABLED:
        return
    try:
        IMPRINT_HOME.mkdir(parents=True, exist_ok=True)
        rec = {"ts": now_iso(), "pid": os.getpid(), "stage": stage}
        rec.update(fields)
        with PROFILE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


import contextlib  # noqa: E402  (profile helper 의존)


@contextlib.contextmanager
def _profile_span(stage: str, **fields: Any):
    if not PROFILE_ENABLED:
        yield
        return
    t0 = time.monotonic()
    err: str | None = None
    try:
        yield
    except Exception as exc:  # noqa: BLE001  (계측만 하고 다시 raise)
        err = type(exc).__name__
        raise
    finally:
        dur_ms = int((time.monotonic() - t0) * 1000)
        _profile_emit(stage, dur_ms=dur_ms, err=err, **fields)


def db() -> sqlite3.Connection:
    IMPRINT_HOME.mkdir(parents=True, exist_ok=True)
    migrate_legacy_claude_db_if_needed()
    conn = sqlite3.connect(IMPRINT_DB, timeout=5.0)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def project_root() -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except (subprocess.SubprocessError, OSError):
        pass
    return Path.cwd()


def load_sources(root: Path) -> dict:
    path = root / ".imprint" / "sources.json"
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except (OSError, json.JSONDecodeError) as exc:
        log("WARN", f"sources.json parse failed: {exc}")
        return {}


def _load_redact_rules() -> list[dict]:
    """Load user override rules first, then plugin defaults. Fail-open."""
    candidates = []
    env_path = os.environ.get("IMPRINT_REDACT_RULES")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(IMPRINT_HOME / "redact-rules.json")
    candidates.append(DEFAULT_REDACT_RULES)

    for path in candidates:
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            rules = data.get("rules") if isinstance(data, dict) else None
            if isinstance(rules, list):
                return [r for r in rules if isinstance(r, dict)]
        except (OSError, json.JSONDecodeError) as exc:
            log("WARN", f"redact rules parse failed {path}: {exc}")
    return []


def redact_text(text: str) -> str:
    """Apply regex redaction before text reaches DB/FTS. Fail-open."""
    if not text:
        return text
    out = text
    for rule in _load_redact_rules():
        pat = rule.get("pattern")
        repl = rule.get("replacement", "[REDACTED]")
        if not isinstance(pat, str) or not pat:
            continue
        if not isinstance(repl, str):
            repl = "[REDACTED]"
        try:
            out = re.sub(pat, repl, out)
        except re.error:
            continue
    return out


def redact_json_value(value: Any) -> Any:
    """Recursively redact string leaves in metadata before JSON storage."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_json_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): redact_json_value(v) for k, v in value.items()}
    return value


# ---------------------------------------------------------------------------
# Background model helpers
# ---------------------------------------------------------------------------


def parse_json_relaxed(text: str | None) -> Any:
    """Pull a JSON object/array out of LLM output that may contain prose or
    a markdown fence. Returns None on failure."""
    if not text:
        return None
    s = text.strip()
    # strip ```json ... ``` fences
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", s, re.DOTALL)
    if fence:
        s = fence.group(1).strip()
    # try direct
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # try first {...} or [...] balanced span
    for opener, closer in (("{", "}"), ("[", "]")):
        i = s.find(opener)
        if i < 0:
            continue
        depth = 0
        for j in range(i, len(s)):
            if s[j] == opener:
                depth += 1
            elif s[j] == closer:
                depth -= 1
                if depth == 0:
                    candidate = s[i:j+1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
    return None


# ---------------------------------------------------------------------------
# Prefill analysis (AC2, D7, D19)
# ---------------------------------------------------------------------------

PREFILL_PROMPT = """\
You analyze a user prompt for an iOS team coding-agent session.

Return STRICT JSON with EXACTLY these keys:
{
  "ambiguity_score": <float 0..1>,
  "keywords": [<short string, ...>],
  "refined_prompt": <string OR null>
}

ambiguity_score: 0 = perfectly specific & actionable. 1 = totally vague.
keywords: 3-8 short search terms. Include Korean AND English synonyms when natural
  (e.g. "결제 흐름" alongside "payment flow"). Lowercase, no quotes.
refined_prompt:
  - If ambiguity_score < 0.5: MUST be null.
  - Otherwise: a more specific rewrite that an iOS engineer would naturally clarify
    (which screen/feature/file, what success looks like, which approach to prefer).
    Korean if the input is Korean.

Output ONLY the JSON object. No markdown fence, no prose.

User prompt:
<<<
{PROMPT}
>>>
"""


def analyze_prompt(prompt: str) -> dict | None:
    out = run_background_model(
        PREFILL_PROMPT.replace("{PROMPT}", prompt[:4000]),
        timeout=MODEL_TIMEOUT_PREFILL,
        needs_tools=False,
    )
    data = parse_json_relaxed(out)
    if not isinstance(data, dict):
        return None
    score = data.get("ambiguity_score")
    keywords = data.get("keywords")
    refined = data.get("refined_prompt")
    if not isinstance(score, (int, float)) or not isinstance(keywords, list):
        return None
    if refined is not None and not isinstance(refined, str):
        refined = None
    return {
        "ambiguity_score": float(score),
        "keywords": [str(k) for k in keywords if isinstance(k, str) and k.strip()][:12],
        "refined_prompt": refined.strip() if isinstance(refined, str) and refined.strip() else None,
    }


# ---------------------------------------------------------------------------
# Slack lazy fetch (AC12, D20)
# ---------------------------------------------------------------------------

SLACK_FETCH_SINGLE_PROMPT = """\
Use the registered Slack MCP tool to fetch the message at this permalink:
{URL}

Return STRICT JSON:
{
  "channel": "<#channel name>",
  "author": "<display name>",
  "posted_at": "<ISO8601>",
  "edited_at": "<ISO8601, omit if not edited>",
  "text": "<message text, <=1000 chars>"
}

If the tool is unavailable or the message can't be fetched, return: {"error": "<short reason>"}
Output ONLY the JSON object. No markdown fence, no prose.
"""

SLACK_FETCH_THREAD_PROMPT = """\
Use the registered Slack MCP tool to fetch the entire thread at:
{URL}

Then SELECT replies most relevant to this user prompt:
<<<
{PROMPT}
>>>

Return STRICT JSON:
{
  "channel": "<#channel name>",
  "posted_at": "<ISO8601 of parent>",
  "summary": "<2-3 sentence Korean summary focused on the prompt>",
  "selected": [
    {"author": "<name>", "posted_at": "<ISO8601>", "edited_at": "<optional>", "text": "<<=500 chars>"},
    ...
  ]
}

Limit selected to AT MOST 2 messages. Skip noise, reactions, off-topic banter.
If unavailable: {"error": "<short reason>"}. Output ONLY the JSON object.
"""

SLACK_KEYWORD_PROMPT = """\
Use the registered Slack MCP tool. Search these channels: {CHANNELS}
for messages most relevant to these keywords: {KEYWORDS}

Return STRICT JSON array (max 3 items):
[
  {
    "channel": "#name",
    "author": "...",
    "posted_at": "ISO8601",
    "edited_at": "<optional>",
    "url": "<permalink>",
    "text": "<<=500 chars>"
  },
  ...
]

If no relevant matches or tool unavailable: [].
Output ONLY the JSON array.
"""


def is_slack_thread_url(url: str) -> bool:
    return "thread_ts=" in url


def fetch_slack_url(url: str, prompt: str) -> list[dict] | None:
    """Returns list of chunk dicts (text + metadata fields) or None on error."""
    if is_slack_thread_url(url):
        out = run_background_model(
            SLACK_FETCH_THREAD_PROMPT.replace("{URL}", url).replace("{PROMPT}", prompt[:1000]),
            timeout=MODEL_TIMEOUT_FETCH,
            needs_tools=True,
        )
        data = parse_json_relaxed(out)
        if not isinstance(data, dict) or "error" in data:
            return None
        chunks: list[dict] = []
        summary = (data.get("summary") or "").strip()
        if summary:
            chunks.append({
                "text": f"[Slack thread summary] {summary}",
                "metadata": {
                    "source": "slack",
                    "url": url,
                    "channel": data.get("channel", ""),
                    "posted_at": data.get("posted_at", ""),
                    "kind": "thread_summary",
                },
            })
        for msg in (data.get("selected") or [])[:2]:
            if not isinstance(msg, dict):
                continue
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            md = {
                "source": "slack",
                "url": url,
                "channel": data.get("channel", ""),
                "author": msg.get("author", ""),
                "posted_at": msg.get("posted_at", ""),
                "kind": "thread_reply",
            }
            if msg.get("edited_at"):
                md["edited_at"] = msg["edited_at"]
            chunks.append({"text": f"[Slack reply] {text}", "metadata": md})
        return chunks
    # single-message permalink
    out = run_background_model(
        SLACK_FETCH_SINGLE_PROMPT.replace("{URL}", url),
        timeout=MODEL_TIMEOUT_FETCH,
        needs_tools=True,
    )
    data = parse_json_relaxed(out)
    if not isinstance(data, dict) or "error" in data:
        return None
    text = (data.get("text") or "").strip()
    if not text:
        return None
    md = {
        "source": "slack",
        "url": url,
        "channel": data.get("channel", ""),
        "author": data.get("author", ""),
        "posted_at": data.get("posted_at", ""),
    }
    if data.get("edited_at"):
        md["edited_at"] = data["edited_at"]
    return [{"text": f"[Slack message] {text}", "metadata": md}]


def fetch_slack_keywords(channels: list[str], keywords: list[str]) -> list[dict]:
    if not channels or not keywords:
        return []
    out = run_background_model(
        SLACK_KEYWORD_PROMPT
            .replace("{CHANNELS}", json.dumps(channels, ensure_ascii=False))
            .replace("{KEYWORDS}", json.dumps(keywords, ensure_ascii=False)),
        timeout=MODEL_TIMEOUT_FETCH,
        needs_tools=True,
    )
    data = parse_json_relaxed(out)
    if not isinstance(data, list):
        return []
    chunks = []
    for item in data[:3]:
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or "").strip()
        url = item.get("url")
        if not text or not url:
            continue
        md = {
            "source": "slack",
            "url": url,
            "channel": item.get("channel", ""),
            "author": item.get("author", ""),
            "posted_at": item.get("posted_at", ""),
        }
        if item.get("edited_at"):
            md["edited_at"] = item["edited_at"]
        chunks.append({"text": f"[Slack message] {text}", "metadata": md})
    return chunks


# ---------------------------------------------------------------------------
# Notion lazy fetch (AC14, D21, D23)
# ---------------------------------------------------------------------------

NOTION_FETCH_PROMPT = """\
Use the registered Notion MCP (notion-fetch) to fetch this page:
{URL_OR_ID}

Return STRICT JSON:
{
  "page_id": "<id>",
  "page_title": "<title>",
  "url": "<canonical URL>",
  "last_edited_at": "<ISO8601>",
  "sections": [
    {"section_title": "<heading verbatim>", "text": "<<=3000 chars>"},
    ...
  ]
}

REQUIREMENTS — read carefully. The user wants HISTORY preserved, not a summary.
- Save EVERY non-QA H1/H2/H3 heading as its OWN section entry. Do NOT merge sections,
  do NOT compress to a fixed count, do NOT cap or take "the first N headings".
- SKIP only QA / testing-checklist sections. Examples of sections to skip:
  "QA 확인 항목", "QA 체크리스트", "테스트 케이스", "Test plan", "Test cases",
  "QA Checklist". When in doubt, KEEP it.
- KEEP all planning and development content: 문서 목적, 배경, 목표, 적용 범위,
  사용자 시나리오, 화면 요구사항, 기능 요구사항, 예외 케이스, 정책/UX 기준,
  Firebase·이벤트 정의, 완료 기준, 데이터 스키마, API 명세 등.
- section_title은 원문 heading 텍스트 그대로 사용한다(병합 금지).
- Each section text <= 3000 chars; preserve all decision-relevant detail.
- Skip only truly empty sections (or QA-only sections per above).

If unavailable: {"error": "<reason>"}.
Output ONLY the JSON object. No markdown fence.
"""

NOTION_KEYWORD_PROMPT = """\
Use the registered Notion MCP. For each of these page references: {PAGES}
fetch and find sections relevant to these keywords: {KEYWORDS}

Return STRICT JSON array (max 3 items):
[
  {
    "page_id": "<id>",
    "page_title": "<title>",
    "section_title": "<heading or null>",
    "url": "<page URL with section anchor when possible>",
    "last_edited_at": "<ISO8601>",
    "text": "<<=1000 chars>"
  },
  ...
]

If nothing relevant or tool unavailable: []. Output ONLY the JSON array.
"""


def fetch_notion_url(url_or_id: str) -> list[dict] | None:
    out = run_background_model(
        NOTION_FETCH_PROMPT.replace("{URL_OR_ID}", url_or_id),
        timeout=MODEL_TIMEOUT_FETCH,
        needs_tools=True,
    )
    data = parse_json_relaxed(out)
    if not isinstance(data, dict) or "error" in data:
        return None
    page_id = data.get("page_id") or url_or_id
    page_title = (data.get("page_title") or "").strip()
    page_url = data.get("url") or url_or_id
    last_edited = data.get("last_edited_at") or ""
    sections = data.get("sections") or []
    if not isinstance(sections, list):
        return None
    chunks = []
    for s in sections:
        if not isinstance(s, dict):
            continue
        text = (s.get("text") or "").strip()
        if not text:
            continue
        section_title = (s.get("section_title") or "").strip() or None
        # per-section URL with anchor when available
        chunk_url = page_url
        if section_title:
            chunk_url = f"{page_url}#{section_title}"
        md = {
            "source": "notion",
            "url": chunk_url,
            "page_id": page_id,
            "page_title": page_title,
        }
        if section_title:
            md["section_title"] = section_title
        if last_edited:
            md["last_edited_at"] = last_edited
        prefix = f"[Notion: {page_title}"
        if section_title:
            prefix += f" / {section_title}"
        prefix += "] "
        chunks.append({"text": prefix + text, "metadata": md})
    return chunks


def fetch_notion_keywords(pages: list[str], keywords: list[str]) -> list[dict]:
    if not pages or not keywords:
        return []
    out = run_background_model(
        NOTION_KEYWORD_PROMPT
            .replace("{PAGES}", json.dumps(pages, ensure_ascii=False))
            .replace("{KEYWORDS}", json.dumps(keywords, ensure_ascii=False)),
        timeout=MODEL_TIMEOUT_FETCH,
        needs_tools=True,
    )
    data = parse_json_relaxed(out)
    if not isinstance(data, list):
        return []
    chunks = []
    for item in data[:3]:
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or "").strip()
        url = item.get("url")
        if not text or not url:
            continue
        md = {
            "source": "notion",
            "url": url,
            "page_id": item.get("page_id", ""),
            "page_title": item.get("page_title", ""),
        }
        if item.get("section_title"):
            md["section_title"] = item["section_title"]
        if item.get("last_edited_at"):
            md["last_edited_at"] = item["last_edited_at"]
        prefix = f"[Notion: {md['page_title']}"
        if md.get("section_title"):
            prefix += f" / {md['section_title']}"
        prefix += "] "
        chunks.append({"text": prefix + text, "metadata": md})
    return chunks


# ---------------------------------------------------------------------------
# Chunk store helpers
# ---------------------------------------------------------------------------

def chunk_url_exists(conn: sqlite3.Connection, project_id: str, url: str) -> bool:
    """페이지 URL 기준 dedup. Notion 섹션은 metadata.url에 `#section`이 붙어
    저장되므로 page-URL로 들어온 query는 정확 일치만으로는 못 잡는다.
    `url` 또는 `url#...` 형태가 하나라도 있으면 hit으로 간주한다."""
    cur = conn.execute(
        "SELECT 1 FROM memory_chunks "
        "WHERE project_id = ? AND ("
        "  json_extract(metadata_json, '$.url') = ? "
        "  OR json_extract(metadata_json, '$.url') LIKE ? "
        ") AND chunk_type != 'source_status' LIMIT 1;",
        (project_id, url, url + "#%"),
    )
    return cur.fetchone() is not None


def stable_text_hash(text: str) -> str:
    """chunk dedup 용 짧은 안정 hash. redaction 후 text 에 대해 계산한다."""
    normalized = " ".join((text or "").split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def chunk_dedup_exists(
    conn: sqlite3.Connection,
    project_id: str,
    *,
    source_uri: str | None,
    evidence_level: str | None,
    text_hash: str,
    source_event_id: str | None = None,
    chunk_type: str | None = None,
) -> bool:
    """새 metadata text_hash 기준 dedup. 기존 row 에 hash 가 없으면 건드리지 않는다."""
    if source_uri and evidence_level:
        cur = conn.execute(
            """
            SELECT 1 FROM memory_chunks
            WHERE project_id = ?
              AND chunk_type != 'source_status'
              AND json_extract(metadata_json, '$.source_uri') = ?
              AND json_extract(metadata_json, '$.evidence_level') = ?
              AND json_extract(metadata_json, '$.text_hash') = ?
            LIMIT 1
            """,
            (project_id, source_uri, evidence_level, text_hash),
        )
        if cur.fetchone() is not None:
            return True
    if source_event_id and chunk_type:
        cur = conn.execute(
            """
            SELECT 1 FROM memory_chunks
            WHERE project_id = ?
              AND source_event_id = ?
              AND chunk_type = ?
              AND json_extract(metadata_json, '$.text_hash') = ?
            LIMIT 1
            """,
            (project_id, source_event_id, chunk_type, text_hash),
        )
        if cur.fetchone() is not None:
            return True
    return False


def insert_external_chunk(
    conn: sqlite3.Connection,
    project_id: str,
    chunk_type: str,
    text: str,
    metadata: dict,
) -> str:
    metadata = dict(metadata or {})
    source = str(metadata.get("source") or ("slack" if chunk_type in ("message", "thread") else "notion"))
    metadata.setdefault("source", source)
    metadata.setdefault("source_type", source)
    metadata.setdefault("evidence_level", "raw_source")
    metadata.setdefault("grounded", True)
    if metadata.get("url") and not metadata.get("source_uri"):
        metadata["source_uri"] = metadata["url"]
    metadata.setdefault("fetched_at", now_iso())
    text = redact_text(text)
    metadata.setdefault("text_hash", stable_text_hash(text))
    metadata = redact_json_value(metadata)
    if chunk_dedup_exists(
        conn,
        project_id,
        source_uri=metadata.get("source_uri"),
        evidence_level=metadata.get("evidence_level"),
        text_hash=str(metadata.get("text_hash") or ""),
    ):
        return ""
    cid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO memory_chunks "
        "(id, project_id, source_event_id, chunk_type, text, metadata_json, created_at, pinned) "
        "VALUES (?, ?, NULL, ?, ?, ?, ?, 0);",
        (cid, project_id, chunk_type, text, json.dumps(metadata, ensure_ascii=False), now_iso()),
    )
    return cid


def insert_extracted_chunk(
    conn: sqlite3.Connection,
    project_id: str,
    source_event_id: str | None,
    chunk_type: str,
    text: str,
    keywords: list[str],
) -> str:
    cid = str(uuid.uuid4())
    text = redact_text(text)
    keywords = [redact_text(k) for k in keywords]
    text_hash = stable_text_hash(text)
    if chunk_dedup_exists(
        conn,
        project_id,
        source_uri=None,
        evidence_level="assistant_extracted",
        text_hash=text_hash,
        source_event_id=source_event_id,
        chunk_type=chunk_type,
    ):
        return ""
    md = {
        "source": "llm_response",
        "source_type": "chat",
        "evidence_level": "assistant_extracted",
        "grounded": False,
        "keywords": keywords,
        "text_hash": text_hash,
    }
    conn.execute(
        "INSERT INTO memory_chunks "
        "(id, project_id, source_event_id, chunk_type, text, metadata_json, created_at, pinned) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 0);",
        (cid, project_id, source_event_id, chunk_type, text, json.dumps(md, ensure_ascii=False), now_iso()),
    )
    return cid


def insert_source_status_chunk(
    conn: sqlite3.Connection,
    project_id: str,
    *,
    source: str,
    status: str,
    text: str,
    metadata: dict,
) -> str:
    """Visible marker for external-source fetch state. Excluded from prefill."""
    md = dict(metadata or {})
    md.update({
        "source": source,
        "source_type": source,
        "status": status,
        "evidence_level": "status_marker",
        "grounded": False,
        "fetched_at": now_iso(),
    })
    if md.get("url") and not md.get("source_uri"):
        md["source_uri"] = md["url"]
    text = redact_text(text)
    md.setdefault("text_hash", stable_text_hash(text))
    md = redact_json_value(md)
    cid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO memory_chunks "
        "(id, project_id, source_event_id, chunk_type, text, metadata_json, created_at, pinned) "
        "VALUES (?, ?, NULL, 'source_status', ?, ?, ?, 0);",
        (cid, project_id, text, json.dumps(md, ensure_ascii=False), now_iso()),
    )
    return cid


# ---------------------------------------------------------------------------
# Stop-hook chunk extraction (AC3, AC11, D8, D12)
# ---------------------------------------------------------------------------

EXTRACT_PROMPT = """\
Extract persistent memory chunks from this assistant response. Return STRICT JSON array.

Each item:
{
  "chunk_type": one of ["decision","error","fix","command","test_result","summary","todo","code_context","note"],
  "text": "<<=400 chars, captures the chunk in plain prose>",
  "keywords": [<3-8 short search terms, Korean+English synonyms when natural>]
}

Skip greetings, small talk, repeated content, narration of what you did.
ONLY save items that would be useful in a future session as a fact, decision, or pointer.
Preserve the original language of the assistant response in "text". Do not translate
Korean facts into English or English facts into Korean.
If nothing worth saving: return [].

Output ONLY the JSON array. No markdown fence, no prose.

Assistant response:
<<<
{RESPONSE}
>>>
"""


def extract_chunks_from_response(response: str) -> list[dict]:
    if not response.strip():
        return []
    out = run_background_model(
        EXTRACT_PROMPT.replace("{RESPONSE}", response[:8000]),
        timeout=MODEL_TIMEOUT_EXTRACT,
        needs_tools=False,
    )
    data = parse_json_relaxed(out)
    if not isinstance(data, list):
        return []
    chunks = []
    for item in data[:20]:
        if not isinstance(item, dict):
            continue
        ct = item.get("chunk_type")
        text = (item.get("text") or "").strip()
        kw = item.get("keywords") or []
        if ct not in CHUNK_TYPES or not text:
            continue
        if not isinstance(kw, list):
            kw = []
        kw = [str(k).strip() for k in kw if isinstance(k, str) and str(k).strip()][:12]
        chunks.append({"chunk_type": ct, "text": text[:400], "keywords": kw})
    return chunks


# ---------------------------------------------------------------------------
# Memory search (AC11) — FTS5 MATCH ∪ keywords array hit
# ---------------------------------------------------------------------------

def fts_escape(query: str) -> str:
    """Wrap each term in double quotes for FTS5 phrase matching, dropping
    the FTS5 syntax characters that would otherwise need escaping."""
    terms = [t for t in re.split(r"\s+", query.strip()) if t]
    safe_terms = []
    for t in terms:
        t = t.replace('"', '')
        if not t:
            continue
        safe_terms.append(f'"{t}"')
    return " OR ".join(safe_terms)


def deterministic_rewrite_terms(prompt: str) -> list[str]:
    """동기 경로용 저비용 검색 표면형 보강.

    LLM 호출 없이 UI/코드 질의에서 자주 필요한 영어 코드 표면형만 추가한다.
    """
    text = (prompt or "").lower()
    terms: list[str] = []
    if any(k in text for k in ("버튼", "button", "클릭", "click", "누르", "탭", "tap")):
        terms.extend([
            "button", "click", "handler", "action",
            "onclick", "ontap", "navigation", "side", "effect",
        ])
    if any(k in text for k in ("화면", "view", "screen", "페이지", "page")):
        terms.extend(["screen", "view", "page", "route", "navigation"])
    if any(k in text for k in ("설정", "동기화", "sync", "저장", "save")):
        terms.extend(["settings", "sync", "synchronize", "save", "state"])

    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        t = term.strip().lower()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def deterministic_query_surfaces(prompt: str) -> list[dict[str, str]]:
    """원문 의미를 바꾸지 않는 검색 표면형 묶음."""
    original = (prompt or "").strip()
    terms = deterministic_rewrite_terms(original)
    surfaces: list[dict[str, str]] = []
    if original:
        surfaces.append({"kind": "original", "text": original})
    if terms:
        action_terms = [
            t for t in terms
            if t in {"button", "click", "handler", "action", "onclick", "ontap", "navigation"}
        ]
        code_terms = [
            t for t in terms
            if t in {
                "handler", "action", "onclick", "ontap", "state", "settings",
                "sync", "synchronize", "save", "side", "effect",
            }
        ]
        if action_terms:
            surfaces.append({"kind": "action", "text": " ".join(action_terms)})
        if code_terms:
            surfaces.append({"kind": "code", "text": " ".join(code_terms)})
    return surfaces[:3]


def retrieval_gate(prompt: str) -> tuple[bool, str]:
    """자동 prefill 에서 retrieved-memory search 를 열지 결정하는 deterministic gate."""
    s = (prompt or "").strip().lower()
    if not s:
        return False, "empty"
    backchannel = re.compile(
        r"^(응|네|넵|ㅇㅇ|좋아|그래|맞아|확인|고마워|감사|오케이|ok|yes|yeah|yep|sure)[\s.!?~]*$",
        re.IGNORECASE,
    )
    simple_action = re.compile(
        r"^(커밋해줘|커밋 진행해줘|커밋|commit|pr 올려줘|푸시해줘|push)[\s.!?~]*$",
        re.IGNORECASE,
    )
    if len(s) <= 24 and (backchannel.match(s) or simple_action.match(s)):
        return False, "backchannel_or_simple_action"
    if SLACK_PERMALINK_RE.search(prompt) or NOTION_URL_RE.search(prompt):
        return True, "explicit_source_url"
    knowledge_terms = (
        "어떻게", "왜", "어디", "동작", "정리", "찾아", "알려", "설명",
        "버튼", "화면", "코드", "함수", "에러", "오류", "버그", "테스트",
        "노션", "슬랙", "문서", "기획", "notion", "slack", "source", "url",
        "handler", "onclick", "ontap", "retrieve", "memory", "rag",
    )
    if any(term in s for term in knowledge_terms):
        return True, "knowledge_keyword"
    if len(TOKEN_RE.findall(s)) >= 5:
        return True, "multi_token_prompt"
    return False, "low_information_prompt"


def prefill_keywords(prompt: str) -> list[str]:
    """원문 token + deterministic rewrite terms 를 FTS/metadata 검색어로 사용."""
    seen: set[str] = set()
    out: list[str] = []
    stopwords = {
        "알려줘", "알려주세요", "설명해줘", "설명해주세요",
        "어떻게", "뭐야", "무엇", "동작",
    }
    for tok in TOKEN_RE.findall(prompt or ""):
        t = tok.strip().lower()
        if len(t) < 2 or t in stopwords or t in seen:
            continue
        seen.add(t)
        out.append(t)
    for surface in deterministic_query_surfaces(prompt):
        for term in TOKEN_RE.findall(surface["text"]):
            t = term.strip().lower()
            if len(t) >= 2 and t not in seen:
                seen.add(t)
                out.append(t)
    return out[:16]


def cleanup_working_memory(
    conn: sqlite3.Connection,
    project_id: str,
    session_id: str,
    now: str,
) -> None:
    """working tier 만 TTL/max 정책으로 정리."""
    try:
        now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
    except ValueError:
        now_dt = datetime.now(timezone.utc)
    cutoff = (now_dt - timedelta(hours=WORKING_TTL_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """
        DELETE FROM memory_chunks
        WHERE project_id = ?
          AND json_extract(metadata_json, '$.memory_tier') = 'working'
          AND created_at < ?;
        """,
        (project_id, cutoff),
    )
    if not session_id or WORKING_MAX_PER_SESSION <= 0:
        return
    conn.execute(
        f"""
        DELETE FROM memory_chunks
        WHERE project_id = ?
          AND json_extract(metadata_json, '$.memory_tier') = 'working'
          AND json_extract(metadata_json, '$.session_id') = ?
          AND id NOT IN (
            SELECT id FROM memory_chunks
            WHERE project_id = ?
              AND json_extract(metadata_json, '$.memory_tier') = 'working'
              AND json_extract(metadata_json, '$.session_id') = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT {WORKING_MAX_PER_SESSION}
          );
        """,
        (project_id, session_id, project_id, session_id),
    )


def insert_working_turn_chunk(
    conn: sqlite3.Connection,
    project_id: str,
    source_event_id: str,
    session_id: str,
    prompt: str,
) -> str:
    now = now_iso()
    cleanup_working_memory(conn, project_id, session_id, now)
    query_surfaces = deterministic_query_surfaces(prompt)
    rewrite_terms = deterministic_rewrite_terms(prompt)
    need_retrieval, retrieval_reason = retrieval_gate(prompt)
    cid = str(uuid.uuid4())
    text = prompt.strip()
    if rewrite_terms:
        text = f"{text}\nSearch surface: {' '.join(rewrite_terms)}"
    safe_text = redact_text(text)
    metadata = {
        "memory_tier": "working",
        "memory_kind": "raw_turn",
        "session_visible": True,
        "session_id": session_id,
        "request_id": source_event_id,
        "source": "user_prompt_submit",
        "source_type": "chat",
        "evidence_level": "raw_turn",
        "grounded": False,
        "write_ts": now,
        "searchable_at": now,
        "need_retrieval": need_retrieval,
        "retrieval_reason": retrieval_reason,
        "query_surfaces": query_surfaces,
        "query_rewrite": " ".join(rewrite_terms),
        "keywords": prefill_keywords(prompt),
        "text_hash": stable_text_hash(safe_text),
    }
    conn.execute(
        "INSERT INTO memory_chunks "
        "(id, project_id, source_event_id, chunk_type, text, metadata_json, created_at, pinned) "
        "VALUES (?, ?, ?, 'raw_turn', ?, ?, ?, 0);",
        (
            cid,
            project_id,
            source_event_id,
            safe_text,
            json.dumps(redact_json_value(metadata), ensure_ascii=False),
            now,
        ),
    )
    cleanup_working_memory(conn, project_id, session_id, now)
    return cid


def load_working_context(
    conn: sqlite3.Connection,
    project_id: str,
    session_id: str,
    limit: int = WORKING_CONTEXT_LIMIT,
) -> list[dict]:
    params: list[Any] = [project_id]
    session_clause = ""
    if session_id:
        session_clause = "AND json_extract(metadata_json, '$.session_id') = ?"
        params.append(session_id)
    params.append(limit)
    cur = conn.execute(
        f"""
        SELECT id, chunk_type, text, metadata_json, pinned, created_at
        FROM memory_chunks
        WHERE project_id = ?
          AND chunk_type != 'source_status'
          AND json_extract(metadata_json, '$.memory_tier') = 'working'
          AND json_extract(metadata_json, '$.session_visible') = 1
          {session_clause}
        ORDER BY created_at DESC
        LIMIT ?;
        """,
        params,
    )
    rows: list[dict] = []
    for row in cur:
        rows.append({
            "id": row[0], "chunk_type": row[1], "text": row[2],
            "metadata_json": row[3], "pinned": row[4], "created_at": row[5],
            "score": 10.0,
        })
    return rows


def _chunk_section(chunk: dict) -> str:
    try:
        md = json.loads(chunk.get("metadata_json") or "{}")
        if not isinstance(md, dict):
            md = {}
    except (json.JSONDecodeError, TypeError):
        md = {}
    if md.get("memory_tier") == "working":
        return "query"
    source = md.get("source_type") or md.get("source")
    if source in ("slack", "notion") or chunk.get("chunk_type") in EXTERNAL_CHUNK_TYPES:
        return "external"
    return "retrieved"


def search_memory(
    conn: sqlite3.Connection,
    project_id: str,
    keywords: list[str],
    prompt: str,
    limit: int = 8,
) -> list[dict]:
    """Returns chunks ranked by (pinned DESC, match_score DESC, recency DESC).

    Match score = (FTS5 hits across keywords) + (keyword-array hits in metadata.keywords).
    """
    seen: dict[str, dict] = {}

    # 1. FTS5 search across keywords
    if keywords:
        fts_query = fts_escape(" ".join(keywords))
        if fts_query:
            try:
                cur = conn.execute(
                    "SELECT m.id, m.chunk_type, m.text, m.metadata_json, m.pinned, m.created_at "
                    "FROM memory_chunks_fts f "
                    "JOIN memory_chunks m ON m.rowid = f.rowid "
                    "WHERE f.text MATCH ? AND m.project_id = ? "
                    "  AND m.chunk_type != 'source_status' "
                    "  AND coalesce(json_extract(m.metadata_json, '$.memory_tier'), '') != 'working' "
                    "ORDER BY m.pinned DESC, m.created_at DESC LIMIT ?;",
                    (fts_query, project_id, limit * 2),
                )
                for row in cur:
                    cid = row[0]
                    seen[cid] = {
                        "id": cid, "chunk_type": row[1], "text": row[2],
                        "metadata_json": row[3], "pinned": row[4], "created_at": row[5],
                        "score": 2.0 + (1.0 if row[4] else 0.0),
                    }
            except sqlite3.OperationalError as exc:
                log("WARN", f"fts search failed: {exc}")

    # 2. metadata.keywords array hit
    if keywords:
        placeholders = ",".join("?" * len(keywords))
        try:
            cur = conn.execute(
                f"""
                SELECT m.id, m.chunk_type, m.text, m.metadata_json, m.pinned, m.created_at,
                       COUNT(DISTINCT je.value) AS hits
                FROM memory_chunks m, json_each(json_extract(m.metadata_json, '$.keywords')) je
                WHERE m.project_id = ?
                  AND m.chunk_type != 'source_status'
                  AND coalesce(json_extract(m.metadata_json, '$.memory_tier'), '') != 'working'
                  AND je.value IN ({placeholders})
                GROUP BY m.id
                ORDER BY hits DESC, m.pinned DESC, m.created_at DESC
                LIMIT ?;
                """,
                [project_id, *keywords, limit * 2],
            )
            for row in cur:
                cid = row[0]
                hits = row[6] or 0
                bonus = 1.0 + 0.5 * hits + (1.0 if row[4] else 0.0)
                if cid in seen:
                    seen[cid]["score"] += bonus
                else:
                    seen[cid] = {
                        "id": cid, "chunk_type": row[1], "text": row[2],
                        "metadata_json": row[3], "pinned": row[4], "created_at": row[5],
                        "score": bonus,
                    }
        except sqlite3.OperationalError as exc:
            log("WARN", f"keywords search failed: {exc}")

    # 2b. LIKE fallback for short Korean/UI tokens that trigram FTS misses.
    if keywords and not seen:
        tokens: list[str] = []
        seen_tokens: set[str] = set()
        for tok in keywords:
            t = tok.strip().lower()
            if len(t) < 2 or t in seen_tokens:
                continue
            seen_tokens.add(t)
            tokens.append(t)
        if tokens:
            clauses = []
            params: list[str] = []
            for tok in tokens[:8]:
                clauses.append("lower(m.text) LIKE ?")
                params.append(f"%{tok}%")
            try:
                cur = conn.execute(
                    f"""
                    SELECT m.id, m.chunk_type, m.text, m.metadata_json, m.pinned, m.created_at
                    FROM memory_chunks m
                    WHERE m.project_id = ?
                      AND m.chunk_type != 'source_status'
                      AND coalesce(json_extract(m.metadata_json, '$.memory_tier'), '') != 'working'
                      AND ({' OR '.join(clauses)})
                    ORDER BY m.pinned DESC, m.created_at DESC
                    LIMIT ?;
                    """,
                    [project_id, *params, limit * 2],
                )
                for row in cur:
                    haystack = (row[2] or "").lower()
                    hits = sum(1 for tok in tokens if tok in haystack)
                    seen[row[0]] = {
                        "id": row[0], "chunk_type": row[1], "text": row[2],
                        "metadata_json": row[3], "pinned": row[4], "created_at": row[5],
                        "score": 1.5 + min(0.5, hits * 0.1) + (1.0 if row[4] else 0.0),
                    }
            except sqlite3.OperationalError as exc:
                log("WARN", f"like fallback search failed: {exc}")

    # 3. fallback: 최근 retrieved memory (decision/fix/todo/note + 외부 source)
    # 외부 source chunk를 'note'에서 spec/message/thread로 분리한 뒤
    # fallback이 빈 결과를 내지 않도록 신규 타입도 포함시킨다.
    if not seen:
        try:
            cur = conn.execute(
                "SELECT id, chunk_type, text, metadata_json, pinned, created_at "
                "FROM memory_chunks "
                "WHERE project_id = ? AND chunk_type IN "
                "  ('decision','fix','todo','note','spec','message','thread') "
                "  AND coalesce(json_extract(metadata_json, '$.memory_tier'), '') != 'working' "
                "ORDER BY pinned DESC, created_at DESC LIMIT ?;",
                (project_id, limit),
            )
            for row in cur:
                seen[row[0]] = {
                    "id": row[0], "chunk_type": row[1], "text": row[2],
                    "metadata_json": row[3], "pinned": row[4], "created_at": row[5],
                    "score": 0.1,
                }
        except sqlite3.OperationalError:
            pass

    ranked = sorted(seen.values(), key=lambda x: (x["score"], x["pinned"], x["created_at"]), reverse=True)
    return ranked[:limit]


# ---------------------------------------------------------------------------
# Lazy fetch orchestration
# ---------------------------------------------------------------------------

def lazy_fetch(
    conn: sqlite3.Connection,
    project_id: str,
    prompt: str,
    keywords: list[str],
    sources: dict,
) -> int:
    """Fetch external context driven by URLs in prompt + sources.json keyword
    mode. Returns number of NEW chunks inserted."""
    inserted = 0

    def _payload_bytes(cs: list[dict] | None) -> int:
        if not cs:
            return 0
        return sum(len((c.get("text") or "").encode("utf-8")) for c in cs)

    # 1) URL-explicit Slack permalinks in prompt
    slack_urls = list(dict.fromkeys(SLACK_PERMALINK_RE.findall(prompt)))
    for url in slack_urls[3:]:
        insert_source_status_chunk(
            conn, project_id,
            source="slack", status="skipped_by_cap",
            text=f"Slack URL skipped by per-turn cap: {url}",
            metadata={"url": url, "cap": 3},
        )
        inserted += 1
    for url in slack_urls[:3]:
        if chunk_url_exists(conn, project_id, url):
            log("INFO", f"slack url cache hit, skip fetch: {url}")
            continue
        chunks: list[dict] | None = None
        with _profile_span("fetch_slack_url", url=url):
            try:
                chunks = fetch_slack_url(url, prompt)
            except Exception as exc:  # noqa: BLE001  (must never propagate)
                log("WARN", f"slack fetch failed {url}: {exc}")
                chunks = None
        _profile_emit("fetch_slack_url.payload",
                      url=url, chunks=len(chunks or []),
                      payload_bytes=_payload_bytes(chunks))
        if not chunks:
            insert_source_status_chunk(
                conn, project_id,
                source="slack", status="fetch_failed",
                text=f"Slack fetch failed or returned no usable content: {url}",
                metadata={"url": url},
            )
            inserted += 1
            continue
        ct = "thread" if is_slack_thread_url(url) else "message"
        for c in chunks:
            if insert_external_chunk(conn, project_id, ct, c["text"], c["metadata"]):
                inserted += 1

    # 2) Notion URLs in prompt
    notion_urls = list(dict.fromkeys(NOTION_URL_RE.findall(prompt)))
    for url in notion_urls[3:]:
        insert_source_status_chunk(
            conn, project_id,
            source="notion", status="skipped_by_cap",
            text=f"Notion URL skipped by per-turn cap: {url}",
            metadata={"url": url, "cap": 3},
        )
        inserted += 1
    for url in notion_urls[:3]:
        if chunk_url_exists(conn, project_id, url):
            continue
        chunks = None
        with _profile_span("fetch_notion_url", url=url):
            try:
                chunks = fetch_notion_url(url)
            except Exception as exc:  # noqa: BLE001
                log("WARN", f"notion url fetch failed {url}: {exc}")
                chunks = None
        _profile_emit("fetch_notion_url.payload",
                      url=url, chunks=len(chunks or []),
                      payload_bytes=_payload_bytes(chunks))
        if not chunks:
            insert_source_status_chunk(
                conn, project_id,
                source="notion", status="fetch_failed",
                text=f"Notion fetch failed or returned no usable content: {url}",
                metadata={"url": url},
            )
            inserted += 1
            continue
        for c in chunks:
            url_dedup = c["metadata"].get("url")
            if url_dedup and chunk_url_exists(conn, project_id, url_dedup):
                continue
            if insert_external_chunk(conn, project_id, "spec", c["text"], c["metadata"]):
                inserted += 1

    # 3) Keyword mode — sources.json channels/pages
    if keywords:
        slack_cfg = (sources.get("slack") or {}) if isinstance(sources, dict) else {}
        channels = slack_cfg.get("channels") or []
        if channels and isinstance(channels, list):
            slack_chunks: list[dict] = []
            with _profile_span("fetch_slack_keywords",
                               channels=len(channels), keywords=len(keywords)):
                try:
                    slack_chunks = fetch_slack_keywords(channels, keywords)
                except Exception as exc:  # noqa: BLE001
                    log("WARN", f"slack keyword search failed: {exc}")
                    slack_chunks = []
            _profile_emit("fetch_slack_keywords.payload",
                          chunks=len(slack_chunks),
                          payload_bytes=_payload_bytes(slack_chunks))
            if not slack_chunks:
                insert_source_status_chunk(
                    conn, project_id,
                    source="slack", status="fetch_empty",
                    text="Slack keyword search returned no usable content.",
                    metadata={"channels": channels[:10], "keywords": keywords[:12]},
                )
                inserted += 1
            for c in slack_chunks:
                url = c["metadata"].get("url")
                if url and chunk_url_exists(conn, project_id, url):
                    continue
                if insert_external_chunk(conn, project_id, "message", c["text"], c["metadata"]):
                    inserted += 1

        notion_cfg = (sources.get("notion") or {}) if isinstance(sources, dict) else {}
        pages = notion_cfg.get("pages") or []
        if pages and isinstance(pages, list):
            notion_chunks: list[dict] = []
            with _profile_span("fetch_notion_keywords",
                               pages=len(pages), keywords=len(keywords)):
                try:
                    notion_chunks = fetch_notion_keywords(pages, keywords)
                except Exception as exc:  # noqa: BLE001
                    log("WARN", f"notion keyword search failed: {exc}")
                    notion_chunks = []
            _profile_emit("fetch_notion_keywords.payload",
                          chunks=len(notion_chunks),
                          payload_bytes=_payload_bytes(notion_chunks))
            if not notion_chunks:
                insert_source_status_chunk(
                    conn, project_id,
                    source="notion", status="fetch_empty",
                    text="Notion keyword search returned no usable content.",
                    metadata={"pages": pages[:10], "keywords": keywords[:12]},
                )
                inserted += 1
            for c in notion_chunks:
                url = c["metadata"].get("url")
                if url and chunk_url_exists(conn, project_id, url):
                    continue
                if insert_external_chunk(conn, project_id, "spec", c["text"], c["metadata"]):
                    inserted += 1

    if inserted:
        conn.commit()
    return inserted


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_analyze_prompt(_argv: list[str]) -> int:
    prompt = sys.stdin.read()
    if not prompt.strip():
        sys.stdout.write("{}")
        return 0
    res = analyze_prompt(prompt)
    sys.stdout.write(json.dumps(res or {}, ensure_ascii=False))
    return 0


def cmd_prefill(argv: list[str]) -> int:
    """Foreground prefill — DB에 이미 저장된 chunk만 검색해서 context block을
    찍는다. analyze_prompt(haiku)·lazy_fetch(MCP)는 LLM/네트워크 왕복으로 수십 초가
    드므로 cmd_lazy_fetch가 백그라운드에서 처리한다 (다음 turn부터 chunk 노출)."""
    if not argv:
        return 1
    project_id = argv[0]
    session_id = argv[1] if len(argv) > 1 else os.environ.get("IMPRINT_SESSION_ID", "")
    request_id = argv[2] if len(argv) > 2 else ""
    prompt = sys.stdin.read()
    if not prompt.strip():
        return 0

    t0 = time.monotonic()
    chunks: list[dict] = []
    working_count = 0
    retrieved_count = 0
    need_retrieval, retrieval_reason = retrieval_gate(prompt)
    try:
        try:
            with db() as conn:
                working = load_working_context(
                    conn, project_id, session_id, limit=WORKING_CONTEXT_LIMIT,
                )
                working_count = len(working)
                retrieved = []
                if need_retrieval:
                    retrieved = search_memory(
                        conn, project_id, prefill_keywords(prompt), prompt,
                        limit=PREFILL_CONTEXT_LIMIT,
                    )
                retrieved_count = len(retrieved)
                seen: set[str] = set()
                chunks = []
                for c in working + retrieved:
                    cid = c.get("id")
                    if cid in seen:
                        continue
                    if cid:
                        seen.add(cid)
                    chunks.append(c)
                    if len(chunks) >= PREFILL_CONTEXT_LIMIT:
                        break
        except sqlite3.Error as exc:
            log("WARN", f"db prefill: {exc}")
            chunks = []
    finally:
        _profile_emit("cmd_prefill",
                      project_id=project_id,
                      dur_ms=int((time.monotonic() - t0) * 1000),
                      chunks=len(chunks),
                      working_chunks=working_count,
                      retrieved_chunks=retrieved_count,
                      retrieved_search_skipped=not need_retrieval,
                      need_retrieval=need_retrieval,
                      retrieval_reason=retrieval_reason,
                      prompt_bytes=len(prompt))

    if not chunks:
        _profile_emit("cmd_prefill.sections",
                      project_id=project_id,
                      query=0, session=0, retrieved=0, external=0,
                      need_retrieval=need_retrieval,
                      retrieval_reason=retrieval_reason)
        return 0

    sections: dict[str, list[dict]] = {
        "query": [],
        "session": [],
        "retrieved": [],
        "external": [],
    }
    for c in chunks:
        md = {}
        try:
            md = json.loads(c.get("metadata_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            pass
        section = _chunk_section(c)
        if section == "query" and request_id and md.get("request_id") != request_id:
            section = "session"
        sections[section].append(c)

    _profile_emit("cmd_prefill.sections",
                  project_id=project_id,
                  query=len(sections["query"]),
                  session=len(sections["session"]),
                  retrieved=len(sections["retrieved"]),
                  external=len(sections["external"]),
                  need_retrieval=need_retrieval,
                  retrieval_reason=retrieval_reason)

    out_lines = ["[Project memory context]"]
    if not need_retrieval:
        out_lines.append(f"(retrieved-memory search skipped: {retrieval_reason})")

    def append_section(title: str, items: list[dict]) -> None:
        if not items:
            return
        out_lines.append(f"[{title}]")
        for c in items:
            md = {}
            try:
                md = json.loads(c.get("metadata_json") or "{}")
            except (json.JSONDecodeError, TypeError):
                pass
            src = md.get("source_type") or md.get("source")
            tag = c["chunk_type"]
            if md.get("memory_tier") == "working":
                tag = "working"
            if src in ("slack", "notion"):
                tag = src
            text = (c["text"] or "").replace("\n", " ").strip()
            if md.get("memory_tier") == "working":
                text = (c["text"] or "").split("\n", 1)[0].strip()
            out_lines.append(f"- [{tag}] {text[:300]}")

    append_section("Query context", sections["query"])
    append_section("Session memory", sections["session"])
    append_section("Retrieved memory", sections["retrieved"])
    append_section("External source context", sections["external"])

    sys.stdout.write("\n" + "\n".join(out_lines) + "\n")
    return 0


def cmd_mini_ingest(argv: list[str]) -> int:
    """UserPromptSubmit 동기 경량 저장.

    현재 turn 의 raw query 를 즉시 FTS-visible memory_chunks row 로 넣는다.
    LLM 기반 persistent memory 분류는 기존처럼 Stop/lazy-fetch background 에 남긴다.
    """
    if len(argv) < 2:
        return 1
    project_id = argv[0]
    source_event_id = argv[1]
    session_id = argv[2] if len(argv) > 2 else ""
    prompt = sys.stdin.read()
    if not prompt.strip():
        return 0
    try:
        with db() as conn:
            insert_working_turn_chunk(
                conn, project_id, source_event_id, session_id, prompt,
            )
            conn.commit()
    except sqlite3.Error as exc:
        log("WARN", f"mini-ingest skipped: {exc}")
    return 0


def cmd_lazy_fetch(argv: list[str]) -> int:
    """Background ingestion — analyze_prompt + lazy_fetch + insert.
    user-prompt-submit hook이 nohup으로 띄워 사용자 turn을 막지 않게 한다.
    stdout 출력 없음. 모든 실패는 plugin.log에만 기록."""
    if not argv:
        return 1
    project_id = argv[0]
    prompt = sys.stdin.read()
    if not prompt.strip():
        return 0

    _profile_emit("cmd_lazy_fetch.enter", project_id=project_id, prompt_bytes=len(prompt))
    t0 = time.monotonic()
    inserted = 0
    try:
        analysis = analyze_prompt(prompt) or {}
        keywords = list(analysis.get("keywords") or [])

        root = project_root()
        sources = load_sources(root)
        try:
            with db() as conn:
                try:
                    inserted = lazy_fetch(conn, project_id, prompt, keywords, sources)
                    log("INFO", f"bg lazy-fetch inserted={inserted} project={project_id}")
                except Exception as exc:  # noqa: BLE001
                    log("WARN", f"bg lazy_fetch wrapper: {exc}")
        except sqlite3.Error as exc:
            log("WARN", f"bg lazy_fetch db: {exc}")
    finally:
        _profile_emit("cmd_lazy_fetch.exit",
                      project_id=project_id,
                      dur_ms=int((time.monotonic() - t0) * 1000),
                      inserted=inserted)
    return 0


def cmd_extract(argv: list[str]) -> int:
    if not argv:
        return 1
    project_id = argv[0]
    source_event_id = argv[1] if len(argv) > 1 else None
    response = sys.stdin.read()
    if not response.strip():
        return 0
    _profile_emit("cmd_extract.enter",
                  project_id=project_id, response_bytes=len(response))
    t0 = time.monotonic()
    chunks_count = 0
    try:
        chunks = extract_chunks_from_response(response)
        chunks_count = len(chunks)
        if not chunks:
            return 0
        try:
            with db() as conn:
                inserted_count = 0
                for c in chunks:
                    if insert_extracted_chunk(
                        conn, project_id, source_event_id,
                        c["chunk_type"], c["text"], c["keywords"],
                    ):
                        inserted_count += 1
                conn.commit()
            log("INFO", f"extracted {inserted_count}/{len(chunks)} chunks for project={project_id}")
        except sqlite3.Error as exc:
            log("WARN", f"extract insert: {exc}")
        return 0
    finally:
        _profile_emit("cmd_extract.exit",
                      project_id=project_id,
                      dur_ms=int((time.monotonic() - t0) * 1000),
                      chunks=chunks_count)


def cmd_refresh(argv: list[str]) -> int:
    """`refresh <project_id> <spec>` — DELETE matching external chunks then re-fetch.

    spec:
      <url>          : single URL refresh
      source slack   : all slack chunks
      source notion  : all notion chunks
      project        : all external chunks
    """
    if len(argv) < 2:
        sys.stderr.write("usage: refresh <project_id> <url|source slack|source notion|project>\n")
        return 1
    project_id = argv[0]
    spec = argv[1]
    rest = argv[2:]

    deleted = 0
    fetched = 0
    try:
        with db() as conn:
            if spec.startswith("http"):
                cur = conn.execute(
                    "DELETE FROM memory_chunks "
                    "WHERE project_id = ? AND json_extract(metadata_json, '$.url') = ?;",
                    (project_id, spec),
                )
                deleted = cur.rowcount
                conn.commit()
                if SLACK_PERMALINK_RE.match(spec):
                    chunks = fetch_slack_url(spec, "")
                    ct = "thread" if is_slack_thread_url(spec) else "message"
                elif NOTION_URL_RE.match(spec):
                    chunks = fetch_notion_url(spec)
                    ct = "spec"
                else:
                    chunks = None
                    ct = "note"
                if chunks:
                    for c in chunks:
                        if insert_external_chunk(conn, project_id, ct, c["text"], c["metadata"]):
                            fetched += 1
                    conn.commit()
            elif spec == "source" and rest and rest[0] in ("slack", "notion"):
                src = rest[0]
                cur = conn.execute(
                    "DELETE FROM memory_chunks "
                    "WHERE project_id = ? AND json_extract(metadata_json, '$.source') = ?;",
                    (project_id, src),
                )
                deleted = cur.rowcount
                conn.commit()
                # No automatic re-fetch for bulk delete — next prefill will repopulate
                # via keyword lazy fetch. This matches D24 (DELETE → 다음 prompt에서 자연 fetch).
            elif spec == "project":
                cur = conn.execute(
                    "DELETE FROM memory_chunks "
                    "WHERE project_id = ? AND json_extract(metadata_json, '$.source') IN ('slack','notion');",
                    (project_id,),
                )
                deleted = cur.rowcount
                conn.commit()
            else:
                sys.stderr.write(f"unknown refresh spec: {spec} {rest}\n")
                return 2
    except sqlite3.Error as exc:
        sys.stderr.write(f"refresh db error: {exc}\n")
        return 3

    sys.stdout.write(f"refresh deleted={deleted} fetched={fetched} spec={spec}\n")
    return 0


COMMANDS = {
    "analyze-prompt": cmd_analyze_prompt,
    "mini-ingest": cmd_mini_ingest,
    "prefill": cmd_prefill,
    "lazy-fetch": cmd_lazy_fetch,
    "extract": cmd_extract,
    "refresh": cmd_refresh,
}


def main(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write("usage: ingestion.py <command> [args]\n")
        sys.stderr.write(f"commands: {', '.join(COMMANDS)}\n")
        return 1
    cmd = argv[0]
    fn = COMMANDS.get(cmd)
    if not fn:
        sys.stderr.write(f"unknown command: {cmd}\n")
        return 1
    try:
        return fn(argv[1:])
    except Exception as exc:  # noqa: BLE001  (hooks must not raise)
        log("ERROR", f"{cmd} fatal: {exc}")
        return 0  # exit 0 so hooks never block the user


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
