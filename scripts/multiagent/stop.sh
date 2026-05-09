#!/bin/bash
# Stop hook: log final assistant response of the turn for memory accumulation.
# Phase 2 minimum: persists the response as a `llm_response` event.
# Chunk extraction (decision/error/fix/etc.) lands in Phase 3.
#
# stdin: JSON with session info; transcript path is in transcript_path field.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

INPUT=$(cat || true)

TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get("transcript_path", ""))
except Exception:
    pass
' 2>>"$MULTIAGENT_LOG" || true)

if [[ -z "${TRANSCRIPT_PATH// }" || ! -f "$TRANSCRIPT_PATH" ]]; then
  exit 0
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  log_error "sqlite3 missing; stop hook skipped"
  exit 0
fi

# Extract last assistant text from the JSONL transcript.
LAST_TEXT=$(python3 - "$TRANSCRIPT_PATH" <<'PY' 2>>"$MULTIAGENT_LOG" || true
import json, sys
path = sys.argv[1]
last = ""
try:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("type") != "assistant":
                continue
            msg = row.get("message", {})
            parts = msg.get("content", [])
            buf = []
            if isinstance(parts, list):
                for p in parts:
                    if isinstance(p, dict) and p.get("type") == "text":
                        buf.append(p.get("text", ""))
                    elif isinstance(p, str):
                        buf.append(p)
            elif isinstance(parts, str):
                buf.append(parts)
            joined = "\n".join([b for b in buf if b])
            if joined:
                last = joined
except FileNotFoundError:
    pass
print(last)
PY
)

if [[ -z "${LAST_TEXT// }" ]]; then
  exit 0
fi

PID=$(project_id)
NOW=$(now_iso)
EVENT_ID=$(new_id)
ESC_TEXT=$(sql_escape "$LAST_TEXT")

db_exec "
  INSERT INTO events (id, project_id, source, kind, text_clean, created_at)
  VALUES ('$EVENT_ID', '$PID', 'claude_code', 'llm_response', '$ESC_TEXT', '$NOW');
" 2>>"$MULTIAGENT_LOG" || true

log_info "stop logged event=$EVENT_ID project=$PID bytes=${#LAST_TEXT}"
exit 0
