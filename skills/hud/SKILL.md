---
name: hud
description: Configure the imprint HUD shown in Claude Code's statusline. Displays 5h/weekly OAuth usage, context window percent, installed skill count, and agent count.
level: 2
---

# Imprint HUD

A statusline HUD that surfaces five elements:

| Element | Source |
| --- | --- |
| `5h` | `rate_limits.five_hour.used_percentage` from Claude Code stdin |
| `wk` | `rate_limits.seven_day.used_percentage` from stdin |
| `ctx` | `context_window.used_percentage` from stdin |
| `skills` | `find ~/.claude/plugins/cache -name SKILL.md` count |
| `agents` | `find ~/.claude/plugins/cache -path */agents/*.md` count |

All data comes from Claude Code's session JSON or local plugin cache. No API keys, no Anthropic API calls — runs purely on what Claude Code already has under OAuth subscription.

## Quick Commands

| Command | Effect |
| --- | --- |
| `/imprint:hud install` | Switch the statusline to the imprint HUD (saves any previous config) |
| `/imprint:hud install --layout focused` | Install with the focused layout |
| `/imprint:hud status` | Show what's currently configured |
| `/imprint:hud layout <minimal|focused|full>` | Change layout without reinstalling |
| `/imprint:hud uninstall` | Restore the previous statusline (or remove the line if none) |

## Layouts

```
minimal   5h:21%
focused   5h:21% │ wk:3% │ ctx:18%
full      imprint │ 5h:21% │ wk:3% │ ctx:18% │ skills:53 │ agents:12
```

Stored in `~/.claude/imprint/hud-config.json`.

## Implementation

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/imprint/hud.sh"          # statusline body
"$CLAUDE_PLUGIN_ROOT/scripts/imprint/hud-setup.sh"    # install/status/uninstall/layout
```

The setup script writes:
- `~/.claude/settings.json` — `statusLine.command` set to invoke `hud.sh`
- `~/.claude/imprint/previous-statusline.json` — backup of any prior statusLine value
- `~/.claude/imprint/backups/settings-<timestamp>.json` — full settings.json snapshot before edit

## Coexistence with Other HUDs

Only one statusline can be active. If OMC's HUD or another tool was configured, `install` saves its `statusLine` block to `previous-statusline.json` and `uninstall` restores it. Switching back and forth is non-destructive.

## Notes

- Restart Claude Code or run `/reload-plugins` after `install` so the new statusLine is picked up.
- If `5h` or `wk` show `-`, Claude Code didn't include rate limit data in the session JSON for the current model/session. The HUD doesn't try to invent values.
- Skill/agent counts include every installed plugin (OMC, codex, imprint, etc.), not just imprint's.
