#!/bin/bash
# Explicit delta/rollup dispatcher.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  cat >&2 <<'USAGE'
usage:
  rollup.sh --session-id <id> [--all] [--json]
  rollup.sh --session-id-if-idle <id> [--min-age-seconds <n>] [--all] [--json]
  rollup.sh --latest [--all] [--json]
  rollup.sh --stale [--exclude-session <id>] [--max-sessions <n>] [--all] [--json]
USAGE
}

ensure_home
if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$IMPRINT_DB" < "$SCRIPT_DIR/lib/schema.sql" >/dev/null 2>>"$IMPRINT_LOG" || true
fi

mode=""
session_id=""
exclude_session=""
max_sessions=""
min_age_seconds=""
extra=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session-id)
      mode="session"
      session_id="${2:-}"
      shift 2
      ;;
    --session-id-if-idle)
      mode="session-if-idle"
      session_id="${2:-}"
      shift 2
      ;;
    --min-age-seconds)
      min_age_seconds="${2:-}"
      shift 2
      ;;
    --latest)
      mode="latest"
      shift
      ;;
    --stale)
      mode="stale"
      shift
      ;;
    --exclude-session)
      exclude_session="${2:-}"
      shift 2
      ;;
    --max-sessions)
      max_sessions="${2:-}"
      shift 2
      ;;
    --all|--json)
      extra+=("$1")
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "rollup: unknown option $1" >&2
      usage
      exit 2
      ;;
  esac
done

PID=$(project_id)
case "$mode" in
  session)
    if [[ -z "${session_id// }" ]]; then
      echo "rollup: --session-id requires a value" >&2
      exit 2
    fi
    (cd "$SCRIPT_DIR/lib" && python3 -m retrieval.cli rollup-session "$PID" "$session_id" "${extra[@]}")
    ;;
  session-if-idle)
    if [[ -z "${session_id// }" ]]; then
      echo "rollup: --session-id-if-idle requires a value" >&2
      exit 2
    fi
    args=(rollup-session-if-idle "$PID" "$session_id")
    if [[ -n "${min_age_seconds// }" ]]; then
      args+=(--min-age-seconds "$min_age_seconds")
    fi
    args+=("${extra[@]}")
    (cd "$SCRIPT_DIR/lib" && python3 -m retrieval.cli "${args[@]}")
    ;;
  latest)
    (cd "$SCRIPT_DIR/lib" && python3 -m retrieval.cli rollup-latest "$PID" "${extra[@]}")
    ;;
  stale)
    args=(rollup-stale "$PID")
    if [[ -n "${exclude_session// }" ]]; then
      args+=(--exclude-session "$exclude_session")
    fi
    if [[ -n "${max_sessions// }" ]]; then
      args+=(--max-sessions "$max_sessions")
    fi
    args+=("${extra[@]}")
    (cd "$SCRIPT_DIR/lib" && python3 -m retrieval.cli "${args[@]}")
    ;;
  *)
    usage
    exit 2
    ;;
esac
