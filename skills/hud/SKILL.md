---
name: hud
description: Configure the imprint HUD shown in Claude Code's statusline. Pick which segments appear from a 12-field menu (rate limits, context %, model, cost, duration, skills/agents counts, etc).
level: 2
---

# Imprint HUD

Statusline HUD that lets the user pick which segments to display from a fixed
12-field menu. All data comes from Claude Code's session JSON (passed via
stdin) or the local plugin cache. No API keys, no Anthropic API calls.

## Available fields

| ID | 표시 형태 | 출처 |
| --- | --- | --- |
| `5h` | `5h: 25% (1h 49m)` | `rate_limits.five_hour.{used_percentage, resets_at}` |
| `wk` | `wk: 3% (1d 9h)` | `rate_limits.seven_day.{used_percentage, resets_at}` |
| `ctx` | `ctx: 12%` | `context_window.used_percentage` |
| `tokens` | `tok: 24k/200k` | `context_window.total_input_tokens + total_output_tokens / context_window_size` |
| `model` | `Opus` | `model.display_name` |
| `effort` | `effort: high+thk` | `effort.level` (+thk if `thinking.enabled`) |
| `style` | `style: explanatory` | `output_style.name` |
| `cost` | `$0.42` | `cost.total_cost_usd` (client-side estimate) |
| `dur` | `dur: 1h 12m` | `cost.total_duration_ms` |
| `skills` | `skills: 17` | filesystem scan of `~/.claude/plugins/cache/**/SKILL.md` etc. |
| `agents` | `agents: 1` | filesystem scan of `**/agents/*.md` |
| `time` | `19:42` | `date +%H:%M` |

기본 활성 필드: `5h ctx time` (사용자가 처음 설치했을 때 가벼운 출력).

## Quick Commands

| Command | Effect |
| --- | --- |
| `/imprint:hud install` | Switch the statusline to the imprint HUD (saves any previous config) |
| `/imprint:hud status` | Show what's currently configured |
| `/imprint:hud uninstall` | Restore the previous statusline (or remove if none) |
| `/imprint:hud fields list [--project]` | 가용 필드와 현재 ON 목록 보기 |
| `/imprint:hud fields set <ids...> [--project]` | 활성 필드 통째 덮어쓰기 — 표시 순서가 인자 순서 |
| `/imprint:hud fields enable <ids...> [--project]` | 추가 |
| `/imprint:hud fields disable <ids...> [--project]` | 제거 |
| `/imprint:hud layout <minimal\|focused\|full>` | (backward-compat) 옛 프리셋 |

`set`이 가장 자주 쓰입니다 — `hud-setup.sh fields set 5h ctx cost time`처럼
원하는 순서대로 한 줄에 박아넣는 게 enable/disable 반복보다 깔끔합니다.

## Scope

설정 파일은 두 군데에서 읽고 **project가 user를 우선**합니다.

| 우선순위 | 경로 |
| --- | --- |
| 1 (먼저) | `<git-root>/.imprint/hud-config.json` (project) |
| 2 | `~/.claude/imprint/hud-config.json` (user) |
| 3 (둘 다 없으면) | default `["5h", "ctx", "time"]` |

`--project` 플래그가 붙은 명령은 1번 위치를 만지고, 없으면 2번 위치를 만집니다. 같은 git 작업 트리 안에서만 다른 HUD를 쓰고 싶을 때 1번을 사용하고, 모든 작업에서 동일한 HUD가 좋다면 2번만 두면 됩니다.

## Examples

```bash
# 사내 프로젝트엔 cost·dur 같은 운영 정보를 띄우고 싶을 때
cd ~/work/ios-app
bash scripts/imprint/hud-setup.sh fields set 5h ctx cost dur time --project

# 모든 다른 프로젝트엔 가벼운 기본만
bash scripts/imprint/hud-setup.sh fields set 5h ctx time

# Opus 사용량 추적이 필요할 때 한시적으로 model+tokens 추가
bash scripts/imprint/hud-setup.sh fields enable model tokens
```

## Implementation

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/imprint/hud.sh"          # statusline body
"$CLAUDE_PLUGIN_ROOT/scripts/imprint/hud-setup.sh"    # install/status/uninstall/layout/fields
```

The setup script writes:
- `~/.claude/settings.json` — `statusLine.command` set to invoke `hud.sh`
- `~/.claude/imprint/previous-statusline.json` — backup of any prior statusLine value
- `~/.claude/imprint/backups/settings-<timestamp>.json` — full settings.json snapshot before edit
- `~/.claude/imprint/hud-config.json` — user-scope `fields` array (or `layout` for backward-compat)
- `<git-root>/.imprint/hud-config.json` — project-scope override (when `--project` is used)

## Coexistence with Other HUDs

Only one statusline can be active. If OMC's HUD or another tool was configured, `install` saves its `statusLine` block to `previous-statusline.json` and `uninstall` restores it. Switching back and forth is non-destructive.

## Notes

- Restart Claude Code or run `/reload-plugins` after `install` so the new statusLine is picked up.
- If `5h` / `wk` / `ctx` / `cost` / `dur` show `-`, Claude Code didn't include the relevant field in the session JSON for the current model/session. The HUD doesn't try to invent values.
- Skill/agent counts include every installed plugin (OMC, codex, imprint, etc.), not just imprint's.
- Backward-compat: `hud-config.json`에 `layout: minimal/focused/full`만 있고 `fields`가 없으면 layout이 동등한 fields 배열로 매핑됩니다. 하지만 `fields`를 명시하면 layout 키는 무시되고 자동 제거됩니다.
