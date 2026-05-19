#!/bin/bash
# Statusline HUD for the imprint plugin.
# Reads Claude Code's session JSON from stdin and prints a one-line status.
#
# 사용자가 어떤 segment를 노출할지 hud-config.json의 fields 배열로 결정한다.
# 우선순위:
#   1. <git-root>/.imprint/hud-config.json (project-scope override)
#   2. ~/.imprint/hud-config.json          (user-scope)
#   3. default fields = ["5h", "ctx", "time"]
#
# Backward-compat: 옛 layout=minimal/focused/full 키만 있고 fields가 없으면
# 그 layout을 동등한 fields 배열로 매핑한다.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

INPUT=$(cat || true)

USER_CONFIG="$IMPRINT_HOME/hud-config.json"
PROJECT_CONFIG=""
if PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null); then
  PROJECT_CONFIG="$PROJECT_ROOT/.imprint/hud-config.json"
fi

# fields 결정: project > user > default. 결과는 공백 구분 문자열.
FIELDS=$(USER_CONFIG="$USER_CONFIG" PROJECT_CONFIG="$PROJECT_CONFIG" python3 -c '
import json, os

ALLOWED = {"model","effort","style","ctx","tokens","cost","dur",
           "5h","wk","skills","agents","time"}
LAYOUT_MAP = {
    "minimal": ["5h","time"],
    "focused": ["5h","wk","ctx","time"],
    "full":    ["5h","wk","ctx","skills","agents","time"],
}
DEFAULT = ["5h","ctx","time"]

def load(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None

def fields_from(cfg):
    if not isinstance(cfg, dict):
        return None
    arr = cfg.get("fields")
    if isinstance(arr, list):
        out = [x for x in arr if isinstance(x, str) and x in ALLOWED]
        return out  # 빈 배열이어도 사용자가 명시적으로 비웠다는 뜻
    layout = cfg.get("layout")
    if isinstance(layout, str) and layout in LAYOUT_MAP:
        return list(LAYOUT_MAP[layout])
    return None

result = (
    fields_from(load(os.environ["PROJECT_CONFIG"]))
    or fields_from(load(os.environ["USER_CONFIG"]))
    or DEFAULT
)
print(" ".join(result))
' 2>/dev/null) || FIELDS="5h ctx time"

# Parse session JSON: 가능한 모든 segment를 미리 채워두고, 최종 출력은 FIELDS만.
# Use '|' as the field separator.
PARSED=$(printf '%s' "$INPUT" | python3 -c '
import json, sys, time

def pct(x):
    if x is None: return "-"
    try: return str(int(round(float(x))))
    except Exception: return "-"

def remaining_short(resets_at, mode):
    if resets_at is None: return "-"
    try:
        secs = int(float(resets_at)) - int(time.time())
    except Exception: return "-"
    if secs <= 0:
        return "0m" if mode == "hm" else "0h"
    if mode == "hm":
        h, rem = divmod(secs, 3600)
        m = rem // 60
        return f"{h}h {m}m" if h else f"{m}m"
    d, rem = divmod(secs, 86400)
    if d:
        h = rem // 3600
        return f"{d}d {h}h"
    h, rem2 = divmod(rem, 3600)
    m = rem2 // 60
    return f"{h}h {m}m" if h else f"{m}m"

def fmt_tokens(n):
    try: n = int(n)
    except Exception: return "-"
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1000:.0f}k"
    return str(n)

def fmt_dur(ms):
    try: secs = int(int(ms) / 1000)
    except Exception: return "-"
    if secs < 60: return f"{secs}s"
    h, rem = divmod(secs, 3600)
    m = rem // 60
    if h: return f"{h}h {m}m"
    return f"{m}m"

def fmt_cost(usd):
    try: usd = float(usd)
    except Exception: return "-"
    return f"${usd:.2f}" if usd >= 0.01 else f"${usd:.4f}"

try: d = json.load(sys.stdin)
except Exception: d = {}

rl   = d.get("rate_limits") or {}
ctx  = d.get("context_window") or {}
five = rl.get("five_hour") or {}
week = rl.get("seven_day") or {}
model = d.get("model") or {}
effort = d.get("effort") or {}
thinking = d.get("thinking") or {}
ostyle = d.get("output_style") or {}
cost = d.get("cost") or {}

# tokens segment: input+output / size
tin  = ctx.get("total_input_tokens")
tout = ctx.get("total_output_tokens")
tsz  = ctx.get("context_window_size")
total = None
if tin is not None or tout is not None:
    try: total = int(tin or 0) + int(tout or 0)
    except Exception: total = None
tokens_str = "-"
if total is not None and tsz:
    tokens_str = f"{fmt_tokens(total)}/{fmt_tokens(tsz)}"

effort_str = "-"
e_lvl = effort.get("level")
thk = thinking.get("enabled") is True
if e_lvl:
    effort_str = e_lvl + ("+thk" if thk else "")
elif thk:
    effort_str = "thk"

print("|".join([
    pct(five.get("used_percentage")),
    remaining_short(five.get("resets_at"), "hm"),
    pct(week.get("used_percentage")),
    remaining_short(week.get("resets_at"), "dh"),
    pct(ctx.get("used_percentage")),
    str(model.get("display_name") or "-"),
    effort_str,
    str(ostyle.get("name") or "-"),
    tokens_str,
    fmt_cost(cost.get("total_cost_usd")) if cost.get("total_cost_usd") is not None else "-",
    fmt_dur(cost.get("total_duration_ms")) if cost.get("total_duration_ms") is not None else "-",
]))
')
IFS='|' read -r FIVE_PCT FIVE_REM WK_PCT WK_REM CTX_PCT MODEL_NAME EFFORT_STR STYLE_NAME TOKENS_STR COST_STR DUR_STR <<<"$PARSED"

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"
PROJECT_DIR="$(pwd)"

# skills/agents 카운트는 statusline JSON에 없어 filesystem 스캔으로 보강.
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

# printf로 진짜 ESC byte를 박아둔다. literal '\033[2m' 문자열을 그대로 변수에
# 두면 'printf "%s" "$VAR"' 패턴(메인 루프의 SEP 출력 등)에서 escape이 해석되지
# 않아 raw 그대로 statusline에 찍힌다.
DIM=$(printf '\033[2m')
BOLD=$(printf '\033[1m')
RESET=$(printf '\033[0m')
LABEL=$(printf '\033[36m')
SEP="${DIM}│${RESET}"

format_pct() {
  local v="$1"
  if [[ "$v" == "-" ]]; then printf '%s' "$v"
  else printf '%s%%' "$v"; fi
}

format_pct_rem() {
  local pct="$1" rem="$2"
  if [[ "$pct" == "-" ]]; then printf '%s' "$pct"
  elif [[ "$rem" == "-" ]]; then printf '%s%%' "$pct"
  else printf "%s%% ${DIM}(%s)${RESET}" "$pct" "$rem"; fi
}

# 각 segment 함수는 출력만 책임진다. SEP는 메인 루프가 처리.
seg_5h()     { printf "${LABEL}5h${RESET}: %s" "$(format_pct_rem "$FIVE_PCT" "$FIVE_REM")"; }
seg_wk()     { printf "${LABEL}wk${RESET}: %s" "$(format_pct_rem "$WK_PCT" "$WK_REM")"; }
seg_ctx()    { printf "${LABEL}ctx${RESET}: %s" "$(format_pct "$CTX_PCT")"; }
seg_model()  { printf "${BOLD}%s${RESET}" "$MODEL_NAME"; }
seg_effort() { printf "${LABEL}effort${RESET}: %s" "$EFFORT_STR"; }
seg_style()  { printf "${LABEL}style${RESET}: %s" "$STYLE_NAME"; }
seg_tokens() { printf "${LABEL}tok${RESET}: %s" "$TOKENS_STR"; }
seg_cost()   { printf "%s" "$COST_STR"; }
seg_dur()    { printf "${LABEL}dur${RESET}: %s" "$DUR_STR"; }
seg_skills() { printf "${LABEL}skills${RESET}: %s" "$SKILL_COUNT"; }
seg_agents() { printf "${LABEL}agents${RESET}: %s" "$AGENT_COUNT"; }
seg_time()   { printf "${DIM}%s${RESET}" "$UPDATED_AT"; }

# 알 수 없는 필드 id는 silent skip하되 plugin.log에 한 줄 남긴다.
emit_segment() {
  case "$1" in
    5h)     seg_5h ;;
    wk)     seg_wk ;;
    ctx)    seg_ctx ;;
    model)  seg_model ;;
    effort) seg_effort ;;
    style)  seg_style ;;
    tokens) seg_tokens ;;
    cost)   seg_cost ;;
    dur)    seg_dur ;;
    skills) seg_skills ;;
    agents) seg_agents ;;
    time)   seg_time ;;
    *)      log_info "hud: unknown field id '$1'" ;;
  esac
}

# 빈 fields면 segments 없이 빈 줄(아무것도 안 찍음)을 emit.
first=1
for f in $FIELDS; do
  if (( first )); then
    first=0
  else
    printf " %s " "$SEP"
  fi
  emit_segment "$f"
done

echo
exit 0
