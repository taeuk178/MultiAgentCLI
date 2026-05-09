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

### `/memory show <chunk-id> [--json]`
Pretty-print a chunk's full text + `metadata_json` for **debugging**. 외부
소스(Slack/Notion)가 어떻게 sectioning됐는지, `url`·`section_title`·
`last_edited_at` 같은 메타데이터가 정확히 어떻게 채워졌는지 확인할 때
사용합니다. `<chunk-id>`는 정확한 ID 또는 unique prefix를 받습니다.

```bash
imprint memory show ab12cd            # 사람이 읽기 좋은 형태
imprint memory show ab12cd --json     # 스크립트 친화적 JSON
```

`--json` 출력은 `id`/`chunk_type`/`metadata`(파싱된 객체)/`text`를 포함해
파이프라인에서 `jq`로 필드를 뽑아 쓰기 좋은 구조입니다.

### `/memory stats [--all] [--json]`
현 프로젝트의 memory 분포를 한 화면 요약: 총 chunk 수, pinned 수, 가장
오래된·가장 최근 chunk 시점, `chunk_type`/`source` 분포, 외부 source의
unique URL 수(notion 페이지, slack 메시지). "지금 memory에 뭐가 얼마나
쌓여 있는가"를 파악할 때 첫 번째로 호출합니다.

```bash
imprint memory stats              # 현 프로젝트 요약
imprint memory stats --all        # 전 프로젝트 한 줄씩 비교
imprint memory stats --json       # 자동화/대시보드용 JSON
```

`/memory list`는 chunk를 행 단위로 나열하지만 분포는 보여주지 않습니다.
`stats`는 그 반대 — 분포만 보여주고 개별 chunk는 안 찍습니다.

### `/memory pin <chunk-id>`
Mark chunk as pinned so the prefill hook always includes it.

### `/memory list [--recent | --pinned | --type <type> | --source <slack|notion|internal>]`
List memory chunks for the current project. 출력에 `source` 컬럼이 포함돼
외부 소스(Slack/Notion)와 내부(LLM 추출 / `remember`로 저장한) chunk를
한눈에 구분할 수 있습니다. `--source slack`/`notion`/`internal`로 필터링
가능합니다.

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
