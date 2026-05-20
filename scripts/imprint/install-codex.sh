#!/bin/bash
# Install Imprint for Codex App with local marketplace, skill link, hooks, and CLI wrapper.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMPRINT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
CODEX_CONFIG="${CODEX_CONFIG:-$CODEX_HOME/config.toml}"
MARKETPLACE_ROOT="${IMPRINT_CODEX_MARKETPLACE_ROOT:-$HOME/.agents}"
LOCAL_BIN="${LOCAL_BIN:-$HOME/.local/bin}"

link_force() {
  local target="$1"
  local link_path="$2"

  if [[ -L "$link_path" || -f "$link_path" ]]; then
    rm -f "$link_path"
  elif [[ -e "$link_path" ]]; then
    echo "Refusing to replace non-link path: $link_path" >&2
    exit 1
  fi

  ln -s "$target" "$link_path"
}

mkdir -p "$MARKETPLACE_ROOT/plugins" "$CODEX_HOME/skills" "$LOCAL_BIN"

link_force "$IMPRINT_ROOT" "$MARKETPLACE_ROOT/plugins/imprint"
link_force "$IMPRINT_ROOT/skills/memory" "$CODEX_HOME/skills/memory"

MARKETPLACE_FILE="$MARKETPLACE_ROOT/plugins/marketplace.json" python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["MARKETPLACE_FILE"])
path.parent.mkdir(parents=True, exist_ok=True)

if path.exists():
    data = json.loads(path.read_text())
else:
    data = {"name": "imprint", "interface": {"displayName": "Imprint"}, "plugins": []}

data.setdefault("name", "imprint")
data.setdefault("interface", {}).setdefault("displayName", "Imprint")
plugins = [plugin for plugin in data.get("plugins", []) if plugin.get("name") != "imprint"]
plugins.append(
    {
        "name": "imprint",
        "source": {"source": "local", "path": "./plugins/imprint"},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Productivity",
    }
)
data["plugins"] = plugins

path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
PY

CODEX_CONFIG="$CODEX_CONFIG" MARKETPLACE_ROOT="$MARKETPLACE_ROOT" python3 - <<'PY'
import os
import re
from pathlib import Path

path = Path(os.environ["CODEX_CONFIG"])
marketplace_root = os.environ["MARKETPLACE_ROOT"]
path.parent.mkdir(parents=True, exist_ok=True)
text = path.read_text() if path.exists() else ""

def ensure_features_plugin_hooks(value: str) -> str:
    pattern = re.compile(r"(?ms)^(\[features\]\n)(.*?)(?=^\[|\Z)")
    match = pattern.search(value)
    if not match:
        return value.rstrip() + "\n\n[features]\nplugin_hooks = true\n"

    body = match.group(2)
    if re.search(r"(?m)^plugin_hooks\s*=", body):
        body = re.sub(r"(?m)^plugin_hooks\s*=.*$", "plugin_hooks = true", body)
    else:
        body = "plugin_hooks = true\n" + body
    return value[: match.start()] + match.group(1) + body + value[match.end() :]

def replace_table(value: str, table: str, body: str) -> str:
    escaped = re.escape(table)
    pattern = re.compile(rf"(?ms)^\[{escaped}\]\n.*?(?=^\[|\Z)")
    block = f"[{table}]\n{body.rstrip()}\n"
    if pattern.search(value):
        return pattern.sub(block, value)
    return value.rstrip() + "\n\n" + block

text = ensure_features_plugin_hooks(text)
text = replace_table(text, 'plugins."imprint@imprint"', "enabled = true")
text = replace_table(
    text,
    "marketplaces.imprint",
    f'source_type = "local"\nsource = "{marketplace_root}"',
)

path.write_text(text.rstrip() + "\n")
PY

cat > "$LOCAL_BIN/imprint" <<SH
#!/bin/bash
set -euo pipefail

IMPRINT_PLUGIN_ROOT="\${IMPRINT_PLUGIN_ROOT:-$IMPRINT_ROOT}"

case "\${1:-}" in
  memory)
    shift
    exec "\$IMPRINT_PLUGIN_ROOT/scripts/imprint/memory.sh" "\$@"
    ;;
  retrieve)
    shift
    exec "\$IMPRINT_PLUGIN_ROOT/scripts/imprint/retrieve.sh" "\$@"
    ;;
  *)
    echo "usage: imprint <memory|retrieve> [args]" >&2
    exit 2
    ;;
esac
SH
chmod +x "$LOCAL_BIN/imprint"

echo "Imprint Codex install complete."
echo "Restart Codex App or open a new thread, then search for 'Imprint: Memory'."
