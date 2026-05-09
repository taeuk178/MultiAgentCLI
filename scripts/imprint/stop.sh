#!/bin/bash
# Stop hook: log final assistant response of the turn for memory accumulation.
# Phase 2 minimum: persists the response as a `llm_response` event.
# Chunk extraction (decision/error/fix/etc.) lands in Phase 3.
#
# stdin: JSON with session info; transcript path is in transcript_path field.

set -euo pipefail

# 재귀 가드: ingestion.py가 spawn한 claude -p 서브프로세스가 종료될 때
# 이 Stop hook이 또 발동해 다시 ingestion.py extract를 부르는 무한 루프를 막는다.
if [[ "${IMPRINT_BYPASS_HOOKS:-0}" == "1" ]]; then
  exit 0
fi

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
' 2>>"$IMPRINT_LOG" || true)

if [[ -z "${TRANSCRIPT_PATH// }" || ! -f "$TRANSCRIPT_PATH" ]]; then
  exit 0
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  log_error "sqlite3 missing; stop hook skipped"
  exit 0
fi

# Extract last assistant text from the JSONL transcript.
LAST_TEXT=$(python3 - "$TRANSCRIPT_PATH" <<'PY' 2>>"$IMPRINT_LOG" || true
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
" 2>>"$IMPRINT_LOG" || true

# Chunk extraction을 백그라운드로 분리한다. claude 응답은 이미 사용자에게 표시된
# 상태이고, chunk 저장은 다음 turn의 prefill에서 활용되면 충분하다.
if [[ "${IMPRINT_DISABLE_EXTRACT:-0}" != "1" ]] && command -v python3 >/dev/null 2>&1; then
  TMP_BG=$(mktemp 2>/dev/null || echo "/tmp/imprint-stop-$$.tmp")
  printf '%s' "$LAST_TEXT" > "$TMP_BG"
  ( python3 "$SCRIPT_DIR/lib/ingestion.py" extract "$PID" "$EVENT_ID" < "$TMP_BG" 2>>"$IMPRINT_LOG"
    rm -f "$TMP_BG"
  ) </dev/null >/dev/null 2>&1 &
  disown 2>/dev/null || true
fi

log_info "stop logged event=$EVENT_ID project=$PID bytes=${#LAST_TEXT}"
exit 0
