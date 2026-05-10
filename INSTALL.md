# Imprint — Claude Code Plugin 설치

이 저장소는 Claude Code 플러그인입니다. 설치 후 Claude Code 세션에서 `memory` 스킬과 자동 hook이 동작합니다.

## 사전 조건

- Claude Code (구독 OAuth로 인증됨)
- `sqlite3` (macOS 기본 포함)
- `python3` (macOS 기본 포함)
- 선택: Slack / Notion MCP (외부 source lazy fetch에서 사용)

## 설치 방법

### 1. 로컬 마켓플레이스로 등록

이 저장소를 Claude Code 마켓플레이스로 추가합니다.

```bash
# Claude Code 세션 안에서 (이 repo의 절대 경로를 사용)
/plugin marketplace add <ABSOLUTE_PATH_TO_THIS_REPO>
/plugin install imprint@imprint
```

### 2. 직접 심볼릭 링크 (개발 모드)

```bash
mkdir -p ~/.claude/plugins/cache/local
ln -s <ABSOLUTE_PATH_TO_THIS_REPO> ~/.claude/plugins/cache/local/imprint
```

이후 Claude Code를 재시작하면 플러그인이 로드됩니다.

## 설치 후 확인

새 Claude Code 세션을 열고 다음 질문을 보내면 `[Project memory context]` 블록이 자동 주입됩니다.

```
이 프로젝트의 최근 결정 사항을 알려줘
```

Hook이 동작하면 `~/.claude/imprint/app.sqlite`가 생성되고, `~/.claude/imprint/plugin.log`에 기록이 남습니다.

## 사용

### Memory skill (Claude Code 세션 안에서)

```
/memory remember <text> [--type decision|fix|todo|...] [--pin] [--redact]
/memory search <query>
/memory list [--recent|--pinned|--type <t>|--source <slack|notion|internal>]
             [--since <date>] [--limit <n>] [--project <path|id-prefix>]
/memory show <chunk-id> [--json]
/memory stats [--all] [--json]
/memory inject <chunk-id>
/memory pin <chunk-id>
/memory forget <chunk-id>
/memory refresh <url|source slack|source notion|project>
```

### Retrieval CLI (shell 또는 별도 skill 에서)

청크 + 요약 + 충돌까지 통합한 retrieval 파이프라인이 별도 명령으로 노출됩니다.
스킬에서 호출하거나 직접 셸에서 실행 가능 (`scripts/imprint/retrieve.sh` 또는
`scripts/imprint/lib` 안에서 `python3 -m retrieval.cli`).

```bash
# 동기 retrieval (chunk-only, 7a 경로)
scripts/imprint/retrieve.sh "디버그 토글 누르면 어떻게 돼?"
scripts/imprint/retrieve.sh --json "..."

# scope routing (local/feature/global 자동 분기)
scripts/imprint/retrieve.sh --routed "테스트 모드 진입 UX 시나리오"
scripts/imprint/retrieve.sh --routed --json "..."

# 외부 문서 ingest (stdin = raw_text)
echo "..." | python3 -m retrieval.cli ingest <project_id> <project_name> <source_type> <source_ref> [raw_chunk_type]

# 큐 drain (J4/J5/J6 처리)
scripts/imprint/ingest-drain.sh

# query scope 분류 단일 검사
python3 -m retrieval.cli classify "..."

# 요약 생성 / 재생성
python3 -m retrieval.cli summarize <project_id> [document_id]

# contradiction 후보 생성 + 판정
python3 -m retrieval.cli contradiction-scan <project_id>

# entity NER (LLM-driven, review queue 적재)
python3 -m retrieval.cli extract-entities <project_id> [document_id]

# entity review queue
python3 -m retrieval.cli entities list-pending <project_id>
python3 -m retrieval.cli entities confirm <alias_id>
python3 -m retrieval.cli entities reject <alias_id>

# supersede 후보 검사 (정규식 시그널 매칭 + 같은 section)
python3 -m retrieval.cli supersede <project_id> "<new chunk text>" [section_path]
```

`project_id` 는 hook 환경에서 git toplevel 경로 해시로 자동 결정됩니다 (`scripts/imprint/lib/common.sh::project_id`). 셸에서 직접 호출할 땐 `retrieve.sh` 가 같은 로직으로 자동 대입.

## 데이터 위치

```
~/.claude/imprint/
  app.sqlite        # 이벤트 로그 + memory chunks + retrieval 데이터 (FTS5 포함)
  plugin.log        # hook/skill 디버그 로그
  profile.jsonl     # IMPRINT_PROFILE=1 활성 시 latency 측정 (생성됨)
```

## 선택: ML 의존성 (retrieval 정확도 향상)

기본 설치만으로 plugin 은 FTS5 trigram 검색 + claude CLI LLM judge 로 동작합니다.
임베딩 / cross-encoder rerank / 동기 NLI 정밀 판정을 켜고 싶다면 다음을 설치:

```bash
pip install -r requirements-optional.txt
# 또는 일부만:
pip install sqlite-vec sentence-transformers transformers
```

설치하면 자동으로 활성화됩니다 (lazy 로더가 import 가능 여부 감지).

**모델 캐시 위치**: 기본은 `~/.cache/huggingface`. 다른 위치에 두려면:

```bash
export IMPRINT_MODEL_CACHE_DIR=/path/to/cache
```

**선택적 비활성화** (예: CI 환경):

```bash
export IMPRINT_DISABLE_EMBEDDING=1
export IMPRINT_DISABLE_RERANK=1
export IMPRINT_DISABLE_NLI=1
export IMPRINT_DISABLE_LLM_JUDGE=1   # claude CLI 호출도 끄려면
export IMPRINT_DISABLE_NER_LLM=1
export IMPRINT_DISABLE_SQLITE_VEC=1
```

## 제거

```bash
/plugin remove imprint
rm -rf ~/.claude/imprint  # memory 까지 같이 지우려면
```

## 동작 원리

**hook 단위:**

- **SessionStart hook**: SQLite 스키마 + 마이그레이션 적용 (idempotent), 현재 프로젝트 row upsert, soul.md 컨텍스트 prepend
- **UserPromptSubmit hook**: 유저 입력을 `events` 에 저장하고, 동기 retrieval 경로 (`QN → SC → RES → QEMB → HYB1/2/3 → RRF → BOOST → RG → (RR → RROK)? → GROUND → CCHECK → CTX`) 결과를 `[Project memory context]` 블록으로 stdout 출력 → Claude Code 가 prompt 에 자동 추가. 비동기로 J1 (lazy fetch) / J3 (warm cache) spawn
- **Stop hook**: turn 종료 시 마지막 assistant 응답을 `transcript_path` 에서 읽어 `events` 에 저장. 비동기로 J2 (response extract) spawn

**비동기 ingestion (priority sorted ingest queue):**

| Job | priority | 트리거 | 역할 |
|---|---|---|---|
| J1 lazy fetch | 1 | UserPromptSubmit spawn | 외부 source(Notion/Slack) MCP fetch + chunk 분할 + embedding |
| J2 response extract | 1 | Stop spawn | claude haiku 가 응답을 9 가지 chunk_type 으로 분류 + chunk 화 |
| J5 summary rebuild | 5 | W1 commit 후 변경 시 | feature → document → project 상향식 요약 재생성 |
| J6 contradiction detection | 5 | W1 commit 후 decision 변경 시 | 같은 entity + decision 쌍 NLI/LLM judge → 3구간 분기 저장 |
| J4 entity NER | 9 | W1 commit 후 새 chunk 시 | chunk → entity mention LLM 추출, conf ≥ 0.9 auto-confirm |
| J3 warm cache | 9 | UserPromptSubmit spawn | 임베딩 모델 cold-load + recent query embedding cache |

**single-writer commit chain (모든 write 가 같은 큐로 수렴):**

`PACK* → ENQ → DEDUPE → VRES → CONF → W1` — race / 중복 / version 충돌 차단. drain 은 `scripts/imprint/ingest-drain.sh` 또는 hook 종료 직전 inline.

**LLM 호출:**

모든 LLM 호출은 Claude Code 본체 또는 hook 이 백그라운드에서 호출하는 `claude -p` (prefill 분석 · Slack/Notion lazy fetch · Stop chunk 추출 · context_prefix 생성 · summary 생성 · contradiction LLM judge · NER) 를 통해 **OAuth 구독으로** 처리됩니다. API key 는 사용하지 않습니다.

ML 모델 (BGE-M3 임베딩 / cross-encoder / mDeBERTa NLI) 은 선택 의존성 — 미설치 시 FTS-only 검색 + claude CLI LLM judge fallback 으로 안전 동작.
