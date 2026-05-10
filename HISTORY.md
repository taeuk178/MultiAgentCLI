# imprint 결정 사유 로그

**문서 책임**
- 본 문서는 **왜 이렇게 했는가**를 남긴다. 코드만 보면 알 수 없는 트레이드오프, 폐기된 대안, 결정 시점의 제약을 사실 위주로 기록한다.
- 큰 그림(비전·Phase 정의·아키텍처): `LoadMap.md`
- 단기 픽업(즉시 검토·deferred TODO·미완 Phase): `HANDOFF.md`
- hook 단계별 시스템 의존·운영 환경 변수: `flow.md`
- 사용·설치: `README.md`

기록 순서는 **최신이 위**. 항목당 한 단락 안에 변경/사유/대안 폐기 근거를 묶는다.

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
