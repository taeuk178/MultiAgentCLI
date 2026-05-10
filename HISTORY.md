# imprint 결정 사유 로그

**문서 책임**
- 본 문서는 **왜 이렇게 했는가**를 남긴다. 코드만 보면 알 수 없는 트레이드오프, 폐기된 대안, 결정 시점의 제약을 사실 위주로 기록한다.
- 큰 그림(비전·Phase 정의·아키텍처): `LoadMap.md`
- 단기 픽업(즉시 검토·deferred TODO·미완 Phase): `HANDOFF.md`
- hook 단계별 시스템 의존·운영 환경 변수: `flow.md`
- 사용·설치: `README.md`

기록 순서는 **최신이 위**. 항목당 한 단락 안에 변경/사유/대안 폐기 근거를 묶는다.

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
