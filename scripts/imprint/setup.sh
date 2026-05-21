#!/bin/bash
# Imprint setup dispatcher.
# Usage:
#   setup.sh vector --status
#   setup.sh vector --install --warmup --backfill [--project-id <id>]
#   setup.sh vector --print-env

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  cat <<'USAGE'
imprint setup <target> [options]

Targets:
  vector        Set up optional vector retrieval dependencies and backfill.

Vector options:
  --status      Show Python dependency readiness without loading BGE-M3.
  --install     Install requirements-optional.txt with user pip.
  --warmup      Load BGE-M3 once and verify embedding output.
  --backfill    Bridge existing memory for this project with embeddings.
  --project-id <id>
                Backfill a specific project id. Default: current git root id.
  --print-env   Print shell env line for automatic embedding on new memory.

Examples:
  setup.sh vector --status
  setup.sh vector --install --warmup --backfill
  setup.sh vector --print-env
USAGE
}

require_python() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 not found in PATH" >&2
    exit 1
  fi
}

vector_status() {
  require_python
  PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY'
import importlib.util
import os
import sys

deps = ("sqlite_vec", "sentence_transformers", "transformers")
missing = []
for name in deps:
    ok = importlib.util.find_spec(name) is not None
    print(f"{name}: {'ok' if ok else 'missing'}")
    if not ok:
        missing.append(name)

print(f"vector_ready: {'no' if missing else 'yes'}")
print("embedding_model: not_loaded_by_status")
print(f"auto_bridge_embedding: {os.environ.get('IMPRINT_MEMORY_BRIDGE_EMBEDDING', '0')}")
print(f"python: {sys.executable}")
PY
}

vector_install() {
  require_python
  python3 -m pip install --user --break-system-packages -r "$IMPRINT_PLUGIN_ROOT/requirements-optional.txt"
}

vector_warmup() {
  require_python
  PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY'
from retrieval import embedding

blob = embedding.embed_text("imprint vector setup warmup")
if blob is None:
    print("embedding_warmup: failed")
    raise SystemExit(1)
print(f"embedding_warmup: ok bytes={len(blob)}")
PY
}

vector_backfill() {
  local pid="$1"
  require_python
  (
    cd "$SCRIPT_DIR/lib"
    python3 -m retrieval.cli bridge-memory "$pid" --all --embed
  )
}

cmd_vector() {
  local do_status=0
  local do_install=0
  local do_warmup=0
  local do_backfill=0
  local do_print_env=0
  local pid=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --status) do_status=1; shift ;;
      --install) do_install=1; shift ;;
      --warmup) do_warmup=1; shift ;;
      --backfill) do_backfill=1; shift ;;
      --project-id) pid="${2:-}"; shift 2 ;;
      --print-env) do_print_env=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
  done

  if (( do_print_env )); then
    echo "export IMPRINT_MEMORY_BRIDGE_EMBEDDING=1"
  fi

  if (( do_install )); then
    vector_install
  fi

  if (( do_warmup )); then
    vector_warmup
  fi

  if (( do_backfill )); then
    [[ -n "$pid" ]] || pid=$(project_id)
    vector_backfill "$pid"
  fi

  if (( do_status || (do_install == 0 && do_warmup == 0 && do_backfill == 0 && do_print_env == 0) )); then
    vector_status
  fi
}

main() {
  ensure_home
  case "${1:-}" in
    vector)
      shift
      cmd_vector "$@"
      ;;
    -h|--help|"")
      usage
      ;;
    *)
      echo "unknown target: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
