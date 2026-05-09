#!/bin/bash
# Statusline HUD for the imprint plugin.
# Reads Claude Code's session JSON from stdin and prints a one-line status.
#
# Layout presets (read from ~/.claude/imprint/hud-config.json):
#   minimal  : 5h
#   focused  : 5h, wk, ctx
#   full     : 5h, wk, ctx, skills, agents (default)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

INPUT=$(cat || true)

LAYOUT="full"
CONFIG_FILE="$IMPRINT_HOME/hud-config.json"
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

# Parse session JSON: rate limits + reset timestamps + ctx percent.
# Use '|' as the field separator since remaining strings contain spaces.
PARSED=$(printf '%s' "$INPUT" | python3 -c '
import json, sys, time

def pct(x):
    if x is None:
        return "-"
    try:
        return str(int(round(float(x))))
    except Exception:
        return "-"

def remaining_short(resets_at, mode):
    """mode=hm -> "2h 22m"; mode=dh -> "5d 2h"."""
    if resets_at is None:
        return "-"
    try:
        secs = int(float(resets_at)) - int(time.time())
    except Exception:
        return "-"
    if secs <= 0:
        return "0m" if mode == "hm" else "0h"
    if mode == "hm":
        h, rem = divmod(secs, 3600)
        m = rem // 60
        return f"{h}h {m}m" if h else f"{m}m"
    # mode == "dh": fall back to "Xh Ym" once days hits 0.
    d, rem = divmod(secs, 86400)
    if d:
        h = rem // 3600
        return f"{d}d {h}h"
    h, rem2 = divmod(rem, 3600)
    m = rem2 // 60
    return f"{h}h {m}m" if h else f"{m}m"

try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
rl = d.get("rate_limits", {}) or {}
ctx = d.get("context_window", {}) or {}
five = rl.get("five_hour") or {}
week = rl.get("seven_day") or {}
print("|".join([
    pct(five.get("used_percentage")),
    remaining_short(five.get("resets_at"), "hm"),
    pct(week.get("used_percentage")),
    remaining_short(week.get("resets_at"), "dh"),
    pct(ctx.get("used_percentage")),
]))
')
IFS='|' read -r FIVE_PCT FIVE_REM WK_PCT WK_REM CTX_PCT <<<"$PARSED"

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"
PROJECT_DIR="$(pwd)"

# Count only skills/agents from currently loaded sources:
#   1) plugins listed in enabledPlugins (settings.json)
#   2) ~/.claude/skills, ~/.claude/agents (user scope)
#   3) <project>/.claude/skills, <project>/.claude/agents (project scope)
read -r SKILL_COUNT AGENT_COUNT <<<"$(SETTINGS_FILE="$SETTINGS_FILE" CLAUDE_DIR="$CLAUDE_DIR" PROJECT_DIR="$PROJECT_DIR" python3 -c '
import json, os, glob

settings_file = os.environ["SETTINGS_FILE"]
claude_dir = os.environ["CLAUDE_DIR"]
project_dir = os.environ["PROJECT_DIR"]

enabled = {}
try:
    with open(settings_file, "r") as f:
        enabled = json.load(f).get("enabledPlugins", {}) or {}
except Exception:
    enabled = {}

skill_paths = set()
agent_paths = set()

for key, on in enabled.items():
    if not on or "@" not in key:
        continue
    plugin, repo = key.split("@", 1)
    base = os.path.join(claude_dir, "plugins", "cache", repo, plugin)
    if not os.path.isdir(base):
        continue
    for ver in os.listdir(base):
        plugin_dir = os.path.join(base, ver)
        if not os.path.isdir(plugin_dir):
            continue
        for p in glob.glob(os.path.join(plugin_dir, "skills", "*", "SKILL.md")):
            skill_paths.add(os.path.realpath(p))
        for p in glob.glob(os.path.join(plugin_dir, "agents", "*.md")):
            agent_paths.add(os.path.realpath(p))

for scope in (claude_dir, os.path.join(project_dir, ".claude")):
    for p in glob.glob(os.path.join(scope, "skills", "**", "SKILL.md"), recursive=True):
        skill_paths.add(os.path.realpath(p))
    for p in glob.glob(os.path.join(scope, "agents", "**", "*.md"), recursive=True):
        agent_paths.add(os.path.realpath(p))

print(len(skill_paths), len(agent_paths))
')"

UPDATED_AT=$(date +"%H:%M")

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

# "25% (2h 22m)" if remaining is known, else just "25%".
format_pct_rem() {
  local pct="$1" rem="$2"
  if [[ "$pct" == "-" ]]; then
    printf '%s' "$pct"
  elif [[ "$rem" == "-" ]]; then
    printf '%s%%' "$pct"
  else
    printf "%s%% ${DIM}(%s)${RESET}" "$pct" "$rem"
  fi
}

build_minimal() {
  printf "${LABEL}5h${RESET}: %s ${SEP} ${DIM}%s${RESET}" \
    "$(format_pct_rem "$FIVE_PCT" "$FIVE_REM")" "$UPDATED_AT"
}

build_focused() {
  printf "${LABEL}5h${RESET}: %s ${SEP} ${LABEL}wk${RESET}: %s ${SEP} ${LABEL}ctx${RESET}: %s ${SEP} ${DIM}%s${RESET}" \
    "$(format_pct_rem "$FIVE_PCT" "$FIVE_REM")" \
    "$(format_pct_rem "$WK_PCT" "$WK_REM")" \
    "$(format_pct "$CTX_PCT")" \
    "$UPDATED_AT"
}

build_full() {
  printf "${BOLD}imprint${RESET} ${SEP} ${LABEL}5h${RESET}: %s ${SEP} ${LABEL}wk${RESET}: %s ${SEP} ${LABEL}ctx${RESET}: %s ${SEP} ${LABEL}skills${RESET}: %s ${SEP} ${LABEL}agents${RESET}: %s ${SEP} ${DIM}%s${RESET}" \
    "$(format_pct_rem "$FIVE_PCT" "$FIVE_REM")" \
    "$(format_pct_rem "$WK_PCT" "$WK_REM")" \
    "$(format_pct "$CTX_PCT")" \
    "$SKILL_COUNT" "$AGENT_COUNT" "$UPDATED_AT"
}

case "$LAYOUT" in
  minimal) build_minimal ;;
  focused) build_focused ;;
  full|*)  build_full ;;
esac

echo
exit 0
