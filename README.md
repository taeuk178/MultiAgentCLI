# imprint — Claude/Codex memory plugin

imprint 는 Claude Code 또는 Codex 세션에 **로컬 작업 기억**을 붙이는 plugin 입니다. 프롬프트, 응답, 사용자가 직접 저장한 메모리, 선택적으로 Slack/Notion 외부 소스를 SQLite + FTS5 에 저장하고, 다음 turn 에 관련 기억을 다시 꺼내 쓸 수 있게 합니다.

## 설치

자세한 절차는 [`INSTALL.md`](INSTALL.md)를 기준으로 합니다.

```bash
claude plugin marketplace add <this-repo>
claude plugin install imprint@imprint
```

설치 후 세션을 새로 열면 `SessionStart` hook 이 `~/.imprint/app.sqlite` 를 만들고 현재 프로젝트를 등록합니다.

Codex에서는 `.codex-plugin/plugin.json` manifest가 같은 `skills/`와 `hooks/hooks.json`을 가리킵니다.

Codex plugin hook을 쓰려면 `~/.codex/config.toml`에 아래 설정이 필요합니다.

```toml
[features]
plugin_hooks = true
```

## 사전 조건

기본 기능은 아래 도구만 있으면 동작합니다.

- `bash`
- `python3`
- `sqlite3`
- `uuidgen`
- Claude Code / `claude` CLI, 또는 Codex / `codex` CLI

선택 의존성은 검색 품질을 높입니다. 없어도 FTS-only fallback 으로 동작합니다.

```bash
pip install -r requirements-optional.txt
```

Slack/Notion lazy-fetch 를 쓰려면 사용 중인 host 쪽에 해당 MCP 가 별도로 등록되어 있어야 합니다.

## Host 자동 감지

background 모델 작업은 hook 환경에서 자동으로 host를 감지해 실행합니다.

```bash
export IMPRINT_HOST=codex   # 또는 claude
export IMPRINT_CODEX_MODEL=gpt-5.4-mini
export IMPRINT_CLAUDE_MODEL=haiku
```

이 설정은 prompt 분석, response extract, 요약, NER, contradiction judge 같은 background 모델 작업에만 적용됩니다. SQLite 저장소, `/memory`, `/search` 검색 로직은 그대로 동작합니다.

기본 DB는 Claude/Codex 공유를 위해 `~/.imprint/app.sqlite` 입니다. 첫 실행 시 새 DB에 사용자 데이터가 없고 기존 `~/.claude/imprint/app.sqlite` 에 데이터가 있으면 자동으로 새 경로에 마이그레이션한 뒤 기존 `app.sqlite` 파일을 제거합니다. 기존 Claude 경로를 계속 쓰려면 `IMPRINT_HOME=$HOME/.claude/imprint`, Codex용으로 분리하려면 `IMPRINT_HOME=$HOME/.codex/imprint` 를 지정하세요.

## 핵심 기능

| 영역 | 설명 |
|---|---|
| Memory | prompt, assistant response, `/remember`, Slack/Notion fetch 결과를 redaction 후 `memory_chunks` 에 저장하고, persistent memory 는 `chunks_v2` 후보로 bridge 합니다. |
| Prefill | 매 prompt 전에 query context, session memory, retrieved memory, external source context 를 `[Project memory context]` 로 자동 prepend 합니다. |
| `/memory` | 저장된 memory 를 검색, 확인, 주입, pin, 삭제, refresh 합니다. |
| `/search` | 문서 RAG(`chunks_v2`/`summaries`)를 우선 검색하고, 결과가 약하면 `memory_chunks` 를 read-only fallback 으로 조회합니다. |
| Setup | 선택 벡터 검색 의존성 설치, 모델 warmup, memory embedding backfill 을 한 명령으로 처리합니다. |
| Routing | `<project>/.imprint/UserPromptSubmit.md` 의 키워드 룰을 보고 routing advisory 를 prepend 합니다. |
| Soul | `<project>/.imprint/soul.md` 를 세션 시작·압축 후 자동 prepend 합니다. |
| HUD | Claude Code statusline 에 5h/wk/context 사용량과 plugin 상태를 표시할 수 있습니다. |

## 기본 흐름

```text
사용자 prompt
  -> UserPromptSubmit hook
       events.user_message 저장
       현재 질문 working mini-chunk 저장
       routing rule 평가
       need-retrieval gate
       context section별 memory prefill
       lazy-fetch background spawn
  -> host 모델 응답
  -> Stop hook
       events.llm_response 저장
       response extract background spawn
  -> 다음 turn
       새 persistent memory 가 prefill/search 후보가 됨
```

`/search` 는 hook 이 자동 호출하지 않습니다. 사용자가 명시적으로 `/search` 를 호출했을 때만 풀 검색 경로를 탑니다. 기본적으로 질문을 보고 local/feature/global 범위를 자동 선택합니다.

전체 Mermaid 다이어그램과 hook 의존성은 [`flow.md`](flow.md)를 봅니다.

## 자주 쓰는 명령

| 하고 싶은 일 | 명령 |
|---|---|
| memory 검색 | `/memory search <query>` |
| 특정 chunk 보기 | `/memory show <id>` 또는 `/memory show <id> --json` |
| 특정 chunk 를 현재 turn 에 주입 | `/memory inject <id>` |
| 직접 기억 저장 | `/remember <text> --high` |
| 항상 위로 올리기 | `/memory pin <id>` |
| pin 해제 | `/memory unpin <id>` |
| 최근/pinned/source별 목록 | `/memory list --recent`, `/memory list --pinned`, `/memory list --source notion`, `/memory list --working` |
| 외부 source 갱신 | `/memory refresh <url>` |
| hook/DB 상태 진단 | `/memory status --json` |
| 느린 지점 요약 | `/memory profile --json` |
| 문서 RAG 명시 조회 | `/search "<question>"` |
| 벡터 검색 셋업 | `imprint setup vector --install --warmup --backfill` |

벡터 검색 상태만 확인하려면:

```bash
imprint setup vector --status
```

## 외부 소스

프로젝트에 `<project>/.imprint/sources.json` 을 두면 Slack/Notion 을 background 로 lazy-fetch 할 수 있습니다.

```json
{
  "slack": { "channels": ["#ios-payment", "#ios-bugs"] },
  "notion": { "pages": ["a1b2c3d4-payment-prd"] }
}
```

fetch 실패, URL cap 초과, stale 상태는 `source_status` marker 로 남고 `/memory list/show` 에서 확인할 수 있습니다. 자동 refresh 는 하지 않으며, 필요할 때 `/memory refresh` 로 명시 갱신합니다.

운영 상태는 `/memory status` 로 확인합니다. DB 접근, 최근 log/profile stage, WARN/ERROR 수,
working TTL/max 설정을 요약합니다. latency/payload 추이는 `IMPRINT_PROFILE=1` 로 수집한 뒤 `/memory profile` 로 요약합니다.

## RAG context sections

Foreground prefill 은 raw 질문을 retrieved context 처럼 취급하지 않도록 context section 을 나눠 출력합니다.

- `Query context`: 현재 질문과 deterministic search surface
- `Session memory`: 최근 session-visible working memory
- `Retrieved memory`: decision/fix/todo/code_context/note 등 저장된 long-term memory
- `External source context`: Slack/Notion/spec/message/thread 같은 grounded source context

working memory 는 기본적으로 24시간 TTL 과 session 당 최신 20개 제한을 가집니다.

## 안전과 한계

- secret-shaped text 는 저장 전에 redaction 합니다. 그래도 민감정보를 일부러 memory 에 넣는 사용은 피하세요.
- hook 은 실패해도 사용자 세션을 끊지 않고 `plugin.log` 에만 남깁니다.
- `sentence_transformers`, `transformers`, `sqlite-vec` 는 선택 의존성입니다. 미설치 시 검색 품질은 낮아질 수 있지만 기본 동작은 유지됩니다.
- `claude -p` 또는 `codex exec` 를 쓰는 lazy-fetch/response extract 는 background 로 실행되며 다음 turn 부터 반영됩니다.
- 사용자의 실제 DB 는 `~/.imprint/app.sqlite` 에 저장됩니다. 테스트할 때는 `IMPRINT_HOME=/tmp/...` 로 격리하세요.
