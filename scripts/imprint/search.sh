#!/bin/bash
# User-facing project search dispatcher.
# Keeps /search as the public skill name while reusing the existing retrieval engine.
# Search is intentionally simple: pass a natural-language query, and imprint
# chooses local / feature / global scope internally.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -lt 1 ]]; then
  echo "usage: $(basename "$0") <query>" >&2
  exit 2
fi

for arg in "$@"; do
  if [[ "$arg" == --* ]]; then
    echo "search does not accept options yet; pass only a query." >&2
    exit 2
  fi
done

QUERY="$*"
exec "$SCRIPT_DIR/retrieve.sh" --routed "$QUERY"
