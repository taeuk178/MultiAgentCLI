# imprint — Claude Code plugin

imprint 는 Claude Code 세션에 **로컬 작업 기억**을 붙이는 plugin 입니다. 프롬프트, 응답, 사용자가 직접 저장한 메모리, 선택적으로 Slack/Notion 외부 소스를 SQLite + FTS5 에 저장하고, 다음 turn 에 관련 기억을 다시 꺼내 쓸 수 있게 합니다.

## 설치

자세한 절차는 [`INSTALL.md`](INSTALL.md)를 기준으로 합니다.

```bash
claude plugin marketplace add <this-repo>
claude plugin install imprint@imprint
```

설치 후 Claude Code 세션을 새로 열면 `SessionStart` hook 이 `~/.claude/imprint/app.sqlite` 를 만들고 현재 프로젝트를 등록합니다.

Codex에서는 `.codex-plugin/plugin.json` manifest가 같은 `skills/`와 `hooks/hooks.json`을 가리킵니다.

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

Slack/Notion lazy-fetch 를 쓰려면 Claude Code 쪽에 해당 MCP 가 별도로 등록되어 있어야 합니다.

## Codex/GPT 백엔드

background GPT 작업은 Codex CLI를 사용합니다. 모델을 명시하고 싶으면 세션 환경에 아래 값을 지정합니다.

```bash
# 선택: 지정하지 않으면 Codex CLI의 기본 모델/프로필을 사용합니다.
export IMPRINT_CODEX_MODEL=gpt-5.4-mini
```

이 설정은 prompt 분석, response extract, 요약, NER, contradiction judge 같은 background GPT 작업에만 적용됩니다. SQLite 저장소, `/memory`, `/retrieve` 검색 로직은 그대로 동작합니다.

## 핵심 기능

| 영역 | 설명 |
|---|---|
| Memory | prompt, assistant response, `/memory remember`, Slack/Notion fetch 결과를 redaction 후 `memory_chunks` 에 저장합니다. |
| Prefill | 매 prompt 전에 현재 turn clues, 최근 session evidence, durable/external evidence 를 `[Project memory context]` 로 자동 prepend 합니다. |
| `/memory` | 저장된 memory 를 검색, 확인, 주입, pin, 삭제, refresh 합니다. |
| `/retrieve` | 문서 RAG(`chunks_v2`/`summaries`)를 우선 검색하고, 결과가 없으면 `memory_chunks` 를 read-only fallback 으로 조회합니다. |
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
       lane별 memory prefill
       lazy-fetch background spawn
  -> Claude 응답
  -> Stop hook
       events.llm_response 저장
       response extract background spawn
  -> 다음 turn
       새 memory_chunks 가 다시 prefill/search/retrieve 후보가 됨
```

`/retrieve` 는 hook 이 자동 호출하지 않습니다. 사용자가 명시적으로 `/retrieve` 또는 `/retrieve --routed` 를 호출했을 때만 풀 retrieval 경로를 탑니다.

전체 Mermaid 다이어그램과 hook 의존성은 [`flow.md`](flow.md)를 봅니다.

## 자주 쓰는 명령

| 하고 싶은 일 | 명령 |
|---|---|
| memory 검색 | `/memory search <query>` |
| 특정 chunk 보기 | `/memory show <id>` 또는 `/memory show <id> --json` |
| 특정 chunk 를 현재 turn 에 주입 | `/memory inject <id>` |
| 직접 기억 저장 | `/memory remember <text> --type decision` |
| 항상 위로 올리기 | `/memory pin <id>` |
| pin 해제 | `/memory unpin <id>` |
| 최근/pinned/source별 목록 | `/memory list --recent`, `/memory list --pinned`, `/memory list --source notion`, `/memory list --working` |
| 외부 source 갱신 | `/memory refresh <url>` |
| hook/DB 상태 진단 | `/memory status --json` |
| 느린 지점 요약 | `/memory profile --json` |
| 문서 RAG 명시 조회 | `/retrieve --routed "<question>"` |

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
working TTL/max 설정을 요약합니다. retrieval 근거를 디버깅할 때는 `/retrieve --json`
출력에서 lane, provenance, fallback/rerank trace 를 확인합니다. latency/payload 추이는
`IMPRINT_PROFILE=1` 로 수집한 뒤 `/memory profile` 로 요약합니다.

## Memory lane

자동 prefill 은 raw 질문을 근거처럼 취급하지 않도록 lane 을 나눠 출력합니다.

- `Current turn clues`: 현재 질문과 deterministic search surface
- `Recent session evidence`: 최근 session-visible working memory
- `Durable evidence`: decision/fix/todo/code_context/note 등 대화에서 추출된 기억
- `External fetched context`: Slack/Notion/spec/message/thread 근거

working memory 는 기본적으로 24시간 TTL 과 session 당 최신 20개 제한을 가집니다.

## 안전과 한계

- secret-shaped text 는 저장 전에 redaction 합니다. 그래도 민감정보를 일부러 memory 에 넣는 사용은 피하세요.
- hook 은 실패해도 사용자 세션을 끊지 않고 `plugin.log` 에만 남깁니다.
- `sentence_transformers`, `transformers`, `sqlite-vec` 는 선택 의존성입니다. 미설치 시 검색 품질은 낮아질 수 있지만 기본 동작은 유지됩니다.
- Codex CLI 를 쓰는 lazy-fetch/response extract 는 background 로 실행되며 다음 turn 부터 반영됩니다.
- 사용자의 실제 DB 는 `~/.claude/imprint/app.sqlite` 에 저장됩니다. 테스트할 때는 `IMPRINT_HOME=/tmp/...` 로 격리하세요.
