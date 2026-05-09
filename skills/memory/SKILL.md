---
name: memory
description: Manage local project memory - search, inject, remember, pin, list, forget. Persistent SQLite-backed memory shared across Claude Code sessions and projects.
level: 3
---

# Memory - Local Project Memory System

This skill provides persistent project memory backed by SQLite. Memory chunks (decisions, errors, fixes, commands, summaries, todos) are stored locally and can be searched, injected into the current Claude Code context, or pinned for automatic prefill injection.

## When to Use

- User asks to remember something for later (`기억해줘`, `remember this`)
- User asks about past decisions or fixes (`이전에 어떻게 해결했지?`)
- Resuming work on a project after a break
- Searching for past errors or solutions
- Curating what gets injected into future prompts

## Memory Storage

Global memory:
```
~/.claude/imprint/app.sqlite
```

Project override:
```
<project>/.claude/imprint/app.sqlite (optional)
```

## Subcommands

### `/memory search <query>`
FTS5 search across memory chunks for the current project.

```bash
imprint memory search "advisor 합성 흐름"
```

### `/memory remember <text>`
Store an explicit memory chunk. Optionally specify chunk_type.

```bash
imprint memory remember "Quick 모드는 one-shot 실행, advisor 활성" --type decision
```

Chunk types:
- `decision` - design or implementation decisions
- `error` - encountered errors
- `fix` - applied fixes
- `command` - useful commands
- `test_result` - test outcomes
- `summary` - work summaries
- `todo` - pending work
- `code_context` - code-specific context
- `note` - generic notes

### `/memory inject <chunk-id>`
Output a specific chunk's text so Claude Code includes it in context.

### `/memory pin <chunk-id>`
Mark chunk as pinned so the prefill hook always includes it.

### `/memory list [--recent | --pinned | --type <type>]`
List memory chunks for the current project.

### `/memory forget <chunk-id>`
Delete a chunk.

## Implementation

All subcommands are dispatched through:

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/imprint/memory.sh" <subcommand> [args...]
```

The script reads/writes `~/.claude/imprint/app.sqlite`, initializing the schema on first run.

## Project Identification

Project is identified by git root (`git rev-parse --show-toplevel`) or current working directory if not in a git repo. Each unique root path gets its own `projects` row.

## Notes

- Memory is local and never sent to any server.
- Sensitive information should be redacted before storing — use `--redact` flag (Phase 1.5).
- The `UserPromptSubmit` hook automatically pulls recent + pinned chunks into prefill (see `hooks/hooks.json`).
