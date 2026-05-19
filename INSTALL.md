# Imprint — Claude/Codex Plugin 설치

이 저장소는 Claude Code/Codex 플러그인입니다. 설치 후 Coding agent 세션에서 자동 hook, `/memory`, `/retrieve` 가 동작합니다.

## 사전 조건

기본 기능:

- Claude Code/`claude` CLI 또는 Codex/`codex` CLI
- `bash`
- `python3`
- `sqlite3`
- `uuidgen`

선택 기능:

- Slack / Notion MCP: 외부 source lazy-fetch
- `requirements-optional.txt`: embedding, rerank, NLI 품질 향상

## 설치 방법

### 1. 로컬 마켓플레이스로 등록

Coding agent 세션 안에서 이 repo의 절대 경로를 사용합니다.

```text
/plugin marketplace add <ABSOLUTE_PATH_TO_THIS_REPO>
/plugin install imprint@imprint
```

설치 후 Coding agent 세션을 새로 열면 `SessionStart` hook 이 실행됩니다.

Codex에서 hook을 쓰려면 `~/.codex/config.toml`에 plugin hook feature를 켜야 합니다.

```toml
[features]
plugin_hooks = true
```

### 2. 직접 심볼릭 링크 (개발 모드)

```bash
mkdir -p ~/.claude/plugins/cache/local
ln -s <ABSOLUTE_PATH_TO_THIS_REPO> ~/.claude/plugins/cache/local/imprint
```

이후 사용 중인 host를 재시작합니다.

Codex 개발 설치는 `.codex-plugin/plugin.json` manifest를 사용합니다. Codex App에서 로컬 plugin을 추가할 때도 같은 repo root를 지정하세요.

## 설치 후 확인

새 Coding agent 세션을 열고 아래 질문을 보냅니다.

```text
이 프로젝트의 최근 결정 사항을 알려줘
```

정상 동작하면:

- `~/.imprint/app.sqlite` 가 생성됩니다.
- `~/.imprint/plugin.log` 에 `session-start ok` 로그가 남습니다.
- 필요한 경우 prompt 앞에 `[Project memory context]` 블록이 prepend 됩니다.

기존 `~/.claude/imprint/app.sqlite` 에 데이터가 있고 새 `~/.imprint/app.sqlite` 가 비어 있으면 첫 실행 때 자동으로 새 경로에 복사한 뒤 기존 `app.sqlite` 파일을 제거합니다. 새 DB에 이미 memory/event/document 데이터가 있으면 덮어쓰거나 제거하지 않습니다.

상태 진단:

```text
/memory status --json
```

## 자주 쓰는 명령

Coding agent 세션 안에서:

```text
/memory remember <text> [--type decision|fix|todo|...] [--pin] [--redact]
/memory search <query>
/memory list [--recent|--pinned|--type <t>|--source <slack|notion|internal>|--working]
/memory show <chunk-id> [--json]
/memory inject <chunk-id>
/memory pin <chunk-id>
/memory unpin <chunk-id>
/memory forget <chunk-id>
/memory refresh <url|source slack|source notion|project>
/memory stats [--all] [--json]
/memory profile [--days <n>] [--json]
/memory status [--json]
```

문서 RAG 명시 조회:

```text
/retrieve "디버그 토글 누르면 어떻게 돼?"
/retrieve --json "디버그 토글 누르면 어떻게 돼?"
/retrieve --routed "테스트 모드 진입 UX 시나리오"
/retrieve --routed --json "테스트 모드 진입 UX 시나리오"
```

`/retrieve --json` 과 `/retrieve --routed --json` 은 trace, context section, provenance, fallback/rerank 이유를 함께 반환합니다.

## 데이터 위치

```text
~/.imprint/
  app.sqlite        # events, memory_chunks, retrieval 데이터
  plugin.log        # hook/skill/debug 로그
  profile.jsonl     # IMPRINT_PROFILE=1 활성 시 latency/payload 측정
```

테스트할 때는 사용자 홈을 건드리지 않도록 임시 홈을 사용합니다.

```bash
IMPRINT_HOME=/tmp/imprint-test python3 scripts/imprint/tests/run_tests.py
```

## 선택: ML 의존성

기본 설치만으로도 FTS5 + LIKE fallback + background model judge fallback 으로 동작합니다. 검색 품질을 높이고 싶다면:

```bash
pip install -r requirements-optional.txt
```

일부만 설치할 수도 있습니다.

```bash
pip install sqlite-vec sentence-transformers transformers
```

설치하면 import 가능 여부를 보고 자동 활성화됩니다.

모델 캐시 위치:

```bash
export IMPRINT_MODEL_CACHE_DIR=/path/to/cache
```

CI 또는 가벼운 환경에서 선택 기능을 끄려면:

```bash
export IMPRINT_DISABLE_EMBEDDING=1
export IMPRINT_DISABLE_RERANK=1
export IMPRINT_DISABLE_NLI=1
export IMPRINT_DISABLE_MODEL_JUDGE=1
export IMPRINT_DISABLE_NER_LLM=1
export IMPRINT_DISABLE_SQLITE_VEC=1
```

## 외부 source 설정

프로젝트에 `<project>/.imprint/sources.json` 을 두면 prompt 키워드 기반으로 Slack/Notion 을 background fetch 할 수 있습니다.

```json
{
  "slack": { "channels": ["#ios-payment", "#ios-bugs"] },
  "notion": { "pages": ["a1b2c3d4-payment-prd"] }
}
```

직접 URL을 prompt에 넣으면 turn 당 source 별 최대 3개까지 시도합니다. 실패, 빈 결과, cap 초과는 `source_status` marker 로 남습니다.

## 동작 원리 요약

### 자동 hook 경로

- `SessionStart`: SQLite 스키마 적용, 프로젝트 등록, `.imprint/soul.md` prepend.
- `UserPromptSubmit`: user prompt redaction, `events.user_message` 저장, working mini-chunk 저장, routing rule 평가, need-retrieval gate, context section prefill, lazy-fetch worker spawn.
- `Stop`: 마지막 assistant 응답 redaction, `events.llm_response` 저장, persistent response extract worker spawn.

자동 hook 경로는 full `/retrieve` 를 호출하지 않습니다. 사용자 turn 을 막지 않기 위해 동기 경로는 lightweight prefill 만 수행합니다.

### 명시 retrieval 경로

`/retrieve` 는 사용자가 명시 호출할 때만 실행됩니다.

- `chunks_v2` / `summaries` 문서 RAG 우선.
- 현재 세션 working memory 를 query context 로 soft union.
- 후보가 없거나 저신뢰이면 `memory_chunks` read-only fallback.
- confirmed contradiction 은 scoring 단계에서 강하게 감점.
- JSON mode 는 trace 와 provenance 를 노출.

### 비동기 작업

- lazy-fetch: background model이 prompt 키워드/URL을 분석하고 Slack/Notion MCP를 read-only fetch.
- response extract: background model이 assistant 응답에서 decision/fix/todo/code_context 등 persistent memory chunk를 추출.
- retrieval v2 ingest queue: 명시 문서 ingestion 뒤 `summary_regen`, `contradiction_scan`, `ner_extract` 를 처리.

자동 hook 의 `memory_chunks` 저장 경로는 현재 ingest queue 를 거치지 않습니다.

## 검증

전체 회귀:

```bash
python3 scripts/imprint/tests/run_tests.py
```

현재 기준선:

```text
19 PASS / 0 FAIL
```

문법만 빠르게 확인:

```bash
python3 -m py_compile scripts/imprint/lib/ingestion.py scripts/imprint/lib/retrieval/retrieve.py
bash -n scripts/imprint/memory.sh
```

## 제거

Coding agent 세션 안에서:

```text
/plugin remove imprint
```

memory DB까지 지우려면:

```bash
rm -rf ~/.imprint
```

DB 삭제는 되돌릴 수 없으니 필요한 경우 먼저 백업하세요.
