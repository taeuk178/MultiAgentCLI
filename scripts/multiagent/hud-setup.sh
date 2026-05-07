#!/bin/bash
# Configure ~/.claude/settings.json statusLine to use multiagent HUD,
# or restore a saved previous configuration.
#
# Usage:
#   hud-setup.sh install [--layout minimal|focused|full]
#   hud-setup.sh status
#   hud-setup.sh layout <minimal|focused|full>
#   hud-setup.sh uninstall

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"
BACKUP_DIR="$MULTIAGENT_HOME/backups"
PREV_FILE="$MULTIAGENT_HOME/previous-statusline.json"
CONFIG_FILE="$MULTIAGENT_HOME/hud-config.json"

if [[ ! -f "$SCRIPT_DIR/hud.sh" ]]; then
  echo "hud.sh missing under $SCRIPT_DIR" >&2
  exit 1
fi

# <plugin-root>/scripts/multiagent → <plugin-root>
PLUGIN_ROOT_GUESS="$(cd "$SCRIPT_DIR/../.." && pwd)"
HUD_CMD="bash \"$PLUGIN_ROOT_GUESS/scripts/multiagent/hud.sh\""

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
if current and 'multiagent' not in json.dumps(current):
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
print('statusLine updated to multiagent HUD')
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
    is_ours = 'multiagent' in (cmd or '')
    print(f'statusLine command: {cmd}')
    print(f'multiagent HUD active: {is_ours}')
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

main() {
  local sub="${1:-status}"; shift || true
  case "$sub" in
    install)   cmd_install "$@" ;;
    status)    cmd_status ;;
    uninstall) cmd_uninstall ;;
    layout)    cmd_layout "$@" ;;
    *) echo "usage: hud-setup.sh install|status|uninstall|layout <name>" >&2; exit 1 ;;
  esac
}

main "$@"
