#!/bin/bash
# Common helpers for Imprint plugin scripts.
# Sourced by all hook and skill scripts.

set -euo pipefail

IMPRINT_HOME="${IMPRINT_HOME:-$HOME/.imprint}"
IMPRINT_DB="$IMPRINT_HOME/app.sqlite"
IMPRINT_LOG="$IMPRINT_HOME/plugin.log"
IMPRINT_LEGACY_CLAUDE_DB="$HOME/.claude/imprint/app.sqlite"

# common.sh가 위치한 lib/ 기준으로 plugin root 도출 (lib → imprint/ → scripts/ → root).
IMPRINT_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMPRINT_PLUGIN_ROOT="$(cd "$IMPRINT_LIB_DIR/../../.." && pwd)"

ensure_home() {
  mkdir -p "$IMPRINT_HOME"
  imprint_migrate_legacy_claude_db_if_needed
}

imprint_migrate_legacy_claude_db_if_needed() {
  [[ "${IMPRINT_DISABLE_LEGACY_MIGRATION:-0}" == "1" ]] && return 0
  [[ "$IMPRINT_HOME" == "$HOME/.imprint" ]] || return 0
  [[ -f "$IMPRINT_LEGACY_CLAUDE_DB" ]] || return 0
  command -v python3 >/dev/null 2>&1 || return 0

  IMPRINT_NEW_DB="$IMPRINT_DB" \
  IMPRINT_OLD_DB="$IMPRINT_LEGACY_CLAUDE_DB" \
  IMPRINT_MIGRATION_LOG="$IMPRINT_LOG" \
  python3 - <<'PY' >/dev/null 2>>"$IMPRINT_LOG" || true
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DATA_TABLES = (
    "events",
    "memory_chunks",
    "documents",
    "chunks_v2",
    "summaries",
    "entities",
    "entity_aliases",
    "contradictions",
    "source_status",
)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg):
    try:
        path = Path(os.environ["IMPRINT_MIGRATION_LOG"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"[{now_iso()}] {msg}\n")
    except OSError:
        pass


def has_user_data(path):
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        for table in DATA_TABLES:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                continue
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if count > 0:
                return True
        return False
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def remove_legacy_files(path):
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(str(path) + suffix).unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            log(f"legacy claude db cleanup skipped path={path}{suffix} err={exc!r}")


new_db = Path(os.environ["IMPRINT_NEW_DB"])
old_db = Path(os.environ["IMPRINT_OLD_DB"])
if has_user_data(new_db) or not has_user_data(old_db):
    raise SystemExit(0)

new_db.parent.mkdir(parents=True, exist_ok=True)
src = sqlite3.connect(f"file:{old_db}?mode=ro", uri=True)
dst = sqlite3.connect(str(new_db))
try:
    src.backup(dst)
finally:
    dst.close()
    src.close()

if has_user_data(new_db):
    remove_legacy_files(old_db)
    log(f"legacy claude db migrated old={old_db} new={new_db} cleanup=removed")
PY
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

# Hook scripts must never block the host coding session. Wrap risky calls so they exit 0.
safe_run() {
  if ! "$@" 2>>"$IMPRINT_LOG"; then
    log_error "command failed: $*"
    return 0
  fi
}

# IMPRINT_PROFILE=1 일 때만 $IMPRINT_HOME/profile.jsonl 에 한 줄을 추가한다.
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
# 룰셋 우선순위: $IMPRINT_REDACT_RULES > $IMPRINT_HOME/redact-rules.json > plugin default.
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

imprint_detect_host() {
  local input="${1:-}"
  local explicit="${IMPRINT_HOST:-}"
  case "$explicit" in
    codex|claude)
      printf '%s\n' "$explicit"
      return 0
      ;;
  esac

  local from_input=""
  if command -v python3 >/dev/null 2>&1; then
    from_input=$(IMPRINT_HOOK_INPUT="$input" python3 -c '
import json, sys
import os
try:
    data = json.loads(os.environ.get("IMPRINT_HOOK_INPUT") or "{}")
except Exception:
    data = {}
keys = set(data) if isinstance(data, dict) else set()
if "last_assistant_message" in keys:
    print("codex")
' 2>/dev/null || true)
  fi
  if [[ "$from_input" == "codex" ]]; then
    printf 'codex\n'
    return 0
  fi

  if [[ -n "${CODEX_PLUGIN_ROOT:-}" || -n "${CODEX_HOME:-}" ]]; then
    printf 'codex\n'
  elif [[ -n "${CLAUDE_PLUGIN_ROOT:-}" || -n "${CLAUDE_CONFIG_DIR:-}" ]]; then
    printf 'claude\n'
  elif [[ -n "${PLUGIN_ROOT:-}" ]]; then
    printf 'codex\n'
  elif command -v codex >/dev/null 2>&1; then
    printf 'codex\n'
  else
    printf 'claude\n'
  fi
}

imprint_emit_context() {
  local event_name="$1"
  local context="${2:-}"
  [[ -z "${context// }" ]] && return 0
  if [[ "${IMPRINT_HOST:-claude}" == "codex" ]]; then
    IMPRINT_HOOK_EVENT="$event_name" python3 -c '
import json, os, sys
context = sys.stdin.read()
event = os.environ.get("IMPRINT_HOOK_EVENT") or "UserPromptSubmit"
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": event,
        "additionalContext": context,
    }
}, ensure_ascii=False))
' <<< "$context"
  else
    printf '%s\n' "$context"
  fi
}

imprint_emit_stop_ok() {
  if [[ "${IMPRINT_HOST:-claude}" == "codex" ]]; then
    printf '{"continue":true}\n'
  fi
}
