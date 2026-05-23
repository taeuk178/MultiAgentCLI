#!/bin/bash
# User-facing explicit memory capture dispatcher.
# Keeps /remember as the simple public skill name while reusing memory storage.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -lt 1 ]]; then
  echo "usage: $(basename "$0") <text> [--require|--high|--middle|--low] [--type <chunk_type>] [--redact]" >&2
  exit 2
fi

exec "$SCRIPT_DIR/memory.sh" remember "$@"
