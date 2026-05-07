#!/bin/bash
# Statusline HUD for the multiagent plugin.
# Reads Claude Code's session JSON from stdin and prints a one-line status.
#
# Layout presets (read from ~/.claude/multiagent/hud-config.json):
#   minimal  : 5h
#   focused  : 5h, wk, ctx
#   full     : 5h, wk, ctx, skills, agents (default)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

INPUT=$(cat || true)

LAYOUT="full"
CONFIG_FILE="$MULTIAGENT_HOME/hud-config.json"
if [[ -f "$CONFIG_FILE" ]]; then
  LAYOUT=$(CONFIG_FILE="$CONFIG_FILE" python3 -c '
import json, os
try:
    with open(os.environ["CONFIG_FILE"], "r") as f:
        cfg = json.load(f)
    val = cfg.get("layout", "full")
    print(val if val in ("minimal", "focused", "full") else "full")
except Exception:
    print("full")
' 2>/dev/null) || LAYOUT="full"
fi

read -r FIVE_H WK CTX <<<"$(printf '%s' "$INPUT" | python3 -c '
import json, sys
def pct(x):
    if x is None:
        return "-"
    try:
        return str(int(round(float(x))))
    except Exception:
        return "-"
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
rl = d.get("rate_limits", {}) or {}
ctx = d.get("context_window", {}) or {}
five = (rl.get("five_hour") or {}).get("used_percentage")
week = (rl.get("seven_day") or {}).get("used_percentage")
ctxp = ctx.get("used_percentage")
print(pct(five), pct(week), pct(ctxp))
')"

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SKILL_COUNT=$(find "$CLAUDE_DIR/plugins/cache" -name "SKILL.md" -type f 2>/dev/null | wc -l | tr -d ' ')
AGENT_COUNT=$(find "$CLAUDE_DIR/plugins/cache" -path "*/agents/*.md" -type f 2>/dev/null | wc -l | tr -d ' ')

DIM='\033[2m'
BOLD='\033[1m'
RESET='\033[0m'
LABEL='\033[36m'
SEP="${DIM}│${RESET}"

format_pct() {
  local v="$1"
  if [[ "$v" == "-" ]]; then
    printf '%s' "$v"
  else
    printf '%s%%' "$v"
  fi
}

build_minimal() {
  printf "${LABEL}5h${RESET}:%s" "$(format_pct "$FIVE_H")"
}

build_focused() {
  printf "${LABEL}5h${RESET}:%s ${SEP} ${LABEL}wk${RESET}:%s ${SEP} ${LABEL}ctx${RESET}:%s" \
    "$(format_pct "$FIVE_H")" "$(format_pct "$WK")" "$(format_pct "$CTX")"
}

build_full() {
  printf "${BOLD}multiagent${RESET} ${SEP} ${LABEL}5h${RESET}:%s ${SEP} ${LABEL}wk${RESET}:%s ${SEP} ${LABEL}ctx${RESET}:%s ${SEP} ${LABEL}skills${RESET}:%s ${SEP} ${LABEL}agents${RESET}:%s" \
    "$(format_pct "$FIVE_H")" "$(format_pct "$WK")" "$(format_pct "$CTX")" "$SKILL_COUNT" "$AGENT_COUNT"
}

case "$LAYOUT" in
  minimal) build_minimal ;;
  focused) build_focused ;;
  full|*)  build_full ;;
esac

echo
exit 0
