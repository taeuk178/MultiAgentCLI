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
  inserted directly into search_entries with source_event_id NULL (D11, AC7).
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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from retrieval.model_runtime import run_background_model
from retrieval._common import migrate_legacy_claude_db_if_needed
from retrieval.entries import build_retrieval_surface, dedup_exists, insert_search_entry

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

# Rollup 이 검색 가능한 implementation memory 로 추출하도록 허용된 타입.
RICH_CHUNK_TYPES = ("decision", "code_context", "summary", "note")
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

# Automatic prefill favors precision. These terms may still generate search
# candidates, but they never count as independent relevance evidence.
PREFILL_WEAK_TOKENS = {
    "memory", "memories", "decision", "decisions", "context", "code",
    "project", "imprint", "메모리", "기억", "결정", "맥락", "코드", "프로젝트",
}
PREFILL_QUERY_STOPWORDS = {
    "알려줘", "알려주세요", "설명해줘", "설명해주세요",
    "어떻게", "뭐야", "무엇", "동작",
}
PREFILL_KOREAN_PARTICLES = (
    "에서", "으로", "에게", "까지", "부터", "처럼",
    "을", "를", "은", "는", "이", "가", "과", "와", "의", "에", "로", "도", "만",
)

# Raw-prompt matchers preserve punctuation that TOKEN_RE deliberately drops.
STRONG_IDENTIFIER_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9_])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+(?![A-Za-z0-9_])"),
    re.compile(r"(?<![A-Za-z0-9_])v?\d+\.\d+(?:\.\d+)+(?:[-+][A-Za-z0-9.-]+)?(?![A-Za-z0-9_])", re.IGNORECASE),
    re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b"),
    re.compile(r"(?<![A-Za-z0-9_.-])[A-Za-z0-9_-]+\.[A-Za-z][A-Za-z0-9]{0,9}(?![A-Za-z0-9_.-])"),
    re.compile(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b"),
    re.compile(r"\b[a-z]+(?:[A-Z][A-Za-z0-9]*)+\b"),
)

# Foreground prefill limits. Hook latency 를 위해 query/session/retrieved context 크기를 제한한다.
WORKING_CONTEXT_LIMIT = int(os.environ.get("IMPRINT_WORKING_CONTEXT_LIMIT") or "4")
PREFILL_CONTEXT_LIMIT = int(os.environ.get("IMPRINT_PREFILL_LIMIT") or "8")
PREFILL_CANDIDATE_LIMIT = int(os.environ.get("IMPRINT_PREFILL_CANDIDATE_LIMIT") or "32")

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
        "SELECT 1 FROM search_entries "
        "WHERE project_id = ? AND ("
        "  json_extract(metadata_json, '$.url') = ? "
        "  OR json_extract(metadata_json, '$.url') LIKE ? "
        ") AND raw_type != 'source_status' AND is_current = 1 LIMIT 1;",
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
    return dedup_exists(
        conn,
        project_id,
        source_uri=source_uri,
        evidence_level=evidence_level,
        text_hash=text_hash,
        source_event_id=source_event_id,
        raw_type=chunk_type,
    )


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
    insert_search_entry(
        conn,
        project_id=project_id,
        origin="external_fetch",
        raw_type=chunk_type,
        text=text,
        metadata=metadata,
        entry_id=cid,
        source_created_at=metadata.get("posted_at") or metadata.get("last_edited_at"),
        source_updated_at=metadata.get("edited_at") or metadata.get("last_edited_at") or metadata.get("fetched_at"),
    )
    return cid


@dataclass
class ExtractedChunkPayload:
    chunk_type: str
    text: str
    keywords: list[str]
    reason: str
    files: list[str]
    symbols: list[str]
    alternatives: list[str]
    tests: list[str]
    metadata: dict[str, Any]
    retrieval_text: str | None
    text_hash: str


def prepare_extracted_chunk(
    chunk_type: str,
    text: str,
    keywords: list[str],
    reason: str | None = None,
    files: list[str] | None = None,
    symbols: list[str] | None = None,
    alternatives: list[str] | None = None,
    tests: list[str] | None = None,
    metadata_extra: dict[str, Any] | None = None,
) -> ExtractedChunkPayload:
    text = redact_text(text)
    keywords = [redact_text(k) for k in keywords]
    reason = redact_text(reason or "").strip()
    files = [redact_text(v) for v in (files or []) if v]
    symbols = [redact_text(v) for v in (symbols or []) if v]
    alternatives = [redact_text(v) for v in (alternatives or []) if v]
    tests = [redact_text(v) for v in (tests or []) if v]
    text_hash = stable_text_hash(text)
    md = {
        "source": "llm_response",
        "source_type": "chat",
        "evidence_level": "assistant_extracted",
        "grounded": False,
        "keywords": keywords,
        "text_hash": text_hash,
    }
    if metadata_extra:
        md.update(metadata_extra)
    if reason:
        md["reason"] = reason
    if files:
        md["files"] = files
    if symbols:
        md["symbols"] = symbols
    if alternatives:
        md["alternatives"] = alternatives
    if tests:
        md["tests"] = tests
    md = redact_json_value(md)
    retrieval_text = None
    if chunk_type == "decision" and (reason or files or symbols):
        retrieval_text = build_retrieval_surface(
            text=text,
            reason=reason or None,
            files=files or None,
            symbols=symbols or None,
        )
    return ExtractedChunkPayload(
        chunk_type=chunk_type,
        text=text,
        keywords=keywords,
        reason=reason,
        files=files,
        symbols=symbols,
        alternatives=alternatives,
        tests=tests,
        metadata=md,
        retrieval_text=retrieval_text,
        text_hash=text_hash,
    )


def insert_prepared_extracted_chunk(
    conn: sqlite3.Connection,
    project_id: str,
    source_event_id: str | None,
    payload: ExtractedChunkPayload,
    *,
    embedding: bytes | None = None,
    generate_embedding: bool = False,
) -> str:
    cid = str(uuid.uuid4())
    if chunk_dedup_exists(
        conn,
        project_id,
        source_uri=None,
        evidence_level="assistant_extracted",
        text_hash=payload.text_hash,
        source_event_id=source_event_id,
        chunk_type=payload.chunk_type,
    ):
        return ""
    insert_search_entry(
        conn,
        project_id=project_id,
        origin="assistant_extract",
        raw_type=payload.chunk_type,
        text=payload.text,
        metadata=payload.metadata,
        source_event_id=source_event_id,
        entry_id=cid,
        embedding=embedding,
        generate_embedding=generate_embedding,
        retrieval_text=payload.retrieval_text,
    )
    return cid


def insert_extracted_chunk(
    conn: sqlite3.Connection,
    project_id: str,
    source_event_id: str | None,
    chunk_type: str,
    text: str,
    keywords: list[str],
    reason: str | None = None,
    files: list[str] | None = None,
    symbols: list[str] | None = None,
    alternatives: list[str] | None = None,
    tests: list[str] | None = None,
    metadata_extra: dict[str, Any] | None = None,
    embedding: bytes | None = None,
    generate_embedding: bool = False,
) -> str:
    payload = prepare_extracted_chunk(
        chunk_type,
        text,
        keywords,
        reason=reason,
        files=files,
        symbols=symbols,
        alternatives=alternatives,
        tests=tests,
        metadata_extra=metadata_extra,
    )
    return insert_prepared_extracted_chunk(
        conn,
        project_id,
        source_event_id,
        payload,
        embedding=embedding,
        generate_embedding=generate_embedding,
    )


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
    insert_search_entry(
        conn,
        project_id=project_id,
        origin="source_status",
        raw_type="source_status",
        text=text,
        metadata=md,
        entry_id=cid,
    )
    return cid


RICH_EXTRACT_PROMPT = """\
Extract cross-turn implementation memory chunks from this transcript. Return STRICT JSON array.

Each item:
{
  "chunk_type": one of ["decision","code_context","summary","note"],
  "text": "<<=400 chars for most items, <=1200 chars for decision, captures the chunk in plain prose>",
  "keywords": [<3-8 short search terms, Korean+English synonyms when natural>],
  "reason": "<optional, decision only, why this decision was made>",
  "files": ["<optional, decision only, file paths literally present in the response>"],
  "symbols": ["<optional, decision only, code symbols literally present in the response>"],
  "alternatives": ["<optional, decision only, rejected options if explicit>"],
  "tests": ["<optional, decision only, test/verification facts if explicit>"]
}

Skip greetings, small talk, repeated content, narration of what you did.
ONLY save items that would be useful in a future session as a fact, decision, or pointer.
For decision items, keep the decision and its reason together in one item when possible.
The only required fields are "chunk_type" and "text"; if a sub-field is uncertain, omit it.
For files/symbols, include only exact strings that appear in the assistant response. Do not infer
or invent paths, filenames, classes, functions, or symbols.
Preserve the original language of the assistant response in "text". Do not translate
Korean facts into English or English facts into Korean.
If nothing worth saving: return [].

Output ONLY the JSON array. No markdown fence, no prose.

Assistant response:
<<<
{RESPONSE}
>>>
"""

# Backward-compatible alias for tests/importers that inspect the old name.
EXTRACT_PROMPT = RICH_EXTRACT_PROMPT


def _safe_optional_text(value: Any, max_chars: int) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_chars].strip()


def _safe_optional_list(
    value: Any,
    *,
    response: str,
    literal_only: bool = False,
    max_items: int = 8,
    max_chars: int = 160,
) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        candidate = item.strip()[:max_chars].strip()
        if not candidate:
            continue
        literal = candidate.strip("`'\"")
        if literal_only and literal not in response and candidate not in response:
            continue
        out.append(candidate)
        if len(out) >= max_items:
            break
    return out


def extract_chunks_from_response(response: str, *, mode: str = "rich") -> list[dict]:
    if not response.strip():
        return []
    if mode != "rich":
        return []
    allowed_types = set(RICH_CHUNK_TYPES)
    out = run_background_model(
        RICH_EXTRACT_PROMPT.replace("{RESPONSE}", response[:8000]),
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
        if ct not in allowed_types or not text:
            continue
        if not isinstance(kw, list):
            kw = []
        kw = [str(k).strip() for k in kw if isinstance(k, str) and str(k).strip()][:12]
        max_text = 1200 if ct == "decision" else 400
        chunk = {"chunk_type": ct, "text": text[:max_text], "keywords": kw}
        if ct == "decision":
            reason = _safe_optional_text(item.get("reason"), 800)
            files = _safe_optional_list(
                item.get("files"),
                response=response,
                literal_only=True,
                max_items=8,
                max_chars=180,
            )
            symbols = _safe_optional_list(
                item.get("symbols"),
                response=response,
                literal_only=True,
                max_items=12,
                max_chars=120,
            )
            alternatives = _safe_optional_list(
                item.get("alternatives"),
                response=response,
                max_items=5,
                max_chars=240,
            )
            tests = _safe_optional_list(
                item.get("tests"),
                response=response,
                max_items=5,
                max_chars=240,
            )
            if reason:
                chunk["reason"] = reason
            if files:
                chunk["files"] = files
            if symbols:
                chunk["symbols"] = symbols
            if alternatives:
                chunk["alternatives"] = alternatives
            if tests:
                chunk["tests"] = tests
        chunks.append(chunk)
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
    for tok in TOKEN_RE.findall(prompt or ""):
        t = tok.strip().lower()
        if len(t) < 2 or t in PREFILL_QUERY_STOPWORDS or t in seen:
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


def _project_weak_tokens(conn: sqlite3.Connection, project_id: str) -> set[str]:
    weak = set(PREFILL_WEAK_TOKENS)
    try:
        row = conn.execute(
            "SELECT root_path, name FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
    except sqlite3.Error:
        row = None
    if row:
        values = [row[1] or ""]
        if row[0]:
            values.append(Path(str(row[0])).name)
        for value in values:
            weak.update(
                tok.lower() for tok in TOKEN_RE.findall(str(value)) if len(tok) >= 2
            )
    return weak


def prefill_original_terms(
    conn: sqlite3.Connection,
    project_id: str,
    prompt: str,
) -> list[str]:
    """Return distinct original non-weak tokens used as relevance evidence."""
    weak = _project_weak_tokens(conn, project_id)
    seen: set[str] = set()
    terms: list[str] = []
    for token in TOKEN_RE.findall(prompt or ""):
        term = token.strip().lower()
        if (
            len(term) < 2
            or term in PREFILL_QUERY_STOPWORDS
            or term in weak
            or term in seen
        ):
            continue
        seen.add(term)
        terms.append(term)
    return terms


def extract_strong_identifiers(prompt: str) -> list[str]:
    """Extract file/path/symbol/version/issue identifiers from the raw prompt."""
    matches: list[tuple[int, int, str]] = []
    for pattern in STRONG_IDENTIFIER_PATTERNS:
        for match in pattern.finditer(prompt or ""):
            matches.append((match.start(), match.end(), match.group(0)))

    # Keep the longest overlapping raw identifier. For "src/foo.py", retaining
    # a second "foo.py" identifier would incorrectly admit broader candidates.
    selected: list[tuple[int, int, str]] = []
    for start, end, value in sorted(
        matches,
        key=lambda item: (-(item[1] - item[0]), item[0]),
    ):
        if any(start >= kept_start and end <= kept_end for kept_start, kept_end, _ in selected):
            continue
        selected.append((start, end, value))

    seen: set[str] = set()
    out: list[str] = []
    for _start, _end, value in sorted(selected, key=lambda item: item[0]):
        normalized = value.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(value)
    return out


def cleanup_working_memory(
    conn: sqlite3.Connection,
    project_id: str,
    session_id: str,
    now: str,
) -> None:
    """Legacy no-op.

    working overlay 는 더 이상 별도 row 로 쓰지 않고 events.metadata_json 에 붙인다.
    TTL/max 정책은 조회 시점의 created_at LIMIT/window 로 처리한다.
    """
    _ = (conn, project_id, session_id, now)


def insert_working_turn_chunk(
    conn: sqlite3.Connection,
    project_id: str,
    source_event_id: str,
    session_id: str,
    prompt: str,
) -> str:
    now = now_iso()
    query_surfaces = deterministic_query_surfaces(prompt)
    rewrite_terms = deterministic_rewrite_terms(prompt)
    need_retrieval, retrieval_reason = retrieval_gate(prompt)
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
    existing = {}
    row = conn.execute("SELECT metadata_json FROM events WHERE id = ?", (source_event_id,)).fetchone()
    if row:
        try:
            value = json.loads(row[0] or "{}")
            if isinstance(value, dict):
                existing = value
        except (json.JSONDecodeError, TypeError):
            existing = {}
    existing.update(redact_json_value(metadata))
    conn.execute(
        "UPDATE events SET metadata_json = ? WHERE id = ? AND project_id = ?",
        (json.dumps(existing, ensure_ascii=False), source_event_id, project_id),
    )
    return source_event_id


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
        SELECT id, kind AS chunk_type, text_clean AS text, metadata_json, 0 AS pinned, created_at
        FROM events
        WHERE project_id = ?
          AND kind = 'user_message'
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


@dataclass
class PrefillSearchResult:
    candidates: list[dict]
    found_count: int
    accepted_count: int
    matched_term_counts: list[int]


def _prefill_metadata(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _prefill_candidate(row: sqlite3.Row | tuple, *, bm25_score: float | None = None) -> dict:
    return {
        "id": row[0],
        "chunk_type": row[1],
        "text": row[2],
        "metadata_json": row[3],
        "pinned": int(row[4] or 0),
        "created_at": row[5] or "",
        "bm25_score": bm25_score,
        "matched_term_count": 0,
        "strong_identifier_match": False,
    }


def _merge_prefill_candidate(seen: dict[str, dict], candidate: dict) -> None:
    existing = seen.get(candidate["id"])
    if existing is None:
        seen[candidate["id"]] = candidate
    elif existing.get("bm25_score") is None and candidate.get("bm25_score") is not None:
        existing["bm25_score"] = candidate["bm25_score"]


def _candidate_literal_values(candidate: dict) -> tuple[list[str], list[str]]:
    metadata = _prefill_metadata(candidate.get("metadata_json"))
    files = metadata.get("files") if isinstance(metadata.get("files"), list) else []
    symbols = metadata.get("symbols") if isinstance(metadata.get("symbols"), list) else []
    evidence_values = [str(candidate.get("text") or "")]
    evidence_values.extend(str(value) for value in files + symbols if value)
    identifier_values = list(evidence_values)
    for key in ("source_uri", "url"):
        value = metadata.get(key)
        if value:
            identifier_values.append(str(value))
    return evidence_values, identifier_values


def _contains_exact_identifier(identifier: str, values: list[str]) -> bool:
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(identifier)}(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )
    return any(pattern.search(value) for value in values)


def _normalize_prefill_evidence_token(token: str) -> str:
    normalized = token.lower()
    for particle in PREFILL_KOREAN_PARTICLES:
        if normalized.endswith(particle) and len(normalized) - len(particle) >= 2:
            return normalized[:-len(particle)]
    return normalized


def _term_matches_evidence(term: str, evidence_tokens: set[str]) -> bool:
    normalized_term = _normalize_prefill_evidence_token(term)
    normalized_evidence = {
        _normalize_prefill_evidence_token(token) for token in evidence_tokens
    }
    if normalized_term in normalized_evidence:
        return True
    if re.fullmatch(r"[가-힣]+", normalized_term):
        return any(token.startswith(normalized_term) for token in normalized_evidence)
    return False


def _score_prefill_candidate(
    candidate: dict,
    original_terms: list[str],
    strong_identifiers: list[str],
) -> dict:
    evidence_values, identifier_values = _candidate_literal_values(candidate)
    evidence_tokens = {
        token.lower()
        for value in evidence_values
        for token in TOKEN_RE.findall(value)
    }
    matched_terms = [
        term for term in original_terms if _term_matches_evidence(term, evidence_tokens)
    ]
    strong_matches = [
        identifier
        for identifier in strong_identifiers
        if _contains_exact_identifier(identifier, identifier_values)
    ]
    candidate["matched_terms"] = matched_terms
    candidate["matched_term_count"] = len(matched_terms)
    candidate["strong_identifiers"] = strong_matches
    candidate["strong_identifier_match"] = bool(strong_matches)
    return candidate


def _prefill_recency(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError):
        return 0.0


def _prefill_candidate_order(candidate: dict) -> tuple:
    bm25_score = candidate.get("bm25_score")
    return (
        -int(bool(candidate.get("strong_identifier_match"))),
        -int(candidate.get("matched_term_count") or 0),
        bm25_score is None,
        float(bm25_score) if bm25_score is not None else 0.0,
        -_prefill_recency(candidate.get("created_at")),
        str(candidate.get("id") or ""),
    )


def _rank_prefill_pool(
    candidates: Iterable[dict],
    original_terms: list[str],
    strong_identifiers: list[str],
    limit: int,
) -> list[dict]:
    scored = [
        _score_prefill_candidate(candidate, original_terms, strong_identifiers)
        for candidate in candidates
    ]
    return sorted(scored, key=_prefill_candidate_order)[: max(0, limit)]


def _accepted_prefill_candidates(candidates: Iterable[dict]) -> list[dict]:
    return [
        candidate
        for candidate in candidates
        if candidate.get("strong_identifier_match")
        or int(candidate.get("matched_term_count") or 0) >= 2
    ]


def load_pinned_memory(
    conn: sqlite3.Connection,
    project_id: str,
    limit: int = PREFILL_CONTEXT_LIMIT,
) -> list[dict]:
    """Load pinned entries regardless of the retrieval gate."""
    cur = conn.execute(
        """
        SELECT id, raw_type, text, metadata_json, pinned, created_at
        FROM search_entries
        WHERE project_id = ?
          AND pinned = 1
          AND is_current = 1
          AND coalesce(raw_type, '') != 'source_status'
        ORDER BY created_at DESC, id
        LIMIT ?
        """,
        (project_id, max(0, limit)),
    )
    return [_prefill_candidate(row) for row in cur]


def _fts_prefill_candidates(
    conn: sqlite3.Connection,
    project_id: str,
    keywords: list[str],
    limit: int,
) -> list[dict]:
    if not keywords:
        return []
    fts_query = fts_escape(" ".join(keywords))
    if not fts_query:
        return []
    try:
        cur = conn.execute(
            """
            SELECT m.id, m.raw_type, m.text, m.metadata_json, m.pinned, m.created_at,
                   bm25(search_entries_fts) AS bm25_score
            FROM search_entries_fts
            JOIN search_entries m ON m.rowid = search_entries_fts.rowid
            WHERE search_entries_fts MATCH ?
              AND m.project_id = ?
              AND m.pinned = 0
              AND m.is_current = 1
              AND coalesce(m.raw_type, '') != 'source_status'
            ORDER BY bm25_score, m.created_at DESC
            LIMIT ?
            """,
            (fts_query, project_id, max(0, limit)),
        )
        return [_prefill_candidate(row, bm25_score=row[6]) for row in cur]
    except sqlite3.OperationalError as exc:
        log("WARN", f"fts search failed: {exc}")
        return []


def _metadata_prefill_candidates(
    conn: sqlite3.Connection,
    project_id: str,
    keywords: list[str],
    limit: int,
) -> list[dict]:
    if not keywords:
        return []
    placeholders = ",".join("?" * len(keywords))
    try:
        cur = conn.execute(
            f"""
            SELECT m.id, m.raw_type, m.text, m.metadata_json, m.pinned, m.created_at,
                   COUNT(DISTINCT lower(CAST(je.value AS TEXT))) AS hits
            FROM search_entries m,
                 json_each(json_extract(m.metadata_json, '$.keywords')) je
            WHERE m.project_id = ?
              AND m.pinned = 0
              AND m.is_current = 1
              AND coalesce(m.raw_type, '') != 'source_status'
              AND lower(CAST(je.value AS TEXT)) IN ({placeholders})
            GROUP BY m.id
            ORDER BY hits DESC, m.created_at DESC
            LIMIT ?
            """,
            [project_id, *keywords, max(0, limit)],
        )
        return [_prefill_candidate(row) for row in cur]
    except sqlite3.OperationalError as exc:
        log("WARN", f"keywords search failed: {exc}")
        return []


def _like_prefill_candidates(
    conn: sqlite3.Connection,
    project_id: str,
    short_terms: list[str],
    limit: int,
) -> list[dict]:
    terms = short_terms[:8]
    if not terms:
        return []
    clauses: list[str] = []
    params: list[str] = []
    for term in terms:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("lower(m.text) LIKE ? ESCAPE '\\'")
        params.append(f"%{escaped}%")
    try:
        cur = conn.execute(
            f"""
            SELECT m.id, m.raw_type, m.text, m.metadata_json, m.pinned, m.created_at
            FROM search_entries m
            WHERE m.project_id = ?
              AND m.pinned = 0
              AND m.is_current = 1
              AND coalesce(m.raw_type, '') != 'source_status'
              AND ({' OR '.join(clauses)})
            ORDER BY m.created_at DESC
            LIMIT ?
            """,
            [project_id, *params, max(0, limit)],
        )
        return [_prefill_candidate(row) for row in cur]
    except sqlite3.OperationalError as exc:
        log("WARN", f"like fallback search failed: {exc}")
        return []


def search_memory(
    conn: sqlite3.Connection,
    project_id: str,
    keywords: list[str],
    prompt: str,
    limit: int = PREFILL_CANDIDATE_LIMIT,
) -> PrefillSearchResult:
    """Generate, filter, and rank unpinned prefill candidates."""
    pool_limit = max(0, limit)
    original_terms = prefill_original_terms(conn, project_id, prompt)
    strong_identifiers = extract_strong_identifiers(prompt)
    seen: dict[str, dict] = {}

    for candidate in _fts_prefill_candidates(conn, project_id, keywords, pool_limit):
        _merge_prefill_candidate(seen, candidate)
    for candidate in _metadata_prefill_candidates(conn, project_id, keywords, pool_limit):
        _merge_prefill_candidate(seen, candidate)

    pool = _rank_prefill_pool(seen.values(), original_terms, strong_identifiers, pool_limit)
    accepted = _accepted_prefill_candidates(pool)
    short_terms = [term for term in original_terms if len(term) == 2]
    if len(accepted) < PREFILL_CONTEXT_LIMIT and short_terms:
        for candidate in _like_prefill_candidates(
            conn, project_id, short_terms, pool_limit,
        ):
            _merge_prefill_candidate(seen, candidate)
        pool = _rank_prefill_pool(
            seen.values(), original_terms, strong_identifiers, pool_limit,
        )
        accepted = _accepted_prefill_candidates(pool)

    accepted = sorted(accepted, key=_prefill_candidate_order)
    return PrefillSearchResult(
        candidates=accepted,
        found_count=len(pool),
        accepted_count=len(accepted),
        matched_term_counts=[
            int(candidate.get("matched_term_count") or 0) for candidate in pool
        ],
    )


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
    pinned_found = 0
    retrieved_found = 0
    retrieved_accepted = 0
    retrieved_included = 0
    matched_term_counts: list[int] = []
    need_retrieval, retrieval_reason = retrieval_gate(prompt)
    try:
        try:
            with db() as conn:
                working = load_working_context(
                    conn, project_id, session_id, limit=WORKING_CONTEXT_LIMIT,
                )
                working_count = len(working)
                pinned = load_pinned_memory(
                    conn, project_id, limit=PREFILL_CONTEXT_LIMIT,
                )
                pinned_found = len(pinned)
                search_result = PrefillSearchResult([], 0, 0, [])
                if need_retrieval:
                    search_result = search_memory(
                        conn, project_id, prefill_keywords(prompt), prompt,
                        limit=PREFILL_CANDIDATE_LIMIT,
                    )
                retrieved_found = search_result.found_count
                retrieved_accepted = search_result.accepted_count
                matched_term_counts = search_result.matched_term_counts

                pinned_ids = {c.get("id") for c in pinned if c.get("id")}
                unpinned = [
                    candidate
                    for candidate in search_result.candidates
                    if candidate.get("id") not in pinned_ids
                ]
                seen: set[str] = set()
                chunks = []
                for c in working:
                    cid = c.get("id")
                    if cid in seen:
                        continue
                    if cid:
                        seen.add(cid)
                    chunks.append(c)
                    if len(chunks) >= PREFILL_CONTEXT_LIMIT:
                        break
                if len(chunks) < PREFILL_CONTEXT_LIMIT:
                    for c in pinned + unpinned:
                        cid = c.get("id")
                        if cid in seen:
                            continue
                        if cid:
                            seen.add(cid)
                        chunks.append(c)
                        retrieved_included += 1
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
                      pinned_found=pinned_found,
                      retrieved_found=retrieved_found,
                      retrieved_accepted=retrieved_accepted,
                      retrieved_skipped_low_relevance=max(
                          0, retrieved_found - retrieved_accepted,
                      ),
                      retrieved_included=retrieved_included,
                      retrieved_chunks=retrieved_included,
                      matched_term_count=matched_term_counts,
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

    현재 turn 의 raw query surface 를 events.metadata_json 에 붙인다.
    LLM 기반 persistent memory 분류는 rollup background 에 남긴다.
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
                    "DELETE FROM search_entries "
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
                    "DELETE FROM search_entries "
                    "WHERE project_id = ? AND json_extract(metadata_json, '$.source') = ?;",
                    (project_id, src),
                )
                deleted = cur.rowcount
                conn.commit()
                # No automatic bulk re-fetch. Keyword lazy fetch can refill only when
                # IMPRINT_ENABLE_LAZY_FETCH=1 is set for a later prompt.
            elif spec == "project":
                cur = conn.execute(
                    "DELETE FROM search_entries "
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
