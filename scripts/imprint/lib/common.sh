#!/bin/bash
# Common helpers for Imprint plugin scripts.
# Sourced by all hook and skill scripts.

set -euo pipefail

IMPRINT_HOME="${IMPRINT_HOME:-$HOME/.claude/imprint}"
IMPRINT_DB="$IMPRINT_HOME/app.sqlite"
IMPRINT_LOG="$IMPRINT_HOME/plugin.log"

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
