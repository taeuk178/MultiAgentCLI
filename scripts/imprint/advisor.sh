#!/bin/bash
# Advisor CLI dispatcher.
# Usage:
#   advisor.sh codex <prompt>
#   advisor.sh gemini <prompt>
#   advisor.sh ccg <prompt>

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

# 무한 대기 차단(D? — Phase 4 마무리). codex/gemini/claude -p가 인증 누락이나
# 네트워크 hang으로 영원히 멈추는 경우를 막는다. macOS는 `timeout`이 기본
# 미설치라 `gtimeout`(brew coreutils)로 폴백하고, 둘 다 없으면 wrapping을
# 건너뛰고 plugin.log에 한 줄 남긴다.
ADVISOR_TIMEOUT="${IMPRINT_ADVISOR_TIMEOUT:-60}"

if command -v timeout >/dev/null 2>&1; then
  TIMEOUT_BIN=timeout
elif command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_BIN=gtimeout
else
  TIMEOUT_BIN=""
  log_info "advisor: timeout/gtimeout not found, advisor calls run unbounded"
fi

# $1...$N → 명령어. timeout binary가 있으면 그 앞에 붙이고, 없으면 그냥 실행.
with_timeout() {
  if [[ -n "$TIMEOUT_BIN" ]]; then
    "$TIMEOUT_BIN" "${ADVISOR_TIMEOUT}s" "$@"
  else
    "$@"
  fi
}

usage() {
  cat <<'USAGE'
imprint advisor <subcommand> <prompt>

  codex <prompt>    Run codex exec with the prompt; persist provider_run.
  gemini <prompt>   Run gemini -p with the prompt; persist provider_run.
  ccg <prompt>      Run codex + gemini in parallel, then synthesize via claude -p.
USAGE
}

ensure_db() {
  if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "sqlite3 not found in PATH" >&2
    exit 1
  fi
  if [[ ! -f "$IMPRINT_DB" ]]; then
    bash "$SCRIPT_DIR/session-start.sh" </dev/null
  fi
}

persist_run() {
  local provider="$1"
  local phase="$2"
  local prompt="$3"
  local output="$4"
  local status="$5"
  local pid; pid=$(project_id)
  local now; now=$(now_iso)
  local prompt_id; prompt_id=$(new_id)
  local out_id; out_id=$(new_id)
  local run_id; run_id=$(new_id)
  local esc_p; esc_p=$(sql_escape "$prompt")
  local esc_o; esc_o=$(sql_escape "$output")
  local esc_provider; esc_provider=$(sql_escape "$provider")
  local esc_phase; esc_phase=$(sql_escape "$phase")
  local esc_status; esc_status=$(sql_escape "$status")
  db_exec "
    INSERT INTO events (id, project_id, source, kind, text_clean, created_at)
      VALUES ('$prompt_id', '$pid', 'advisor', 'advisor_prompt', '$esc_p', '$now');
    INSERT INTO events (id, project_id, source, kind, text_clean, created_at)
      VALUES ('$out_id', '$pid', '$esc_provider', 'advisor_response', '$esc_o', '$now');
    INSERT INTO provider_runs
      (id, project_id, provider, phase, prompt_event_id, output_event_id, status, started_at, finished_at)
      VALUES ('$run_id', '$pid', '$esc_provider', '$esc_phase',
              '$prompt_id', '$out_id', '$esc_status', '$now', '$now');
  " || true
  echo "$run_id"
}

run_codex() {
  local prompt="$1"
  if ! command -v codex >/dev/null 2>&1; then
    echo "codex CLI not found" >&2
    return 1
  fi
  with_timeout codex exec "$prompt"
}

run_gemini() {
  local prompt="$1"
  if ! command -v gemini >/dev/null 2>&1; then
    echo "gemini CLI not found" >&2
    return 1
  fi
  export GEMINI_CLI_TRUST_WORKSPACE=true
  with_timeout gemini -p "$prompt"
}

cmd_codex() {
  local prompt="$*"
  [[ -z "${prompt// }" ]] && { echo "codex requires <prompt>" >&2; exit 1; }
  local out
  if out=$(run_codex "$prompt"); then
    persist_run "codex" "single" "$prompt" "$out" "succeeded" >/dev/null
    printf '%s\n' "$out"
  else
    persist_run "codex" "single" "$prompt" "$out" "failed" >/dev/null
    return 1
  fi
}

cmd_gemini() {
  local prompt="$*"
  [[ -z "${prompt// }" ]] && { echo "gemini requires <prompt>" >&2; exit 1; }
  local out
  if out=$(run_gemini "$prompt"); then
    persist_run "gemini" "single" "$prompt" "$out" "succeeded" >/dev/null
    printf '%s\n' "$out"
  else
    persist_run "gemini" "single" "$prompt" "$out" "failed" >/dev/null
    return 1
  fi
}

cmd_ccg() {
  local prompt="$*"
  [[ -z "${prompt// }" ]] && { echo "ccg requires <prompt>" >&2; exit 1; }

  local tmp_codex tmp_gemini
  tmp_codex=$(mktemp)
  tmp_gemini=$(mktemp)
  trap 'rm -f "$tmp_codex" "$tmp_gemini"' EXIT

  local codex_prompt="Architecture, correctness, backend, risks. Question: $prompt"
  local gemini_prompt="UX, alternatives, edge-case usability, docs. Question: $prompt"

  ( run_codex "$codex_prompt" >"$tmp_codex" 2>/dev/null
    persist_run "codex" "advisor_draft" "$codex_prompt" "$(cat "$tmp_codex")" \
      "$([[ -s "$tmp_codex" ]] && echo succeeded || echo failed)" >/dev/null
  ) &
  local pid_c=$!

  ( run_gemini "$gemini_prompt" >"$tmp_gemini" 2>/dev/null
    persist_run "gemini" "advisor_review" "$gemini_prompt" "$(cat "$tmp_gemini")" \
      "$([[ -s "$tmp_gemini" ]] && echo succeeded || echo failed)" >/dev/null
  ) &
  local pid_g=$!

  wait "$pid_c" || true
  wait "$pid_g" || true

  local codex_out gemini_out
  codex_out=$(cat "$tmp_codex")
  gemini_out=$(cat "$tmp_gemini")

  if [[ -z "${codex_out// }" && -z "${gemini_out// }" ]]; then
    echo "Both advisors returned empty output." >&2
    return 1
  fi

  local synth_prompt
  synth_prompt=$(cat <<EOF
Synthesize a final answer from two advisor outputs.

Original question:
$prompt

[Codex perspective]
$codex_out

[Gemini perspective]
$gemini_out

Produce one unified answer with: agreed points, conflicts (called out), final direction, action checklist.
EOF
)

  if command -v claude >/dev/null 2>&1; then
    local final
    if final=$(with_timeout claude -p "$synth_prompt"); then
      persist_run "claude" "advisor_synthesize" "$synth_prompt" "$final" "succeeded" >/dev/null
      printf '%s\n' "$final"
    else
      persist_run "claude" "advisor_synthesize" "$synth_prompt" "$final" "failed" >/dev/null
      echo "claude -p synthesis failed/timeout; printing raw advisor outputs." >&2
      printf '[Codex]\n%s\n\n[Gemini]\n%s\n' "$codex_out" "$gemini_out"
    fi
  else
    echo "claude CLI not found; printing raw advisor outputs." >&2
    printf '[Codex]\n%s\n\n[Gemini]\n%s\n' "$codex_out" "$gemini_out"
  fi
}

main() {
  ensure_db
  local sub="${1:-}"; shift || true
  case "$sub" in
    codex)  cmd_codex "$@" ;;
    gemini) cmd_gemini "$@" ;;
    ccg)    cmd_ccg "$@" ;;
    ""|-h|--help|help) usage ;;
    *) usage; exit 1 ;;
  esac
}

main "$@"
