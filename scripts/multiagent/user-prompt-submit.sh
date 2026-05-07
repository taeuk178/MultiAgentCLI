#!/bin/bash
# UserPromptSubmit hook: log user input, inject pinned + recent memory chunks
# as additional context for Claude Code.
#
# stdin: JSON with { "prompt": "...", "session_id": "...", ... }
# stdout: extra context text (Claude Code appends to the user message)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

INPUT=$(cat || true)
PROMPT=$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get("prompt", ""))
except Exception:
    pass
' 2>>"$MULTIAGENT_LOG" || true)

if [[ -z "${PROMPT// }" ]]; then
  exit 0
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  log_error "sqlite3 missing; user-prompt-submit skipped"
  exit 0
fi

PID=$(project_id)
NOW=$(now_iso)
EVENT_ID=$(new_id)
ESC_PROMPT=$(sql_escape "$PROMPT")

db_exec "
  INSERT INTO events (id, project_id, source, kind, text_clean, created_at)
  VALUES ('$EVENT_ID', '$PID', 'claude_code', 'user_message', '$ESC_PROMPT', '$NOW');
" 2>>"$MULTIAGENT_LOG" || true

# Inject pinned + recent decision/fix/todo chunks for this project.
INJECTED=$(db_exec "
  SELECT '- [' || chunk_type || '] ' || REPLACE(text, char(10), ' ')
  FROM memory_chunks
  WHERE project_id = '$PID'
    AND chunk_type IN ('decision', 'fix', 'todo', 'note')
  ORDER BY pinned DESC, created_at DESC
  LIMIT 5;
" 2>>"$MULTIAGENT_LOG" || true)

if [[ -n "${INJECTED// }" ]]; then
  printf '\n[Project memory context]\n%s\n' "$INJECTED"
fi

exit 0
