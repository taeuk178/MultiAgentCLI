#!/bin/bash
# Common helpers for Imprint plugin scripts.
# Sourced by all hook and skill scripts.

set -euo pipefail

IMPRINT_HOME="${IMPRINT_HOME:-$HOME/.claude/imprint}"
IMPRINT_DB="$IMPRINT_HOME/app.sqlite"
IMPRINT_LOG="$IMPRINT_HOME/plugin.log"

# common.sh가 위치한 lib/ 기준으로 plugin root 도출 (lib → imprint/ → scripts/ → root).
IMPRINT_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMPRINT_PLUGIN_ROOT="$(cd "$IMPRINT_LIB_DIR/../../.." && pwd)"

ensure_home() {
  mkdir -p "$IMPRINT_HOME"
}

# Resolve project root: git toplevel if inside a repo, otherwise PWD.
project_root() {
  if root=$(git rev-parse --show-toplevel 2>/dev/null); then
    echo "$root"
  else
    echo "$PWD"
  fi
}

project_id() {
  local root
  root=$(project_root)
  printf '%s' "$root" | shasum -a 256 | awk '{print $1}' | cut -c1-16
}

now_iso() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

new_id() {
  if command -v uuidgen >/dev/null 2>&1; then
    uuidgen | tr '[:upper:]' '[:lower:]'
  else
    printf '%s-%s' "$(date +%s%N)" "$RANDOM"
  fi
}

# Escape a string for use as a single-quoted SQLite literal.
sql_escape() {
  printf '%s' "$1" | sed "s/'/''/g"
}

db_exec() {
  ensure_home
  sqlite3 "$IMPRINT_DB" "$@"
}

log_info() {
  ensure_home
  printf '[%s] %s\n' "$(now_iso)" "$*" >> "$IMPRINT_LOG"
}

log_error() {
  ensure_home
  printf '[%s] ERROR: %s\n' "$(now_iso)" "$*" >> "$IMPRINT_LOG"
}

# Hook scripts must never block Claude Code. Wrap risky calls so they exit 0.
safe_run() {
  if ! "$@" 2>>"$IMPRINT_LOG"; then
    log_error "command failed: $*"
    return 0
  fi
}

# IMPRINT_PROFILE=1 일 때만 ~/.claude/imprint/profile.jsonl 에 한 줄을 추가한다.
# 기본 OFF — 평소 hook latency 영향은 env 검사 한 번뿐.
# usage: profile_emit STAGE key1=val1 key2=val2 ...
# stage·key·val 안의 따옴표는 단순 escape만 한다 (값에 큰따옴표 쓰지 말 것).
profile_emit() {
  [[ "${IMPRINT_PROFILE:-0}" != "1" ]] && return 0
  local stage="${1:-unknown}"; shift || true
  local kv="$*"
  ensure_home
  printf '{"ts":"%s","pid":%s,"stage":"%s","kv":"%s"}\n' \
    "$(now_iso)" "$$" "${stage//\"/\\\"}" "${kv//\"/\\\"}" \
    >> "$IMPRINT_HOME/profile.jsonl" 2>/dev/null || true
}

# 현재 시각을 ms 단위 정수로 반환. profile span 측정용.
now_ms() {
  python3 -c 'import time; print(int(time.monotonic()*1000))' 2>/dev/null || echo 0
}

# 정규식 룰셋으로 secret을 마스킹한다. argv[1]을 입력으로 받고 결과를 stdout.
# 룰셋 우선순위: $IMPRINT_REDACT_RULES > ~/.claude/imprint/redact-rules.json > plugin default.
# python3·룰 파일·re.sub 중 하나라도 실패하면 원문 그대로 통과(무 redaction)한다.
redact_text() {
  local text="$1"
  local rules="${IMPRINT_REDACT_RULES:-$IMPRINT_HOME/redact-rules.json}"
  if [[ ! -f "$rules" ]]; then
    rules="$IMPRINT_LIB_DIR/redact-rules.default.json"
  fi
  if [[ ! -f "$rules" ]] || ! command -v python3 >/dev/null 2>&1; then
    printf '%s' "$text"
    return 0
  fi
  REDACT_RULES="$rules" python3 -c '
import json, os, re, sys
text = sys.stdin.read()
try:
    with open(os.environ["REDACT_RULES"]) as f:
        cfg = json.load(f)
except Exception:
    sys.stdout.write(text); sys.exit(0)
for rule in cfg.get("rules", []):
    pat = rule.get("pattern")
    repl = rule.get("replacement", "[REDACTED]")
    if not pat:
        continue
    try:
        text = re.sub(pat, repl, text)
    except re.error:
        continue
sys.stdout.write(text)
' <<< "$text"
}
