#!/bin/bash
# SessionStart hook:
#   1) ensure DB exists and schema is current
#   2) seed <project>/.imprint/ with editable defaults (Guardrail.md, UserPromptSubmit.md)
#      from plugin defaults — never overwriting user edits
#   3) emit Guardrail.md content to stdout so it gets prepended to the session context
#
# Output: stdout is appended to the session context. Codex receives JSON
# hookSpecificOutput.additionalContext. stderr is silent.

set -euo pipefail

# 재귀 가드: ingestion.py가 spawn한 background model 서브프로세스에서 SessionStart가
# 다시 발동해 schema 재적용·Guardrail.md emit이 일어나는 걸 막는다.
if [[ "${IMPRINT_BYPASS_HOOKS:-0}" == "1" ]]; then
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

INPUT=$(cat || true)
IMPRINT_HOST="$(imprint_detect_host "$INPUT")"
export IMPRINT_HOST
SESSION_ID=$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get("session_id") or data.get("conversation_id") or data.get("thread_id") or "")
except Exception:
    pass
' 2>>"$IMPRINT_LOG" || true)

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
  # Check first so new DBs do not emit duplicate-column noise into plugin.log.
  HAS_NOISE_COL=$(db_exec "SELECT COUNT(*) FROM pragma_table_info('events') WHERE name = 'noise';" \
    2>>"$IMPRINT_LOG" || echo 0)
  if [[ "$HAS_NOISE_COL" == "0" ]]; then
    db_exec "ALTER TABLE events ADD COLUMN noise INTEGER NOT NULL DEFAULT 0;" \
      >/dev/null 2>>"$IMPRINT_LOG" || true
  fi
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

  if [[ "${IMPRINT_DISABLE_ROLLUP:-0}" != "1" && -n "${SESSION_ID// }" && -x "$(command -v python3)" ]]; then
    ROLLUP_ARGS=(--stale --json)
    if [[ -n "${SESSION_ID// }" ]]; then
      ROLLUP_ARGS+=(--exclude-session "$SESSION_ID")
    fi
    ROLLUP_ARGS+=(--max-sessions "${IMPRINT_ROLLUP_MAX_STALE_SESSIONS:-3}")
    profile_emit "session.rollup.spawn" "project=$PID exclude_session=$SESSION_ID"
    ( bash "$SCRIPT_DIR/rollup.sh" "${ROLLUP_ARGS[@]}" 2>>"$IMPRINT_LOG" || true
    ) </dev/null >/dev/null 2>&1 &
    disown 2>/dev/null || true
  fi
else
  log_error "sqlite3 not found in PATH; skipping DB setup"
  ROOT=$(project_root)
fi

# --- 2. Seed <project>/.imprint/ -----------------------------------------
# Skipped when IMPRINT_NO_SEED=1 so users can opt out per-shell or per-project.

if [[ "${IMPRINT_NO_SEED:-0}" != "1" && -d "$DEFAULTS_DIR" ]]; then
  MA_DIR="$ROOT/.imprint"
  mkdir -p "$MA_DIR" 2>/dev/null || true

  # Backward-compatible rename: preserve a user-edited soul.md by copying it
  # once into Guardrail.md before default seeding can create Guardrail.md.
  # Do not remove the legacy file automatically.
  if [[ ! -e "$MA_DIR/Guardrail.md" && -f "$MA_DIR/soul.md" ]]; then
    cp "$MA_DIR/soul.md" "$MA_DIR/Guardrail.md" 2>>"$IMPRINT_LOG" \
      && log_info "migrated $MA_DIR/soul.md to $MA_DIR/Guardrail.md" \
      || log_error "failed to migrate $MA_DIR/soul.md"
  fi

  # Top-level configs: Guardrail.md, UserPromptSubmit.md, sources.json
  for fname in Guardrail.md UserPromptSubmit.md sources.json; do
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

# --- 3. Emit Guardrail.md as session-context prepend -------------------------
# Order of preference:
#   <project>/.imprint/Guardrail.md   (user-editable, project-local)
#   <project>/.imprint/soul.md        (legacy fallback)
#   $DEFAULTS_DIR/Guardrail.md        (plugin default fallback)

GUARDRAIL=""
if [[ -f "$ROOT/.imprint/Guardrail.md" ]]; then
  GUARDRAIL="$ROOT/.imprint/Guardrail.md"
elif [[ -f "$ROOT/.imprint/soul.md" ]]; then
  GUARDRAIL="$ROOT/.imprint/soul.md"
elif [[ -f "$DEFAULTS_DIR/Guardrail.md" ]]; then
  GUARDRAIL="$DEFAULTS_DIR/Guardrail.md"
fi

if [[ -n "$GUARDRAIL" ]]; then
  GUARDRAIL_CONTEXT=$(
    printf '\n[imprint Guardrail — %s]\n' "$(basename "$GUARDRAIL")"
    cat "$GUARDRAIL"
    printf '\n'
  )
  imprint_emit_context "SessionStart" "$GUARDRAIL_CONTEXT"
fi

log_info "session-start ok project=${PID:-unknown} root=$ROOT guardrail=${GUARDRAIL:-none}"
exit 0
