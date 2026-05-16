#!/bin/bash
# Memory CLI dispatcher.
# Usage:
#   memory.sh search <query>
#   memory.sh remember <text> [--type <chunk_type>] [--pin]
#   memory.sh inject <chunk-id>
#   memory.sh pin <chunk-id>
#   memory.sh unpin <chunk-id>
#   memory.sh list [--recent | --pinned | --type <type>]
#   memory.sh forget <chunk-id>

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  cat <<'USAGE'
imprint memory <subcommand> [args]

  search <query>             FTS search across this project's memory
  remember <text>            Store an explicit chunk (--type <t>, --pin, --redact)
  inject <id>                Print a chunk's text for context injection
  show <id> [--json]         Pretty-print a chunk's text + metadata (debug)
  stats [--all] [--json]     Memory 분포·통계 요약(현 프로젝트 또는 전 프로젝트)
  profile [--days <n>] [--json]
                              Summarize IMPRINT_PROFILE=1 latency/payload data
  pin <id>                   Mark chunk as pinned (always prefilled)
  unpin <id>                 Remove pinned status
  list [--recent|--pinned|--type <t>|--source <slack|notion|internal>|--working]
       [--since <YYYY-MM-DD>] [--limit <n>] [--project <path|id-prefix>]
  forget <id>                Delete a chunk
  refresh <spec>             Drop cached external chunks matching spec
                             and re-fetch on next prefill (D24, AC16):
                               <url>          single URL — DELETE + immediate re-fetch
                               source slack   all slack chunks (re-fetch on next prefill)
                               source notion  all notion chunks (re-fetch on next prefill)
                               project        all external (slack+notion) chunks
USAGE
}

ensure_db() {
  if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "sqlite3 not found in PATH" >&2
    exit 1
  fi
  if [[ ! -f "$IMPRINT_DB" ]]; then
    bash "$SCRIPT_DIR/session-start.sh" </dev/null
  fi
}

cmd_search() {
  local query="${1:-}"
  if [[ -z "$query" ]]; then
    echo "search requires <query>" >&2
    exit 1
  fi
  local pid; pid=$(project_id)
  IMPRINT_DB="$IMPRINT_DB" SEARCH_PROJECT_ID="$pid" SEARCH_QUERY="$query" python3 - <<'PY'
import os
import re
import sqlite3

db_path = os.environ["IMPRINT_DB"]
project_id = os.environ["SEARCH_PROJECT_ID"]
query = os.environ["SEARCH_QUERY"].strip()

def fts_escape(q):
    terms = [t.replace('"', '') for t in re.split(r"\s+", q) if t.replace('"', '')]
    return " OR ".join(f'"{t}"' for t in terms)

conn = sqlite3.connect(db_path, timeout=5.0)
rows = []
try:
    fts_query = fts_escape(query)
    if fts_query:
        try:
            rows = conn.execute(
                """
                SELECT m.id, m.chunk_type, substr(m.text, 1, 200), m.pinned, m.created_at
                FROM memory_chunks_fts f
                JOIN memory_chunks m ON m.rowid = f.rowid
                WHERE f.text MATCH ? AND m.project_id = ?
                  AND coalesce(json_extract(m.metadata_json, '$.memory_tier'), '') != 'working'
                ORDER BY m.pinned DESC, m.created_at DESC
                LIMIT 20;
                """,
                (fts_query, project_id),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []

    if not rows:
        tokens = []
        seen = set()
        for tok in re.findall(r"[가-힣A-Za-z0-9]+", query.lower()):
            if len(tok) < 2 or tok in seen:
                continue
            seen.add(tok)
            tokens.append(tok)
        if tokens:
            clauses = []
            params = []
            for tok in tokens[:8]:
                clauses.append("lower(text) LIKE ?")
                params.append(f"%{tok}%")
            rows = conn.execute(
                f"""
                SELECT id, chunk_type, substr(text, 1, 200), pinned, created_at
                FROM memory_chunks
                WHERE project_id = ?
                  AND coalesce(json_extract(metadata_json, '$.memory_tier'), '') != 'working'
                  AND ({' OR '.join(clauses)})
                ORDER BY pinned DESC, created_at DESC
                LIMIT 20;
                """,
                (project_id, *params),
            ).fetchall()
finally:
    conn.close()

for row in rows:
    print("|".join(str(v) for v in row[:3]))
PY
}

cmd_remember() {
  local text=""
  local chunk_type="note"
  local pinned=0
  local redact=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --type)   chunk_type="${2:-note}"; shift 2 ;;
      --pin)    pinned=1; shift ;;
      --redact) redact=1; shift ;;
      *)        text+="${text:+ }$1"; shift ;;
    esac
  done
  if [[ -z "${text// }" ]]; then
    echo "remember requires <text>" >&2
    exit 1
  fi
  local metadata="{}"
  local redacted_text
  redacted_text=$(redact_text "$text")
  if (( redact )) || [[ "$redacted_text" != "$text" ]]; then
    text="$redacted_text"
    metadata='{"redacted":true}'
  else
    text="$redacted_text"
  fi
  local pid; pid=$(project_id)
  local id; id=$(new_id)
  local now; now=$(now_iso)
  local esc_text; esc_text=$(sql_escape "$text")
  local esc_type; esc_type=$(sql_escape "$chunk_type")
  local esc_md; esc_md=$(sql_escape "$metadata")
  db_exec "
    INSERT INTO memory_chunks (id, project_id, chunk_type, text, metadata_json, created_at, pinned)
    VALUES ('$id', '$pid', '$esc_type', '$esc_text', '$esc_md', '$now', $pinned);
  "
  echo "remembered $id ($chunk_type, pinned=$pinned, redacted=$redact)"
}

cmd_inject() {
  local id="${1:-}"
  if [[ -z "$id" ]]; then
    echo "inject requires <chunk-id>" >&2
    exit 1
  fi
  local esc; esc=$(sql_escape "$id")
  db_exec "SELECT text FROM memory_chunks WHERE id = '$esc';"
}

cmd_pin() {
  local id="${1:-}"
  local val="${2:-1}"
  if [[ -z "$id" ]]; then
    echo "pin requires <chunk-id>" >&2
    exit 1
  fi
  local esc; esc=$(sql_escape "$id")
  db_exec "UPDATE memory_chunks SET pinned = $val WHERE id = '$esc';"
  echo "ok"
}

cmd_list() {
  local mode="recent"
  local type_filter=""
  local source_filter=""
  local since_filter=""
  local limit="50"
  local project_filter=""
  local include_working=0
  local stale_days="${IMPRINT_STALE_DAYS:-14}"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --recent)  mode="recent"; shift ;;
      --pinned)  mode="pinned"; shift ;;
      --type)    type_filter="${2:-}"; shift 2 ;;
      --source)  source_filter="${2:-}"; shift 2 ;;
      --working) include_working=1; shift ;;
      --since)   since_filter="${2:-}"; shift 2 ;;
      --limit)   limit="${2:-50}"; shift 2 ;;
      --project) project_filter="${2:-}"; shift 2 ;;
      *)         shift ;;
    esac
  done

  # --limit 안전: 정수가 아니면 50으로 폴백
  if ! [[ "$limit" =~ ^[0-9]+$ ]]; then
    limit=50
  fi
  if ! [[ "$stale_days" =~ ^[0-9]+$ ]]; then
    stale_days=14
  fi

  # project 결정: --project 없으면 현 프로젝트, 있으면 path(절대경로 시작)는
  # sha256으로 변환, 그 외엔 project_id prefix 매칭(LIKE).
  local where=""
  if [[ -n "$project_filter" ]]; then
    if [[ "$project_filter" == /* ]]; then
      local pid_for_path
      pid_for_path=$(printf '%s' "$project_filter" | shasum -a 256 | awk '{print $1}' | cut -c1-16)
      where="project_id = '$pid_for_path'"
    else
      local esc_pf; esc_pf=$(sql_escape "$project_filter")
      where="project_id LIKE '$esc_pf%'"
    fi
  else
    local pid; pid=$(project_id)
    where="project_id = '$pid'"
  fi

  if [[ "$mode" == "pinned" ]]; then
    where+=" AND pinned = 1"
  fi
  if [[ -n "$type_filter" ]]; then
    local esc_t; esc_t=$(sql_escape "$type_filter")
    where+=" AND chunk_type = '$esc_t'"
  fi
  if [[ -n "$source_filter" ]]; then
    local esc_s; esc_s=$(sql_escape "$source_filter")
    if [[ "$source_filter" == "internal" ]]; then
      where+=" AND coalesce(json_extract(metadata_json, '\$.source'), '') NOT IN ('slack','notion')"
    else
      where+=" AND json_extract(metadata_json, '\$.source') = '$esc_s'"
    fi
  fi
  if [[ -n "$since_filter" ]]; then
    local esc_since; esc_since=$(sql_escape "$since_filter")
    where+=" AND created_at >= '$esc_since'"
  fi
  if [[ "$include_working" == "1" ]]; then
    where+=" AND json_extract(metadata_json, '\$.memory_tier') = 'working'"
  else
    where+=" AND coalesce(json_extract(metadata_json, '\$.memory_tier'), '') != 'working'"
  fi
  db_exec "
    SELECT id, chunk_type, pinned,
           CASE
             WHEN json_extract(metadata_json, '\$.memory_tier') = 'working'
               THEN 'working'
             ELSE coalesce(json_extract(metadata_json, '\$.source'), 'internal')
           END AS src,
           CASE
             WHEN json_extract(metadata_json, '\$.status') IS NOT NULL
               THEN json_extract(metadata_json, '\$.status')
             WHEN coalesce(json_extract(metadata_json, '\$.source'), '') IN ('slack','notion')
               AND json_extract(metadata_json, '\$.fetched_at') IS NOT NULL
               AND datetime(replace(replace(json_extract(metadata_json, '\$.fetched_at'), 'T', ' '), 'Z', '')) < datetime('now', '-$stale_days days')
               THEN 'stale'
             ELSE 'ok'
           END AS status,
           substr(text, 1, 100)
    FROM memory_chunks
    WHERE $where
    ORDER BY pinned DESC, created_at DESC
    LIMIT $limit;
  "
}

cmd_show() {
  local id=""
  local fmt="pretty"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) fmt="json"; shift ;;
      *)      [[ -z "$id" ]] && id="$1"; shift ;;
    esac
  done
  if [[ -z "$id" ]]; then
    echo "show requires <chunk-id>" >&2
    exit 1
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 not found in PATH" >&2
    exit 1
  fi
  IMPRINT_DB="$IMPRINT_DB" CHUNK_ID="$id" CHUNK_FMT="$fmt" python3 - <<'PY'
import json, os, sqlite3, sys, textwrap
from datetime import datetime, timedelta, timezone

db_path = os.environ["IMPRINT_DB"]
chunk_id = os.environ["CHUNK_ID"]
fmt = os.environ.get("CHUNK_FMT", "pretty")

try:
    conn = sqlite3.connect(db_path, timeout=5.0)
except sqlite3.Error as exc:
    sys.stderr.write(f"db open failed: {exc}\n")
    sys.exit(1)

# Allow exact match OR unique prefix match (UUIDs are long).
cur = conn.execute(
    "SELECT id, project_id, source_event_id, chunk_type, text, "
    "       metadata_json, created_at, pinned "
    "FROM memory_chunks WHERE id = ? OR id LIKE ? LIMIT 2;",
    (chunk_id, chunk_id + "%"),
)
rows = cur.fetchall()
if not rows:
    sys.stderr.write(f"no chunk found for id: {chunk_id}\n")
    sys.exit(2)
if len(rows) > 1 and rows[0][0] != chunk_id:
    sys.stderr.write(f"id prefix '{chunk_id}' is ambiguous ({len(rows)} matches)\n")
    sys.exit(3)

row = rows[0]
(rid, project_id, source_event_id, chunk_type, text,
 metadata_json, created_at, pinned) = row

try:
    metadata = json.loads(metadata_json) if metadata_json else {}
except json.JSONDecodeError:
    metadata = {"_parse_error": metadata_json}

def source_status(md):
    if md.get("status"):
        return md["status"]
    if md.get("source") not in ("slack", "notion"):
        return "ok"
    fetched = md.get("fetched_at")
    if not fetched:
        return "unknown"
    try:
        ts = datetime.fromisoformat(str(fetched).replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    stale_days = int(os.environ.get("IMPRINT_STALE_DAYS", "14"))
    return "stale" if datetime.now(timezone.utc) - ts > timedelta(days=stale_days) else "ok"

status = source_status(metadata)

if fmt == "json":
    sys.stdout.write(json.dumps({
        "id": rid, "project_id": project_id,
        "source_event_id": source_event_id, "chunk_type": chunk_type,
        "pinned": bool(pinned), "created_at": created_at,
        "source_status": status, "metadata": metadata, "text": text,
    }, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    sys.exit(0)

# pretty
def line(label, value):
    print(f"  {label:<14} {value}")

print(f"ID:            {rid}")
print(f"Project:       {project_id}")
print(f"Chunk type:    {chunk_type}")
print(f"Pinned:        {'yes' if pinned else 'no'}")
print(f"Created at:    {created_at}")
print(f"Source status: {status}")
print(f"Source event:  {source_event_id or '<none — external or manual>'}")
print()
print("Metadata:")
if metadata:
    # Stable ordering: source/url first, then everything else alphabetically.
    priority = ["memory_tier", "memory_kind", "session_visible", "session_id",
                "request_id", "searchable_at", "query_rewrite",
                "source", "url", "channel", "author", "posted_at", "edited_at",
                "page_id", "page_title", "section_title", "last_edited_at",
                "fetched_at", "keywords", "kind"]
    seen = set()
    for k in priority:
        if k in metadata:
            line(k + ":", metadata[k])
            seen.add(k)
    for k in sorted(metadata):
        if k in seen:
            continue
        line(k + ":", metadata[k])
else:
    print("  <empty>")
print()
print("Text:")
wrapped = textwrap.fill(text, width=88, initial_indent="  ", subsequent_indent="  ")
print(wrapped)
PY
}

cmd_stats() {
  local scope="project"
  local fmt="pretty"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --all)  scope="all"; shift ;;
      --json) fmt="json"; shift ;;
      *)      shift ;;
    esac
  done
  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 not found in PATH" >&2
    exit 1
  fi
  local pid; pid=$(project_id)
  local root; root=$(project_root)
  IMPRINT_DB="$IMPRINT_DB" \
  STATS_PROJECT_ID="$pid" \
  STATS_PROJECT_ROOT="$root" \
  STATS_SCOPE="$scope" \
  STATS_FMT="$fmt" \
  python3 - <<'PY'
import json, os, sqlite3, sys

db_path = os.environ["IMPRINT_DB"]
project_id = os.environ["STATS_PROJECT_ID"]
project_root = os.environ["STATS_PROJECT_ROOT"]
scope = os.environ.get("STATS_SCOPE", "project")
fmt = os.environ.get("STATS_FMT", "pretty")

try:
    conn = sqlite3.connect(db_path, timeout=5.0)
except sqlite3.Error as exc:
    sys.stderr.write(f"db open failed: {exc}\n")
    sys.exit(1)

def project_summary(pid):
    cur = conn.execute(
        "SELECT COUNT(*), SUM(pinned), MIN(created_at), MAX(created_at) "
        "FROM memory_chunks WHERE project_id = ?;",
        (pid,),
    )
    total, pinned, oldest, newest = cur.fetchone()
    total = total or 0
    pinned = pinned or 0

    type_dist = conn.execute(
        "SELECT chunk_type, COUNT(*) FROM memory_chunks "
        "WHERE project_id = ? GROUP BY chunk_type ORDER BY 2 DESC;",
        (pid,),
    ).fetchall()

    source_dist = conn.execute(
        "SELECT COALESCE(json_extract(metadata_json,'$.source'),'internal'), COUNT(*) "
        "FROM memory_chunks WHERE project_id = ? "
        "GROUP BY 1 ORDER BY 2 DESC;",
        (pid,),
    ).fetchall()

    notion_urls = conn.execute(
        "SELECT COUNT(DISTINCT json_extract(metadata_json,'$.page_id')) "
        "FROM memory_chunks WHERE project_id = ? "
        "  AND json_extract(metadata_json,'$.source') = 'notion';",
        (pid,),
    ).fetchone()[0] or 0

    slack_urls = conn.execute(
        "SELECT COUNT(DISTINCT json_extract(metadata_json,'$.url')) "
        "FROM memory_chunks WHERE project_id = ? "
        "  AND json_extract(metadata_json,'$.source') = 'slack';",
        (pid,),
    ).fetchone()[0] or 0

    return {
        "project_id": pid,
        "total": total, "pinned": pinned,
        "oldest": oldest, "newest": newest,
        "chunk_type": dict(type_dist),
        "source": dict(source_dist),
        "external_urls": {"notion_pages": notion_urls, "slack_messages": slack_urls},
    }

def all_projects():
    rows = conn.execute(
        "SELECT p.id, p.root_path, COUNT(m.id), SUM(m.pinned), MAX(m.created_at) "
        "FROM projects p LEFT JOIN memory_chunks m ON m.project_id = p.id "
        "GROUP BY p.id, p.root_path "
        "ORDER BY 3 DESC;"
    ).fetchall()
    return [
        {"project_id": r[0], "path": r[1], "total": r[2] or 0,
         "pinned": r[3] or 0, "newest": r[4]}
        for r in rows
    ]

if scope == "all":
    summary = all_projects()
    if fmt == "json":
        sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        sys.exit(0)
    if not summary:
        print("(no projects)")
        sys.exit(0)
    print(f"{'project_id':<18} {'chunks':>7} {'pinned':>7}  newest                path")
    for r in summary:
        newest = r["newest"] or "-"
        print(f"{r['project_id']:<18} {r['total']:>7} {r['pinned']:>7}  {newest:<20}  {r['path']}")
    sys.exit(0)

# project scope
s = project_summary(project_id)
if fmt == "json":
    s["path"] = project_root
    sys.stdout.write(json.dumps(s, ensure_ascii=False, indent=2) + "\n")
    sys.exit(0)

print(f"project:       {s['project_id']}")
print(f"path:          {project_root}")
print(f"chunks total:  {s['total']}")
print(f"pinned:        {s['pinned']}")
print(f"oldest:        {s['oldest'] or '-'}")
print(f"newest:        {s['newest'] or '-'}")
print()
print("chunk_type:")
if s["chunk_type"]:
    for k, v in sorted(s["chunk_type"].items(), key=lambda x: (-x[1], x[0])):
        print(f"  {k:<14} {v}")
else:
    print("  <empty>")
print()
print("source:")
if s["source"]:
    for k, v in sorted(s["source"].items(), key=lambda x: (-x[1], x[0])):
        print(f"  {k:<14} {v}")
else:
    print("  <empty>")
print()
print("external URLs (unique):")
print(f"  notion_pages   {s['external_urls']['notion_pages']}")
print(f"  slack_messages {s['external_urls']['slack_messages']}")
PY
}

cmd_profile() {
  local days="7"
  local fmt="pretty"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --days) days="${2:-7}"; shift 2 ;;
      --json) fmt="json"; shift ;;
      *)      shift ;;
    esac
  done
  if ! [[ "$days" =~ ^[0-9]+$ ]]; then
    days=7
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 not found in PATH" >&2
    exit 1
  fi
  IMPRINT_HOME="$IMPRINT_HOME" PROFILE_DAYS="$days" PROFILE_FMT="$fmt" python3 - <<'PY'
import json, os, statistics, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

home = Path(os.environ["IMPRINT_HOME"])
path = home / "profile.jsonl"
days = int(os.environ.get("PROFILE_DAYS", "7"))
fmt = os.environ.get("PROFILE_FMT", "pretty")
since = datetime.now(timezone.utc) - timedelta(days=days)

def parse_ts(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None

def percentile(vals, pct):
    if not vals:
        return None
    vals = sorted(vals)
    idx = int(round((len(vals) - 1) * pct))
    return vals[idx]

stages = {}
payloads = {}
total = 0
kept = 0
if path.exists():
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            total += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = parse_ts(row.get("ts"))
            if ts is not None and ts < since:
                continue
            kept += 1
            stage = row.get("stage") or "unknown"
            dur = row.get("dur_ms")
            if dur is None and isinstance(row.get("kv"), dict):
                dur = row["kv"].get("ms") or row["kv"].get("dur_ms")
            if isinstance(dur, (int, float)):
                stages.setdefault(stage, []).append(float(dur))
            payload = row.get("payload_bytes")
            if payload is None and isinstance(row.get("kv"), dict):
                payload = row["kv"].get("payload_bytes")
            if isinstance(payload, (int, float)):
                payloads.setdefault(stage, []).append(float(payload))

summary = {
    "profile_path": str(path),
    "days": days,
    "rows_total": total,
    "rows_in_window": kept,
    "stages": {
        k: {
            "count": len(v),
            "p50_ms": percentile(v, 0.50),
            "p95_ms": percentile(v, 0.95),
            "max_ms": max(v),
        }
        for k, v in sorted(stages.items())
    },
    "payloads": {
        k: {
            "count": len(v),
            "p50_bytes": percentile(v, 0.50),
            "p95_bytes": percentile(v, 0.95),
            "max_bytes": max(v),
        }
        for k, v in sorted(payloads.items())
    },
}

if fmt == "json":
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    sys.exit(0)

print(f"profile: {path}")
print(f"window:  past {days}d, rows {kept}/{total}")
if not path.exists():
    print("status:  no profile.jsonl yet; enable IMPRINT_PROFILE=1")
    sys.exit(0)
print()
print("latency:")
if summary["stages"]:
    print(f"{'stage':<32} {'n':>5} {'p50':>8} {'p95':>8} {'max':>8}")
    for stage, s in summary["stages"].items():
        print(f"{stage:<32} {s['count']:>5} {s['p50_ms']:>8.1f} {s['p95_ms']:>8.1f} {s['max_ms']:>8.1f}")
else:
    print("  <no duration samples>")
print()
print("payload:")
if summary["payloads"]:
    print(f"{'stage':<32} {'n':>5} {'p50':>8} {'p95':>8} {'max':>8}")
    for stage, s in summary["payloads"].items():
        print(f"{stage:<32} {s['count']:>5} {s['p50_bytes']:>8.0f} {s['p95_bytes']:>8.0f} {s['max_bytes']:>8.0f}")
else:
    print("  <no payload samples>")
PY
}

cmd_forget() {
  local id="${1:-}"
  if [[ -z "$id" ]]; then
    echo "forget requires <chunk-id>" >&2
    exit 1
  fi
  local esc; esc=$(sql_escape "$id")
  db_exec "DELETE FROM memory_chunks WHERE id = '$esc';"
  echo "deleted $id"
}

cmd_refresh() {
  if [[ $# -lt 1 ]]; then
    echo "refresh requires <url|source slack|source notion|project>" >&2
    exit 1
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 not found in PATH" >&2
    exit 1
  fi
  local pid; pid=$(project_id)
  python3 "$SCRIPT_DIR/lib/ingestion.py" refresh "$pid" "$@"
}

main() {
  ensure_db
  local sub="${1:-}"; shift || true
  case "$sub" in
    search)   cmd_search "$@" ;;
    remember) cmd_remember "$@" ;;
    inject)   cmd_inject "$@" ;;
    show)     cmd_show "$@" ;;
    stats)    cmd_stats "$@" ;;
    profile)  cmd_profile "$@" ;;
    pin)      cmd_pin "$@" 1 ;;
    unpin)    cmd_pin "$@" 0 ;;
    list)     cmd_list "$@" ;;
    forget)   cmd_forget "$@" ;;
    refresh)  cmd_refresh "$@" ;;
    ""|-h|--help|help) usage ;;
    *) usage; exit 1 ;;
  esac
}

main "$@"
