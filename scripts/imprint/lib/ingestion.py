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
- Dedup key = metadata_json.url. If a chunk with the same url already exists
  for this project, fetch is skipped entirely (D22, AC15).
- All claude -p calls use --model haiku for latency + cost (D19, AC13).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

IMPRINT_HOME = Path(os.environ.get("IMPRINT_HOME") or (Path.home() / ".claude" / "imprint"))
IMPRINT_DB = IMPRINT_HOME / "app.sqlite"
IMPRINT_LOG = IMPRINT_HOME / "plugin.log"

AMBIGUITY_THRESHOLD = float(os.environ.get("IMPRINT_AMBIGUITY_THRESHOLD") or "0.5")
# 실측: spawn된 claude -p haiku는 사용자 repo의 CLAUDE.md까지 로드하므로
# 단순 prompt도 10~20초 걸린다. fetch는 MCP RTT까지 더해져 더 오래 걸림.
CLAUDE_TIMEOUT_PREFILL = int(os.environ.get("IMPRINT_CLAUDE_TIMEOUT_PREFILL") or "25")
CLAUDE_TIMEOUT_FETCH = int(os.environ.get("IMPRINT_CLAUDE_TIMEOUT_FETCH") or "45")
CLAUDE_TIMEOUT_EXTRACT = int(os.environ.get("IMPRINT_CLAUDE_TIMEOUT_EXTRACT") or "30")
CLAUDE_BIN = os.environ.get("IMPRINT_CLAUDE_BIN") or "claude"

# LLM이 응답에서 추출하도록 허용된 chunk_type. 외부 source 전용 타입
# (spec/message/thread)은 ingestion 경로에서만 직접 INSERT한다.
CHUNK_TYPES = (
    "decision", "error", "fix", "command", "test_result",
    "summary", "todo", "code_context", "note",
)
EXTERNAL_CHUNK_TYPES = ("spec", "message", "thread")

SLACK_PERMALINK_RE = re.compile(
    r"https://[a-z0-9\-]+\.slack\.com/archives/[A-Z0-9]+/p\d+(?:\?[^\s]*)?",
    re.IGNORECASE,
)
NOTION_URL_RE = re.compile(
    r"https://(?:www\.)?notion\.so/(?:[^\s/]+/)?[^\s?]+(?:\?[^\s]*)?",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(level: str, msg: str) -> None:
    try:
        IMPRINT_HOME.mkdir(parents=True, exist_ok=True)
        with IMPRINT_LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{now_iso()}] {level}: {msg}\n")
    except OSError:
        pass


def db() -> sqlite3.Connection:
    IMPRINT_HOME.mkdir(parents=True, exist_ok=True)
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


# ---------------------------------------------------------------------------
# claude -p haiku helpers
# ---------------------------------------------------------------------------

DEFAULT_ALLOWED_TOOLS_FETCH = os.environ.get(
    "IMPRINT_ALLOWED_TOOLS_FETCH",
    # 사용자가 어떤 이름으로 Notion/Slack MCP를 등록했는지는 환경마다 다르다.
    # 인증/거부는 claude가 자체 처리하므로 plugin은 read-only MCP 이름 패턴만
    # 와일드카드로 열어두면 충분하다. --dangerously-skip-permissions는 쓰지 않음.
    "mcp__claude_ai_Notion__*,"
    "mcp__notion__*,"
    "mcp__claude_ai_Slack__*,"
    "mcp__slack__*",
)


def call_claude(prompt: str, *, timeout: int, needs_tools: bool = False) -> str | None:
    """Run `claude -p --model haiku` with the given prompt. Returns stdout
    text on success, None on any failure (timeout, non-zero exit, missing CLI).

    needs_tools=True passes a read-only allow-list of Slack/Notion MCP tools so
    fetch operations work non-interactively. Pure analysis/extraction calls
    pass no allow-list so claude -p stays in tool-less mode (faster, safer)."""
    cmd = [CLAUDE_BIN, "-p", "--model", "haiku", "--output-format", "text"]
    if needs_tools and DEFAULT_ALLOWED_TOOLS_FETCH:
        cmd.extend(["--allowed-tools", DEFAULT_ALLOWED_TOOLS_FETCH])
    else:
        cmd.extend(["--allowed-tools", ""])
    cmd.append("--")
    cmd.append(prompt)
    # 서브프로세스가 다시 imprint hook을 타면서 자기 자신을 무한히 spawn하는 걸
    # 막는다. session-start / user-prompt-submit / stop 모두 이 변수를 보고 즉시 종료한다.
    sub_env = os.environ.copy()
    sub_env["IMPRINT_BYPASS_HOOKS"] = "1"
    try:
        # stdin=DEVNULL: claude -p가 stdin을 3초 기다리는 "no stdin data received"
        # 경고를 회피한다. 우리는 prompt를 argv로만 전달하므로 stdin이 필요 없다.
        result = subprocess.run(
            cmd,
            capture_output=True, text=True,
            timeout=timeout,
            env=sub_env,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        log("WARN", f"claude CLI not found at {CLAUDE_BIN}")
        return None
    except subprocess.TimeoutExpired:
        log("WARN", f"claude -p timeout after {timeout}s")
        return None
    except OSError as exc:
        log("WARN", f"claude -p exec error: {exc}")
        return None
    if result.returncode != 0:
        log("WARN", f"claude -p rc={result.returncode}: {result.stderr[:300]}")
        return None
    return result.stdout


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
You analyze a user prompt for an iOS team Claude Code session.

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
    out = call_claude(
        PREFILL_PROMPT.replace("{PROMPT}", prompt[:4000]),
        timeout=CLAUDE_TIMEOUT_PREFILL,
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
        out = call_claude(
            SLACK_FETCH_THREAD_PROMPT.replace("{URL}", url).replace("{PROMPT}", prompt[:1000]),
            timeout=CLAUDE_TIMEOUT_FETCH,
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
    out = call_claude(
        SLACK_FETCH_SINGLE_PROMPT.replace("{URL}", url),
        timeout=CLAUDE_TIMEOUT_FETCH,
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
    out = call_claude(
        SLACK_KEYWORD_PROMPT
            .replace("{CHANNELS}", json.dumps(channels, ensure_ascii=False))
            .replace("{KEYWORDS}", json.dumps(keywords, ensure_ascii=False)),
        timeout=CLAUDE_TIMEOUT_FETCH,
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
    out = call_claude(
        NOTION_FETCH_PROMPT.replace("{URL_OR_ID}", url_or_id),
        timeout=CLAUDE_TIMEOUT_FETCH,
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
    out = call_claude(
        NOTION_KEYWORD_PROMPT
            .replace("{PAGES}", json.dumps(pages, ensure_ascii=False))
            .replace("{KEYWORDS}", json.dumps(keywords, ensure_ascii=False)),
        timeout=CLAUDE_TIMEOUT_FETCH,
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
        ") LIMIT 1;",
        (project_id, url, url + "#%"),
    )
    return cur.fetchone() is not None


def insert_external_chunk(
    conn: sqlite3.Connection,
    project_id: str,
    chunk_type: str,
    text: str,
    metadata: dict,
) -> str:
    metadata = dict(metadata or {})
    metadata.setdefault("fetched_at", now_iso())
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
    md = {"source": "llm_response", "keywords": keywords}
    conn.execute(
        "INSERT INTO memory_chunks "
        "(id, project_id, source_event_id, chunk_type, text, metadata_json, created_at, pinned) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 0);",
        (cid, project_id, source_event_id, chunk_type, text, json.dumps(md, ensure_ascii=False), now_iso()),
    )
    return cid


# ---------------------------------------------------------------------------
# Stop-hook chunk extraction (AC3, AC11, D8, D12)
# ---------------------------------------------------------------------------

EXTRACT_PROMPT = """\
Extract durable knowledge chunks from this assistant response. Return STRICT JSON array.

Each item:
{
  "chunk_type": one of ["decision","error","fix","command","test_result","summary","todo","code_context","note"],
  "text": "<<=400 chars, captures the chunk in plain prose>",
  "keywords": [<3-8 short search terms, Korean+English synonyms when natural>]
}

Skip greetings, small talk, repeated content, narration of what you did.
ONLY save items that would be useful in a future session as a fact, decision, or pointer.
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
    out = call_claude(
        EXTRACT_PROMPT.replace("{RESPONSE}", response[:8000]),
        timeout=CLAUDE_TIMEOUT_EXTRACT,
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

    # 3. fallback: 최근 durable chunk (decision/fix/todo/note + 외부 source)
    # 외부 source chunk를 'note'에서 spec/message/thread로 분리한 뒤
    # fallback이 빈 결과를 내지 않도록 신규 타입도 포함시킨다.
    if not seen:
        try:
            cur = conn.execute(
                "SELECT id, chunk_type, text, metadata_json, pinned, created_at "
                "FROM memory_chunks "
                "WHERE project_id = ? AND chunk_type IN "
                "  ('decision','fix','todo','note','spec','message','thread') "
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

    # 1) URL-explicit Slack permalinks in prompt
    for url in list(dict.fromkeys(SLACK_PERMALINK_RE.findall(prompt)))[:3]:
        if chunk_url_exists(conn, project_id, url):
            log("INFO", f"slack url cache hit, skip fetch: {url}")
            continue
        try:
            chunks = fetch_slack_url(url, prompt)
        except Exception as exc:  # noqa: BLE001  (must never propagate)
            log("WARN", f"slack fetch failed {url}: {exc}")
            chunks = None
        if not chunks:
            continue
        ct = "thread" if is_slack_thread_url(url) else "message"
        for c in chunks:
            insert_external_chunk(conn, project_id, ct, c["text"], c["metadata"])
            inserted += 1

    # 2) Notion URLs in prompt
    for url in list(dict.fromkeys(NOTION_URL_RE.findall(prompt)))[:3]:
        if chunk_url_exists(conn, project_id, url):
            continue
        try:
            chunks = fetch_notion_url(url)
        except Exception as exc:  # noqa: BLE001
            log("WARN", f"notion url fetch failed {url}: {exc}")
            chunks = None
        if not chunks:
            continue
        for c in chunks:
            url_dedup = c["metadata"].get("url")
            if url_dedup and chunk_url_exists(conn, project_id, url_dedup):
                continue
            insert_external_chunk(conn, project_id, "spec", c["text"], c["metadata"])
            inserted += 1

    # 3) Keyword mode — sources.json channels/pages
    if keywords:
        slack_cfg = (sources.get("slack") or {}) if isinstance(sources, dict) else {}
        channels = slack_cfg.get("channels") or []
        if channels and isinstance(channels, list):
            try:
                slack_chunks = fetch_slack_keywords(channels, keywords)
            except Exception as exc:  # noqa: BLE001
                log("WARN", f"slack keyword search failed: {exc}")
                slack_chunks = []
            for c in slack_chunks:
                url = c["metadata"].get("url")
                if url and chunk_url_exists(conn, project_id, url):
                    continue
                insert_external_chunk(conn, project_id, "message", c["text"], c["metadata"])
                inserted += 1

        notion_cfg = (sources.get("notion") or {}) if isinstance(sources, dict) else {}
        pages = notion_cfg.get("pages") or []
        if pages and isinstance(pages, list):
            try:
                notion_chunks = fetch_notion_keywords(pages, keywords)
            except Exception as exc:  # noqa: BLE001
                log("WARN", f"notion keyword search failed: {exc}")
                notion_chunks = []
            for c in notion_chunks:
                url = c["metadata"].get("url")
                if url and chunk_url_exists(conn, project_id, url):
                    continue
                insert_external_chunk(conn, project_id, "spec", c["text"], c["metadata"])
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
    prompt = sys.stdin.read()
    if not prompt.strip():
        return 0

    try:
        with db() as conn:
            # keywords는 비워서 search_memory의 recency-fallback 경로를 탄다.
            chunks = search_memory(conn, project_id, [], prompt, limit=8)
    except sqlite3.Error as exc:
        log("WARN", f"db prefill: {exc}")
        chunks = []

    if not chunks:
        return 0

    out_lines = ["[Project memory context]"]
    for c in chunks:
        md = {}
        try:
            md = json.loads(c.get("metadata_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            pass
        src = md.get("source")
        tag = c["chunk_type"]
        if src in ("slack", "notion"):
            tag = src
        text = (c["text"] or "").replace("\n", " ").strip()
        out_lines.append(f"- [{tag}] {text[:300]}")

    sys.stdout.write("\n" + "\n".join(out_lines) + "\n")
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
    return 0


def cmd_extract(argv: list[str]) -> int:
    if not argv:
        return 1
    project_id = argv[0]
    source_event_id = argv[1] if len(argv) > 1 else None
    response = sys.stdin.read()
    if not response.strip():
        return 0
    chunks = extract_chunks_from_response(response)
    if not chunks:
        return 0
    try:
        with db() as conn:
            for c in chunks:
                insert_extracted_chunk(
                    conn, project_id, source_event_id,
                    c["chunk_type"], c["text"], c["keywords"],
                )
            conn.commit()
        log("INFO", f"extracted {len(chunks)} chunks for project={project_id}")
    except sqlite3.Error as exc:
        log("WARN", f"extract insert: {exc}")
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
                        insert_external_chunk(conn, project_id, ct, c["text"], c["metadata"])
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
