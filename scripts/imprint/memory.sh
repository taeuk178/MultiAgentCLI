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
  remember <text>            Store an explicit chunk (--type <t>, --pin)
  inject <id>                Print a chunk's text for context injection
  show <id> [--json]         Pretty-print a chunk's text + metadata (debug)
  pin <id>                   Mark chunk as pinned (always prefilled)
  unpin <id>                 Remove pinned status
  list [--recent|--pinned|--type <t>|--source <slack|notion|internal>]
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
  local esc; esc=$(sql_escape "$query")
  db_exec "
    SELECT m.id, m.chunk_type, substr(m.text, 1, 200)
    FROM memory_chunks_fts f
    JOIN memory_chunks m ON m.rowid = f.rowid
    WHERE f.text MATCH '$esc' AND m.project_id = '$pid'
    ORDER BY m.pinned DESC, m.created_at DESC
    LIMIT 20;
  "
}

cmd_remember() {
  local text=""
  local chunk_type="note"
  local pinned=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --type) chunk_type="${2:-note}"; shift 2 ;;
      --pin)  pinned=1; shift ;;
      *)      text+="${text:+ }$1"; shift ;;
    esac
  done
  if [[ -z "${text// }" ]]; then
    echo "remember requires <text>" >&2
    exit 1
  fi
  local pid; pid=$(project_id)
  local id; id=$(new_id)
  local now; now=$(now_iso)
  local esc_text; esc_text=$(sql_escape "$text")
  local esc_type; esc_type=$(sql_escape "$chunk_type")
  db_exec "
    INSERT INTO memory_chunks (id, project_id, chunk_type, text, created_at, pinned)
    VALUES ('$id', '$pid', '$esc_type', '$esc_text', '$now', $pinned);
  "
  echo "remembered $id ($chunk_type, pinned=$pinned)"
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
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --recent) mode="recent"; shift ;;
      --pinned) mode="pinned"; shift ;;
      --type)   type_filter="${2:-}"; shift 2 ;;
      --source) source_filter="${2:-}"; shift 2 ;;
      *)        shift ;;
    esac
  done
  local pid; pid=$(project_id)
  local where="project_id = '$pid'"
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
      # internal = chunks without an explicit external source tag
      where+=" AND coalesce(json_extract(metadata_json, '\$.source'), '') NOT IN ('slack','notion')"
    else
      where+=" AND json_extract(metadata_json, '\$.source') = '$esc_s'"
    fi
  fi
  db_exec "
    SELECT id, chunk_type, pinned,
           coalesce(json_extract(metadata_json, '\$.source'), 'internal') AS src,
           substr(text, 1, 100)
    FROM memory_chunks
    WHERE $where
    ORDER BY pinned DESC, created_at DESC
    LIMIT 50;
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

if fmt == "json":
    sys.stdout.write(json.dumps({
        "id": rid, "project_id": project_id,
        "source_event_id": source_event_id, "chunk_type": chunk_type,
        "pinned": bool(pinned), "created_at": created_at,
        "metadata": metadata, "text": text,
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
print(f"Source event:  {source_event_id or '<none — external or manual>'}")
print()
print("Metadata:")
if metadata:
    # Stable ordering: source/url first, then everything else alphabetically.
    priority = ["source", "url", "channel", "author", "posted_at", "edited_at",
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
