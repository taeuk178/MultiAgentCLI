#!/bin/bash
# Hybrid retrieval dispatcher — Python module 호출용 얇은 wrapper.
# usage:
#   retrieve.sh <query> [top_k]
#   retrieve.sh --json <query> [top_k]
# project_id 는 git toplevel 기반으로 자동 결정.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

ensure_home

JSON_MODE=0
if [[ "${1:-}" == "--json" ]]; then
  JSON_MODE=1
  shift
fi

if [[ $# -lt 1 ]]; then
  echo "usage: $(basename "$0") [--json] <query> [top_k]" >&2
  exit 2
fi

QUERY="$1"
TOP_K="${2:-10}"
PID=$(project_id)

cmd="retrieve"
[[ "$JSON_MODE" == "1" ]] && cmd="retrieve_json"

cd "$SCRIPT_DIR/lib" && python3 -m retrieval.cli "$cmd" "$PID" "$QUERY" "$TOP_K"
