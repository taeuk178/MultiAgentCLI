#!/bin/bash
# UserPromptSubmit hook:
#   1) log user input to events
#   2) write a sync working mini-chunk for first-turn visibility
#   3) inject working + query-aware memory chunks (project memory context block)
#   4) evaluate keyword routing rules from .imprint/UserPromptSubmit.md and
#      prepend any matched advisories
#
# stdin: JSON with { "prompt": "...", "session_id": "...", ... }
# stdout: extra context text (Claude Code prepends to the user message)

set -euo pipefail

# 재귀 가드: ingestion.py가 spawn한 claude -p 서브프로세스가 또 이 hook을
# 타면서 무한히 자기 자신을 호출하는 걸 막는다. ingestion.py가 IMPRINT_BYPASS_HOOKS=1
# 을 넘기면 stdout만 빈값으로 비우고 즉시 종료한다.
if [[ "${IMPRINT_BYPASS_HOOKS:-0}" == "1" ]]; then
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEFAULTS_DIR="$PLUGIN_ROOT/prompts/defaults"

INPUT=$(cat || true)
PROMPT=$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get("prompt", ""))
except Exception:
    pass
' 2>>"$IMPRINT_LOG" || true)
SESSION_ID=$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get("session_id", ""))
except Exception:
    pass
' 2>>"$IMPRINT_LOG" || true)

if [[ -z "${PROMPT// }" ]]; then
  exit 0
fi
SAFE_PROMPT=$(redact_text "$PROMPT")
NOISE=0
NOISE=$(SAFE_PROMPT="$SAFE_PROMPT" python3 - <<'PY' 2>>"$IMPRINT_LOG" || echo 0
import os, re
s = (os.environ.get("SAFE_PROMPT") or "").strip().lower()
backchannel = re.compile(r"^(응|네|넵|ㅇㅇ|좋아|그래|맞아|확인|커밋해줘|오케이|ok|yes|yeah|yep|sure)[\\s.!?~]*$", re.I)
print(1 if len(s) <= 20 and backchannel.match(s) else 0)
PY
)

# --- 1. Persist user_message event ------------------------------------------

if command -v sqlite3 >/dev/null 2>&1; then
  PID=$(project_id)
  NOW=$(now_iso)
  EVENT_ID=$(new_id)
  ESC_PROMPT=$(sql_escape "$SAFE_PROMPT")
  db_exec "
    INSERT INTO events (id, project_id, source, kind, text_clean, noise, created_at)
    VALUES ('$EVENT_ID', '$PID', 'claude_code', 'user_message', '$ESC_PROMPT', $NOISE, '$NOW');
  " 2>>"$IMPRINT_LOG" || true
  if [[ "$NOISE" == "0" && -x "$(command -v python3)" ]]; then
    printf '%s' "$SAFE_PROMPT" \
      | python3 "$SCRIPT_DIR/lib/ingestion.py" mini-ingest "$PID" "$EVENT_ID" "$SESSION_ID" \
        2>>"$IMPRINT_LOG" || true
  fi
else
  log_error "sqlite3 missing; user-prompt-submit DB write skipped"
  PID=""
fi

# --- 2. Routing advisories from .imprint/UserPromptSubmit.md -------------
# Resolution: <project>/.imprint/UserPromptSubmit.md  →  plugin default

ROOT=$(project_root)
RULES_FILE=""
if [[ -f "$ROOT/.imprint/UserPromptSubmit.md" ]]; then
  RULES_FILE="$ROOT/.imprint/UserPromptSubmit.md"
elif [[ -f "$DEFAULTS_DIR/UserPromptSubmit.md" ]]; then
  RULES_FILE="$DEFAULTS_DIR/UserPromptSubmit.md"
fi

ROUTING=""
if [[ -n "$RULES_FILE" ]]; then
  ROUTING=$(PROMPT="$PROMPT" RULES_FILE="$RULES_FILE" python3 - <<'PY' 2>>"$IMPRINT_LOG" || true
import os, re, sys

prompt = os.environ.get("PROMPT", "")
rules_path = os.environ.get("RULES_FILE", "")
if not prompt or not rules_path:
    sys.exit(0)

def split_cells(line):
    """Split a markdown table row on unescaped `|`. Treats `\\|` as a literal
    pipe inside a cell (used for regex alternation in our rules)."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    cells = re.split(r'(?<!\\)\|', s)
    cells = [c.replace(r'\|', '|').strip() for c in cells]
    return cells

def is_separator(line):
    return bool(re.match(r'^\s*\|[\s\-:|]+\|\s*$', line))

def strip_backticks(s):
    s = s.strip()
    if s.startswith("`") and s.endswith("`"):
        s = s[1:-1]
    return s

def collect_table_after(lines, predicate):
    """Yield cells lists for each row of the first markdown table whose header
    line satisfies `predicate(line)`. Stops at the first non-row line."""
    i = 0
    n = len(lines)
    while i < n:
        if predicate(lines[i]) and lines[i].lstrip().startswith("|"):
            i += 1
            if i < n and is_separator(lines[i]):
                i += 1
            while i < n and lines[i].lstrip().startswith("|") and not is_separator(lines[i]):
                yield split_cells(lines[i])
                i += 1
            return
        i += 1

def section_lines(lines, heading_substring):
    """Return the slice of lines under a heading containing `heading_substring`,
    stopping at the next heading or horizontal rule."""
    start = None
    for i, line in enumerate(lines):
        if heading_substring in line and line.lstrip().startswith("#"):
            start = i + 1
            break
    if start is None:
        return []
    end = len(lines)
    for j in range(start, len(lines)):
        s = lines[j].strip()
        if s.startswith("#") or s == "---":
            end = j
            break
    return lines[start:end]

with open(rules_path, "r", encoding="utf-8") as f:
    lines = f.read().splitlines()

# --- Negation patterns: skip routing if any matches the prompt ---
neg_lines = section_lines(lines, "부정 키워드")
neg_patterns = []
for cells in collect_table_after(neg_lines, lambda l: "패턴" in l):
    for c in cells:
        pat = strip_backticks(c)
        if pat and pat != "패턴":
            neg_patterns.append(pat)

for pat in neg_patterns:
    try:
        if re.search(pat, prompt, re.IGNORECASE):
            sys.exit(0)
    except re.error:
        continue

# --- Routing rules: 3-column table (pattern | agent | message) ---
out = []
for cells in collect_table_after(lines, lambda l: "Agent" in l and "패턴" in l):
    if len(cells) < 3:
        continue
    pat = strip_backticks(cells[0])
    agent = cells[1].strip()
    msg = "|".join(cells[2:]).strip()
    if not pat or pat.lower() == "패턴":
        continue
    try:
        if re.search(pat, prompt, re.IGNORECASE):
            out.append(f"- [{agent}] {msg}")
    except re.error:
        continue

if out:
    print("[imprint routing — UserPromptSubmit]")
    for line in out:
        print(line)
PY
)
fi

if [[ -n "${ROUTING// }" ]]; then
  printf '\n%s\n' "$ROUTING"
fi

# --- 3. Prefill pipeline ----------------------------------------------------
# 백그라운드: 무거운 작업(analyze_prompt + Slack/Notion fetch + chunk insert)을
#   nohup으로 분리한다. 새 chunk는 다음 turn의 prefill에서 노출된다.
# 포어그라운드: SQLite에 이미 저장된 chunk만 검색해서 즉시 emit (sub-second).
# 어느 쪽도 사용자 turn을 막지 않는다.

if [[ -n "$PID" && -x "$(command -v python3)" ]]; then
  TMP_BG=$(mktemp 2>/dev/null || echo "/tmp/imprint-ups-$$.tmp")
  printf '%s' "$SAFE_PROMPT" > "$TMP_BG"
  profile_emit "ups.spawn" "project=$PID prompt_bytes=${#SAFE_PROMPT}"
  ( python3 "$SCRIPT_DIR/lib/ingestion.py" lazy-fetch "$PID" < "$TMP_BG" 2>>"$IMPRINT_LOG"
    rm -f "$TMP_BG"
  ) </dev/null >/dev/null 2>&1 &
  disown 2>/dev/null || true
fi

PREFILL_OUT=""
if [[ -n "$PID" && -x "$(command -v python3)" ]]; then
  PREFILL_OUT=$(printf '%s' "$SAFE_PROMPT" \
    | python3 "$SCRIPT_DIR/lib/ingestion.py" prefill "$PID" "$SESSION_ID" "$EVENT_ID" 2>>"$IMPRINT_LOG" || true)
fi

# Fallback: if ingestion.py produced nothing (claude CLI missing, OAuth not
# configured, etc.) emit the legacy simple memory context so the user still
# benefits from prior chunks.
if [[ -z "${PREFILL_OUT// }" && -n "$PID" ]] && command -v sqlite3 >/dev/null 2>&1; then
  INJECTED=$(db_exec "
    SELECT '- [' || chunk_type || '] ' || REPLACE(text, char(10), ' ')
    FROM memory_chunks
    WHERE project_id = '$PID'
      AND chunk_type IN ('decision', 'fix', 'todo', 'note')
      AND coalesce(json_extract(metadata_json, '$.memory_tier'), '') != 'working'
    ORDER BY pinned DESC, created_at DESC
    LIMIT 5;
  " 2>>"$IMPRINT_LOG" || true)

  if [[ -n "${INJECTED// }" ]]; then
    PREFILL_OUT=$(printf '\n[Project memory context]\n%s' "$INJECTED")
  fi
fi

if [[ -n "${PREFILL_OUT// }" ]]; then
  printf '%s\n' "$PREFILL_OUT"
fi

exit 0
