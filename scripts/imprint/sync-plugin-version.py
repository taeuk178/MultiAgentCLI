#!/usr/bin/env python3
"""Synchronize Claude/Codex plugin release metadata.

Usage:
  python3 scripts/imprint/sync-plugin-version.py
  python3 scripts/imprint/sync-plugin-version.py 0.1.1

The version string is shared by:
- VERSION
- .claude-plugin/plugin.json
- .claude-plugin/marketplace.json
- .codex-plugin/plugin.json
- .agents/plugins/marketplace.json source.ref
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPO = "https://github.com/taeuk178/imprint.git"


def load_version(argv: list[str]) -> str:
    if len(argv) > 1:
        version = argv[1].strip()
    else:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
        raise SystemExit(f"invalid semver version: {version!r}")
    return version


def update_json(path: Path, updater) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    updater(data)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    version = load_version(argv)
    ref = version

    (ROOT / "VERSION").write_text(version + "\n", encoding="utf-8")

    update_json(
        ROOT / ".claude-plugin" / "plugin.json",
        lambda data: data.__setitem__("version", version),
    )

    def update_claude_marketplace(data: dict) -> None:
        data["version"] = version
        for plugin in data.get("plugins", []):
            if plugin.get("name") == "imprint":
                plugin["version"] = version

    update_json(ROOT / ".claude-plugin" / "marketplace.json", update_claude_marketplace)

    update_json(
        ROOT / ".codex-plugin" / "plugin.json",
        lambda data: data.__setitem__("version", version),
    )

    def update_codex_marketplace(data: dict) -> None:
        for plugin in data.get("plugins", []):
            if plugin.get("name") != "imprint":
                continue
            source = plugin.setdefault("source", {})
            source["source"] = "url"
            source.setdefault("url", DEFAULT_REPO)
            source["ref"] = ref

    update_json(ROOT / ".agents" / "plugins" / "marketplace.json", update_codex_marketplace)

    print(f"synced imprint plugin metadata to {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
