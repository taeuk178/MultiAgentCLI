#!/bin/bash
# SessionStart hook:
#   1) ensure DB exists and schema is current
#   2) seed <project>/.imprint/ with editable defaults (soul.md, UserPromptSubmit.md)
#      from plugin defaults — never overwriting user edits
#   3) emit soul.md content to stdout so it gets prepended to the session context
#
# Output: stdout is appended to the session context. stderr is silent.

set -euo pipefail

# 재귀 가드: ingestion.py가 spawn한 claude -p 서브프로세스에서 SessionStart가
# 다시 발동해 schema 재적용·soul.md emit이 일어나는 걸 막는다.
if [[ "${IMPRINT_BYPASS_HOOKS:-0}" == "1" ]]; then
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEFAULTS_DIR="$PLUGIN_ROOT/prompts/defaults"

ensure_home

# --- 1. SQLite schema -------------------------------------------------------

if command -v sqlite3 >/dev/null 2>&1; then
  # Suppress stdout (PRAGMA results etc) — SessionStart's stdout becomes
  # session context, so any stray output would pollute the model input.
  sqlite3 "$IMPRINT_DB" < "$SCRIPT_DIR/lib/schema.sql" >/dev/null 2>>"$IMPRINT_LOG" \
    || log_error "schema apply failed"
  # Existing DB migration: CREATE TABLE IF NOT EXISTS won't add new columns.
  db_exec "ALTER TABLE events ADD COLUMN noise INTEGER NOT NULL DEFAULT 0;" \
    >/dev/null 2>>"$IMPRINT_LOG" || true
  db_exec "CREATE INDEX IF NOT EXISTS idx_events_project_noise ON events (project_id, noise, created_at DESC);" \
    >/dev/null 2>>"$IMPRINT_LOG" || true

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
  " >/dev/null 2>>"$IMPRINT_LOG" || log_error "project upsert failed"
else
  log_error "sqlite3 not found in PATH; skipping DB setup"
  ROOT=$(project_root)
fi

# --- 2. Seed <project>/.imprint/ -----------------------------------------
# Skipped when IMPRINT_NO_SEED=1 so users can opt out per-shell or per-project.

if [[ "${IMPRINT_NO_SEED:-0}" != "1" && -d "$DEFAULTS_DIR" ]]; then
  MA_DIR="$ROOT/.imprint"
  mkdir -p "$MA_DIR" 2>/dev/null || true

  # Top-level configs: soul.md, UserPromptSubmit.md, sources.json
  for fname in soul.md UserPromptSubmit.md sources.json; do
    src="$DEFAULTS_DIR/$fname"
    dst="$MA_DIR/$fname"
    if [[ -f "$src" && ! -e "$dst" ]]; then
      cp "$src" "$dst" 2>>"$IMPRINT_LOG" \
        && log_info "seeded $dst from defaults" \
        || log_error "failed to seed $dst"
    fi
  done

  # Hook reference docs: prompts/defaults/hooks/*.md
  if [[ -d "$DEFAULTS_DIR/hooks" ]]; then
    mkdir -p "$MA_DIR/hooks" 2>/dev/null || true
    for src in "$DEFAULTS_DIR"/hooks/*.md; do
      [[ -f "$src" ]] || continue
      fname=$(basename "$src")
      dst="$MA_DIR/hooks/$fname"
      if [[ ! -e "$dst" ]]; then
        cp "$src" "$dst" 2>>"$IMPRINT_LOG" \
          && log_info "seeded $dst from defaults" \
          || log_error "failed to seed $dst"
      fi
    done
  fi
fi

# --- 3. Emit soul.md as session-context prepend -----------------------------
# Order of preference:
#   <project>/.imprint/soul.md   (user-editable, project-local)
#   $DEFAULTS_DIR/soul.md           (plugin default fallback)

SOUL=""
if [[ -f "$ROOT/.imprint/soul.md" ]]; then
  SOUL="$ROOT/.imprint/soul.md"
elif [[ -f "$DEFAULTS_DIR/soul.md" ]]; then
  SOUL="$DEFAULTS_DIR/soul.md"
fi

if [[ -n "$SOUL" ]]; then
  printf '\n[imprint soul — %s]\n' "$(basename "$SOUL")"
  cat "$SOUL"
  printf '\n'
fi

log_info "session-start ok project=${PID:-unknown} root=$ROOT soul=${SOUL:-none}"
exit 0
