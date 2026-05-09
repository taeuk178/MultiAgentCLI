#!/bin/bash
# UserPromptSubmit hook:
#   1) log user input to events
#   2) inject pinned + recent memory chunks (project memory context block)
#   3) evaluate keyword routing rules from .imprint/UserPromptSubmit.md and
#      prepend any matched advisories
#
# stdin: JSON with { "prompt": "...", "session_id": "...", ... }
# stdout: extra context text (Claude Code prepends to the user message)

set -euo pipefail
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

if [[ -z "${PROMPT// }" ]]; then
  exit 0
fi

# --- 1. Persist user_message event ------------------------------------------

if command -v sqlite3 >/dev/null 2>&1; then
  PID=$(project_id)
  NOW=$(now_iso)
  EVENT_ID=$(new_id)
  ESC_PROMPT=$(sql_escape "$PROMPT")
  db_exec "
    INSERT INTO events (id, project_id, source, kind, text_clean, created_at)
    VALUES ('$EVENT_ID', '$PID', 'claude_code', 'user_message', '$ESC_PROMPT', '$NOW');
  " 2>>"$IMPRINT_LOG" || true
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
# ingestion.py prefill handles:
#   - claude -p haiku ambiguity analysis (AC2)
#   - Slack/Notion lazy fetch with url-based dedup (AC1, AC12, AC15)
#   - Memory search via FTS5 + keywords union ranking (AC11)
#   - Emits [Refined prompt suggestion] + [Project memory context] blocks
# Failures are silent (log-only) so the hook never blocks the user (AC4).

PREFILL_OUT=""
if [[ -n "$PID" && -x "$(command -v python3)" ]]; then
  PREFILL_OUT=$(printf '%s' "$PROMPT" \
    | python3 "$SCRIPT_DIR/lib/ingestion.py" prefill "$PID" 2>>"$IMPRINT_LOG" || true)
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
