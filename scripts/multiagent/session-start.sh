#!/bin/bash
# SessionStart hook: ensure DB exists and schema is current.
# Output: nothing (hook runs silently unless errors).

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

ensure_home

if ! command -v sqlite3 >/dev/null 2>&1; then
  log_error "sqlite3 not found in PATH"
  exit 0
fi

sqlite3 "$MULTIAGENT_DB" < "$SCRIPT_DIR/lib/schema.sql" 2>>"$MULTIAGENT_LOG" || {
  log_error "schema apply failed"
  exit 0
}

# Upsert the current project row.
ROOT=$(project_root)
PID=$(project_id)
NAME=$(basename "$ROOT")
NOW=$(now_iso)

ESC_ROOT=$(sql_escape "$ROOT")
ESC_NAME=$(sql_escape "$NAME")

db_exec "
  INSERT INTO projects (id, root_path, name, created_at, updated_at)
  VALUES ('$PID', '$ESC_ROOT', '$ESC_NAME', '$NOW', '$NOW')
  ON CONFLICT(root_path) DO UPDATE SET updated_at = excluded.updated_at;
" || log_error "project upsert failed"

log_info "session-start ok project=$PID root=$ROOT"
exit 0
