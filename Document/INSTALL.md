# Imprint — Claude/Codex Plugin 설치

이 저장소는 Claude Code/Codex 플러그인입니다. 설치 후 세션에서 자동 hook, `/memory`, `/search`, `/remember` 가 동작합니다.

## 사전 조건

기본 기능:

- Claude Code/`claude` CLI 또는 Codex/`codex` CLI
- `bash`, `python3`, `sqlite3`, `uuidgen`

선택 기능:

- `requirements-optional.txt`: embedding, rerank, NLI 품질 향상
- Slack / Notion MCP: opt-in 외부 source fetch

## 설치 방법

### 1. GitHub release 기반 설치

Claude Code 는 `.claude-plugin/marketplace.json` 을 읽습니다.

```text
/plugin marketplace add taeuk178/imprint
/plugin install imprint@imprint
```

Codex 는 GitHub release tag 를 marketplace 로 추가합니다. plugin 본문은 repo root 의 `plugin.json` 에서 읽습니다.

```bash
codex plugin marketplace add taeuk178/imprint --ref 0.2
codex plugin marketplace upgrade
```

재설치하려면 Claude Code 는 `/plugin uninstall imprint@imprint` → `/plugin marketplace remove imprint` 후 위 설치를 다시 실행하고, Codex 는 `codex plugin marketplace remove imprint` 후 다시 add/upgrade 합니다. Codex CLI 에는 `plugin install` 명령이 없으므로 실제 plugin 설치는 Codex App UI 에서 수행합니다.

### 2. 로컬 마켓플레이스로 등록

세션 안에서 이 repo 의 절대 경로를 사용합니다.

```text
/plugin marketplace add <ABSOLUTE_PATH_TO_THIS_REPO>
/plugin install imprint@imprint
```

Codex App 에서 `Imprint: Memory` 같은 스킬까지 바로 쓰려면 설치 스크립트를 실행합니다. `~/.codex/config.toml` 설정과 skill/wrapper 링크(`~/.codex/skills/`, `~/.agents/plugins/imprint`, `~/.local/bin/imprint`)를 한 번에 처리합니다. 설정 후 Codex App 을 재시작하거나 새 thread 를 엽니다.

```bash
bash <ABSOLUTE_PATH_TO_THIS_REPO>/scripts/imprint/install-codex.sh
```

### 3. 직접 심볼릭 링크 (개발 모드)

```bash
mkdir -p ~/.claude/plugins/cache/local
ln -s <ABSOLUTE_PATH_TO_THIS_REPO> ~/.claude/plugins/cache/local/imprint
```

이후 사용 중인 host 를 재시작합니다. Codex 개발 설치는 `.codex-plugin/plugin.json` manifest 를 사용하며, Codex App 에서 로컬 plugin 을 추가할 때도 같은 repo root 를 지정합니다.

### Codex hook 활성화

Codex 에서 hook 을 쓰려면 `~/.codex/config.toml` 에 plugin hook feature 가 켜져 있어야 합니다. `install-codex.sh` 를 썼다면 자동으로 추가됩니다.

```toml
[features]
plugin_hooks = true

[plugins."imprint@imprint"]
enabled = true
```

## 설치 후 확인

새 세션을 열고 "이 프로젝트의 최근 결정 사항을 알려줘" 같은 질문을 보냅니다. 정상 동작하면:

- `~/.imprint/app.sqlite` 가 생성됩니다.
- `~/.imprint/plugin.log` 에 `session-start ok` 로그가 남습니다.
- 필요한 경우 prompt 앞에 `[Project memory context]` 블록이 prepend 됩니다.

상태 진단은 `/memory status --json` 으로 합니다.

기존 `~/.claude/imprint/app.sqlite` 에 데이터가 있고 새 `~/.imprint/app.sqlite` 가 비어 있으면 첫 실행 때 자동으로 새 경로에 복사한 뒤 기존 파일을 제거합니다. 새 DB 에 이미 데이터가 있으면 덮어쓰거나 제거하지 않습니다.

## 자주 쓰는 명령

세션 안에서:

```text
/remember <text> [--require|--high|--middle|--low] [--redact]
/remember --stdin [--title <s>] [--split auto|always|never]
/memory search <query>
/memory list [--recent|--pinned|--type <t>|--source <slack|notion|internal>|--working]
/memory show <chunk-id> [--json]
/memory inject <chunk-id>
/memory pin <chunk-id> | unpin <chunk-id>
/memory forget <chunk-id> | forget --group <id-or-group-id>
/memory refresh <url|source slack|source notion|project>
/memory stats [--all] [--json]
/memory profile [--days <n>] [--json]
/memory status [--json]
/search "<질문>"
```

셸에서 직접 실행할 때:

```bash
imprint remember "테스트 모드 진입은 확인 모달을 먼저 거친다." --high
imprint search "테스트 모드 진입 UX 시나리오"
```

`/search` 는 질문에 따라 local/feature/global 범위를 자동으로 고릅니다. 사용자-facing dispatcher 는 옵션 없이 자연어 질문만 받습니다.

## 기존 DB migration

| migration | 실행 방식 | 설명 |
|---|---|---|
| 저장 위치 migration | 자동 | 기존 `~/.claude/imprint/app.sqlite` 만 있고 새 `~/.imprint/app.sqlite` 가 비어 있으면 첫 실행 때 새 위치로 복사합니다. |
| `search_entries` 스키마 migration | 명시 실행 | legacy `memory_chunks`, `documents`, `chunks_v2` 데이터를 `search_entries` 중심 스키마로 옮깁니다. |

기존 imprint DB 를 새 검색 구조로 옮기려면 설치 후 한 번 실행합니다. 백업을 만든 뒤 legacy row 를 옮기며, 이미 migration 된 DB 에서 다시 실행하면 no-op 입니다. 새 사용자는 migration 없이 새 스키마로 시작합니다.

```bash
imprint migrate search-entries
```

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

기본 설치만으로 FTS5(키워드) 검색으로 동작합니다. **의미(유사도) 검색이 필요할 때만** 추가하세요. plugin 에 포함되지 않으므로 사용자별로 설치해야 하며, 미설치 시 키워드 검색으로 자동 폴백합니다.

권장 경로는 setup dispatcher 입니다. 의존성 설치, BGE-M3 warmup, memory embedding backfill 을 한 번에 처리하고, 단계별 진행 로그와 실패 시 복구 힌트를 화면과 `plugin.log` 에 남깁니다.

```bash
imprint setup vector --install --warmup --backfill   # 전체 셋업
imprint setup vector --status                        # 상태 확인만
```

각 패키지의 역할 (`requirements-optional.txt`):

- `sentence-transformers`: BGE-M3 embedding 과 cross-encoder rerank. 없으면 `/search` 는 FTS5 중심으로 동작합니다.
- `transformers`: contradiction NLI 판정. 없으면 LLM judge 또는 rule fallback 으로 내려갑니다.
- `sqlite-vec`: SQLite vector extension. 없으면 embedding BLOB 을 Python cosine 으로 순회하는 fallback 을 사용합니다.

기존 entry 의 벡터 검색은 설치 후 `--backfill` 로 embedding 을 채워야 켜집니다. 새 rollup entry 는 vector 런타임이 있으면 background rollup 안에서 자동 embedding 됩니다(hook 동기 경로는 막지 않습니다).

모델 캐시 위치와 기능별 kill switch:

```bash
export IMPRINT_MODEL_CACHE_DIR=/path/to/cache
export IMPRINT_DISABLE_EMBEDDING=1   # 같은 형식: RERANK, NLI, MODEL_JUDGE, NER_LLM, SQLITE_VEC
```

## 외부 source 설정

외부 source fetch 는 기본으로 꺼져 있습니다. `IMPRINT_ENABLE_LAZY_FETCH=1` 을 설정하고 `<project>/.imprint/sources.json` 을 두면 prompt 키워드 기반으로 Slack/Notion 을 background fetch 합니다.

```json
{
  "slack": { "channels": ["#ios-payment", "#ios-bugs"] },
  "notion": { "pages": ["a1b2c3d4-payment-prd"] }
}
```

직접 URL 을 prompt 에 넣으면 turn 당 source 별 최대 3개까지 시도합니다. 실패, 빈 결과, cap 초과는 `source_status` marker 로 남습니다. fetch 결과는 현재 turn 답변 근거로 보장되지 않고 다음 turn/search 후보가 됩니다. 명시 갱신은 `/memory refresh <url>` 로 합니다.

## 동작 원리

hook 경로, 저장 테이블, 검색 파이프라인의 상세 흐름은 [`flow.md`](flow.md) 를 봅니다. 요약:

- `SessionStart`: 스키마 적용, 프로젝트 등록, Guardrail prepend, stale session background rollup.
- `UserPromptSubmit`: prompt redaction·archive, 경량 prefill. full `/search` 는 자동 호출하지 않습니다.
- `Stop`: assistant 응답 redaction·archive. 검색용 구현 기억은 이후 delta/rollup 이 `events` 에서 추출합니다.

## 검증

```bash
python3 scripts/imprint/tests/run_tests.py
```

현재 기준선과 커버리지는 [`TestCase.md`](TestCase.md) 를 봅니다.

문법만 빠르게 확인:

```bash
python3 -m py_compile scripts/imprint/lib/ingestion.py scripts/imprint/lib/retrieval/retrieve.py
bash -n scripts/imprint/memory.sh
```

## 배포 (메인테이너)

release 전 repo root 에서 버전을 동기화하고 main/tag/GitHub Release 를 같은 버전으로 맞춥니다. 기존 tag/release 확인은 `git tag --list <v>`, `gh release view <v>`.

```bash
python3 scripts/imprint/sync-plugin-version.py 0.2
git add VERSION plugin.json .claude-plugin .codex-plugin .agents/plugins/marketplace.json
git commit -m "plugin 배포 버전 0.2 동기화"
git push origin main
git tag 0.2 && git push origin 0.2
gh release create 0.2 --title "imprint 0.2" --notes-file <notes-file>
```

## 제거

세션 안에서:

```text
/plugin remove imprint
```

memory DB 까지 지우려면 `rm -rf ~/.imprint`. DB 삭제는 되돌릴 수 없으니 필요한 경우 먼저 백업하세요.
