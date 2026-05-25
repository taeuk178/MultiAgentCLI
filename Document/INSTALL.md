# Imprint — Claude/Codex Plugin 설치

이 저장소는 Claude Code/Codex 플러그인입니다. 설치 후 Coding agent 세션에서 자동 hook, `/memory`, `/search` 가 동작합니다.

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

### 1. GitHub release 기반 설치

Claude Code와 Codex 모두 같은 Git tag 버전을 기준으로 설치할 수 있습니다.

Release 전에는 repo root에서 버전을 동기화하고, main/tag/GitHub Release를 같은 버전으로 맞춥니다.

```bash
python3 scripts/imprint/sync-plugin-version.py 0.1.4
git add VERSION plugin.json .claude-plugin .codex-plugin .agents/plugins/marketplace.json
git commit -m "plugin 배포 버전 0.1.4 동기화"
git push origin main
git tag 0.1.4
git push origin 0.1.4
gh release create 0.1.4 --title "imprint 0.1.4" --notes-file /tmp/imprint-0.1.4-release.md
```

이미 tag나 release가 있는지 확인하려면 아래 명령을 먼저 실행합니다.

```bash
git tag --list 0.1.4
gh release view 0.1.4
```

Claude Code에서는 `.claude-plugin/marketplace.json`을 읽습니다.

```text
/plugin marketplace add taeuk178/imprint
/plugin install imprint@imprint
```

Codex에서는 GitHub release tag를 marketplace로 추가합니다. plugin 본문은 repo root의 `plugin.json`에서 읽으므로 sparse checkout을 사용하지 않습니다.

```bash
codex plugin marketplace add taeuk178/imprint --ref 0.1.4
codex plugin marketplace upgrade
```

이미 설치된 plugin을 `0.1.4` 기준으로 제거 후 다시 추가하려면 아래 순서로 실행합니다.

```bash
codex plugin marketplace remove imprint
codex plugin marketplace add taeuk178/imprint --ref 0.1.4
codex plugin marketplace upgrade imprint
```

Codex App에서 실제 plugin install까지 다시 필요하면, 현재 CLI에는 `plugin install` 명령이 없으므로 App UI에서 `imprint@imprint`를 설치하거나 app-server API로 설치합니다.

Claude Code에서 제거 후 다시 설치하려면 Claude Code 세션 안에서 아래 명령을 실행합니다.

```text
/plugin uninstall imprint@imprint
/plugin marketplace remove imprint
/plugin marketplace add taeuk178/imprint
/plugin install imprint@imprint
```

Codex에서 hook을 쓰려면 `~/.codex/config.toml`에 plugin hook feature를 켜야 합니다.

```toml
[features]
plugin_hooks = true

[plugins."imprint@imprint"]
enabled = true
```

### 2. 로컬 마켓플레이스로 등록

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

Codex App에서 `Imprint: Memory` 스킬까지 바로 쓰려면 설치 스크립트를 실행합니다.

```bash
bash <ABSOLUTE_PATH_TO_THIS_REPO>/scripts/imprint/install-codex.sh
```

이 스크립트는 `~/.codex/config.toml`에 `plugin_hooks`, `imprint@imprint`, local marketplace 설정을 추가하고, `~/.codex/skills/` 아래 imprint skills, `~/.agents/plugins/imprint`, `~/.local/bin/imprint` 연결을 생성합니다.

설정 후 Codex App을 완전히 재시작하거나 새 thread를 열면 `Imprint: Memory`, `Imprint: Setup` 같은 스킬이 목록에 표시됩니다.

### 3. 직접 심볼릭 링크 (개발 모드)

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
/remember <text> [--require|--high|--middle|--low] [--redact]
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
search "디버그 토글 누르면 어떻게 돼?"
search "테스트 모드 진입 UX 시나리오"

# 셸에서 직접 실행할 때
imprint remember "테스트 모드 진입은 확인 모달을 먼저 거친다." --high
imprint search "테스트 모드 진입 UX 시나리오"
# 또는: (cd scripts/imprint/lib && python3 -m retrieval.cli retrieve_json <project_id> "<질문>" 5)
```

`/search` 는 기본적으로 질문에 따라 local/feature/global 범위를 고릅니다. 현재 사용자-facing dispatcher 는 옵션 없이 자연어 질문만 받습니다.

## 기존 DB migration

imprint 는 두 종류의 migration 을 구분합니다.

| migration | 실행 방식 | 설명 |
|---|---|---|
| 저장 위치 migration | 자동 | 기존 `~/.claude/imprint/app.sqlite` 만 있고 새 `~/.imprint/app.sqlite` 가 비어 있으면 첫 실행 때 새 위치로 복사합니다. 새 DB에 이미 데이터가 있으면 덮어쓰지 않습니다. |
| `search_entries` 스키마 migration | 명시 실행 | legacy `memory_chunks`, `documents`, `chunks_v2` 데이터를 새 `search_entries` 중심 스키마로 옮깁니다. 자동 실행하지 않습니다. |

기존 imprint DB를 새 검색 구조로 옮기려면 설치 후 한 번 실행합니다.

```bash
imprint migrate search-entries
```

이 명령은 백업을 만든 뒤 legacy memory/document/search row 를 `source_documents`, `search_entries`, `search_summaries` 쪽으로 옮깁니다. `memory_chunks:<id>` synthetic document 는 새 구조에 남기지 않고, persistent memory row 만 `search_entries` 로 흡수합니다.

이미 migration 된 DB에서 다시 실행하면 no-op 이며, 새 사용자는 별도 migration 없이 새 스키마로 시작합니다.

## 데이터 위치

```text
~/.imprint/
  app.sqlite        # events, source_documents, search_entries, search_summaries
  plugin.log        # hook/skill/debug 로그
  profile.jsonl     # IMPRINT_PROFILE=1 활성 시 latency/payload 측정
```

테스트할 때는 사용자 홈을 건드리지 않도록 임시 홈을 사용합니다.

```bash
IMPRINT_HOME=/tmp/imprint-test python3 scripts/imprint/tests/run_tests.py
```

## 선택: ML 의존성

기본 설치만으로도 FTS5(키워드) 검색으로 동작합니다. **의미(유사도) 기반 검색이 필요할 때만** 아래 의존성을 추가하세요. plugin 에 포함되지 않으므로 **사용자별로 각자 설치**해야 하며, 미설치 시 키워드 검색으로 자동 폴백합니다.

권장 경로는 setup dispatcher 입니다. 의존성 설치, BGE-M3 warmup, 현재 프로젝트 memory embedding backfill 을 한 번에 처리합니다.
실행 중에는 `[imprint setup] status 시작/완료`, `install 실패 ...` 형식의 진행 로그가 출력되고, 같은 내용은 `~/.imprint/plugin.log` 에도 남습니다. 실패하면 단계별 복구 힌트를 먼저 확인하세요.

```bash
imprint setup vector --install --warmup --backfill
```

상태 확인만 하려면:

```bash
imprint setup vector --status
```

설치 입력 파일은 repo root 의 `requirements-optional.txt` 를 유지합니다. 이 파일은 문서가 아니라 `pip install -r requirements-optional.txt` 로 바로 사용할 수 있는 선택 의존성 목록입니다. 설치 이유와 적용 범위 설명만 이 문서에서 관리합니다.

현재 적용 범위에 주의하세요.

- `sentence-transformers`: `BAAI/bge-m3` embedding 생성과 `BAAI/bge-reranker-v2-m3` cross-encoder rerank 에 사용합니다. 없으면 `/search` 는 vector/rerank 없이 FTS5 중심으로 동작합니다.
- `transformers`: contradiction NLI 판정에 사용합니다. 없으면 Claude/LLM judge 또는 rule fallback 으로 내려갑니다.
- `sqlite-vec`: SQLite vector extension 로드 후보입니다. 없으면 현재 `/search` 는 embedding BLOB 을 Python cosine 으로 순회하는 fallback 구현을 사용합니다.

`search_entries` 에는 embedding 컬럼이 있습니다. 기존 entry 의 벡터 검색까지 켜려면 선택 ML 설치 후 setup dispatcher 의 `--backfill` 을 사용하세요. hook 동기 경로에서는 모델 cold-load 를 피하기 위해 새 entry 저장 시점의 embedding 생성을 기본으로 켜지 않습니다.

설치하면 import 가능 여부를 보고 해당 경로에서 자동 활성화됩니다.

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

외부 source fetch 는 기본 RAG 루프에서 꺼져 있습니다. 필요할 때만 `IMPRINT_ENABLE_LAZY_FETCH=1` 을 설정하고, 프로젝트에 `<project>/.imprint/sources.json` 을 두면 prompt 키워드 기반으로 Slack/Notion 을 background fetch 할 수 있습니다.

```json
{
  "slack": { "channels": ["#ios-payment", "#ios-bugs"] },
  "notion": { "pages": ["a1b2c3d4-payment-prd"] }
}
```

자동 lazy fetch 를 켠 상태에서 직접 URL을 prompt에 넣으면 turn 당 source 별 최대 3개까지 시도합니다. 실패, 빈 결과, cap 초과는 `source_status` marker 로 남습니다. 현재 turn 답변 근거로 즉시 보장하지 않고 다음 turn/search 후보가 됩니다. 명시 갱신은 `/memory refresh <url>` 로 수행합니다.

## 동작 원리 요약

### 자동 hook 경로

- `SessionStart`: SQLite 스키마 적용, 프로젝트 등록, `.imprint/Guardrail.md` prepend.
- `UserPromptSubmit`: user prompt redaction, `events.user_message` 저장, working surface metadata 저장, routing rule 평가, need-retrieval gate, context section prefill. `IMPRINT_ENABLE_LAZY_FETCH=1` 일 때만 external lazy-fetch worker 를 spawn 합니다.
- `Stop`: 마지막 assistant 응답 redaction, `events.llm_response` 저장. 검색용 구현 기억은 stale session 또는 명시 delta/rollup 이 나중에 `events` 에서 추출합니다.

자동 hook 경로는 full `/search` 를 호출하지 않습니다. 사용자 turn 을 막지 않기 위해 동기 경로는 lightweight prefill 만 수행합니다. 이 경로는 `events.metadata_json` 의 working surface 와 `search_entries` 를 가볍게 읽고, 후보가 있을 때만 `[Project memory context]` 에 넣습니다.

### 명시 search 경로

`/search` 는 사용자가 명시 호출할 때만 실행됩니다.

- `search_entries` / `search_summaries` 검색.
- 현재 세션 working surface 를 query context 로 soft union.
- 후보가 없거나 저신뢰이면 trace 에 이유를 남기고, raw events 자동 fallback 은 열지 않습니다.
- confirmed contradiction 은 scoring 단계에서 강하게 감점.
- JSON mode 는 trace 와 provenance 를 노출.

### 비동기 작업

- opt-in lazy-fetch: `IMPRINT_ENABLE_LAZY_FETCH=1` 일 때 background model이 prompt 키워드/URL을 분석하고 Slack/Notion MCP를 read-only fetch.
- rollup extract: background model이 session 단위 `events` 에서 decision/code_context/summary/note 구현 기억을 추출해 `search_entries` 에 저장.
- retrieval ingest queue: 명시 문서 ingestion 뒤 `summary_regen`, `contradiction_scan`, `ner_extract` 를 처리.

`/remember` 와 rollup 의 직접 `search_entries` 저장 경로는 현재 ingest queue 를 거치지 않습니다.

## 검증

전체 회귀:

```bash
python3 scripts/imprint/tests/run_tests.py
```

현재 기준선:

```text
31 PASS / 0 FAIL
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
