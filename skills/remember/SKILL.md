---
name: remember
description: 명시적인 프로젝트 기억을 imprint에 저장합니다. /remember, 기억해줘, 결정 저장, 프로젝트 맥락 캡처, 나중에 의미 검색할 사실 보존 요청에 사용합니다.
level: 3
---

# Remember - Explicit Project Memory

Use this skill when the user wants to store a fact, decision, implementation note, command, test result, or follow-up for future sessions.

Prefer `/remember` language in user-facing replies. `/memory remember` remains the underlying storage command, but this skill is the simpler public entry point.

## Dispatcher

All remember actions go through:

```bash
DISPATCHER="${IMPRINT_PLUGIN_ROOT:-${PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}}}/scripts/imprint/remember.sh"
```

In this repo, the direct path is:

```bash
bash scripts/imprint/remember.sh "기억할 내용" --high
```

## Usage

Store concise, durable project context:

```bash
bash "$DISPATCHER" "로그인 공유하기는 초대 토큰 기반 딥링크로 처리한다. Universal Link는 초기 릴리스에서 보류한다." --high
```

Use importance flags instead of asking users to pick storage internals:

```bash
bash "$DISPATCHER" "프로젝트 전체 운영 원칙: hooks 는 사용자 세션을 막지 않는다." --require
bash "$DISPATCHER" "로그인 공유하기는 초대 토큰 기반 딥링크로 처리한다." --high
bash "$DISPATCHER" "README 설치 섹션을 다시 다듬는다." --middle
bash "$DISPATCHER" "임시로 확인한 후보 아이디어." --low
```

Default importance is `--middle`. Unknown flags must fail instead of being stored as text.

Use `--redact` when the text may contain secrets. `--type <chunk_type>` remains available for internal/debug use, but the public `/remember` path should prefer importance flags.

## Notes

- `/remember` stores into the unified `search_entries` table.
- Importance is stored in metadata as `importance=require|high|middle|low`.
- `--require` and `--high` also pin the row internally so important memories sort higher in existing memory paths.
- `/search` retrieves remembered entries directly through the unified hybrid path.
- Do not create a separate `remember` table; keeping one search entry store avoids duplicate search, pin, and forget logic.
