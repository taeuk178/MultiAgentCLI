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
multiagent memory <subcommand> [args]

  search <query>             FTS search across this project's memory
  remember <text>            Store an explicit chunk (--type <t>, --pin)
  inject <id>                Print a chunk's text for context injection
  pin <id>                   Mark chunk as pinned (always prefilled)
  unpin <id>                 Remove pinned status
  list [--recent|--pinned|--type <t>]
  forget <id>                Delete a chunk
USAGE
}

ensure_db() {
  if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "sqlite3 not found in PATH" >&2
    exit 1
  fi
  if [[ ! -f "$MULTIAGENT_DB" ]]; then
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
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --recent) mode="recent"; shift ;;
      --pinned) mode="pinned"; shift ;;
      --type)   type_filter="${2:-}"; shift 2 ;;
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
  db_exec "
    SELECT id, chunk_type, pinned, substr(text, 1, 120)
    FROM memory_chunks
    WHERE $where
    ORDER BY pinned DESC, created_at DESC
    LIMIT 50;
  "
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

main() {
  ensure_db
  local sub="${1:-}"; shift || true
  case "$sub" in
    search)   cmd_search "$@" ;;
    remember) cmd_remember "$@" ;;
    inject)   cmd_inject "$@" ;;
    pin)      cmd_pin "$@" 1 ;;
    unpin)    cmd_pin "$@" 0 ;;
    list)     cmd_list "$@" ;;
    forget)   cmd_forget "$@" ;;
    ""|-h|--help|help) usage ;;
    *) usage; exit 1 ;;
  esac
}

main "$@"
