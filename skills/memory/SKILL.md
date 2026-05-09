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

### `/memory refresh <spec>`
Drop cached external (Slack/Notion) chunks so the next prefill re-fetches.
Manual-only — there is no automatic refresh trigger (D24).

```bash
# 단일 URL 갱신 (즉시 재 fetch)
imprint memory refresh https://workspace.slack.com/archives/C123/p1234567890

# 채널 단위 일괄 갱신 — DELETE 후 다음 prefill에서 키워드 매칭으로 자연 재 fetch
imprint memory refresh source slack
imprint memory refresh source notion

# 외부 소스 chunk 전체 무효화
imprint memory refresh project
```

## Implementation

All subcommands are dispatched through:

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/imprint/memory.sh" <subcommand> [args...]
```

The script reads/writes `~/.claude/imprint/app.sqlite`, initializing the schema on first run.

## Project Identification

Project is identified by git root (`git rev-parse --show-toplevel`) or current working directory if not in a git repo. Each unique root path gets its own `projects` row.

## External Source Ingestion

`UserPromptSubmit` hook은 prefill 시점에 사내 컨텍스트(Slack 메시지, Notion 페이지)를 lazy fetch로 흡수해 memory에 누적하고, FTS5 + keywords 배열 union ranking으로 관련 chunk를 prepend합니다.

- 정의 위치: `<project>/.imprint/sources.json` (git-share 가능)
  - `slack.channels`: 키워드 매칭 모드에서 검색할 채널 목록
  - `notion.pages`: 키워드 매칭 모드에서 fetch할 페이지 URL/ID 목록
- 자동 트리거:
  - prompt에 Slack permalink가 들어 있으면 즉시 fetch (thread는 reply selection + 요약, single은 단건)
  - prompt에 Notion URL이 들어 있으면 페이지 전체를 섹션 단위로 분해해 chunk화
  - 모호한 prompt에서는 sources.json 채널·페이지를 키워드로 검색
- 캐시: `metadata_json.url` 기반 dedup, TTL 무한. 갱신은 `/memory refresh` 명시 명령으로만.

`scripts/imprint/lib/ingestion.py`가 Python 단일 모듈로 모든 ingestion 단계를 처리하며, 실패는 plugin.log에만 기록되고 사용자 세션을 차단하지 않습니다.

## Notes

- Memory is local and never sent to any server.
- Sensitive information should be redacted before storing — use `--redact` flag (Phase 1.5).
- The `UserPromptSubmit` hook automatically pulls recent + pinned chunks into prefill (see `hooks/hooks.json`).
- External source chunks (Slack/Notion) are NOT written to the events table — they live only in `memory_chunks` with `source_event_id IS NULL` (D11, AC7).
