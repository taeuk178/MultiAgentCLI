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
FTS5 search across memory chunks for the current project. If trigram FTS returns
no rows, the dispatcher falls back to short-token `LIKE` search so Korean 2-char
terms like `버튼` can still find relevant chunks.

```bash
imprint memory search "Notion 페이지 섹션 분해 규칙"
```

### `/memory remember <text> [--type <t>] [--pin] [--redact]`
Store an explicit memory chunk. Optionally specify chunk_type or pin it.
Secret-shaped text is redacted before storage; `--redact` keeps the same
behavior explicit and records `redacted: true` metadata even when no pattern
matched.

```bash
imprint memory remember "Quick 모드는 one-shot 실행, lazy fetch 즉시 트리거" --type decision
imprint memory remember "key sk-ant-XXX 작동 확인" --redact     # secrets masked before INSERT
```

정규식 룰셋은 저장 전 chunk text를 마스킹하고, 마스킹이 발생했거나 `--redact`를 지정하면 metadata에 `redacted: true`를 기록합니다. 룰셋 우선순위: `$IMPRINT_REDACT_RULES` > `~/.claude/imprint/redact-rules.json` > plugin default(`scripts/imprint/lib/redact-rules.default.json`). 사용자 룰셋 형식은 plugin default를 그대로 복사해 추가 패턴을 더하면 됩니다.

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
`last_edited_at`, `source_status` 같은 메타데이터가 정확히 어떻게 채워졌는지 확인할 때
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

### `/memory profile [--days <n>] [--json]`
Summarize `~/.claude/imprint/profile.jsonl` after running sessions with
`IMPRINT_PROFILE=1`. Shows stage-level latency p50/p95/max and external fetch
payload sizes, which is the first input for daemon split or threshold tuning.

```bash
export IMPRINT_PROFILE=1
imprint memory profile --days 7
imprint memory profile --days 7 --json
```

### `/memory pin <chunk-id>`
Mark chunk as pinned so the prefill hook always includes it.

### `/memory list [필터들...]`
List memory chunks for the current project (또는 `--project`로 다른 프로젝트).

| 필터 | 동작 |
|---|---|
| `--recent` (기본) / `--pinned` | 정렬·pinned-only 토글 |
| `--type <chunk_type>` | `decision`/`spec`/`message`/`thread` 등 enum 필터 |
| `--source <slack|notion|internal>` | 외부 source 또는 내부(LLM 추출/`remember`) 필터 |
| `--since <YYYY-MM-DD>` | `created_at >= ?` |
| `--limit <n>` | 결과 행 수 (기본 50, 정수 아니면 50으로 폴백) |
| `--project <path|id-prefix>` | 다른 프로젝트 검색. 절대경로면 sha256으로 project_id 변환, 아니면 `LIKE 'prefix%'` |

출력은 `id|chunk_type|pinned|source|status|text` 순서입니다. `status`는
`ok`, `stale`, `fetch_failed`, `fetch_empty`, `skipped_by_cap` 등을 표시합니다.

`--project`는 `/memory stats --all`로 본 짧은 id를 그대로 붙여넣어 다른 프로젝트의 chunk를 빠르게 훑을 때 유용합니다.

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
"${IMPRINT_PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}}/scripts/imprint/memory.sh" <subcommand> [args...]
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
- 상태 표시: fetch 실패, URL cap 초과, 빈 keyword 결과는 `source_status`
  marker chunk로 남아 `/memory list/show`에서 확인할 수 있습니다. 오래된 외부
  chunk는 `IMPRINT_STALE_DAYS`(기본 14일) 기준으로 `stale` 표시됩니다.

`scripts/imprint/lib/ingestion.py`가 Python 단일 모듈로 모든 ingestion 단계를 처리하며, 실패는 plugin.log에만 기록되고 사용자 세션을 차단하지 않습니다.

## Notes

- Memory is local and never sent to any server.
- Hook 저장 경로와 `/memory remember`는 secret-shaped text를 저장 전 redaction 룰셋으로 마스킹합니다. 그래도 민감정보를 일부러 memory에 넣는 사용은 피하세요.
- The `UserPromptSubmit` hook automatically pulls recent + pinned chunks into prefill (see `hooks/hooks.json`).
- External source chunks (Slack/Notion) are NOT written to the events table — they live only in `memory_chunks` with `source_event_id IS NULL` (D11, AC7).
- 기본 사용자 RAG 경로는 자동 prefill + `/memory search`/`inject` 입니다. `/retrieve`는 별도 `documents`/`chunks_v2`/`summaries` 기반 문서 retrieval 경로를 먼저 사용하고, 문서 후보가 없을 때 `memory_chunks`를 read-only fallback 으로 조회합니다.
