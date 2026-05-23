# imprint 결정 사유 로그

**imprint 만든 이유**
- claude code, codex 사용 시 session이 종료되면 구현 사항에 대한 히스토리를 확인하기 어려워 해당 내용을 저장시켜 추후에도 확인하게 하기 위함
  - 코드 구현부를 보고 imprint에 물어봤을 때 관련 구현 세부 내용(왜 이렇게 구현했는지), 부가 설명을 듣기 위함
- 여러 LLM provider 사용 시 같은 히스토리 공유 목적

**문서 책임**
- 본 문서는 **왜 이렇게 했는가**를 남긴다. 코드만 보면 알 수 없는 트레이드오프, 폐기된 대안, 결정 시점의 제약을 사실 위주로 기록한다.
- 큰 그림(비전·Phase 정의·아키텍처): `LoadMap.md`
- 단기 픽업(즉시 검토·deferred TODO·미완 Phase): `HANDOFF.md`
- hook 단계별 시스템 의존·운영 환경 변수: `flow.md`
- 사용·설치: `README.md`
- 보관용 초안·폐기/후순위 handoff: `archive/`

기록 순서는 **최신이 위**. 항목당 한 단락 안에 변경/사유/대안 폐기 근거를 묶는다.

## 2026-05-24 — `/search` rollup 세부 근거 출력 개선

**무엇:** `/search` 와 `retrieval.cli retrieve_json` 이 `search_entries.metadata_json` 과 `source_event_id` 를 후보에 보존하도록 했다. 텍스트 출력은 rollup decision entry 에 `reason`, `files`, `symbols`, `tests`, `event_range`, `rollup session` 이 있으면 본문 아래에 짧은 detail line 으로 함께 보여준다.

**왜:** delta/rollup extract 로 구현 결정 arc 를 `search_entries` 에 저장해도, 출력이 display text 만 보여주면 사용자는 "왜 그렇게 했는지", "어느 파일/심볼/테스트와 연결되는지"를 다시 확인하기 어렵다. raw events 자동 검색을 열지 않는 대신, 정제 entry 가 이미 가진 provenance 를 검색 결과 UX 에 노출해 구현 히스토리 회수성을 높인다.

## 2026-05-24 — delta/rollup extract 로 구현 결정 arc 저장

**무엇:** 여러 turn 에 걸친 구현 결정 흐름을 `search_entries` 로 정제하기 위해 delta/rollup extract 를 추가했다. `Stop` 은 assistant `llm_response` event 에도 `metadata_json.session_id` 를 저장하고, per-turn extract 는 `fix/todo/command/error/test_result` 같은 flat 타입만 즉시 저장한다. `decision/code_context/summary/note` 는 `extract_state(project_id, session_id)` cursor 기반 bounded rollup 이 담당하며, 명시 명령은 `scripts/imprint/rollup.sh --session-id <id>|--latest|--stale` 와 `python3 -m retrieval.cli rollup-*` 로 제공한다. `SessionStart` 는 현재 session_id 를 알 때만 현재 세션을 제외한 30분 이상 stale session 을 background 로 보완 rollup 한다.

**왜:** 구현 이유는 보통 "A안 제안 → 사용자 반박 → B안 결정 → 테스트"처럼 여러 turn 에 걸쳐 드러난다. 마지막 assistant 응답만 보는 Stop extract 를 단순히 N-turn window 로 넓히면 같은 결정이 매 turn 다른 문장으로 재추출되어 text_hash dedup 을 빠져나가는 near-duplicate 가 쌓인다. 따라서 per-turn 과 rollup 의 타입 집합을 분리해 중복을 구조적으로 막고, rollup 재실행 중복은 search entry insert 와 cursor 전진을 한 SQLite transaction 으로 묶어 dedup 이 아니라 atomic cursor 로 막는다.

**남은 점:** 신선도 요구가 생기면 per-turn decision 즉시 저장 + rollup supersede(B안) 로 승격할 수 있다. 긴 세션 자동 K-turn cadence, `feature_key`/`plan_key` 자동 채움, file/symbol 정규화, search 결과 grouping, `/search --events` 는 별도 retrieval/output 트랙으로 남긴다.

## 2026-05-24 — `search_entries` 통합 스키마 구현

**무엇:** 2026-05-24 결정 로그의 `search_entries` 통합 설계를 실제 코드에 반영했다. 새 스키마는 `source_documents`, `search_entries`, `search_summaries`, `entry_entities` 를 만들고, 신규 DB에서는 `memory_chunks`, `documents`, `chunks_v2`, `events_fts` 를 더 이상 만들지 않는다. `/remember`, assistant response extract, Slack/Notion lazy-fetch, source document ingest 는 모두 `search_entries` 에 직접 저장한다. working overlay 는 영구 entry 로 만들지 않고 `events.metadata_json.query_surfaces`/`need_retrieval`/`retrieval_reason` 을 검색 시점에 읽는다. `origin=source_document` 는 `source_document_id` 가 있는 명시 ingest row 에만 쓰고, lazy-fetch 는 `external_fetch`, 상태 marker 는 `source_status` 로 분리한다. 기존 사용자 DB는 자동 파괴하지 않고 `imprint migrate search-entries` 명시 명령으로 백업 후 one-shot migration 한다.

**왜:** bridge 구조는 memory 한 건을 synthetic document 와 chunk 로 복제해 저장 의미와 검색 경로를 동시에 흐렸다. 구현을 단일 entry 인덱스로 수렴시키면 `/remember` 와 `/search` 의 사용자 모델이 단순해지고, optional vector backfill 도 `search_entries.embedding` 하나만 채우면 된다. raw events 전체 자동 fallback 은 정확도와 민감정보 노출 리스크가 있어 열지 않고, 사용자가 확인 가능한 `/search` trace 와 명시 저장을 중심으로 둔다.

**남은 점:** `plan_key`/`feature_key` 는 컬럼만 있고 자동 채움 경로는 아직 없다. `confidence`/`evidence_strength` 표현은 실제 eval 결과를 본 뒤 정한다. 기존 실사용 DB는 사용자가 `imprint migrate search-entries` 를 실행해야 새 구조로 옮겨진다. source document 재수집 시 validity 캐리오버 정책과 직접 저장 entry 를 summary/entity/contradiction queue 에 어디까지 연결할지는 후속 측정 뒤 결정한다.

## 2026-05-24 — `memory_chunks + chunks_v2` bridge 구조 폐기, `search_entries` 통합 결정

**무엇:** 저장 스키마를 다음 4개 축으로 재정의하기로 결정했다 (배포 전이므로 스키마 직접 변경 허용). `events` = raw 대화 로그(검색 제외, working overlay 소스로만 사용), `source_documents` = 진짜 원본 문서만(Slack/Notion/PRD/Plan/ADR/file), `search_entries` = 영구·큐레이션된 검색 단위(`/remember`, assistant 추출 결정/요약/todo/fix, source_documents 에서 chunking 된 항목), `search_summaries` = feature/global 요약 검색. 기존 대응은 `documents → source_documents`, `chunks_v2 → search_entries`, `summaries → search_summaries`, `chunk_entities → entry_entities` 이고 `memory_chunks` 는 제거(search_entries 로 흡수), `events_fts` 는 제거한다. `search_entries` 에는 nullable provenance 컬럼 `source_document_id`, `source_event_id`, `plan_key`, `feature_key` 와 `origin`(`manual_remember | assistant_extract | source_document`) 을 둔다. type 은 `raw_type` / `normalized_type` 2층을 유지하고, `importance` 는 별도 컬럼으로 승격하지 않고 `pinned` 와 `metadata_json.importance` 로 보존한다. drop/recreate 가 아니라 현재 도그푸딩 DB 를 새 스키마로 옮기는 one-shot migration 으로 진행한다.

**왜:** 2026-05-22 에 넣은 `memory_chunks → chunks_v2` bridge 가 실측에서 구조적 중복을 만들었다. memory 1건이 synthetic `documents` 1건 + `chunks_v2` 1건으로 승격되면서 같은 텍스트가 최대 5벌(`memory_chunks.text`, `documents.raw_text`, `chunks_v2.chunk_text`/`retrieval_text`, FTS 2벌)로 저장되고, `documents` 라는 "원본 문서" 테이블에 `memory_chunks:<id>` synthetic 문서가 잔뜩 섞여 의미가 깨졌다. `/search` 도 chunks_v2 primary + memory_chunks fallback 으로 같은 내용을 두 경로로 찾고 있었다. 통합하면 bridge·synthetic document·이중 FTS·fallback 이 한꺼번에 사라지고, `search_entries` 가 "검색 가능한 모든 단위의 단일 인덱스"라는 의도와 이름이 정확히 맞는다. `events_fts` 는 트리거로 유지만 되고 retrieval 어디서도 query 하지 않는 죽은 인덱스라 write 비용만 있어 제거한다.

**폐기된 대안:** (1) rename 만 하기 — 이름은 선명해지지만 1:1 bridge 중복을 그대로 둔 채 "source_documents" 이름의 테이블에 비-source memory 가 들어가는 모순을 박제한다. (2) 2계층 유지 + bridge 정직화(synthetic document 중단 + embedding 상시) — 중복은 줄지만 working/curated 구분이 결국 컬럼+필터로 남고 memory_chunks/search_entries 이중 write 가 유지된다. (3) `entry_links` 그래프 테이블 즉시 도입 — `derived_from` 은 `source_document_id` 컬럼, `supersedes` 는 기존 `supersedes_chunk_id`/version, `contradicts` 는 기존 `contradictions` 테이블과 겹쳐 지금은 N:M `implements` 수요가 실제로 생길 때까지 보류. (4) `importance` 컬럼 승격 — ranking 에 실제 반영 계획이 없으면 `events_fts` 같은 죽은 컬럼이 되므로 보류. 이 결정으로 2026-05-22 bridge 1차 구현과 2026-05-16 memory_chunks read-only fallback 은 폐기 대상이 된다.

**남은 점:** 아직 결정/스키마 작성 단계이고 구현은 착수 전이다. (1) `plan_key`/`feature_key` 는 자리만 두고, 무엇이 채울지(특히 `feature_key` 와 기존 `entities`/`ner.py` 의 통합 여부)는 별도 과제로 미정 — day-1 엔 대부분 NULL 임을 전제한다. (2) working overlay 를 `events` 에서 session_id 기준으로 뽑으면 기존 working mini-chunk 가 갖던 결정적 query rewrite surface 를 잃는다. raw prompt 만 쓸지, 검색 시점에 surface 를 재계산할지 미정. (3) `source_documents` 재수집(checksum 변경) 시 child `search_entries` 의 validity(`valid_from/valid_to/is_current/supersedes`) 캐리오버 정책 확정 필요. (4) one-shot migration 스크립트 작성. 구현 착수 전에 `flow.md` 에 새 스키마 초안을 먼저 적는다.

## 2026-05-24 — Soul 을 Guardrail 로 명칭 변경

**무엇:** 세션 시작 컨텍스트 파일의 사용자-facing 명칭을 `soul.md` 에서 `Guardrail.md` 로 바꿨다. `SessionStart` 는 이제 `<project>/.imprint/Guardrail.md` 를 우선 prepend 하고, `startup|resume|clear|compact` matcher 로 compact 이후에도 같은 Guardrail 을 다시 주입한다. 기존 프로젝트의 `.imprint/soul.md` 는 첫 seed 시 `.imprint/Guardrail.md` 로 1회 복사하되 legacy 파일은 자동 삭제하지 않는다. Guardrail default 에 민감정보 저장 금지 원칙을 넣고, LoadMap 에도 API key, OAuth token, 비밀번호, 인증 쿠키, 개인식별정보, 사내 기밀 원문은 memory 로 남기지 않는다는 원칙을 명시했다.

**왜:** `Soul` 은 persona 느낌이 강해 실제 역할인 안전 기준·운영 규칙·저장 금지 정책을 설명하기에 모호했다. `Guardrail` 은 모델이 세션 시작과 compact 이후 다시 참고해야 하는 기준선이라는 뜻이 명확하다. 기존 파일을 바로 삭제하거나 rename 만 강제하는 대안은 사용자 편집 파일을 잃을 수 있으므로, 복사 migration 과 legacy fallback 을 둔다.

## 2026-05-24 — setup vector 진행 로그와 실패 힌트 보강

**무엇:** `imprint setup vector` 가 `--status`, `--install`, `--warmup`, `--backfill` 단계마다 `[imprint setup] status 시작/완료`, `install 실패 ...` 같은 한국어 진행 로그를 stdout/stderr 와 `plugin.log` 에 남기도록 보강했다. 실패 시 단계별 힌트(`pip`/네트워크/PEP 668, HF Hub 인증·모델 cache, project id/backfill 확인)를 출력하고, 알 수 없는 옵션은 사용자가 입력한 오타를 그대로 저장하거나 무시하지 않고 에러와 로그로 남긴다. `TC-23` 으로 status 진행 로그와 오타 옵션 거부를 회귀 테스트에 추가했다.

**왜:** optional vector setup 은 Python site-packages 설치, HuggingFace 모델 다운로드, 기존 memory backfill 처럼 실패 지점이 많고 시간이 걸릴 수 있다. 사용자가 “멈춘 것인지, 설치 중인지, 어떤 단계에서 실패했는지”를 바로 알 수 있어야 setup 을 신뢰할 수 있다. 전체 설치를 자동 복구하는 대안은 사용자 Python 환경과 네트워크 정책을 과하게 건드리므로 보류하고, 현재는 진행 상태와 복구 단서가 명확히 보이는 UX 를 먼저 적용한다.

## 2026-05-23 — `/remember` 명시 저장 스킬 추가

**무엇:** `skills/remember/SKILL.md` 와 `scripts/imprint/remember.sh` 를 추가해 기존 `/memory remember` 저장 경로를 사용자-facing `/remember` 로 노출했다. Codex 설치 wrapper 에도 `imprint remember` subcommand 를 추가했고, plugin keyword/default prompt 와 사용 문서를 `/remember` 기준으로 보강했다. `/remember` 는 새 저장소를 만들지 않고 `memory_chunks` 에 저장한 뒤 기존 bridge 를 통해 `chunks_v2` 검색 후보로 승격한다. public 중요도 플래그는 `--require` / `--high` / `--middle` / `--low` 로 두고 기본값은 `middle` 이며, metadata 의 `importance` 로 보존한다. 알 수 없는 `--옵션` 은 텍스트로 저장하지 않고 에러와 plugin log 를 남긴다.

**왜:** imprint 의 사용 핵심은 "이 결정/맥락을 다음 세션에서도 찾아줘"라는 명시 저장 행위다. `/memory remember` 는 기능적으로 맞지만 사용자가 매번 namespace 를 기억해야 하므로, `/search` 와 같은 수준의 짧은 진입점이 더 자연스럽다. 별도 `remember` SQLite 테이블을 만드는 대안은 이름은 선명하지만 pin/forget/search/bridge/redaction 로직을 이중화하므로 보류했다. 현재는 `remember` 를 public verb 로 두고, 저장 canonical table 은 `memory_chunks` 로 유지한다.

## 2026-05-23 — `/search` skill 로 벡터 검색 사용자 진입점 추가

**무엇:** `skills/search/SKILL.md` 와 `scripts/imprint/search.sh` 를 추가해 기존 hybrid retrieval 엔진을 사용자-facing `/search` 스킬로 노출했다. Codex 설치 wrapper 에도 `imprint search` subcommand 를 추가했고, plugin manifest keyword/default prompt 와 README/INSTALL/HANDOFF/LoadMap 문서를 `/search` 명칭 기준으로 정리했다. 내부 `retrieve.sh`/`retrieval.cli` 는 호환성을 위해 유지하고, `search.sh` 가 그 엔진을 얇게 호출한다.

**왜:** imprint 의 핵심 목적은 세션 종료 뒤 구현 의도와 히스토리를 자연어로 다시 떠올리는 것이다. `memory_chunks → chunks_v2` bridge 와 optional embedding 이 준비돼도, 사용자가 실제로 벡터/hybrid 검색을 호출할 슬래시 스킬이 없으면 목적까지 닿지 못한다. 단순히 기존 `/retrieve` 문서명을 스킬로 만드는 대안도 있었지만, 사용자 입장에서는 “검색한다”는 행위가 더 직접적이고 `/memory search` 와 대비하기 쉽다. 따라서 내부 구현명은 보존하고 공개 진입점만 `/search` 로 잡았다.

**추가 조정:** `/search` 는 기본적으로 routed 검색을 수행하도록 바꿨다. 사용자가 매번 `--routed` 를 붙이는 것은 제품 의도와 맞지 않고, “검색”이라고 말하면 local/feature/global 범위를 시스템이 판단하는 것이 자연스럽다. 초기 사용자-facing dispatcher 는 옵션 없이 query 만 받게 단순화했다. 추후 필요하면 `local` 같은 키워드나 detail/debug 모드를 별도 UX 로 붙인다.

## 2026-05-22 — 0.1.1 release metadata 동기화

**무엇:** bridge/search-v2 연동과 vector setup dispatcher 가 `main`에 병합된 뒤 plugin release metadata 를 `0.1.1` 로 올렸다. `VERSION`, root/Codex/Claude plugin manifest, Claude marketplace, Codex marketplace ref 를 같은 버전으로 맞추고 설치 문서의 release 예시도 `0.1.1` 기준으로 갱신했다.

**왜:** `0.1.1` 은 첫 공개 설치 기준인 `0.1.0` 이후 persistent memory 를 `chunks_v2` 검색 후보로 연결하고, optional vector 의존성 설치/모델 warmup/backfill 을 setup skill 로 제공하는 첫 patch release 다. manifest 와 marketplace ref 가 엇갈리면 Claude Code/Codex 설치 경로별로 서로 다른 코드를 받게 되므로 release tag 생성 전 metadata 를 한 번에 동기화한다.

## 2026-05-22 — vector setup skill/dispatcher 추가 및 로컬 벡터 환경 검증

**무엇:** `imprint setup vector` dispatcher 와 `setup` skill 을 추가했다. `--status` 는 `sqlite-vec`/`sentence-transformers`/`transformers` import 가능 여부를 가볍게 확인하고, `--install --warmup --backfill` 은 선택 의존성 설치, BGE-M3 warmup, 현재 프로젝트 memory embedding backfill 을 한 번에 수행한다. Codex 설치 스크립트는 `memory` 하나만 링크하지 않고 `skills/` 아래 모든 skill 을 `~/.codex/skills` 로 연결하도록 바꿨고, `imprint` wrapper 에 `setup` subcommand 를 추가했다. 로컬 사용자 환경에서는 `requirements-optional.txt` 설치, BGE-M3 4096-byte embedding 생성, 임시 DB vector retrieve(`embedding_used=true`) 까지 확인했다.

**왜:** plugin 설치만으로 RAG 경험이 완성되는 서드파티와 달리, imprint 는 API key 없는 로컬 우선 설계라 semantic vector 를 쓰려면 Python optional deps, 모델 cache, 기존 memory backfill 이 필요하다. 이 절차를 문서로만 두면 사용자가 `<project_id>`/pip/환경 변수 순서를 직접 기억해야 한다. 별도 원격 embedding API 를 기본값으로 넣는 대안은 과금·키 관리·네트워크 의존이 생기고, plugin 에 torch/model 을 vendoring 하는 대안은 크기와 OS 호환성 부담이 크다. 따라서 현 단계에서는 얇은 setup dispatcher 로 설치 UX 를 모으는 것이 가장 단순하다.

**남은 점:** `IMPRINT_MEMORY_BRIDGE_EMBEDDING=1` 을 기본값으로 켤지는 아직 결정하지 않았다. 모델 cold-load 가 hook latency 를 늘릴 수 있으므로, setup 은 backfill 과 warmup 을 지원하되 자동 embedding 상시 활성화는 사용자 opt-in 으로 둔다. HF Hub 인증 토큰(`HF_TOKEN`) 안내, 실패 재시도, Claude Code 설치 동기화 UX 는 실사용 피드백 뒤 보강한다.

## 2026-05-22 — `memory_chunks → chunks_v2` bridge 1차 구현

**무엇:** persistent `memory_chunks` 를 synthetic `documents`/`chunks_v2` row 로 승격하는 bridge 를 추가했다. Stop extract, external lazy-fetch, `/memory remember` 로 저장되는 비-working memory 는 `chunks_v2` 후보로도 보이며, 기존 row 는 `python3 -m retrieval.cli bridge-memory <project_id> --all [--embed] [limit]` 로 backfill 할 수 있다. `source_status` marker 와 working raw turn 은 context section 분리 원칙에 따라 bridge 대상에서 제외한다. `chunks_v2.metadata_json` 을 추가해 원본 `memory_chunks.id`, `source_event_id`, `chunk_type`, `source_type`, `evidence_level`, `text_hash` 를 보존하고 retrieve JSON 후보에도 provenance 를 노출한다.

**왜:** imprint 생성 목적은 세션이 끝난 뒤 구현 의도와 히스토리를 자연어로 다시 떠올리는 것이다. 2026-05-21 실측에서 자동 저장 memory 가 retrieval v2 와 분리되어 있어, 임베딩을 설치해도 핵심 memory 가 vector/search-v2 후보가 되지 않는 구조적 갭이 확인됐다. `memory_chunks` 자체에 embedding 컬럼을 붙이는 대안은 빠르지만 저장소 이중화가 계속 커진다. 반대로 bridge 는 기존 `chunks_v2` FTS/vector/retrieve/metadata 경로를 재사용하고, migration 안정화 기간 동안 legacy `memory_chunks` fallback 도 그대로 남길 수 있어 가장 작게 목적과 정렬된다.

**남은 점:** 기본 자동 bridge 는 hook latency 와 의존성 cold-load 를 피하기 위해 embedding 생성을 켜지 않는다. 의미 검색 품질 검증은 `sentence-transformers` 설치 후 `bridge-memory --all --embed` 또는 `IMPRINT_MEMORY_BRIDGE_EMBEDDING=1` 로 embedding 을 채운 상태에서 별도로 측정한다. bridge row 를 summary/entity/contradiction queue 에 자동 연결할지는 profile 과 eval 결과를 본 뒤 결정한다.

## 2026-05-16 — `/retrieve` memory_chunks read-only fallback 적용

**무엇:** `/retrieve` 의 문서 retrieval 결과가 0개일 때 `memory_chunks` 를 read-only fallback 으로 조회하도록 연결했다. 기본 경로는 그대로 `chunks_v2`/`summaries` 우선이며, fallback 은 `source_status` marker 를 제외하고 `decision/spec/message/thread/...` 같은 실제 memory chunk 만 후보로 만든다. `TC-14 Retrieve memory_chunks fallback` 으로 direct `/retrieve` 와 routed `/retrieve --routed` 모두에서 자동 hook·`/memory remember` 계열 기억이 보이는지 고정했다.

**왜:** 실제 프로젝트 사용성 테스트에 들어가기 전, “자동 hook 이 저장한 기억을 다음 turn prefill 뿐 아니라 명시 조회에서도 확인할 수 있는가”가 먼저 필요했다. `memory_chunks → chunks_v2` bridge 는 복제·dedup·versioning 정책까지 같이 건드리므로 아직 무겁다. 빈 결과일 때만 fallback 하는 방식은 기존 문서 retrieval 품질을 건드리지 않으면서 기본 RAG 신뢰성을 빠르게 올린다.

**남은 점:** fallback 은 수렴을 위한 최소 연결이며, `chunks_v2` 의 entity grounding·summary link·contradiction scan 품질을 `memory_chunks` 에 그대로 제공하지는 않는다. 실제 사용성 테스트에서 memory fallback 이 자주 주 경로가 되면 bridge 또는 unified storage 를 다시 검토한다.

## 2026-05-16 — RAG 운영 관찰성 1차 적용: source status, noise flag, profile summary

**무엇:** RAG 기본 동작 안정화의 남은 관찰성 항목을 1차 적용. Slack/Notion lazy-fetch 에서 URL cap 초과는 `skipped_by_cap`, explicit URL 실패는 `fetch_failed`, keyword 결과 없음은 `fetch_empty` 로 `source_status` marker chunk 를 남긴다. `/memory list` 는 `ok/stale/fetch_failed/skipped_by_cap` 상태 컬럼을 표시하고, `/memory show --json` 은 계산된 `source_status` 를 반환한다. `events` 테이블에 `noise INTEGER DEFAULT 0` 을 추가하고, `UserPromptSubmit` 에서 짧은 backchannel prompt 를 `noise=1` 로 표식한다. `/memory profile` 은 `IMPRINT_PROFILE=1` 로 누적된 `profile.jsonl` 의 stage 별 p50/p95/max latency 와 payload bytes 를 요약한다.

**왜:** 외부 문서 기반 RAG는 “무엇을 못 가져왔는지”, “지금 보는 기억이 낡았는지”가 보여야 사용자가 답변 근거를 신뢰할 수 있다. 자동 refresh 는 트래픽과 stale 판단 정책이 필요하므로 보류하고, 먼저 관찰 가능한 상태 marker 를 남긴다. Noise turn 은 삭제하지 않고 표식만 붙여 raw 보존 철학을 유지하면서 나중에 감쇠/삭제 정책을 측정 기반으로 결정할 수 있게 한다. Latency/threshold/daemon 분리는 추정으로 고치기보다 `/memory profile` 로 1주 데이터를 본 뒤 판단한다.

**남은 점:** `source_status` marker 가 너무 많이 쌓이면 TTL 또는 dedupe 정책을 추가한다. `events.noise` 는 user_message 에만 붙이며 assistant response 중요도 평가는 보류한다. `/memory profile` 은 요약만 제공하고 자동 튜닝은 하지 않는다.

## 2026-05-16 — RAG 기본 기능 1차 안정화: redaction, hook loop, 읽기 경로, 검색 fixture

**무엇:** RAG 기본 동작 안정화 우선순위 1~4를 1차 적용. `user-prompt-submit.sh` 는 user prompt를 `events`에 저장하기 전 redaction 하고, lazy-fetch/prefill 입력도 redacted text를 사용한다. `stop.sh` 는 마지막 assistant 응답을 `events.llm_response`에 저장하기 전 redaction 하고, response extract worker에도 redacted text를 넘긴다. `ingestion.py` 는 external source chunk/text/metadata 와 extracted response chunk를 `memory_chunks`에 INSERT 하기 직전 Python 쪽 redaction을 한 번 더 적용한다. `/memory remember` 도 secret-shaped text를 기본 redaction 하며, default 룰셋에 fine-grained GitHub PAT, bearer/authorization, password assignment, 주민등록번호, card-like 패턴을 추가했다. 테스트에는 `TC-11 Hook memory loop + redaction`, `TC-12 Memory search/list/inject fixture` 를 추가해 자동 hook 루프와 기본 `/memory` 검색 경로를 고정했다.

**왜:** 실제 프로젝트에서 RAG를 쓰려면 기능 수보다 “안전하게 저장되고, 다음 turn에 다시 보이며, 사용자가 근거로 꺼내볼 수 있음”이 먼저다. Redaction 누락은 DB/FTS raw 누출로 바로 이어져 사용 불가 리스크가 가장 크다. Hook loop smoke test는 `SessionStart → UserPromptSubmit → Stop → 다음 UserPromptSubmit` 생명선을 직접 검증한다. 읽기 경로는 단기적으로 기본 사용자 RAG와 `/memory search/inject` 로 명확히 하고, 별도 `chunks_v2`/`summaries` 문서 retrieval 경로는 분리해 유지한다. 검색 품질 fixture는 decision/fix/todo/note/spec/message/thread, pinned 우선순위, type/source 필터, inject 출력을 고정해 “저장됐는데 못 찾는” 회귀를 먼저 잡기 위함이다.

**남은 점:** `memory_chunks → chunks_v2` bridge 또는 `/retrieve` legacy fallback 은 아직 중기 과제다. 과거에 이미 raw 로 저장된 row 청소는 사용자 승인 액션으로 분리한다. Credit-card-like 정규식은 단순 패턴이라 false positive 가능성이 있어, 필요하면 Luhn callback 기반 redaction helper 로 고도화한다.

**추가 실측 반영:** 실제 `claude -p haiku` 검증에서 Stop extract 가 한국어 응답을 영어 chunk text 로 번역하는 사례가 있어 extract prompt 에 원문 언어 보존 지시를 추가했다. 같은 검증에서 `/memory search "버튼"` 이 FTS5 trigram 의 2자 한글 토큰 제약으로 빈 결과가 되는 것이 확인되어, FTS 결과가 없을 때만 짧은 토큰 `LIKE` fallback 을 타도록 보강했다. `TC-12` 는 이 fallback 을 회귀 검증한다.

## 2026-05-16 — 완료 단계 기록 이관: Phase 1~4.5, 7a/7b, NER, ML opt-in

**무엇:** `HANDOFF.md` 와 `LoadMap.md` 에 남아 있던 완료 단계 요약을 본 결정 사유 로그로 이관. 완료로 분류한 항목은 Phase 1(SQLite memory 저장소 + FTS5 trigram), Phase 2(SessionStart/UserPromptSubmit/Stop hook 통합), Phase 3(`/memory` skill: search/remember/pin/list/stats/forget/refresh/inject), Phase 4.5(Slack/Notion lazy fetch + `sources.json`), Phase 7a(chunk-level hybrid retrieval: SQLite/FTS5/sqlite-vec, BGE-M3 opt-in, contextual prefix, entity alias canonicalization, versioning, RRF + conditional rerank, single-writer ingest queue), Phase 7b(project-level interpretation: feature/document/project summaries, rule-based scope classifier, grounding drill-down, contradiction detection), chunk_entities 자동 NER, ML 의존성 opt-in(`requirements-optional.txt`, `IMPRINT_MODEL_CACHE_DIR`, FTS-only + LLM judge fallback) 이다.

**왜:** `HANDOFF.md` 는 다음 세션에서 바로 집을 미완료 작업과 검증 안건만 담아야 하고, `LoadMap.md` 는 앞으로의 방향과 우선순위를 보여줘야 한다. 완료된 기능 목록이 두 문서에 남아 있으면 “다음에 무엇을 해야 하는가”가 흐려지고, 특히 현재 목표인 “실제 프로젝트에서 RAG가 기본 기능으로 저장·검색·참조되는지 검증”보다 workflow skill 같은 기능 확장이 먼저 보이는 문제가 있었다. 완료 사실과 결정 배경은 `HISTORY.md` 에 보존하고, 진행 문서는 RAG 기본 동작 안정화 중심으로 재정렬한다.

**참고:** Phase 7a/7b 의 세부 결정 사유는 아래 2026-05-10 항목들에 이미 상세 기록되어 있다. 본 항목은 문서 책임을 정리하기 위한 완료 목록 이관 기록이다.

## 2026-05-10 — Phase 7b 우선순위 11 완료: NLI primary + LLM judge fallback chain

**무엇:** Phase 7b 명세 우선순위 11번 (NLI / LLM judge 연결 + timeout 500 ms + 3구간 분기) 의 결정적 부분을 채움. 판정 파이프라인을 `_judge_pair(a_text, b_text)` 단일 진입점으로 통일하고 fallback chain 명시: (1) NLI 시도 (transformers 가용 시, 500 ms timeout). (2) NLI high confidence(≥0.8 또는 <0.4 — 양 극단) 면 그대로 채택. (3) NLI mid 영역(0.4~0.6) 또는 NLI 미가용/timeout 이면 LLM judge (claude CLI haiku, 30 s timeout) 호출. (4) NLI/LLM 둘 다 실패하면 rule 약 신호(score=0.5) + `needs_retry=True` 로 status=candidate 강제 — 다음 scan 배치가 가용 환경에서 재판정. confirmed/dismissed 가 이미 있는 chunk pair 는 사용자 결정 보호로 덮지 않음.

**왜:** 명세는 "NLI primary, 실패/low confidence 시 LLM judge fallback, 둘 다 timeout 시 status=candidate 재시도" 라는 3계층을 그렸는데, 구현 초안은 NLI 미가용 시 곧장 rule 로 떨어져 LLM judge 가 빠진 상태였음. 그래서 transformers 미설치 환경에서도 사실상 결정 품질이 작동해야 한다 — claude OAuth 구독은 항상 가용한 자원이므로 LLM judge 가 NLI 빈자리를 메우는 것이 정체성("로컬 단일 파일 + OAuth 친화") 과 정합. 실측 RTT 측정 결과 claude haiku 가 11~28 s 라 LLM_JUDGE_TIMEOUT_MS 기본값을 30 s 로 설정 (NLI 의 500 ms 와 분리 — NLI 는 동기 경로 가능, LLM 은 BG side 전제). LLM judge 응답이 verdict / score / reason 의 JSON 한 줄을 반환하도록 명시 프롬프트 + verdict-score 정합성 클램프 (모델이 "neutral" 라며 0.9 주는 등 모순 시 verdict 우선) 로 안정화.

**폐기한 대안:**
- **LLM judge 를 sonnet/opus** — RTT 가 30 s 를 넘겨 BG queue 처리 시간 폭주. haiku 가 한국어 짧은 결정문 판정에 충분.
- **rule fallback 시 status=neutral 그대로 저장** — 이게 명세 위반. NLI/LLM 가용 환경에서 재판정 트리거가 안 일어나 영구 미판정 상태로 굳어짐. needs_retry=True → status=candidate 가 명세의 "다음 배치에서 재시도" 의 정확한 구현.
- **mid 영역 LLM 보강 생략** — NLI 결과를 그대로 쓰면 mid 영역(0.4~0.6) 이 모두 neutral 로 떨어져 false negative 가 누적. LLM 정밀 판정으로 그 구간을 분리.
- **LLM_REFINE 범위를 0.3~0.7 로 넓히기** — LLM 호출 빈도가 늘어 BG queue 부담. 0.4~0.6 이 NLI 가 "애매"한 진짜 mid 구간으로 충분.

**참고 매핑:** 다이어그램 `J6 → CDCAND → CDJUDGE → CDCONF` 의 CDJUDGE 가 `_judge_pair` 에 해당. CDCONF score 3구간 분기는 `_classify_status` 가 high → candidate, mid·low → neutral 로 처리 (자동 dismiss 금지 원칙 유지). 실측 검증: 충돌(0.95→candidate), 같은 방향(0.1→neutral), 무관(0.5→neutral) 3 시나리오 모두 정확.

## 2026-05-10 — Phase 7b 후속 결정 4건 락인 (NLI 모델 · scope classifier · summary 갱신 빈도 · contradiction 임계)

**무엇:** Phase 7b (계층 요약 + 충돌 감지) 진입 직전, HANDOFF.md 후속 결정 4건을 한 라운드에 확정. (7b-1) NLI = **mDeBERTa-v3-base-mnli-xnli** (다국어, 한국어 포함, 약 280M 파라미터) — `xlm-roberta-large-xnli` 는 더 무겁고 한국어 fine-tune 차이 크지 않음, `klue/roberta-base` 는 NLI head 없어 전이학습 부담. (7b-2) Scope classifier = **rule-based 우선** + 명세 시드 그대로: `전체|전반|프로젝트|정리|흐름 전체` → global, `기능|플로우|과정|UX|시나리오` → feature, 그 외 + entity 매칭 + ≤ 30 자 → local. fallback 순서 local→feature→global. (7b-3) Summary 갱신 빈도 = **즉시 sync(commit-trigger 기반 incremental)** + 명시 호출 가능. 매 turn 재생성 X — `J5` 가 W1 commit 분석 결과 변경 감지 시에만 enqueue. (7b-4) Contradiction 3구간 임계 = 명세 예시값 그대로 시작 — `≥ 0.8 → candidate`, `0.4~0.8 → neutral`, `< 0.4 → neutral`. 자동 dismiss 금지 (false negative 영구 손실 방지). 임계는 NLI 모델 첫 100~200 쌍 측정 후 캘리브레이션.

**왜:** 7b 도 7a 와 동일하게 "1차 구현 진입을 막지 않는 합리적 기본값" 이 핵심. mDeBERTa-v3 는 NLI 벤치마크 한국어 성능이 안정적이고 메모리 부담(약 1GB)이 cross-encoder 와 비슷해 daemon 모드에서 병렬 운영 가능. rule-based scope classifier 는 LLM 호출 추가 없이 동기 경로 budget(~10 ms) 안에 동작, 명세 시드 키워드만으로 90% 케이스 커버. 즉시 sync 전략은 "사용자가 새 정책을 commit 한 다음 turn 부터 새 답변" 이라는 일관성 보장 — 5분 배치는 그 사이에 잘못된 답이 나갈 위험. 충돌 임계 0.8/0.4 는 NLI 통상 분포의 타당한 분할이고, 정확한 값은 측정 데이터 없이는 결정 불가라 명세 예시 그대로 시작.

**폐기한 대안:**
- **7b-1 — `xlm-roberta-large-xnli`** — 정확도는 살짝 ↑ 이지만 모델 크기 2배(560M) 로 메모리·로드 시간 부담. mDeBERTa-v3 가 한국어 NLI 에 보통 동등 이상 성능.
- **7b-1 — `klue/roberta-base` + NLI fine-tune** — 한국어 단일 fine-tune 으로 정확도 ↑ 이지만 영어/혼합 코드 컨텍스트(stack trace, command output)에 취약. retrieval 의 다국어 robustness 우선.
- **7b-2 — LLM 분류기 우선** — 정확도 ↑ 이지만 동기 경로 budget 위반 위험 + claude OAuth 호출 비용. rule-based 가 의도적으로 fallback 인 이유는 명세에서 이미 결정.
- **7b-3 — 5분 배치 / 매시간 배치** — 첫 구현엔 트래픽 측정 데이터 없어 배치 간격 정당화 어려움. incremental commit-trigger 가 "변경 없으면 J5 spawn 도 안 함" 으로 유휴 비용 0. 트래픽이 보이면 그때 배치 도입.
- **7b-4 — 자동 dismiss 활성화** — high score 가 아니면 dismiss 로 영구 정리하면 contradiction 추적이 끊김. neutral 보존이 false negative 영구 손실 방지.

**참고:** 4건 모두 첫 구현 머지 후 측정 인프라 위에서 재평가. 가장 휘발성 높은 항목은 (7b-1) NLI 모델 정확도, (7b-4) 임계치. (7b-3) 즉시 sync 는 트래픽 측정 결과로 배치 도입 여부만 결정.

## 2026-05-10 — Phase 7a 후속 결정 7건 락인 (임베딩 모델 · chunk_type 매핑 · supersedes 트리거 · 함수 시그니처 · warm cache · rerank cache · ingest queue)

**무엇:** 스키마 v1 진입 직전, HANDOFF.md 후속 결정 7건을 한 라운드에 확정. (2-1) 임베딩 = **BGE-M3 1024 dim**. (3-1) `raw_chunk_type → normalized_chunk_type` 매핑표 = `decision/fix → decision`, `todo/spec → requirement`, `error/test_result/summary/note/message/thread → discussion`, `command/code_context → code_note`. (5-1) supersedes 자동 제안 = **정규식 트리거 1단계** (한국어 "변경한다 / 대체한다 / 폐기 / 취소 / 업데이트 / 이제는 / 롤백" + 영어 "supersede / replace / deprecate / cancel / now use / rollback") — 매칭 시 후보 제시만, 자동 적용 X. (6-1) 함수 시그니처 = **Python module** (`imprint.retrieval.retrieve(query, project_id, top_k) -> RetrievalResult`). inline / daemon 모두 같은 import, daemon 은 RPC 위임. (7a-7) warm cache = **lazy spawn** (첫 query 시 cold-load, 이후 keep alive, `IMPRINT_WARM_CACHE=always` 로 강제 always-on 옵션). (7a-8) rerank cache key = `sha256(query_normalized + sorted(candidate_ids) + project_id)`, **세션 단위 TTL · 메모리 LRU 64개 · 영속 X**. (7a-9) ingest queue = **SQLite append-only 테이블 + polling worker** (`ingest_queue (id, project_id, payload_json, status, created_at, claimed_at, completed_at)`). inline 모드는 hook 종료 직전 직접 drain.

**왜:** 7건 모두 결정 자체보다 "1차 구현 진입을 막지 않는 합리적 기본값" 이 핵심. 각 항목이 latency / 정확도 / 운영 부담 사이의 tradeoff 인데, 정확한 답은 측정 데이터가 쌓여야 보임. 따라서 "되돌리기 쉬운 가장 단순한 선택" 으로 통일. 임베딩은 BGE-M3 가 한국어 PRD/Slack 에 강하고 1024 차원이 sqlite-vec blob 비용 대비 합리. 매핑표는 "결정으로 볼지 토의로 볼지" 의 기준에 정렬 (fix 는 결정, summary 는 토의 맥락). supersedes 정규식은 false negative 가 쌓일 때 LLM 분류기로 escape hatch 가 열려 있음. Python module 시그니처는 ingestion.py 가 이미 Python 이라 자연스럽고 daemon 도입 시 RPC adapter 만 추가. warm cache lazy spawn 은 사용자가 retrieval 을 안 쓰면 비용 0. rerank cache 는 LRU 64 가 일반 세션의 같은 query 반복을 충분히 흡수, 영속화는 측정 후. ingest queue SQLite 테이블은 단일 파일 정체성과 정합 + polling worker 가 inline / daemon 양쪽 모드를 동일 인터페이스로 운영 가능.

**폐기한 대안:**
- **multilingual-e5-large 1024** — BGE-M3 와 성능 비슷하지만 한국어 기술 문서·Slack 짧은 발화에 BGE-M3 토큰화가 더 안정적. 차원 동일이라 schema 영향 없음 — 임베딩 worker 만 모델 swap 가능하게 추상화.
- **BGE-ko-small 384 dim** — 한국어 단일 fine-tune 으로 정확도는 좋지만 영어/혼합 코드 컨텍스트(stack trace, command output)에 약함. 다국어 retrieval 의 robustness 우선.
- **chunk_type 매핑 — fix → discussion** — fix 는 "왜 이렇게 결정했는가" 의 결과라 decision 쪽이 retrieval boost 정합. summary 는 정반대로 "토의 산출물 요약" 이라 discussion.
- **supersedes LLM 분류기 우선** — Phase 7a 에서 OAuth 호출 추가는 동기 경로 위반 위험. 정규식은 false negative 가 일부 있어도 사용자 명시(결정 #5)가 backup. LLM 은 후속 단계에서 패턴 누수 측정 후 도입.
- **함수 시그니처 — shell command / RPC standard 우선** — Python module 이 가장 마찰 적음. shell wrapper 는 hook 호출 측에 얇게 추가 (`scripts/imprint/retrieve.sh`), RPC 는 daemon 도입 시 같은 시그니처로 wrap.
- **warm cache always-on (SessionStart spawn)** — 사용자가 retrieval 을 안 쓰는 세션 (단순 메모 작성 / HUD 만) 에서 모델 메모리 점유 비용. 명시적 opt-in (`IMPRINT_WARM_CACHE=always`) 으로 보존.
- **rerank cache 영속 (SQLite 테이블)** — TTL 정책·invalidation 복잡도. 같은 query 가 세션 넘어 반복되는 빈도가 측정되기 전엔 LRU 메모리로 충분.
- **ingest queue Unix socket / mmap ring** — 더 빠르지만 POSIX/플랫폼 fragility. SQLite 테이블 polling 이 ms 수준 budget 안에 들어오면 그대로 유지, latency 위반 누적 시에만 escape hatch.

**참고:** 7건 모두 schema v1 머지 후 측정 인프라(IMPRINT_PROFILE=1) 위에서 6개월 안에 재평가 대상. 가장 휘발성 높은 항목은 (2-1) 임베딩 모델 (정확도 측정 후 swap), (7a-8) rerank cache TTL/사이즈 (실제 hit rate 보고).

## 2026-05-10 — Phase 7a 7개 결정 (스택 · 임베딩 · chunk_type · alias · supersedes · hosting · rerank)

**무엇:** Phase 7a (chunk + hybrid retrieval + entity + versioning) 진입 전 7개 결정 확정. (1) Storage = SQLite + FTS5 + sqlite-vec, (2) Embedding = 로컬 multilingual (multilingual-e5 또는 BGE 계열), (3) chunk_type = 기존 9+3 유지 + normalized 4-category 컬럼 이중 계층, (4) Entity alias = 자동 추출 + review queue, (5) Supersedes = 사용자 명시 기본 + 자동 제안 보조, (6) Hosting = inline-first + daemon-ready abstraction, (7) Rerank = 로컬 cross-encoder first + Cohere 옵션 + Claude judge 실험. 동시에 LoadMap.md 의 Phase 7 을 7a (chunk-level) / 7b (project-level graph: hierarchical summary · contradiction detection · entity-relation graph) 로 분리.

**왜:** 7개 항목의 공통 축은 "**로컬 단일 파일 + OAuth 친화 + 점진 진화**" 라는 imprint 정체성을 일관되게 관통한다는 점. PostgreSQL · 외부 임베딩 API · 외부 reranker · 완전 자동 alias / supersede 같은 옵션은 각각 기능적으로 좋아도 "별도 데몬 / 별도 API key / 외부 정책 의존 / 오탐의 retrieval 오염" 중 하나에 걸려, 한 군데 무너지면 나머지 결정도 같이 흔들린다. 반대 방향(로컬·OAuth 친화·반자동·이중 계층) 으로 전부 묶으면 정체성이 한 사이클 안에 일관되게 유지되고 다음 진화 경로(PostgreSQL migration / 외부 reranker 옵션 / Phase 7b 자동화) 가 모두 열린 채 남는다.

**폐기한 대안:**
- **PostgreSQL + pgvector + FTS** — 운영 단순성↑이지만 별도 데몬·설치·마이그레이션·백업·배포가 plugin 정체성과 충돌. 기능 한계(동시성·확장성)가 실제로 보이는 시점에 migration path 만 남겨둠.
- **외부 임베딩 API (OpenAI / Voyage / Cohere) 우선** — 별도 API key 의존이 OAuth 구독 정체성과 충돌하고, 다중 사용자/제품 성격으로 갈 때 키 관리·과금이 추가 부담. 차원 수(1536 등) 도 모델에 종속되므로 모델 결정이 schema 보다 선행.
- **chunk_type 4개로 일괄 마이그레이션** — 현 9+3 enum 이 검색·필터·UI 디버그 신호로 이미 의미가 있어 버리면 손실. `raw_chunk_type` 유지 + `normalized_chunk_type` 추가의 이중 계층화로 호환과 단순화 양립.
- **entity alias 완전 자동 link** — UI 요소 alias 의미가 프로젝트마다 달라("디버그 토글" 이 한 화면에선 같은 entity 지만 다른 화면에선 다를 수 있음) 오탐이 retrieval 전체를 영구 오염시킴. review queue 로 점진 학습.
- **supersedes 완전 자동 (동일 entity + 동일 section → 자동 supersede)** — 보완 설명을 폐기로 오인할 위험. 자동 detection 은 contradiction detection 영역이라 Phase 7b 로 연기.
- **Cohere rerank-3 / Claude haiku as judge 우선** — 비용·정책 리스크 + 외부 의존. 핵심 retrieval 파이프라인의 rerank 를 외부에 묶지 않고 로컬 cross-encoder 로 시작, Cohere 는 옵션, Claude judge 는 실험 기능으로 격하.
- **Retrieval API 완전 데몬 (`imprintd`)** — 설치·운영 부담. 반대로 완전 인라인은 기능이 늘수록 hook/skill 코드가 비대화. inline-first + 동일 함수 시그니처로 추상화해 두고 배포 형태만 늦게 결정하는 하이브리드.

**남은 후속 결정 (Phase 7a 구현 진입 전 좁힘):** (2-1) multilingual-e5 vs BGE 정확한 모델·차원 — schema `embedding vector(N)` 확정용. (3-1) `raw_chunk_type → normalized_chunk_type` 매핑표 — 9+3 → 4 의 결정표. (5-1) supersedes 자동 제안의 트리거 패턴 — 정규식("변경 / 대체 / 폐기") vs LLM 분류기. (6-1) inline / daemon backend 의 공통 함수 시그니처. 본 결정과 별개로 짧은 라운드 1회씩에서 좁힐 수 있는 분량이라 별도 항목으로 분리.

**참고 자료 매핑:** Anthropic contextual retrieval (Phase 7a context_prefix + retrieval_text 이중 표현), RAPTOR (Phase 7b hierarchical summary 의 직접 참고), MemoryBank (TTL · stale 정책), CoALA (chunk_type 의 working / episodic / semantic / procedural 매핑). HippoRAG / GraphRAG / 풀 knowledge graph 는 영구 deferred — Phase 7b 가 "그래프 DB 도입" 이 아니라 "RAPTOR 형 경량 계층 요약 + contradiction awareness" 로 결정.

## 2026-05-09 — Advisor skill 완전 제거

**무엇:** `scripts/imprint/advisor.sh`, `skills/advisor/SKILL.md`, `provider_runs` 테이블 정의(`schema.sql`), plugin manifest의 advisor/ccg keyword·tag·description 흔적을 모두 삭제. 같은 날 직전 커밋(`e2c75f1`)에서 추가했던 advisor timeout wrapping(`IMPRINT_ADVISOR_TIMEOUT`·`with_timeout`·`gtimeout` 폴백)도 함께 제거됨.

**왜:** advisor(`/advisor codex/gemini/ccg`)는 본인 워크플로에서 거의 호출되지 않는다. 코드(dispatcher 211줄, SKILL 77줄)와 schema(`provider_runs` 테이블)·plugin manifest 키워드·운영 환경 변수를 유지하는 비용이 거의-안-쓰이는 기능의 가치를 넘어선다. 이번 세션 내에 timeout wrapping까지 박은 직후라 상태가 깨끗할 때 통째로 제거하는 게 나중에 부분 제거하는 것보다 훨씬 작업이 단순.

**폐기한 대안:**
- 코드는 두고 plugin manifest의 keyword에서만 빼기 — dead code가 남으면 다음 세션에서 또 결정해야 함. 한 번에 정리.
- `provider_runs` 테이블에 `DROP TABLE` 추가 — 기존 사용자 DB의 row를 지우는 건 부작용이 큼. `CREATE TABLE IF NOT EXISTS`만 빼서 새 사용자에게는 안 깔리고, 기존 row는 그대로 둠.
- workflow skill(Phase 5)이 `claude -p` 합성을 쓸 때 advisor를 다시 살리는 옵션 — Phase 5는 단일 LLM 호출만으로 충분(memory + git porcelain 합성). multi-provider 합성을 다시 만들 때가 오면 그때 처음부터 다시.

## 2026-05-09 — Phase 3 마무리: redaction · `memory list` 필터

**무엇:** (1) `common.sh`에 `redact_text()` + `lib/redact-rules.default.json`(7개 룰: API key/PAT/JWT/AWS/private key block) 추가, `memory.sh remember --redact` 플래그로 INSERT 직전 마스킹. (2) `memory list`에 `--since <YYYY-MM-DD>`, `--limit <n>`, `--project <path|id-prefix>` 추가.

**왜:**
- Redaction은 `LoadMap.md` 위험요소 #1(민감정보 저장)의 직접 대응. 룰셋 파일을 외부로 빼서 사용자가 추가 룰을 정의할 수 있게 함 — 사내 토큰 패턴은 조직마다 달라서 plugin이 결정할 수 없음.
- `--limit`은 정수 검증으로 hardcoded 50 폴백, `--project`는 절대경로면 sha256 변환·아니면 prefix LIKE — path를 쓸 때 즉시 식별, prefix는 stats 출력에서 본 짧은 id를 그대로 붙여넣을 수 있게.

**폐기한 대안:**
- Redaction을 `EXTRACT_PROMPT`/`UserPromptSubmit hook`에 박는 경로 — chunk INSERT 단계에서 처리하는 게 가장 좁고, FTS 인덱싱은 trigger가 자동 동기화하므로 별도 단계 불필요.
- `--project` 인자에서 자동 fuzzy match — 모호하면 명시적 실패가 안전. path 또는 id-prefix 두 모드만 결정적으로 처리.

## 2026-05-09 — 외부 source `chunk_type` 분리 (`note` → `spec`/`message`/`thread`)

**무엇:** `memory_chunks.chunk_type`에 `spec`(Notion), `message`(Slack 단발), `thread`(Slack thread)를 추가하고 `ingestion.py`의 5개 INSERT 자리(`fetch_slack_url` URL/keyword, `fetch_notion_url` URL/keyword, `cmd_refresh`)에서 hardcoded `"note"`를 source별로 분기. `migrations.sh`에 backfill 함수(`backfill_external_chunk_types`) 추가 — `chunk_type='note'` 필터로 멱등성 보장. `search_memory` fallback 쿼리에 새 타입 포함.

**왜:** DB를 까보니 28건 전부 `note × source=notion` 한 칸에 통밥된 상태(`HANDOFF.md` 2026-05-09 검토). 9개 enum이 의미를 못 살리고, 같은 Notion 페이지 N개 섹션·Slack thread reply·단발 메시지가 한 타입 안에 섞여 있어 `/memory list --type` 같은 필터가 무력. `chunk_type`은 enum이라 자유 텍스트화는 일관성을 무너뜨리므로 enum에 3개를 추가하는 쪽을 선택.

**폐기한 대안:**
- 외부 source 별도 테이블(`external_chunks`) — 28건 규모에 union/trigger/FTS 두 벌 운영비가 분류 이득보다 큼. 향후 row 수가 만 단위로 갈 때 재검토.
- `metadata.source` 인덱스 승격(generated column + index) — 같은 검토에 묶여 있던 2단계. 검색 체감이 느려진 시점에 점진 도입 권장(`HANDOFF.md` 2단계 제안).

**타이밍 근거:** schema migration이 사용자 머신마다 한 번 돌아야 하지만, 데이터 양 28건일 때가 부담이 가장 작은 시점. 현재 시점(2026-05-09) 외 다른 시점에는 backfill 비용이 선형 증가.

**범위 노트:** LLM 추출 enum(`CHUNK_TYPES` 9개)은 그대로 두고, 외부 source 전용 enum을 `EXTERNAL_CHUNK_TYPES = ("spec", "message", "thread")`로 분리. `EXTRACT_PROMPT`(Stop hook이 응답에서 추출)는 9개만 유지 — 응답 본문에서 spec/message/thread를 추출하는 의미는 없음.

## 2026-05-?? 이전 — 누락 항목

이 문서는 2026-05-09에 신설됐다. 이전 결정(Phase 4.5 ingestion, Tauri 폐기, FTS5 trigram 채택, IMPRINT_BYPASS_HOOKS 가드 도입 등)의 사유는 `LoadMap.md`·`HANDOFF.md`·각 파일 상단 docstring과 git log에 분산되어 있다. 신설 이후 결정만 본 문서에 누적한다.
