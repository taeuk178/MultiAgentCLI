#!/bin/bash
# Configure ~/.claude/settings.json statusLine to use imprint HUD,
# or restore a saved previous configuration.
#
# Usage:
#   hud-setup.sh install [--layout minimal|focused|full]
#   hud-setup.sh status
#   hud-setup.sh layout <minimal|focused|full>          (backward-compat)
#   hud-setup.sh fields list   [--project]
#   hud-setup.sh fields set    <id...> [--project]
#   hud-setup.sh fields enable <id...> [--project]
#   hud-setup.sh fields disable <id...> [--project]
#   hud-setup.sh uninstall

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"
BACKUP_DIR="$IMPRINT_HOME/backups"
PREV_FILE="$IMPRINT_HOME/previous-statusline.json"
CONFIG_FILE="$IMPRINT_HOME/hud-config.json"

if [[ ! -f "$SCRIPT_DIR/hud.sh" ]]; then
  echo "hud.sh missing under $SCRIPT_DIR" >&2
  exit 1
fi

# <plugin-root>/scripts/imprint → <plugin-root>
PLUGIN_ROOT_GUESS="$(cd "$SCRIPT_DIR/../.." && pwd)"
HUD_CMD="bash \"$PLUGIN_ROOT_GUESS/scripts/imprint/hud.sh\""

require_python3() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 required" >&2
    exit 1
  fi
}

backup_settings() {
  ensure_home
  mkdir -p "$BACKUP_DIR"
  if [[ -f "$SETTINGS_FILE" ]]; then
    cp "$SETTINGS_FILE" "$BACKUP_DIR/settings-$(date +%Y%m%d-%H%M%S).json"
  fi
}

write_layout() {
  local layout="$1"
  ensure_home
  CONFIG_FILE="$CONFIG_FILE" LAYOUT="$layout" python3 - <<'PY'
import json, os
path = os.environ['CONFIG_FILE']
layout = os.environ['LAYOUT']
data = {}
if os.path.exists(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        data = {}
data['layout'] = layout
with open(path, 'w') as f:
    json.dump(data, f, indent=2)
PY
  echo "layout set to $layout"
}

cmd_install() {
  local layout="full"
  if [[ "${1:-}" == "--layout" && -n "${2:-}" ]]; then
    layout="$2"
  fi

  require_python3
  ensure_home
  backup_settings

  SETTINGS_FILE="$SETTINGS_FILE" PREV_FILE="$PREV_FILE" HUD_CMD="$HUD_CMD" python3 - <<'PY'
import json, os
settings_path = os.environ['SETTINGS_FILE']
prev_path = os.environ['PREV_FILE']
hud_cmd = os.environ['HUD_CMD']

data = {}
if os.path.exists(settings_path):
    with open(settings_path, 'r') as f:
        try:
            data = json.load(f)
        except Exception:
            data = {}

current = data.get('statusLine')
if current and 'imprint' not in json.dumps(current):
    with open(prev_path, 'w') as f:
        json.dump(current, f, indent=2)

data['statusLine'] = {
    'type': 'command',
    'command': hud_cmd,
    'padding': 0,
}

os.makedirs(os.path.dirname(settings_path), exist_ok=True)
with open(settings_path, 'w') as f:
    json.dump(data, f, indent=2)
print('statusLine updated to imprint HUD')
PY

  write_layout "$layout"
  echo "Restart Claude Code or run /reload-plugins to apply."
}

cmd_status() {
  if [[ ! -f "$SETTINGS_FILE" ]]; then
    echo "settings.json not found"
    return
  fi
  SETTINGS_FILE="$SETTINGS_FILE" python3 - <<'PY'
import json, os
with open(os.environ['SETTINGS_FILE']) as f:
    data = json.load(f)
sl = data.get('statusLine')
if not sl:
    print('statusLine: not configured')
else:
    cmd = sl.get('command') if isinstance(sl, dict) else sl
    is_ours = 'imprint' in (cmd or '')
    print(f'statusLine command: {cmd}')
    print(f'imprint HUD active: {is_ours}')
PY
  if [[ -f "$CONFIG_FILE" ]]; then
    printf 'layout config: '
    cat "$CONFIG_FILE"
    echo
  fi
  if [[ -f "$PREV_FILE" ]]; then
    echo "previous statusLine saved at: $PREV_FILE"
  fi
}

cmd_uninstall() {
  if [[ ! -f "$SETTINGS_FILE" ]]; then
    echo "settings.json not found"
    return
  fi
  require_python3
  backup_settings
  SETTINGS_FILE="$SETTINGS_FILE" PREV_FILE="$PREV_FILE" python3 - <<'PY'
import json, os
settings_path = os.environ['SETTINGS_FILE']
prev_path = os.environ['PREV_FILE']
with open(settings_path, 'r') as f:
    data = json.load(f)

if os.path.exists(prev_path):
    with open(prev_path, 'r') as pf:
        try:
            data['statusLine'] = json.load(pf)
            print('previous statusLine restored')
        except Exception:
            data.pop('statusLine', None)
            print('previous statusLine corrupt; removed')
else:
    data.pop('statusLine', None)
    print('statusLine removed')

with open(settings_path, 'w') as f:
    json.dump(data, f, indent=2)
PY
}

cmd_layout() {
  local layout="${1:-}"
  case "$layout" in
    minimal|focused|full) write_layout "$layout" ;;
    *) echo "layout must be one of: minimal | focused | full" >&2; exit 1 ;;
  esac
}

# fields 관련 헬퍼 ----------------------------------------------------------

ALLOWED_FIELDS="5h wk ctx tokens model effort style cost dur skills agents time"

# --project 플래그를 골라내고 나머지를 globals에 채운다.
parse_fields_args() {
  FIELDS_SCOPE="user"
  FIELDS_ARGS=()
  for a in "$@"; do
    if [[ "$a" == "--project" ]]; then
      FIELDS_SCOPE="project"
    else
      FIELDS_ARGS+=("$a")
    fi
  done
}

resolve_config_path() {
  if [[ "$FIELDS_SCOPE" == "project" ]]; then
    local root
    root=$(git rev-parse --show-toplevel 2>/dev/null) || {
      echo "--project requires a git repo (or run inside one)" >&2; exit 1; }
    mkdir -p "$root/.imprint"
    FIELDS_CONFIG="$root/.imprint/hud-config.json"
  else
    ensure_home
    FIELDS_CONFIG="$IMPRINT_HOME/hud-config.json"
  fi
}

# 알 수 없는 id를 검사해서 stderr에 한 번에 보고하고 비-zero 종료.
validate_field_ids() {
  local bad=()
  for id in "$@"; do
    case " $ALLOWED_FIELDS " in
      *" $id "*) ;;
      *) bad+=("$id") ;;
    esac
  done
  if (( ${#bad[@]} )); then
    echo "unknown field id(s): ${bad[*]}" >&2
    echo "allowed: $ALLOWED_FIELDS" >&2
    exit 1
  fi
}

write_fields() {
  local ids_csv="$1"
  CONFIG="$FIELDS_CONFIG" IDS="$ids_csv" python3 - <<'PY'
import json, os
path = os.environ['CONFIG']
ids = [x for x in os.environ['IDS'].split(',') if x]
data = {}
if os.path.exists(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        data = {}
data['fields'] = ids
# 명시적 fields가 있을 때 layout 키는 제거 (혼란 방지)
data.pop('layout', None)
with open(path, 'w') as f:
    json.dump(data, f, indent=2)
PY
  echo "fields ($FIELDS_SCOPE) = $(echo "$ids_csv" | tr ',' ' ')"
  echo "  $FIELDS_CONFIG"
}

read_fields() {
  CONFIG="$FIELDS_CONFIG" python3 - <<'PY'
import json, os
path = os.environ['CONFIG']
if not os.path.exists(path):
    print("")
    raise SystemExit(0)
try:
    with open(path) as f:
        data = json.load(f)
except Exception:
    print("")
    raise SystemExit(0)
fields = data.get('fields')
if isinstance(fields, list):
    print(' '.join(x for x in fields if isinstance(x, str)))
    raise SystemExit(0)
LAYOUT_MAP = {
    "minimal": ["5h","time"],
    "focused": ["5h","wk","ctx","time"],
    "full":    ["5h","wk","ctx","skills","agents","time"],
}
layout = data.get('layout')
if isinstance(layout, str) and layout in LAYOUT_MAP:
    print(' '.join(LAYOUT_MAP[layout]))
    raise SystemExit(0)
print("")
PY
}

cmd_fields_list() {
  parse_fields_args "$@"
  resolve_config_path
  local current; current=$(read_fields)
  echo "scope:        $FIELDS_SCOPE"
  echo "config:       $FIELDS_CONFIG"
  if [[ -z "$current" ]]; then
    echo "active:       (none — falls back to default 5h ctx time)"
  else
    echo "active:       $current"
  fi
  echo
  echo "available IDs:"
  printf '  %s\n' \
    "5h       5-hour rate limit %(used) + remaining time" \
    "wk       7-day rate limit %(used) + remaining" \
    "ctx      context window used %" \
    "tokens   input+output tokens / context size" \
    "model    model display name (Opus / Sonnet)" \
    "effort   reasoning effort + thinking flag" \
    "style    output style name" \
    "cost     session cost in USD" \
    "dur      session wall-clock duration" \
    "skills   loaded skills count (filesystem)" \
    "agents   loaded agents count (filesystem)" \
    "time     current time HH:MM"
}

cmd_fields_set() {
  parse_fields_args "$@"
  if (( ${#FIELDS_ARGS[@]} == 0 )); then
    echo "fields set requires at least one id (or use 'fields list' to inspect)" >&2; exit 1
  fi
  validate_field_ids "${FIELDS_ARGS[@]}"
  resolve_config_path
  local csv; csv=$(IFS=,; echo "${FIELDS_ARGS[*]}")
  write_fields "$csv"
}

cmd_fields_enable() {
  parse_fields_args "$@"
  if (( ${#FIELDS_ARGS[@]} == 0 )); then
    echo "fields enable requires at least one id" >&2; exit 1
  fi
  validate_field_ids "${FIELDS_ARGS[@]}"
  resolve_config_path
  local current; current=$(read_fields)
  local merged=()
  for x in $current "${FIELDS_ARGS[@]}"; do
    local seen=0
    for y in "${merged[@]:-}"; do
      [[ "$y" == "$x" ]] && { seen=1; break; }
    done
    (( seen )) || merged+=("$x")
  done
  local csv; csv=$(IFS=,; echo "${merged[*]}")
  write_fields "$csv"
}

cmd_fields_disable() {
  parse_fields_args "$@"
  if (( ${#FIELDS_ARGS[@]} == 0 )); then
    echo "fields disable requires at least one id" >&2; exit 1
  fi
  resolve_config_path
  local current; current=$(read_fields)
  if [[ -z "$current" ]]; then
    echo "no active fields to remove" >&2; return
  fi
  local kept=()
  for x in $current; do
    local drop=0
    for y in "${FIELDS_ARGS[@]}"; do
      [[ "$y" == "$x" ]] && { drop=1; break; }
    done
    (( drop )) || kept+=("$x")
  done
  local csv; csv=$(IFS=,; echo "${kept[*]:-}")
  write_fields "$csv"
}

cmd_fields() {
  local action="${1:-list}"; shift || true
  case "$action" in
    list)    cmd_fields_list "$@" ;;
    set)     cmd_fields_set "$@" ;;
    enable)  cmd_fields_enable "$@" ;;
    disable) cmd_fields_disable "$@" ;;
    *) echo "fields action must be one of: list | set | enable | disable" >&2; exit 1 ;;
  esac
}

main() {
  local sub="${1:-status}"; shift || true
  case "$sub" in
    install)   cmd_install "$@" ;;
    status)    cmd_status ;;
    uninstall) cmd_uninstall ;;
    layout)    cmd_layout "$@" ;;
    fields)    cmd_fields "$@" ;;
    *) echo "usage: hud-setup.sh install|status|uninstall|layout <name>|fields <list|set|enable|disable> [ids...] [--project]" >&2; exit 1 ;;
  esac
}

main "$@"
