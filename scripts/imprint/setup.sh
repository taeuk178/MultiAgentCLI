#!/bin/bash
# Imprint setup dispatcher.
# Usage:
#   setup.sh vector --status
#   setup.sh vector --install --warmup --backfill [--project-id <id>]

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
  --backfill    Embed current search entries.
  --project-id <id>
                Backfill a specific project id. Default: current git root id.
Examples:
  setup.sh vector --status
  setup.sh vector --install --warmup --backfill
USAGE
}

require_python() {
  if ! command -v python3 >/dev/null 2>&1; then
    setup_error "PATH에서 python3를 찾을 수 없습니다"
    return 1
  fi
}

setup_log() {
  local msg="$*"
  echo "[imprint setup] $msg"
  log_info "setup: $msg"
}

setup_error() {
  local msg="$*"
  echo "[imprint setup] ERROR: $msg" >&2
  log_error "setup: $msg"
}

setup_hint() {
  local label="$1"
  case "$label" in
    install)
      echo "[imprint setup] 힌트: network, pip, Python 환경 정책 때문에 install이 막혔을 수 있습니다." >&2
      echo "[imprint setup] 힌트: 인터넷 연결을 확인한 뒤 다시 실행하고, 필요하면 $IMPRINT_LOG 를 확인하세요." >&2
      ;;
    warmup)
      echo "[imprint setup] 힌트: model 다운로드 또는 cache 접근이 막혔을 수 있습니다. HF_TOKEN을 설정하면 HuggingFace rate limit이 완화됩니다." >&2
      echo "[imprint setup] 힌트: Python traceback은 $IMPRINT_LOG 에서 확인하세요." >&2
      ;;
    backfill)
      echo "[imprint setup] 힌트: project id를 확인하고 'imprint setup vector --status' 를 먼저 실행해 보세요." >&2
      echo "[imprint setup] 힌트: embedding backfill 상세 내용은 $IMPRINT_LOG 에서 확인하세요. legacy DB 전환은 'imprint migrate search-entries' 를 별도로 실행하세요." >&2
      ;;
    status)
      echo "[imprint setup] 힌트: status는 import 가능 여부만 확인합니다. python3 사용 가능 여부와 $IMPRINT_LOG 를 확인하세요." >&2
      ;;
  esac
}

run_step() {
  local label="$1"
  shift
  local start
  start=$(date +%s)
  setup_log "$label 시작"
  if "$@"; then
    local end
    end=$(date +%s)
    setup_log "$label 완료 ($((end - start))s)"
    return 0
  fi
  local rc=$?
  setup_error "$label 실패 (exit=$rc)"
  setup_hint "$label"
  return "$rc"
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
print(f"embedding_disabled: {os.environ.get('IMPRINT_DISABLE_EMBEDDING', '0')}")
print(f"python: {sys.executable}")
PY
}

vector_install() {
  require_python
  local req="$IMPRINT_PLUGIN_ROOT/requirements-optional.txt"
  if python3 -m pip help install 2>/dev/null | grep -q -- '--break-system-packages'; then
    python3 -m pip install --user --break-system-packages -r "$req"
  else
    python3 -m pip install --user -r "$req"
  fi
}

vector_warmup() {
  require_python
  PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY'
from retrieval import embedding

blob = embedding.embed_text("imprint vector setup warmup")
if blob is None:
    print("embedding_warmup: 실패")
    raise SystemExit(1)
print(f"embedding_warmup: 완료 bytes={len(blob)}")
PY
}

vector_backfill() {
  local pid="$1"
  require_python
  (
    cd "$SCRIPT_DIR/lib"
    python3 -m retrieval.cli embed-entries "$pid" --all
  )
}

cmd_vector() {
  local do_status=0
  local do_install=0
  local do_warmup=0
  local do_backfill=0
  local pid=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --status) do_status=1; shift ;;
      --install) do_install=1; shift ;;
      --warmup) do_warmup=1; shift ;;
      --backfill) do_backfill=1; shift ;;
      --project-id) pid="${2:-}"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) setup_error "알 수 없는 vector 옵션: $1"; usage >&2; exit 2 ;;
    esac
  done

  setup_log "vector setup 로그: $IMPRINT_LOG"
  setup_log "vector 실행 계획: status=$do_status install=$do_install warmup=$do_warmup backfill=$do_backfill project_id=${pid:-auto}"

  if (( do_install )); then
    run_step install vector_install
  fi

  if (( do_warmup )); then
    run_step warmup vector_warmup
  fi

  if (( do_backfill )); then
    [[ -n "$pid" ]] || pid=$(project_id)
    setup_log "project_id 확인: $pid"
    run_step backfill vector_backfill "$pid"
  fi

  if (( do_status || (do_install == 0 && do_warmup == 0 && do_backfill == 0 && do_print_env == 0) )); then
    run_step status vector_status
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
      setup_error "알 수 없는 setup target: $1"
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
