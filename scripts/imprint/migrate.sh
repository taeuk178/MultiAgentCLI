#!/bin/bash
# Explicit migration dispatcher.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  echo "usage: imprint migrate search-entries" >&2
}

case "${1:-}" in
  search-entries)
    shift
    ensure_home
    (cd "$SCRIPT_DIR/lib" && python3 -m retrieval.cli migrate-search-entries "$@")
    ;;
  -h|--help|"")
    usage
    ;;
  *)
    echo "migrate: unknown target ${1:-}" >&2
    usage
    exit 2
    ;;
esac
