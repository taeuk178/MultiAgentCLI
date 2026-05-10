#!/bin/bash
# ingest_queue 에 쌓인 pending 항목을 drain.
# inline 모드: hook 종료 직전 직접 호출. daemon 모드: 별도 프로세스가 polling.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

ensure_home
PID=$(project_id)

cd "$SCRIPT_DIR/lib" && python3 -m retrieval.cli drain "$PID"
