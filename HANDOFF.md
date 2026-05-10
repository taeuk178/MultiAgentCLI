# Handoff — 다음 세션 픽업

**문서 책임**
- 본 문서는 **단기**: 즉시 다음에 손댈 검토 안건, deferred TODO, 직전 작업의 미완 Phase, 다음 세션 시작 시 픽업 지점만 담는다.
- **큰 그림**(비전·Phase 정의·아키텍처·위험 요소·미시작 Phase 5/6/7)은 `LoadMap.md` 참조.
- **결정 사유 로그**(왜 그렇게 바꿨는지)는 `HISTORY.md` 참조.
- 구현 완료된 Phase 1·2·3·4.5·HUD·플러그인 설치의 사용·구조·데이터 위치는 `README.md` 참조.

최종 업데이트: 2026-05-10.

## Phase 7a — 청크 + 의미 검색 + 엔티티 정규화 + 버전 (1단계 명세) — 2026-05-10

이 섹션은 시스템 디자인 1단계 — chunk pipeline + hybrid retrieval + entity normalization + versioning — 의 명세입니다. LoadMap.md 의 Phase 7 을 **7a (chunk-level)** / **7b (project-level graph: hierarchical summary, contradiction detection, graph memory)** 로 분리한 첫 단계에 해당합니다. 명세 진입 전에 아래 7개 결정 사항을 합의해야 하며, 합의 결과는 `HISTORY.md` 의 결정 사유 로그로 남깁니다.

### 결정 사항 (2026-05-10 확정)

7개 결정의 공통 축은 "**로컬 단일 파일 + OAuth 친화 + 점진 진화**" 라는 imprint 정체성 유지입니다. 결정 사유 로그는 `HISTORY.md` 2026-05-10 항목 참조.

| # | 항목 | 결정 | 핵심 사유 |
|---|---|---|---|
| 1 | 스토리지 스택 | **SQLite + FTS5 + sqlite-vec** | 로컬 단일 파일 정체성과 정합. 한 파일에 문서·FTS·벡터 동거. 한계 보일 때 PostgreSQL migration path 만 열어둠. |
| 2 | 임베딩 공급자 | **로컬 multilingual (multilingual-e5 또는 BGE 계열) 우선** | claude OAuth 구독에 임베딩 API 없음 + 외부 API key 의존 회피. 한국어 PRD·Slack 대응. 차원은 모델 결정 후 확정. |
| 3 | chunk_type | **기존 9+3 유지 + normalized 4-category 컬럼 이중 계층** | 기존 데이터 호환 + 검색 단순화 양립. `raw_chunk_type` / `normalized_chunk_type` 두 컬럼. |
| 4 | entity_aliases 자동화 | **자동 추출 + review queue** | 완전 자동은 오탐이 retrieval 전체를 오염. 프로젝트별 용어 사전을 점진 학습. |
| 5 | supersedes 결정 | **사용자 명시 기본 + 자동 제안 보조** | 보완 설명을 폐기로 오인할 위험. 자동 supersede 는 contradiction detection 영역이라 Phase 7b. |
| 6 | Retrieval API 호스팅 | **inline-first + daemon-ready abstraction** | 현 hook/skill 구조 유지. `retrieve(query)` 시그니처만 추상화해 두고 배포 형태는 늦게 결정. |
| 7 | rerank 모델 | **로컬 cross-encoder first + Cohere 옵션 + Claude judge 실험** | OAuth 친화 + 비용 통제. 핵심 파이프라인을 외부 의존에 묶지 않음. |

#### 결정 보강 (다이어그램 검증으로 도출, 2026-05-10)

README "Phase 7a — 검색 정밀도 (1단계)" 의 mermaid 검토 과정에서 동기 경로 무거움 우려가 제기되어 위 7개 결정 위에 다음 세부 패턴이 합의됨:

- **결정 #1 보강 — single-writer ingest queue**: 모든 백그라운드(`J1/J2/J4`)가 `PACK*` 만 만들어 같은 `ENQ` 큐로 보내고 `DEDUPE → VRES → CONF → W1` 한 줄로 직렬 commit. 이전 성능 병목 진단의 **영구 deferred 였던 C축 #3 (단일 writer 큐) 가 7a 의 자연 일부로 흡수**. WAL+busy_timeout 보강이 아니라 락 자체를 없애는 패턴.
- **결정 #6 보강 — daemon-ready 노드 5개 명시**: `QEMB` (query embedding) · `HYB` (FTS5 + sqlite-vec) · `RR` (cross-encoder rerank) · `W1` (single writer commit) · `WC` (warm cache manager). 평소엔 inline 으로 동작하고, 동기 경로 latency budget 위반 시 이 5개를 daemon (`imprintd`) 으로 분리하는 것이 첫 escape hatch.
- **결정 #7 보강 — RG 게이트 기준 + timeout**: cross-encoder rerank 는 `count ≥ 10 AND top-1 score < 0.85 AND rerank cache miss` 셋 모두 성립할 때만 발동, 그 외엔 BOOST 결과 직접 prepend. 발동 시에도 200 ms timeout — 만료되면 boost 결과로 graceful degradation (RROK 분기).

#### 남은 후속 결정 (구현 진입 전 좁혀야 할 세부)

- **2-1**: multilingual-e5 vs BGE 계열 정확한 모델명 + 차원 (multilingual-e5-large = 1024 / BGE-M3 = 1024 / BGE-ko-small = 384 등) — schema `embedding vector(N)` 확정
- **3-1**: `normalized_chunk_type` 의 9+3 → 4 매핑 룰 — `decision / fix / todo / error / command / test_result / summary / code_context / note + spec / message / thread` → `requirement / decision / discussion / code_note` 결정표
- **5-1**: supersedes 자동 제안의 패턴 트리거 — 정규식("변경한다 / 대체한다 / 폐기" 등) vs LLM 분류기 — Phase 7a 안에서 결정
- **6-1**: inline backend / daemon backend 의 공통 함수 시그니처 — Python module / shell command / RPC 중 어느 인터페이스를 표준으로
- **7a-7**: warm cache (`J3`) 정책 — daemon always-on / lazy spawn / first-query-on-demand 중 어디에 머무를지. 임베딩 모델 콜드 로드 비용 (+500 ms~) 흡수가 목적
- **7a-8**: rerank cache key 설계 — `query hash + candidate id set hash + project_id` 조합, TTL (분 단위? 세션 단위?), retrieval scope 별 구분 여부
- **7a-9**: ingest queue 구현체 — SQLite append-only 테이블 + polling worker / Unix socket IPC / mmap ring buffer 중 어느 형태. inline-only 모드와 daemon 모드 전환 시 동일 인터페이스 유지가 조건

> **명세 본문 주의**: 아래 명세 일부는 PostgreSQL 기준으로 작성되어 있습니다 (시스템 구성·테이블 설계 SQL·`vector(1536)` 등). 결정 #1 (SQLite + FTS5 + sqlite-vec) 에 따라 첫 구현 PR 에서 SQLite 스키마로 재작성합니다 — 본문은 설계 의도와 컬럼 단위 의미를 보존하기 위한 참고로 유지합니다.

### 목표

이 단계의 목표는 사용자의 짧고 모호한 질문을 받아도, 프로젝트 내부 문서·슬랙·노션에 흩어진 정보를 같은 엔티티 기준으로 묶고, 최신 결정 기준으로 검색해서 Claude 에 안정적으로 넘기는 것입니다.

검색 파이프라인은 "문자열 일치"가 아니라 **문맥 보강된 청크 + 의미 검색 + 키워드 검색 + 엔티티 정규화 + 버전 필터링** 으로 동작해야 합니다.

### 범위

이번 1단계 (Phase 7a) 에 포함되는 것:

- 데이터 수집: Notion, Slack, PRD, 회의록, 이슈
- 청킹: 문서별 chunk 생성
- contextual prefix 생성
- embedding 생성 및 저장
- BM25 / FTS 인덱스 생성
- entity alias 추출 및 canonicalization
- versioning 필드 저장
- query 시 hybrid retrieval + reranking + context assembly

이번 단계에서 **제외**하는 것 (Phase 7b 로 이월):

- hierarchical summary (RAPTOR 류 — feature / document / project 계층 요약)
- contradiction detection (NLI 기반 후보 + 정밀 판정)
- query scope classifier 와 retrieval routing (local / feature / global)

영구 deferred (Phase 7b 에서도 도입 안 함):

- full knowledge graph DB 도입 (GraphRAG / HippoRAG 풀스택)
- community detection 기반 preprocessing
- graph traversal 기반 multi-hop reasoning
- 자동 belief revision 엔진 / 완전 자동 supersede 확정

### 시스템 구성

스택 결정 #1 에 따라 **SQLite + FTS5 + sqlite-vec** (단일 파일) 로 확정. 하나의 DB 에서 벡터 검색과 키워드 검색을 같이 돌리고 RRF 로 점수 융합하는 방식은 동일 — sqlite-vec 가 `vec_distance_cosine` / `MATCH` 결과를 같은 SQL 쿼리에서 join 가능합니다. 아래 PostgreSQL 표기는 컬럼 의미·인덱스 의도 보존을 위한 참고로 유지하고, SQLite 스키마는 첫 구현 PR 에서 다시 작성합니다.

구성 요소:

- **Ingestion Worker** — Notion / Slack / 문서 수집 (J1 lazy fetch)
- **Chunking Worker** — 문서 분리 및 메타데이터 부착
- **Context Builder** — 각 chunk 에 `context_prefix` 생성
- **Embedding Worker** — contextualized text 임베딩 생성 (chunk-side EMB1/EMB2 + query-side QEMB, daemon-ready)
- **Entity Resolver** — alias 추출, canonical entity 연결 (entity mention 추출 + `chunk_entities` link, J4 alias mining)
- **Single-Writer Worker** — `ENQ` 큐 consumer. `DEDUPE → VRES → CONF → W1/W2` 직렬 commit. 모든 ingest 경로가 이 워커 하나를 통과
- **Warm Cache Manager** — J3 가 spawn. 임베딩 모델 warm-up + recent query embedding cache 를 `QEMB` 에 dotted 제공
- **Rerank Worker** — 로컬 cross-encoder, RG 게이트 통과 시에만 호출. timeout 200 ms 가드 (daemon-ready)
- **Retrieval API** — query 전처리, hybrid search, RG 게이트, rerank, context 조립
- **Claude Adapter** — 최종 prompt 구성 후 Claude 호출

### 테이블 설계

핵심은 **원문, 검색용 텍스트, 엔티티, 버전 정보를 분리**하는 것입니다.

```sql
-- 프로젝트
create table projects (
  id uuid primary key,
  name text not null,
  created_at timestamptz not null default now()
);

-- 원문 문서
create table documents (
  id uuid primary key,
  project_id uuid not null references projects(id),
  source_type text not null,              -- notion, slack, prd, meeting, jira
  source_ref text not null,               -- notion page id, slack ts/channel, file path
  title text,
  author text,
  created_at timestamptz,
  updated_at timestamptz,
  raw_text text not null,
  checksum text not null,
  is_deleted boolean not null default false
);

-- 청크
create table chunks (
  id uuid primary key,
  project_id uuid not null references projects(id),
  document_id uuid not null references documents(id),
  chunk_index int not null,
  section_path text,                      -- 예: 결제 > 테스트모드 > 버튼동작
  chunk_text text not null,               -- 원본 청크
  context_prefix text,                    -- LLM 생성 문맥 설명
  retrieval_text text not null,           -- context_prefix + '\n' + chunk_text
  embedding vector(1536),                 -- 결정 #2 후속(2-1) 에서 모델 확정 — multilingual-e5-large 1024 / BGE-M3 1024 / BGE-ko-small 384 등
  tsv tsvector,                           -- SQLite 재작성 시 FTS5 virtual table 로
  raw_chunk_type text,                    -- 결정 #3: 기존 9+3 (decision / fix / todo / error / command / test_result / summary / code_context / note / spec / message / thread)
  normalized_chunk_type text,             -- 결정 #3: 4-category (requirement / decision / discussion / code_note) — 매핑 룰은 후속 결정 3-1
  source_created_at timestamptz,
  source_updated_at timestamptz,
  valid_from timestamptz,
  valid_to timestamptz,
  is_current boolean not null default true,
  supersedes_chunk_id uuid null references chunks(id),
  created_at timestamptz not null default now()
);

-- 엔티티 canonical
create table entities (
  id uuid primary key,
  project_id uuid not null references projects(id),
  entity_type text not null,              -- ui_element, screen, api, feature_flag
  canonical_name text not null,           -- 예: test_button
  display_name text not null,             -- 예: Test 버튼
  created_at timestamptz not null default now()
);

-- 엔티티 alias
create table entity_aliases (
  id uuid primary key,
  entity_id uuid not null references entities(id),
  alias text not null,                    -- 예: 테스트 모드 진입 버튼, 디버그 토글
  normalized_alias text not null,
  created_at timestamptz not null default now()
);

-- 청크와 엔티티 연결
create table chunk_entities (
  chunk_id uuid not null references chunks(id),
  entity_id uuid not null references entities(id),
  mention text not null,
  confidence numeric(4,3) not null,
  primary key (chunk_id, entity_id, mention)
);
```

검색 성능 인덱스:

```sql
create index idx_chunks_project_doc on chunks(project_id, document_id);
create index idx_chunks_current on chunks(project_id, is_current);
create index idx_chunks_valid_time on chunks(project_id, valid_from, valid_to);
create index idx_chunks_section on chunks(project_id, section_path);
create index idx_entity_aliases_norm on entity_aliases(normalized_alias);
create index idx_chunks_tsv on chunks using gin(tsv);
-- pgvector index 는 환경에 맞춰 ivfflat 또는 hnsw 사용
```

### 저장 규칙

청크 저장 시 핵심 규칙:

- `chunk_text` — 원문 그대로 저장
- `context_prefix` — 문서 전체 맥락 속에서 이 청크가 무엇인지 설명하는 1~2 문장
- `retrieval_text` — `context_prefix + "\n" + chunk_text`
- `embedding` — `retrieval_text` 기준으로 생성
- `tsv` — `retrieval_text` 기준으로 생성
- Claude 최종 답변에 넣을 때는 우선 `chunk_text` 중심으로 사용하고, 필요시 `context_prefix` 를 보조 정보로 사용

즉 단순히 "A 버튼 동작" 만 저장하는 것이 아니라 **검색용 표현을 하나 더 만든다** 고 보면 됩니다.

### Ingestion 플로우

문서 수집부터 저장까지의 표준 플로우:

1. 외부 소스에서 문서 수집
2. 문서 checksum 비교로 변경 여부 확인
3. 변경된 문서만 청킹 수행
4. 각 청크마다 `context_prefix` 생성
5. `retrieval_text` 생성
6. embedding 생성
7. 엔티티 추출 및 alias 연결
8. 기존 chunk 와 비교해 versioning 처리
9. DB upsert

### 청킹 기준

초기에는 너무 복잡하게 가지 말고 아래 기준을 권장:

- 문단 / 섹션 기반 우선
- 300~800 tokens 정도
- overlap 10~15%
- section title, heading path, source metadata 같이 보존
- 슬랙은 thread 단위 또는 대화 window 단위
- 회의록은 agenda / subtopic 단위

### context_prefix 생성 규칙

LLM 에 각 chunk 의 상위 문맥을 설명하게 합니다. **Anthropic 의 contextual retrieval** 방식과 같은 방향입니다.

**입력**

- 문서 제목
- 문서 메타데이터
- 문서 전체 요약 또는 상위 섹션
- 현재 chunk 원문

**출력 규칙**

- 1~2 문장
- 사실만, 추론 최소화
- 문서 내부 위치와 기능적 의미를 설명
- "이 내용은 …에 관한 것이다" 스타일 허용
- 장황한 요약 금지

**예시 프롬프트**

```text
You are generating retrieval context for a chunk.

Given:
- project name
- document title
- source type
- section path
- surrounding section summary
- chunk text

Write 1-2 sentences that explain what this chunk is about in the context of the whole project.
Be concrete and factual.
Mention the feature/screen/component if identifiable.
Do not repeat the chunk verbatim unless needed.
Output only the context text.
```

**예시 결과**

원문:

```text
A 버튼 클릭 시 테스트 모드로 진입한다.
```

`context_prefix`:

```text
iOS 앱 A 화면의 우상단 테스트 진입 버튼 동작을 설명하는 요구사항이다. 테스트 모드 진입 UX 와 관련된 기능 정의이다.
```

`retrieval_text`:

```text
iOS 앱 A 화면의 우상단 테스트 진입 버튼 동작을 설명하는 요구사항이다. 테스트 모드 진입 UX 와 관련된 기능 정의이다.
A 버튼 클릭 시 테스트 모드로 진입한다.
```

### Entity Alias 설계

이 단계에서 entity 는 완전 자동 지식 그래프 수준까지 갈 필요는 없습니다. canonical entity + alias 사전 정도면 충분합니다.

**권장 엔티티 타입**

- `ui_element`
- `screen`
- `feature`
- `api`
- `state`
- `experiment_flag`

**처리 규칙**

- chunk ingest 시 mention 후보 추출
- 정규화: 공백 제거, lowercasing, 특수문자 단순화
- 기존 alias 사전에 있으면 기존 entity 연결
- 없으면 후보 entity 생성 또는 review queue 적재
- alias confidence 낮으면 auto-link 하지 않고 human review

**예시**

```text
canonical entity: test_button
display_name: Test 버튼

aliases:
- test 버튼
- 테스트 버튼
- 테스트 모드 진입 버튼
- 디버그 토글
- debug toggle
```

이렇게 해두면 사용자가 "디버그 토글 뭐야" 라고 물어도 같은 엔티티 관련 chunk 를 확장 검색할 수 있습니다.

### Versioning 규칙

1단계의 versioning 은 단순하고 명확하게:

**최소 필드**

- `valid_from`
- `valid_to`
- `is_current`
- `supersedes_chunk_id`

**동작 규칙**

- 새 문서 / 회의록 / 결정이 기존 요구를 대체하면 이전 chunk 의 `valid_to` 를 채우고 `is_current = false`
- 새 chunk 는 `is_current = true`
- 대체 관계가 명확하면 `supersedes_chunk_id` 연결
- 불명확하면 둘 다 current 로 두되 metadata 만 남김

**예시**

3월:

```text
test 버튼 클릭 시 바로 테스트 모드로 진입
```

5월:

```text
test 버튼 클릭 시 확인 모달 후 테스트 모드로 진입
```

저장 결과:

- 3월 chunk: `valid_to = 2026-05-01`, `is_current = false`
- 5월 chunk: `valid_from = 2026-05-01`, `is_current = true`, `supersedes_chunk_id = <3월 chunk id>`

### Retrieval API 플로우

질문이 들어오면 아래 순서로 처리. README **"Phase 7a — 검색 정밀도 (1단계)"** 다이어그램이 같은 흐름을 시각화합니다.

1. **`QN`** query normalize *(sync)*
2. **`RES`** entity alias resolve *(sync)*
3. query expansion *(sync, RES 안에서 alias 사전 적용)*
4. **`QEMB`** query embedding 생성 *(sync/daemon-ready, J3 warm cache 우선)*
5. **`HYB`** hybrid retrieval — FTS5 BM25 top-N + sqlite-vec ANN top-N *(sync/daemon-ready)*
6. **`RRF`** score fusion *(sync)*
7. **`BOOST`** version filter (`is_current`) + recency + entity coverage *(sync)*
8. **`RG{rerank 필요?}`** 게이트 — `count ≥ 10 AND top-1 < 0.85 AND cache miss` 면 yes, 아니면 skip
9. **`RR`** (RG = yes 시) 로컬 cross-encoder rerank *(sync/daemon-ready, timeout 200 ms)*
10. **`RROK`** timeout 분기 — success 또는 timeout 둘 다 다음 단계로 (graceful degradation)
11. **`CTX`** top-K 구조화 context assembly *(sync)*
12. Claude 호출

**query normalize**

- 소문자화
- 조사 / 불용어 경량 제거
- 버튼 / 클릭 / 탭 같은 도메인 동의어 normalization
- 한국어는 형태소 분석기까지는 나중에, 초기엔 rule-based 로 시작

**entity alias resolve**

```text
입력: "디버그 토글 누르면 뭐 돼?"
resolve:
- matched alias: "디버그 토글"
- canonical entity: test_button
```

**query expansion**

```text
원본: 디버그 토글 누르면 뭐 돼?
확장: 디버그 토글, test 버튼, 테스트 모드 진입 버튼, A 화면, 탭 동작
```

### Hybrid Search 설계

Anthropic cookbook 기준처럼 semantic + BM25 결과를 각각 과다 회수한 뒤 score fusion 하는 방식. README 다이어그램의 `QEMB → HYB → RRF → BOOST → RG` 흐름이 이 단계.

**추천 기본값**

- vector topN: 100~150
- bm25 topN: 100~150
- final fusion candidate: 150~250
- rerank input: top 30~50 (단, RG 게이트 통과 시에만)
- final context topK: 8~15

**`RG` 게이트 — rerank 발동 조건 (AND 셋 모두 성립 시 yes)**

| 조건 | 의미 | 이유 |
|---|---|---|
| `boost 통과 candidate count ≥ 10` | 후보가 충분히 많을 때만 | 후보 < 10 이면 rerank 가 정렬 효용 미미 |
| `boost 후 top-1 score < 0.85` | 확신 있는 1위가 없을 때만 | top-1 이 압도적이면 rerank 가 결과를 바꾸지 않음 |
| `rerank cache miss` | 같은 (query hash, candidate id set, project) 조합이 캐시에 없을 때만 | 같은 의미 query 가 반복되면 캐시 hit 으로 동기 비용 0 |

세 조건 중 하나라도 안 맞으면 RG = no → BOOST 결과 그대로 `CTX` 로 직행. 후속 결정 7a-8 이 cache key·TTL 을 확정.

**RRF 예시**

```text
rrf_score = 0.8 * (1 / (60 + vector_rank)) + 0.2 * (1 / (60 + bm25_rank))
```

초기 가중치는 Anthropic cookbook 예시처럼 semantic 80, BM25 20 으로 시작하고 튜닝합니다.

**recency / current boost**

```text
final_score = rrf_score
  + 0.15 if is_current = true
  + 0.10 if matched_entity = canonical entity
  + 0.05 if source_updated_at is recent
```

정확한 수치는 로그 보고 조정.

### Reranking

초기 retrieval 은 recall 중심이고, reranking 은 precision 중심.

**진입 조건**: 위 `RG` 게이트의 AND 조건 셋이 모두 성립할 때만 (README 다이어그램의 `RG -->|yes| RR`).

**rerank 입력**

- user query
- candidate chunk 의 `retrieval_text`
- metadata: `source_type`, `section_path`, `is_current`, entity match

**rerank 목적**

- 질문과 직접 관계있는 청크 상위 배치
- 최신 정책 우선
- 중복 청크 제거
- 같은 의미의 여러 청크 중 대표성 높은 청크 선택

**Timeout 정책 — graceful degradation (`RROK`)**

cross-encoder 는 후보 30 개 × forward pass 라 시간 분포가 큽니다. 200 ms 안에 끝나지 않으면:

1. inference 를 강제 종료하지 않고 (모델 상태 보호) 별도 watcher 가 200 ms 시점에 분기
2. `RROK -->|timeout| CTX` 경로로 BOOST 결과를 그대로 prepend
3. 끝난 rerank 결과는 도착 시점에 cache 에 저장 — 다음 같은 query 에서 cache hit 으로 활용

평소 동기 경로 budget 을 깨지 않으면서 rerank 효용을 시간차로 흡수하는 패턴.

### 동기 경로 latency budget

UPS hook 의 동기 경로는 README 본 플로우의 "≈1초 보장" 정신을 유지합니다. 7a 도입으로 retrieval 단계가 늘어나므로 budget 을 두 케이스로 나눠 명시:

| rerank 발동 여부 | budget | 단계별 추정 |
|---|---|---|
| `RG = no` (skip) | **< 100 ms** | `QN` < 5 + `RES` < 5 + `QEMB` 50~100 (warm cache hit 시 < 5) + `HYB` 30~80 + `RRF` < 1 + `BOOST` < 5 + `CTX` < 5 |
| `RG = yes` (발동) | **< 300 ms** | 위 + `RR` ≤ 200 (timeout cap). timeout 시 200 ms 직후 `RROK → CTX` |

**위반 감지 + 대응**

- 모든 `(sync)` 와 `(sync/daemon-ready)` 노드는 진입/탈출 시 wall clock 측정. 위반 시 `plugin.log` WARN + profile.jsonl 에 stage 기록 (성능 병목 진단의 IMPRINT_PROFILE=1 인프라 재사용).
- 같은 budget 위반이 5분 윈도에 3회 이상 → 결정 #6 의 daemon backend escape hatch 발동: `QEMB` / `HYB` / `RR` 중 가장 무거운 노드부터 daemon 으로 분리. inline backend 와 동일 함수 시그니처(후속 결정 6-1) 라 호출 측 코드는 변경 없음.
- `QEMB` 콜드 로드 비용 흡수는 J3 warm cache (후속 결정 7a-7) 가 1차 방어, daemon 분리가 2차 방어.

### Final Context Assembly 규칙

- 같은 document / section 에서 중복 청크 너무 많이 넣지 않기
- 같은 entity 에 대한 최신 / 대표 청크 우선
- 필요 시 최신 1개 + 과거 1개만 같이 넣기
- Slack 잡담보다 PRD / 결정문서 가중치 높게

### Claude 전달 포맷

검색 결과를 그냥 붙이지 말고 구조화해서 전달:

```text
[Project]
프로젝트명: A iOS App

[User Question]
디버그 토글 누르면 지금 어떻게 동작해?

[Resolved Entity]
canonical: test_button
aliases matched: 디버그 토글

[Retrieved Context]
1. source=PRD, section=테스트모드>진입, current=true, updated=2026-05-01
   test 버튼 클릭 시 확인 모달을 먼저 노출한 후 테스트 모드로 진입한다.

2. source=Slack, section=QA 스레드, current=true, updated=2026-05-02
   디버그 토글이라는 문구로 변경되었으며 기존 test 버튼과 동일한 UI 요소를 의미한다.

3. source=Meeting Note, section=릴리즈 정책, current=false, updated=2026-03-10
   test 버튼 클릭 시 바로 테스트 모드로 진입한다.

[Instructions]
- Answer based on the current decision first.
- Mention prior behavior only if relevant.
- If the current behavior changed from previous documents, explain the update clearly.
```

이렇게 하면 Claude 가 최신 / 과거를 덜 혼동합니다.

### 실제 동작 시나리오

**저장 시점**

기획 문서:

```text
A 화면 우상단의 test 버튼 클릭 시 테스트 모드로 진입한다.
```

회의록:

```text
릴리즈 전 변경: test 버튼은 바로 진입하지 않고 확인 모달 이후 진입으로 바꾼다.
```

슬랙:

```text
이제 문구는 디버그 토글로 통일하자.
```

시스템 저장 결과:

- entity `test_button`
- alias: `test 버튼`, `디버그 토글`
- old chunk: 직접 진입, `is_current = false`
- new chunk: 확인 모달 후 진입, `is_current = true`

**조회 시점**

사용자 질문:

```text
디버그 토글 누르면 뭐 해?
```

파이프라인:

1. "디버그 토글" alias 매칭
2. canonical entity `test_button` resolve
3. vector search 가 "버튼 동작", "테스트 모드 진입" 관련 청크 회수
4. BM25 가 "디버그 토글" 정확 매칭된 슬랙 청크 회수
5. RRF 결합
6. `is_current = true` 청크 가중치
7. rerank 후 최종 context 구성

Claude 답변:

> 현재 디버그 토글은 확인 모달을 먼저 띄운 뒤 테스트 모드로 진입합니다. 이전에는 즉시 진입 정책이 있었지만 이후 변경되었습니다.

이게 1단계의 핵심 가치입니다 — **표현이 달라도 찾고, 최신 결정으로 정리해서 답하게 만드는 것**.

### API 계약 예시

**Ingest API**

```json
POST /v1/projects/:projectId/documents/ingest
{
  "sourceType": "notion",
  "sourceRef": "page_123",
  "title": "테스트 모드 정책",
  "updatedAt": "2026-05-01T12:00:00Z",
  "rawText": "..."
}
```

**Query API**

```json
POST /v1/projects/:projectId/query
{
  "question": "디버그 토글 누르면 뭐 해?",
  "topK": 10,
  "includeHistory": true
}
```

**Query 응답 내부 디버그 예시**

```json
{
  "resolvedEntities": [
    { "canonical": "test_button", "matchedAlias": "디버그 토글" }
  ],
  "retrievedChunks": [
    { "chunkId": "c1", "score": 0.91, "isCurrent": true },
    { "chunkId": "c2", "score": 0.72, "isCurrent": false }
  ],
  "answer": "현재는 확인 모달 후 테스트 모드로 진입합니다."
}
```

### 구현 우선순위

가장 안정적인 구현 순서 (README 다이어그램의 노드 묶음 기준):

1. **스키마 v1** — `documents`, `chunks` (이중 `chunk_type`), `entities`, `entity_aliases`, `chunk_entities` 저장 구조 + sqlite-vec extension 로딩 + FTS5 trigger
2. **chunking 파이프라인 (BG side)** — `SPL → CP → (EMB ‖ ENT) → PACK` 분해 구현. 두 hook (J1/J2) 모두 같은 정의를 공유
3. **single-writer ingest queue** — `ENQ → DEDUPE → VRES → CONF → W1/W2`. C축 #3 단일 writer 큐 패턴이 자연스럽게 흡수
4. **hybrid retrieval 동기 경로** — `QN → RES → QEMB → HYB → RRF → BOOST → CTX` (rerank 없이) 먼저 작동시키고 본 다이어그램의 SEARCH 자리에 swap
5. **entity alias** — 수동 seed + 반자동 추출 + review queue (`/memory entities` 스킬). W2 → ENTS → ENQ 순환 완성
6. **versioning** — `valid_from / valid_to / is_current / supersedes_chunk_id` + `/memory remember --supersedes` 인자. `BOOST` 의 current 우선 정렬 활성화
7. **RG 게이트 + cross-encoder rerank + RROK timeout** — RR 발동 조건 + cache + 200 ms graceful
8. **warm cache (J3) + entity refresh (J4)** — `WC -.cache.-> QEMB` dotted edge. 콜드 로드 흡수
9. **Claude prompt assembly 구조화** — 명세 "Claude 전달 포맷" 적용
10. **latency budget 모니터링** — IMPRINT_PROFILE=1 인프라에 7a stage 추가, 위반 시 WARN. daemon escape hatch 발동 조건 명시

### 완료 조건

1단계가 끝났다고 볼 수 있는 기준:

- 같은 의미의 다른 표현으로 물어도 관련 청크가 검색된다
- 최신 결정이 과거 결정보다 우선적으로 선택된다
- alias 기반으로 같은 UI 요소를 하나의 entity 로 묶을 수 있다
- Claude 답변이 "현재 기준" 과 "이전 기준" 을 구분해 설명한다
- retrieval debug 로그로 왜 이 청크가 선택되었는지 추적 가능하다

### 다음 액션

- (완료, 2026-05-10) 7개 결정 합의 — 본 섹션 "결정 사항" 표 + `HISTORY.md` 2026-05-10 참조
- (완료, 2026-05-10) 다이어그램 검증으로 결정 #1 / #6 / #7 보강 — single-writer queue · daemon-ready 노드 5개 · RG 게이트 기준 · timeout 200 ms graceful · 동기 경로 latency budget. README **"Phase 7a — 검색 정밀도 (1단계)"** 가 같은 흐름을 시각화.
- (완료, 2026-05-10) `LoadMap.md` Phase 7 → 7a / 7b 분리 갱신
- (완료, 2026-05-10) `HISTORY.md` 결정 사유 로그 추가
- **(다음 PR — 결정 라운드 1회)** 후속 결정 7건 좁히기 (2-1 · 3-1 · 5-1 · 6-1 · 7a-7 · 7a-8 · 7a-9). 짧은 인터뷰 한 번에 묶을 수 있는 분량.
- **(그 다음 PR)** 구현 우선순위 1번 (SQLite 스키마 v1) — `documents`, `chunks` (이중 `chunk_type`), `entities`, `entity_aliases`, `chunk_entities` + sqlite-vec extension + FTS5 trigger. idempotent migration.
- **(그 다음 PR 들)** 구현 우선순위 2~10번 (chunking → ingest queue → hybrid retrieval → entity alias → versioning → RG 게이트+rerank → warm cache → assembly → latency 모니터)

## Phase 7b — 계층 요약 + 충돌 감지 (2단계 명세) — 2026-05-10

이 섹션은 시스템 디자인 2단계 — Phase 7a retrieval 엔진 위에 **질문 해상도에 맞는 요약 계층** 과 **충돌 감지 계층** 을 얹는 단계 — 의 명세입니다. 작은 질문은 여전히 chunk 기반으로 답하되, 큰 질문은 feature / document / project summary 부터 접근하고, 서로 상충하는 결정이 있으면 명시적으로 표시해야 합니다.

**진입 조건**: Phase 7a 가 안정적으로 운용된 뒤. Phase 7a 의 후속 결정 4건과 SQLite 스키마 v1 이 머지된 상태가 전제.

### 명세 보강 (다이어그램 검증으로 도출, 2026-05-10)

README "Phase 7b — 프로젝트 수준 해석 (2단계)" 의 mermaid 검토 과정에서 다음 4가지 보강이 합의됨. 본 명세 본문은 이 보강을 반영해 갱신:

- **`GROUND` drill-down 룰 명시** — summary 검색 결과는 `summary_links` 테이블의 `child_kind = chunk` 항목 1~3개를 추가 조회해 grounding context 에 함께 첨부. summary 만 단독으로 답변에 들어가는 케이스 차단. (Answer Assembly grounding 규칙)
- **`W1` commit trigger edge — incremental 원칙 시각화** — `J5` (summary rebuild) 와 `J6` (contradiction detection) 는 `ST` 가 아니라 single-writer commit 직후 변경이 감지된 entity / feature / decision 이 있을 때만 trigger. 매 turn 무조건 재생성 X. (배치 / 갱신 전략)
- **NLI judge 결과 3구간 — neutral 저장으로 false negative 방지** — `CDCONF` score 가 high 면 `status=candidate`, mid·low 면 `status=neutral` 저장 (재검토 가능). 자동 dismiss 안 함. (Contradiction Detection 플로우 "3. 저장")
- **Summary retrieval depth limit 명시** — feature 검색은 `summary 5 + chunk 8` 까지, global 검색은 `proj 1 + doc 3 + feat 5 + chunk 6` 까지. context 폭주 방지. (Retrieval 라우팅)

추가로 NLI judge timeout 500 ms (실패 시 status=candidate 유지 + 다음 배치 재시도) 와 `J6` candidate 생성 조건 (same entity + decision + time gap < 90 d, O(n²) 방지) 도 명세 본문에 박힘.

### 한 줄 요약

> Phase 7b 는 SQLite 기반 1단계 retrieval 엔진 위에 RAPTOR 형 계층 요약과 경량 contradiction awareness 를 추가해, 작은 질문은 정확하게 답하고 큰 질문은 구조적으로 설명하며, 충돌 시 이를 숨기지 않고 드러내는 단계.

### 단계 정의 (1·2 단계 분리)

| 단계 | 한 문장 정의 | 핵심 컴포넌트 |
|---|---|---|
| **1단계 (Phase 7a)** | 검색을 잘하게 만든다 | hybrid retrieval (RRF) · entity alias canonicalization · versioning · contextual prefix |
| **2단계 (Phase 7b)** | 검색된 결과를 프로젝트 수준에서 해석하게 만든다 | feature / document / project summary · query scope classifier · contradiction candidate + 판정 · resolution-aware answer assembly |

### 전제

- 로컬 단일 파일 지향 (Phase 7a 결정 #1 유지)
- SQLite + FTS5 + sqlite-vec 기반 유지
- Claude OAuth 중심 사용
- 1단계에서 이미 chunks · entities · entity_aliases · versioning · hybrid retrieval 이 구현되어 있음
- 2단계에서는 대규모 GraphRAG 풀스택 대신 RAPTOR 에 가까운 **경량 계층 요약 구조** 채택

즉 2단계는 "그래프 DB 도입" 이 아니라 현재 로컬 retrieval 엔진을 더 높은 해상도의 질문에 대응하게 만드는 확장.

### 범위

**포함**

- feature / document / project 단위 summary 생성
- summary 자체를 retrieval 대상에 포함
- query scope classifier 도입
- local question 과 global question 의 retrieval 경로 분기
- contradiction candidate 생성
- NLI 또는 LLM 기반 contradiction 판정
- answer assembly 시 conflict 표시

**제외 (영구 deferred)**

- full knowledge graph 구축
- community detection 기반 GraphRAG preprocessing
- graph traversal 기반 multi-hop reasoning
- 자동 belief revision 엔진
- 완전 자동 supersede 확정

### 설계 원칙

1. **Local-first** — 모든 요약 / 충돌 데이터는 기존 SQLite 파일에 저장
2. **Incremental** — 전체 재빌드보다 변경 영향 범위만 재생성
3. **Resolution-aware** — 질문 크기에 따라 retrieval 단위를 바꿈
4. **Grounded** — summary 만으로 답하지 않고 항상 근거 chunk 를 함께 유지
5. **Cautious conflict handling** — contradiction 은 자동 확정이 아니라 candidate 와 confirmed 를 구분

### 추가 데이터 모델

#### `summaries`

```sql
create table summaries (
  id text primary key,
  project_id text not null,
  level text not null,                  -- feature, document, project
  target_key text not null,             -- feature:<key>, document:<id>, project:<id>
  title text,
  summary_text text not null,
  retrieval_text text not null,
  embedding blob,
  tsv text,
  source_chunk_count integer not null default 0,
  source_summary_count integer not null default 0,
  valid_from text,
  valid_to text,
  is_current integer not null default 1,
  updated_at text not null
);
```

- `summary_text` — 사용자에게 보여줄 요약 본문
- `retrieval_text` — 검색용 텍스트, 필요 시 context prefix 포함
- `level` — 질문 범위에 맞는 레벨 선택에 사용
- `target_key` — 같은 feature / document / project 를 식별하는 키

#### `summary_links`

```sql
create table summary_links (
  parent_summary_id text not null,
  child_kind text not null,             -- summary, chunk
  child_id text not null,
  rank_order integer not null default 0,
  weight real not null default 1.0,
  primary key (parent_summary_id, child_kind, child_id)
);
```

summary 가 어떤 하위 summary / chunk 를 대표하는지 연결. 답변 시 drill-down 근거 추적에 사용.

#### `contradictions`

```sql
create table contradictions (
  id text primary key,
  project_id text not null,
  entity_id text,
  scope_key text,                       -- feature or section scope
  chunk_a_id text not null,
  chunk_b_id text not null,
  contradiction_score real not null,
  detector text not null,               -- nli, llm
  status text not null,                 -- candidate, confirmed, dismissed
  reason text,
  created_at text not null,
  updated_at text not null
);
```

contradiction 결과 캐시. query 시 매번 모든 chunk 쌍을 다시 비교하지 않기 위해 저장.

### Summary 계층 정의

3계층만 먼저 지원:

#### feature summary

생성 기준: 같은 entity / 같은 feature key / 같은 `section_path` / 같은 `normalized_chunk_type` 집합

예: `feature:test_mode_entry`, `feature:payment_auth_flow`, `feature:debug_toggle_behavior`

실무에서 가장 자주 쓰이는 해상도.

#### document summary

생성 기준: 동일 document 하위 chunk / feature summary 집합

예: `document:notion_prd_123`, `document:meeting_2026_05_01`

#### project summary

생성 기준: 동일 project 의 최신 document summary 집합

예: `project:ios_app_alpha`

RAPTOR 처럼 하위 정보를 재귀적으로 요약해서 상위 요약을 만든다는 점이 핵심.

### Summary 생성 플로우

문서 변경 또는 chunk 변경이 발생했을 때:

1. 변경된 document / chunk 식별
2. 영향받는 feature key 집합 계산
3. 각 feature 별 최신 current chunk 수집
4. feature summary 재생성
5. 영향받는 document summary 재생성
6. 영향받는 project summary 재생성
7. 각 summary 에 embedding / FTS 인덱싱 업데이트

#### feature summary 생성 입력

- feature 에 연결된 최신 chunk 목록
- 관련 entity 이름과 alias
- source metadata
- current / obsolete 정보
- 필요 시 직전 summary

#### feature summary 생성 규칙

- 4~8 문장 이내
- "현재 기준 동작" 우선
- 과거 변경은 1~2 문장만 언급
- source 간 합의 / 불일치 여부 표시
- 구현 세부보다 기능 의미 중심

예시:

```text
테스트 모드 진입 기능은 A 화면 우상단의 디버그 토글을 통해 시작된다. 현재 정책상 버튼 탭 시 즉시 진입하지 않고 확인 모달을 먼저 노출한다. 이후 사용자 확인 시 테스트 모드 화면으로 이동한다. 과거 문서에는 즉시 진입으로 기록된 내용이 있으나 최신 회의록과 PRD 기준으로 모달 방식이 현재 유효하다.
```

#### document summary 생성 규칙

- 문서 목적과 핵심 결정 위주
- feature summary 들의 공통 흐름을 묶음
- 회의록이면 "결정 / 변경사항" 중심
- PRD 면 "기능 정의 / 예외 / 조건" 중심

#### project summary 생성 규칙

- 전체 프로젝트의 주요 기능 축 요약
- 현재 유효한 정책 중심
- 문서 간 변경 흐름이 있으면 간단히 언급
- 너무 자세한 구현 설명 금지

### Query Scope Classifier

2단계 핵심은 질문 해상도를 먼저 구분하는 것.

| 분류 | 정의 | 예시 |
|---|---|---|
| **local** | 특정 버튼 / 화면 / API / 문장 의미 질문 | "디버그 토글 누르면 뭐 돼?" |
| **feature** | 하나의 기능 흐름 전체를 묻는 질문 | "테스트 모드 진입 UX 전체 설명해줘" |
| **global** | 프로젝트 전체 정책 / 구조 / 주제 요약 질문 | "이 프로젝트의 테스트 관련 정책 전체 정리해줘" |

#### 구현 방식

초기에는 LLM 분류보다 **rule-based classifier 우선**:

- "전체", "전반", "프로젝트", "정리", "흐름 전체" → global
- "기능", "플로우", "과정", "UX", "시나리오" → feature
- 엔티티 직접 언급 + 짧은 질문 → local

애매한 경우 local → feature 순으로 fallback.

### Retrieval 라우팅

#### local 질문

1단계 경로를 그대로 우선 사용:

1. entity alias resolve
2. chunk hybrid retrieval
3. current / recency boost
4. rerank
5. answer assembly

필요 시 feature summary 1개만 보조로 붙임.

#### feature 질문

summary 우선 retrieval 로 전환. **depth limit: feature summary 최대 5개 + drill-down chunk 최대 8개**.

1. entity / feature key resolve
2. feature summary retrieval (최대 5개)
3. 관련 하위 chunk drill-down (최대 8개, `summary_links` 따라)
4. contradiction check (read-only `contradictions` 조회)
5. answer assembly

#### global 질문

상위 summary 부터 시작. **depth limit: project 1 + document 3 + feature 5 + 대표 chunk 4~6 (총 15 항목 이내)**.

1. project summary retrieval (1개)
2. 관련 document summary retrieval (최대 3개)
3. 필요 시 feature summary drill-down (최대 5개)
4. 대표 chunk 근거 회수 (4~6개, `summary_links` 따라)
5. contradiction check
6. map-reduce 식 answer assembly

> **depth limit 의미**: GraphRAG 의 global summary retrieval 패턴처럼 상위 summary 에서 답의 구조를 먼저 잡되, drill-down 의 폭이 무한히 늘어나지 않도록 각 레벨에 상한을 둠. context 폭주 방지 + Claude 호출 비용 통제.

GraphRAG 의 global summary retrieval 패턴처럼, global question 은 상위 summary 에서 먼저 답의 구조를 잡는 방식.

### 동기 경로 latency 관리 (7a budget 대비)

7b 는 동기 경로에 `SC` · `SCOPE` 분기 · `GROUND` · `CCHECK` 4 단계가 추가됩니다. 모두 가벼운 조회·분류·판정 로직이라 추가 지연은 **10~30 ms** 이내로 예상됩니다. 따라서 7a 의 latency budget (rerank skip < 100 ms / 발동 < 300 ms) 위에 30 ms 만 더 잡으면 됩니다.

| 7a 케이스 | 7a budget | + 7b 4 단계 | 7b 합계 budget |
|---|---|---|---|
| RG = no (skip) | < 100 ms | + 10~30 ms | **< 130 ms** |
| RG = yes (발동) | < 300 ms | + 10~30 ms | **< 330 ms** |

다만 `HYB2` / `HYB3` 의 summary retrieval 정확도는 summary embedding 품질에 직결되므로 — chunk embedding 보다 신중하게 생성. 자세한 생성 규칙은 위 "feature / document / project summary 생성 규칙" 참조.

**위반 감지·대응**

7a 의 "동기 경로 latency budget" 섹션 룰을 그대로 적용합니다 (5분 윈도 3회 위반 → daemon backend 분리). 다만 7b 진입 후 30 ms 헤드룸이 SC · GROUND · CCHECK 추가로 사라진 상태라, 위반이 한 번이라도 보이면 즉시 daemon 단계로 가는 것이 안전합니다 — 7a 보다 보수적으로 운영.

### Contradiction Detection 플로우

"후보 생성 → 정밀 판정 → 캐시 → 노출" 4단계 구조.

#### 1. 후보 생성

비교 대상 축소 규칙 (모든 chunk 쌍 비교는 비용 과다, O(n²) 방지):

- 같은 `entity_id`
- 같은 `normalized_chunk_type = decision`
- 같은 `scope_key` 또는 `section_path`
- 둘 다 `is_current = true` 이거나 current 와 직전 버전 관계
- **time gap < 90 일** — 너무 오래된 쌍은 후보에서 제외

이 단계는 **규칙 기반**. 다이어그램의 `J6 → CDCAND` 가 이 단계.

#### 2. 정밀 판정

우선순위:

- 로컬 NLI 모델
- 실패 또는 low confidence 시 LLM judge fallback
- **timeout 500 ms** — 만료 시 status = `candidate` 유지하고 다음 배치에서 재시도 (1단계 RR timeout 200 ms 와 비례)

입력: chunk A · chunk B · entity / context metadata
출력: entailment / contradiction / neutral · confidence · 짧은 이유

다이어그램의 `J6 → CDCAND → CDJUDGE → CDCONF` 가 이 단계.

#### 3. 저장 — score 3 구간 분기

`CDCONF{score 구간}` 으로 NLI 결과를 3구간으로 나눠 `contradictions` 테이블에 저장. 자동 dismiss 는 **금지** — false negative 가 영구 손실되는 위험을 차단.

| 구간 | status | 의미 |
|---|---|---|
| **high** (예: ≥ 0.8) | `candidate` | NLI 가 충돌로 확신. 사용자 검토 후 `confirmed` 승격 가능 |
| **mid** (예: 0.4~0.8) | `neutral` | NLI 가 애매. 같은 entity 쌍이 재등장하거나 임계 조정 시 재검토 |
| **low** (예: < 0.4) | `neutral` | NLI 가 충돌 아님으로 본 것 — 그래도 dismissed 가 아닌 neutral 로 보존해 추적 가능 |

`confirmed` 는 사용자가 `/memory entities` 또는 별도 confirm 명령으로 명시 승격할 때만. `dismissed` 는 사용자가 명시 거부했을 때만 — 자동 처리 X. 정확한 임계치 (0.8 / 0.4) 는 **후속 결정 7b-4** 에서 측정 데이터로 확정.

다이어그램의 `CDCONF -->|high| PACK5_CAND` / `-->|mid·low| PACK5_NEUT` 가 이 흐름. 둘 다 `ENQ` 큐로 보내져 single-writer commit.

#### 4. query 시 활용

질문과 연관된 entity / feature 에 confirmed contradiction 이 있으면 답변 생성 시 표시:

```text
현재 기준으로는 확인 모달 후 진입이 맞습니다. 다만 과거 문서에는 즉시 진입으로 기록된 결정이 있으며, 기능 정의가 변경된 이력이 있습니다.
```

### Answer Assembly 규칙

"요약 + 근거 + 충돌 표시" 구조.

#### local 질문

- 현재 chunk answer 우선
- 필요 시 feature summary 1개
- 과거 변경 이력은 1줄만

#### feature 질문

- feature summary 로 서두 작성
- 대표 chunk 2~4개 근거 첨부
- conflict 있으면 중간에 별도 문장으로 표시

#### global 질문

- project summary 로 전체 구조 설명
- document / feature summary 로 세부 분기
- 중요한 current decision chunk 만 근거로 첨부
- conflict 는 "프로젝트 내 변경 / 불일치" 섹션으로 분리

#### grounding 규칙

- summary 만 단독 사용 **금지** — 최종 answer 마다 최소 1~3 개의 current chunk 근거 포함
- summary 검색 결과는 `summary_links` 테이블의 `child_kind = chunk` 항목 1~3 개를 추가 조회해 grounding context 에 함께 첨부 (다이어그램의 `GROUND` 단계)
  - SQL 형태 예: `SELECT * FROM summary_links WHERE parent_summary_id = ? AND child_kind = 'chunk' ORDER BY rank_order LIMIT 3`
  - 검색 결과에 chunk 가 이미 포함된 경우 추가 drill-down 생략
- obsolete chunk (`is_current = false`) 는 "과거 이력" 으로만 사용

### 실제 동작 시나리오

**시나리오 A — local 질문**

질문: `디버그 토글 누르면 지금 뭐 돼?`

1. alias resolve → `test_button`
2. local classifier
3. 1단계 hybrid retrieval 실행
4. 최신 decision chunk 선택
5. feature summary 1개 보조
6. contradiction 존재 시 변경 이력 한 줄 추가

출력 성격: 짧고 직접적, 최신 current 정책 우선.

**시나리오 B — feature 질문**

질문: `테스트 모드 진입 UX 전체 설명해줘`

1. feature classifier
2. `feature:test_mode_entry` summary retrieval
3. 관련 current chunk 3~5개 로딩
4. contradiction candidate 확인
5. feature summary 기반으로 흐름 설명
6. 하위 chunk 근거 인용

출력 성격: 버튼 → 모달 → 진입 흐름 순서 설명, 변경 이력 있으면 마지막에 설명.

**시나리오 C — global 질문**

질문: `이 프로젝트의 테스트 관련 정책 전체 정리해줘`

1. global classifier
2. project summary retrieval
3. 관련 document summary 2~4개 선택
4. 중요 feature summary drill-down
5. 각 summary 에서 partial answer 생성
6. 최종 종합 answer 생성
7. confirmed contradiction 있으면 별도 표시

출력 성격: 기능군 기준 구조화된 요약, 문서 간 합의 / 변경 포인트 포함.

### 배치 / 갱신 전략

실시간 전부 재계산이 아니라 **비동기 incremental 갱신**. 매 turn 무조건 재생성이 아니라 **single-writer commit 직후 변경이 감지된 entity / feature / decision 이 있을 때만** trigger — 다이어그램의 `W1 -.변경 발생 시 trigger.-> J5 / J6` edge.

#### J5 (summary rebuild) trigger

`W1` 가 commit 한 변경을 분석해 다음 중 하나가 발생한 경우에만 spawn:

- 새 문서 ingest (`documents` INSERT)
- 기존 문서 update (`documents` UPDATE)
- entity merge / split (`chunk_entities` 변경)
- supersede 상태 변경 (`supersedes_chunk_id` 갱신)
- current flag 변경 (`is_current` flip)

변경 없으면 `J5` 자체를 spawn 하지 않음.

#### 재계산 범위

- 변경된 chunk 와 연결된 feature summary 만 재생성
- 그 다음 해당 document summary 재생성
- 마지막으로 project summary 재생성

leaf 변경이 상위 summary 로 전파되는 방식. 다이어그램의 `J5 → SMTRIG → SMGEN → SMEMB → PACK4 → ENQ` 가 이 흐름.

#### J6 (contradiction detection) trigger

`W1` commit 직후 다음 중 하나가 감지될 때만 spawn:

- 새 decision chunk 생성 (`normalized_chunk_type = decision` INSERT)
- entity alias merge (같은 entity 묶음 변화)
- supersede 확정 (`supersedes_chunk_id` 갱신)
- current / current 쌍 변화

변경 없으면 `J6` 자체를 spawn 하지 않음. 다이어그램의 `J6 → CDCAND → CDJUDGE → CDCONF → PACK5_*` 가 이 흐름.

### 비동기 job 우선순위

비동기 job 이 6개로 늘어나 각자 다른 우선순위가 필요. 큐 consumer 가 같은 ENQ 에서 꺼낼 때 다음 순서:

| Job | 우선순위 | 이유 |
|---|---|---|
| `J2` response extract | 높음 | 다음 turn 의 retrieval 후보에 즉시 영향 |
| `J1` lazy fetch | 높음 | 사용자가 명시한 외부 source — 즉시 노출 가치 |
| `J5` summary rebuild | 중간 | feature / global 질문 대응 품질에 직결, 단 첫 사용까지 시간 여유 있음 |
| `J6` contradiction detection | 중간 | conflict 표시 품질에 영향, 단 즉시 노출 필수 X |
| `J4` entity refresh | 낮음 | alias 사전의 점진적 개선 |
| `J3` warm cache | 낮음 | 성능 보조 (콜드 로드 흡수), 기능 회귀 영향 X |

### 후속 결정 (구현 진입 전 좁혀야 할 세부)

| # | 항목 | 후보 | 비고 |
|---|---|---|---|
| 7b-1 | NLI 모델 선택 | mDeBERTa-v3-base-mnli-xnli / korNLI fine-tuned / 다국어 NLI | 정확도·메모리·다국어 trade. Phase 7a 임베딩 모델 결정 후 함께 잡으면 효율. |
| 7b-2 | scope classifier rule-set 시드 | 키워드 매칭 / 정규식 / 단순 LLM 보조 | 초기 rule 시드 (전체·전반·프로젝트·정리 → global, 기능·플로우·UX → feature, 그 외 → local) |
| 7b-3 | summary 갱신 빈도 | 즉시 sync / 5분 배치 / 매시간 배치 | incremental update 구현이 끝난 뒤 트래픽 측정 후 결정 |
| 7b-4 | contradiction score 3 구간 임계 + neutral 정책 | high ≥ 0.8 → `candidate` / 0.4~0.8 → `neutral` / < 0.4 → `neutral` (예시) | 초기 임계는 위 예시값으로 시작. 실제 값은 NLI 모델 결정 (7b-1) 후 첫 100~200 쌍 측정으로 캘리브레이션. `confirmed` 승격은 항상 사용자 명시 (자동 X). |

### 구현 우선순위

가장 안정적인 구현 순서 (README 다이어그램의 노드 묶음 기준):

1. `summaries`, `summary_links`, `contradictions` 테이블 추가 (이중 status enum: `candidate` / `neutral` / `confirmed` / `dismissed`)
2. **W1 commit dispatcher** — single-writer commit 결과를 분석해 변경된 entity / feature / decision 이 있으면 `J5` / `J6` spawn (incremental)
3. `J5` feature summary 생성기 + `summary_links` 연결
4. `J5` document / project summary 생성기 (상향식 전파)
5. summary embedding + FTS 인덱싱 (`PACK4`)
6. query scope classifier (`SC` 노드)
7. **retrieval routing 분기 + depth limit** (`HYB1` / `HYB2` summary 5+chunk 8 / `HYB3` proj 1+doc 3+feat 5+chunk 6)
8. **`GROUND` drill-down** — `summary_links` 따라 근거 chunk 1~3 개 추가 조회
9. **`CCHECK`** — retrieved entity 의 `confirmed` contradiction read-only 조회
10. `J6` contradiction candidate generator (same entity + decision + time gap < 90 d)
11. NLI / LLM judge 연결 + **timeout 500 ms** + **score 3 구간 분기 (`PACK5_CAND` / `PACK5_NEUT`)**
12. answer assembly 업데이트 (summary + 근거 chunk + conflict 표시)
13. **비동기 우선순위 큐** — `ENQ` consumer 가 J2/J1 (높음) → J5/J6 (중간) → J4/J3 (낮음) 순서로 처리

### 완료 조건

- "전체", "흐름", "정리" 류 질문에 chunk 나열이 아니라 구조화된 답이 나온다
- summary retrieval 후에도 실제 current chunk 근거가 함께 유지된다
- 같은 entity 의 상충 decision 이 자동 candidate 로 잡힌다
- confirmed contradiction 이 있으면 답변에서 명시적으로 드러난다
- summary rebuild 가 full rebuild 가 아니라 incremental update 로 동작한다

### 다음 액션

- **(전제)** Phase 7a 안정 운용 — 후속 결정 2-1·3-1·5-1·6-1 합의 후 SQLite 스키마 v1·hybrid retrieval·rerank 까지 머지된 상태
- **(다음 PR)** 후속 결정 7b-1~4 좁히기 — NLI 모델 / classifier rule-set / 갱신 빈도 / confirmed 임계
- **(그 다음 PR)** 명세 "구현 우선순위" 1번 (summaries · summary_links · contradictions 테이블) 부터 PR 단위로 분해

## 성능 병목 진단 — 3축 (2026-05-09)

README의 mermaid가 그리는 hook/ingestion 파이프라인에서 **현재는 괜찮으나 설계상 미래에 터질 수 있는** 3축을 사전 진단한 결과입니다. LoadMap.md "설계상 병목 후보·대응 플랜" 섹션은 큰 그림 요약이고, 이 섹션은 "왜 문제인가 / 왜 이 대안인가"의 추론 과정을 풀어 둔 자료입니다.

**계측 hook은 박혔지만 아직 활성화는 사용자 액션이 필요합니다.** (probe lifecycle = `env_gated`)

```bash
# Claude Code 를 띄운 셸에서:
export IMPRINT_PROFILE=1
# 그 후 Claude Code 세션을 새로 시작 — 매 turn 마다 stage 별 측정값이
# ~/.claude/imprint/profile.jsonl 에 JSONL 한 줄씩 누적됩니다.
```

비활성화 시 hook 추가 비용은 env 검사 한 번뿐이라 평소에는 켜둘 필요가 없습니다. 임계 근접 의심이 들거나 설계 변경 전후 비교가 필요할 때만 켜는 것을 권장합니다.

A축은 격리 환경에서 동일 파싱 로직을 인라인 Python 으로 5회씩 측정한 값(스크립트 자체의 `IMPRINT_PROFILE=1` 경로를 거치지 않은, 동일 코드의 직접 실측)이라 코드 수정 없이도 신뢰할 수 있습니다. B·C 축은 운영 환경 OAuth + MCP 의존이라 hook 활성화 후 자연스러운 사용 안에서만 데이터가 모입니다.

---

### A축 — Stop hook 의 transcript JSONL 재파싱

**stage**: `stop.transcript_reparse`

#### 무엇이 일어나는가

매 turn 종료 직후 `stop.sh` 가 Claude Code 가 넘겨준 `transcript_path`(JSONL) 의 **첫 줄부터 끝까지** 읽으면서 `type == "assistant"` 인 줄의 본문을 갱신해 마지막 assistant 응답 텍스트를 추출합니다. 추출 결과를 `events.llm_response` 로 저장하고, 백그라운드 chunk extraction 으로 넘깁니다.

#### 왜 문제가 될 수 있는가

세션 길이에 대해 O(n) 입니다. 매 turn 마다 같은 파일을 처음부터 다시 훑기 때문에, 세션이 길어질수록 동기 hook 경로가 단조 증가합니다. README mermaid 의 "동기 ≈1초 보장" 약속이 깨지면 사용자 입력 직후 한 박자 멈추는 체감이 생깁니다.

실측 (5회 median, 같은 머신):

| 파일 크기 | 줄 수 | assistant 줄 | 추출 last bytes | median ms | max ms |
|---:|---:|---:|---:|---:|---:|
| 36.6 KB | 11 | 4 | 3,665 | 0.2 | 1.2 |
| 553.7 KB | 217 | 106 | 109 | 2.7 | 3.1 |
| 3,603.3 KB | 1,199 | 498 | 1,933 | 12.1 | 14.2 |

선형 모델 ≈ `0.2 + 0.0101 × lines` ms (≈ `3.4 ms / MB`).

#### 무엇 때문에 그렇게 동작하는가

`stop.sh` 는 Claude Code 가 hook 입력 JSON 으로 `transcript_path` 만 주기 때문에, "마지막 assistant 응답"을 알려면 직접 파일을 열어 읽어야 합니다. 가장 단순한 안전 구현은 "처음부터 끝까지 훑으면서 마지막 assistant 줄만 갱신하기" 입니다 (40-74행에 그렇게 짜여 있습니다). 작성 시점엔 세션 길이가 길어질 거라는 가정이 약했고, 작은 세션에서는 1 ms 미만이라 문제가 안 보였습니다.

#### 임계점 후보

- 동기 hook 추가 지연 100 ms → ~10,000 lines / ~30 MB / ~4,000 assistants
- 동기 hook 추가 지연 500 ms → ~50,000 lines / ~150 MB / ~20,000 assistants

3.6 MB / 1,199 lines 에서 12.1 ms 라는 실측이 있고, 위 임계점은 같은 선형 모델의 외삽치입니다. 일상 세션이 5 MB 를 넘는 경우는 드물어 당장은 안전 영역이지만, "하루 종일 이어가는 세션" 패턴에서 한 번씩 임계 근접이 생길 수 있습니다.

#### 대응 후보

1. **tail-only seek** *(가장 단순)*

   파일 끝에서 ~64 KB 만 `f.seek(max(0, file_bytes - 64*1024))` 로 잡고, 첫 incomplete line 한 줄만 버린 뒤 그 뒤를 line 단위로 읽으면서 마지막 assistant 줄을 추출합니다. assistant 응답 한 건은 보통 1~30 KB 라 64 KB 윈도면 거의 항상 충분하고, 특이하게 큰 응답이면 윈도를 두 배씩 키우며 retry 해도 됩니다.
   - **왜 이 안인가**: 코드 변경 ~10 줄, 추가 자료구조 0 개, 기존 동작과 동일 결과(마지막 assistant 텍스트 한 건). simplicity first 원칙에 정확히 맞습니다.
   - **트레이드오프**: 64 KB 안에 어떤 assistant 줄도 없는 극단 케이스(매우 긴 단일 응답이 64 KB 를 넘어가는 경우)에서는 retry 한 번이 추가됩니다 — 흔한 패턴은 아닙니다.

2. **incremental offset 저장** *(정확하지만 상태 추가)*

   `~/.claude/imprint/transcript-offsets/<session_id>.txt` 에 마지막으로 읽었던 byte offset 을 기록하고, 다음 turn 은 그 위치부터만 read 합니다.
   - **왜 후순위인가**: 정확하지만 새 디렉토리 + 세션 ID 별 상태 파일 + 정합성(파일 truncate / 세션 재개) 처리가 추가됩니다. 1번이 임계 한참 아래까지 흡수해 주므로 1번이 부족한 시점에야 진입할 가치가 생깁니다.

#### 다음 액션

- IMPRINT_PROFILE=1 활성화 후 `stop.transcript_reparse.dur_ms` 가 80 ms 를 한두 번 넘기 시작하면 1번(tail-only) 진입.
- 그때까지는 measurement 만 모으고 코드는 손대지 않습니다(CLAUDE.md Surgical Changes).

---

### B축 — 외부 fetch payload 폭주 (Notion / Slack)

**stages**: `fetch_slack_url`, `fetch_notion_url`, `fetch_slack_keywords`, `fetch_notion_keywords`, `cmd_lazy_fetch.enter|exit`, `call_claude`

#### 무엇이 일어나는가

UserPromptSubmit hook 의 백그라운드 spawn 이 `cmd_lazy_fetch` 를 호출하면 (1) 사용자 prompt 안의 Slack permalink / Notion URL 을 정규식으로 뽑고, (2) 처음 3개 URL 까지만 `claude -p haiku` + read-only MCP 로 fetch + sectioning 하며, (3) `<project>/.imprint/sources.json` 에 등록된 채널·페이지에 대해 키워드 검색을 한 번씩 더 돌립니다. 결과는 `memory_chunks` 에 INSERT 되고 dedup 키는 `metadata_json.url` 입니다.

#### 왜 문제가 될 수 있는가

여러 가지 silent failure mode 가 누적될 수 있습니다.

1. **큰 Notion 페이지의 sectioning 부하**
   `fetch_notion_url` 은 H1/H2/H3 heading 을 각각 별도 chunk 로 보존합니다(README "처리 규칙" 참조). 페이지가 클수록 `claude -p haiku` 가 모든 heading 을 JSON 으로 뱉어야 하므로 응답 토큰이 늘고 wall clock 이 늘어 `CLAUDE_TIMEOUT_FETCH = 45 s` (env override 가능) 임박합니다. 타임아웃이 발생하면 `call_claude` 가 None 을 반환하고 그 turn 의 chunk 는 통째로 비노출(silent skip + plugin.log warn).

2. **prompt 내 URL 4개 이상에서 silent skip**
   `lazy_fetch:812` `for url in list(dict.fromkeys(SLACK_PERMALINK_RE.findall(prompt)))[:3]` 처럼 처음 3개만 처리합니다. Notion 도 같은 패턴입니다. 사용자가 5개를 붙여넣으면 4·5번째 URL 은 fetch 없이 사라지지만 plugin.log 에 별도 경고가 없어 사용자가 모르고 지나갑니다.

3. **dedup TTL 무한**
   `chunk_url_exists` 는 같은 URL 의 chunk 가 하나라도 있으면 fetch 자체를 skip 합니다(README dedup 규칙). Notion 페이지가 갱신되거나 Slack thread 에 새 reply 가 달려도 강제 `/memory refresh` 전엔 옛날 chunk 만 prepend 됩니다 — 즉 시간이 갈수록 stale 비율이 올라갑니다.

4. **dedup 미스 — 같은 페이지의 chunk N개 vs 단일 URL 매칭**
   `fetch_notion_url` 은 한 페이지를 H1/H2/H3 별 chunk N 개로 쪼개고 각 chunk 의 `metadata_json.url` 에 같은 page URL 을 박습니다. 처음 fetch 후에는 페이지 URL 단일 매칭으로 skip 됩니다 — 이건 의도된 동작입니다. 다만 이 구조 때문에 (3) 의 stale 누적이 chunk 수만큼 더 크게 보입니다.

#### 무엇 때문에 그렇게 동작하는가

`[:3]` 상한과 `claude -p haiku` 단일 호출은 **한 turn 의 백그라운드 비용을 묶기 위한 의도된 결정**입니다. 사용자가 URL 을 무한히 넣어도 fetch 가 turn 당 최대 6 회 (Slack 3 + Notion 3) + keyword 검색 2 회로 묶입니다. URL > 3 silent skip 은 이 의도의 부산물이고, dedup TTL 무한은 사용자가 명시 갱신하기 전까지 외부 system 트래픽을 0 으로 만들기 위한 결정입니다 (README "갱신" 항목).

당시엔 "사용자가 모르는 silent skip" 보다 "사용자가 모르게 큰 fetch 가 반복되는" 시나리오를 더 위험하다고 본 trade 라 보면 자연스럽습니다.

#### 임계점 후보 (코드 분석, IMPRINT_PROFILE=1 데이터로 갱신 예정)

- 단일 fetch payload(`fetch_*_url.payload.payload_bytes`) > 50 KB → `claude -p haiku` 단일 응답으로 모든 heading 을 JSON 직렬화하기 어려움.
- 단일 `fetch_*_url.dur_ms` > 30,000 → 45 s 타임아웃의 67%, 다음 turn 에 chunk 비노출 위험.
- prompt 내 동일 source URL > 3 → 4번째부터 silent skip (현 상태).
- chunk `fetched_at` age > 14 d → stale 위험 — 분류·정책 도입 후보.

#### 대응 후보

1. **URL 개수 cap 을 silent 에서 visible 로 승격** *(가장 단순)*

   `lazy_fetch` 의 `[:3]` 분기에서 잘려나간 URL 수를 세서 `plugin.log` 에 `WARN: lazy_fetch dropped {n} URLs (cap=3) — first 3 fetched` 한 줄 emit. 코드 변경 ~3 줄.
   - **왜 이 안인가**: 사용자가 자기 prompt 의 어떤 URL 이 무시됐는지 추적 가능해지고, 동작은 그대로 두므로 회귀 위험 0. simplicity first.
   - **다음 단계**: 빈도가 높으면 cap 자체를 5·7로 올리는 검토.

2. **`fetched_at` TTL → stale flag** *(중간 복잡도)*

   `metadata_json.fetched_at` 이 N일(예: 14d) 지난 url-dedup chunk 는 `/memory list` / `/memory show` 가 `[stale]` 태그로 표시. 자동 refresh 는 하지 않고, 사용자가 보고 `/memory refresh <url>` 을 칠 수 있게 신호만 줍니다.
   - **왜 이 안인가**: TTL 무한 정책 자체는 외부 트래픽 보호로 유지하면서, "stale 인지 알기"의 사각지대만 좁힙니다. 자동 refresh 는 Notion 페이지가 사일런트로 새로 fetch 되는 부작용이 있어 의도적으로 피합니다.
   - **트레이드오프**: 14d 임계는 임의값 — 측정 데이터가 모이면 source 별로 다르게 잡을 수 있습니다.

3. **Notion chunking 단순화 (H1 only)** *(상대적으로 큰 변경, 보류)*

   현재 H1/H2/H3 모두 별도 chunk 인데, 큰 페이지는 chunk 수십 개로 쪼개져 검색 후보가 분산됩니다. H1 단위로만 chunk 하고 H2·H3 는 본문에 inline 시키면 chunk 수가 줄고 sectioning 응답도 짧아집니다.
   - **왜 후순위인가**: 검색 정밀도 trade — H3 단위로 검색되던 사용자 흐름이 깨질 수 있어 측정 데이터를 본 뒤 결정합니다.

#### 다음 액션

- IMPRINT_PROFILE=1 활성화 후 stage 들의 dur_ms / payload_bytes 분포가 모이면 임계점 수치를 재조정.
- "URL > 3 cap 잘림" 빈도가 한 번이라도 나오면 1번(visible cap)부터 진입 — 코드 ~3 줄, 회귀 위험 0.

---

### C축 — 동시 백그라운드 부하 (UPS lazy-fetch + Stop extract 겹침)

**stages**: `ups.spawn`, `cmd_lazy_fetch.enter|exit`, `stop.spawn`, `cmd_extract.enter|exit`, `call_claude`

#### 무엇이 일어나는가

매 turn 마다 두 hook 이 백그라운드 프로세스를 spawn 합니다.
- `UserPromptSubmit` → `cmd_lazy_fetch` (외부 fetch + chunk INSERT)
- `Stop` → `cmd_extract` (응답에서 chunk 추출 + INSERT)

각 프로세스는 `claude -p haiku` 를 호출하고 같은 `~/.claude/imprint/app.sqlite` 에 INSERT 합니다.

#### 왜 문제가 될 수 있는가

turn 사이클이 빠를수록 두 프로세스가 겹쳐 동시 실행됩니다.

1. **claude CLI 동시 실행 2개**
   turn N 의 `cmd_extract` 가 30 s 안에 끝나지 않은 상태에서 turn N+1 의 prompt 가 제출되면 `cmd_lazy_fetch` 가 새로 뜹니다. 두 프로세스는 각각 `claude -p haiku` 서브프로세스를 spawn 하므로 OAuth refresh 가 두 번 일어나고 API 트래픽이 곱해집니다.

2. **SQLite write 경합**
   둘 다 `memory_chunks` 에 INSERT 합니다. 이미 schema.sql 에 `PRAGMA journal_mode = WAL` + `PRAGMA busy_timeout = 5000` 가 켜져 있어 일반 동시 INSERT 는 흡수됩니다 — 즉 즉각적 위험은 낮습니다. 다만 5 s busy_timeout 안에 못 끝나는 long write 가 있으면 그 turn 의 INSERT 는 silent fail 하고 다음 turn 부터 그 chunk 가 검색 대상에서 빠집니다.

3. **좀비 spawn 누적**
   노트북 슬립/재개, 네트워크 단절, claude CLI 가 응답 없이 멈추는 등의 상황에서 `cmd_lazy_fetch` / `cmd_extract` 가 enter 만 찍고 exit 가 안 떨어질 수 있습니다. 사용자에겐 보이지 않는 백그라운드 프로세스가 누적되어 시스템 리소스를 점유합니다.

#### 무엇 때문에 그렇게 동작하는가

"hook 은 사용자 turn 을 차단하지 않는다" 는 CLAUDE.md 규약을 지키기 위해 무거운 작업을 모두 백그라운드로 분리한 결과입니다 (`( ... ) & + disown`). 동시성 제어를 명시적으로 두지 않은 이유는 (1) WAL + busy_timeout 으로 SQLite 는 보호되고, (2) `IMPRINT_BYPASS_HOOKS=1` 가드로 hook 무한 재귀는 차단되며, (3) 일반 사용 패턴에서 turn 간격이 30 s 이상이라 겹침이 거의 없을 거라는 가정이 있었기 때문입니다.

`/loop`, `ooo auto`, 또는 사용자가 빠르게 prompt 를 던지는 패턴은 이 가정을 벗어납니다.

#### 이미 있는 보호

- `schema.sql` 의 `PRAGMA journal_mode = WAL` (concurrent read + single write)
- `schema.sql` 의 `PRAGMA busy_timeout = 5000` (lock 5 s 까지 자동 retry)
- `IMPRINT_BYPASS_HOOKS = 1` 재귀 가드 — `ingestion.py` 가 spawn 하는 `claude` 서브프로세스가 다시 hook 을 타며 무한 재귀하지 않게.
- `IMPRINT_DISABLE_EXTRACT = 1` escape hatch — 사용자가 chunk 추출만 끄고 싶을 때.

#### 임계점 후보 (활성화 후 수치로 갱신)

- 5분 윈도에서 enter 만 있고 exit 없는 spawn 이 2건 이상 → CPU·OAuth 부하 알림.
- `call_claude.dur_ms` 동시 실행 > 2 → API 큐잉 대기 발생.
- profile.jsonl 의 enter ↔ exit 짝이 30 s 초과 미매칭 → 좀비 후보.

#### 대응 후보

1. **lazy-fetch lockfile** *(가장 단순)*

   `~/.claude/imprint/locks/lazy-fetch.lock` 에 PID + 시작시각을 적고, `cmd_lazy_fetch` 진입 시 lock 파일이 존재하고 PID 가 살아 있으면 silent skip + plugin.log info. lock 파일이 stale (PID 죽음) 이면 덮어쓰기.
   - **왜 이 안인가**: turn N+1 의 lazy-fetch 는 어차피 turn N+2 prefill 에서나 노출됩니다. 한 turn 빠지더라도 손실이 미미하고, 코드 변경은 작은 함수 한 개로 끝나고 외부 라이브러리 추가 0.
   - **트레이드오프**: 사용자가 빠른 turn 을 연속으로 치면 일부 turn 의 fetch 가 빠집니다 — 다음 turn 에 자연스럽게 다시 잡히므로 누적 손실은 0 에 가깝습니다.

2. **좀비 detection** *(분석 도구 차원)*

   `/memory stats` 가 profile.jsonl 을 읽어 enter ↔ exit 짝을 맞추고, 30 s 초과 unmatched enter 수를 "stale spawn" 으로 표시. 자동 kill 은 하지 않고 사용자에게 보고만 합니다.
   - **왜 이 안인가**: 자동 kill 은 정상 fetch 를 중단시킬 위험(특히 큰 Notion 페이지). 사용자가 보고 결정하게 두는 게 안전합니다.

3. **단일 writer 큐** *(보류, 측정 후 결정)*

   여러 백그라운드가 SQLite write 를 단일 큐에 보내고 한 프로세스가 직렬화. WAL + busy_timeout 만으로 부족하다고 판단되는 경우에만 진입.
   - **왜 후순위인가**: 추가 데몬이 필요하고 기존 hook 단순성을 깹니다. 측정해서 BUSY 빈도가 의미 있게 나올 때만 검토합니다.

#### 다음 액션

- IMPRINT_PROFILE=1 활성화 후 enter ↔ exit 짝짓기 데이터로 (a) 동시 실행 빈도, (b) 좀비 빈도, (c) BUSY 빈도를 한 주씩 모음.
- 동시 실행이 5분 윈도에 2건 이상 관찰되면 1번(lockfile) 진입.
- 좀비가 한 번이라도 관찰되면 2번(`/memory stats` 표시) 진입.
- BUSY 가 한 번도 안 나면 3번(단일 writer 큐) 는 영구 보류.

---

### 측정 → 의사결정 흐름

```
IMPRINT_PROFILE=1 활성화
  → ~/.claude/imprint/profile.jsonl 누적
  → stage 별 분포 (dur_ms / payload_bytes / chunks / rc / err)
  → 임계점 후보 수치 갱신 (이 문서 + LoadMap.md)
  → 임계 도달 시 해당 축의 1번(simplicity first) 대응 진입
  → fix 직후 측정 비교 (계측 hook 그대로 유지)
  → 안정 확인 후 다음 축으로 이동
```

계측 hook 자체는 영구 코드(env_gated)로 남기고, 영구 fix 진입은 별도 사이클로 분리해 진행합니다.

## Chunk 분류 2단계 (대기)

`metadata.source` / `page_id`를 generated column으로 승격하고 인덱스를 추가한다. 검색 체감이 느려진 시점에 점진 도입.

```sql
ALTER TABLE memory_chunks ADD COLUMN
  meta_source TEXT GENERATED ALWAYS AS (json_extract(metadata_json,'$.source')) VIRTUAL;
ALTER TABLE memory_chunks ADD COLUMN
  meta_page_id TEXT GENERATED ALWAYS AS (json_extract(metadata_json,'$.page_id')) VIRTUAL;
CREATE INDEX idx_chunks_source ON memory_chunks(project_id, meta_source);
CREATE INDEX idx_chunks_page ON memory_chunks(project_id, meta_page_id);
```

진입 조건: `chunk_url_exists` / `cmd_refresh` / prefill 검색에서 row-level `json_extract` 비용이 체감될 때. 현재 28건 규모에서는 측정 가능한 차이가 없어 보류. 1단계(외부 source `chunk_type` 분리)의 사유와 두 단계로 끊은 이유는 `HISTORY.md` 2026-05-09 참조.

## TODO — 다음 세션에서 이어서

### TODO 1. Chunk lifecycle 인터뷰 라운드 (deferred)

다뤄야 할 미해결:
- **dedup 정책**: 같은 의미 chunk가 여러 turn에서 누적될 때 — 자동 dedup 룰? 사용자 명령? 무시 후 검색 단계 dedup?
- **자동 pin 룰**: high-confidence decision은 자동 pin? confidence 임계치? 사용자 명시 pin만?
- **prefill 검색 ranking 가중치**: `pinned DESC, created_at DESC, BM25` 외에 source별·chunk_type별 가중? D17의 keywords union 점수 합산 방식?

진입 명령: `/ouroboros:interview chunk lifecycle (dedup·자동 pin·검색 ranking 가중치)`

### TODO 2. 보안·운영 인터뷰 라운드 (deferred)

다뤄야 할 미해결:
- **redaction 정규식**: 어떤 패턴(`sk-`, `xoxb-`, JWT, IP, email...)을 어디 단계에서(chunk insert 전 / FTS 인덱싱 시)? 사용자 정의 추가 가능?
- **plugin.log 회전**: 크기·날짜 기반 회전 정책. 압축? 며칠 보관?
- **반복 실패 사용자 알림**: silent fail이 누적될 때 statusline·session-start prepend로 보고할지. 임계치?
- **conversation_id 관리**: 한 SessionStart마다 새 conversation? idle 시간 기준 분리?

진입 명령: `/ouroboros:interview 보안·운영 (redaction·log 회전·에러 알림·conversation_id)`

### TODO 3. 사용자 환경 검증

1. iOS 팀 멤버 1명이 브랜치 checkout 후 자기 사내 프로젝트에서 1주 정성 검증 (AC5)
2. `IMPRINT_ALLOWED_TOOLS_FETCH` 가 사용자 등록 Slack/Notion MCP 이름과 일치하는지 확인 (각자 다를 수 있음)
3. plugin.log에서 `WARN: claude -p` 빈도 모니터링 — 일정 임계 초과 시 timeout 조정

## 단기 Watch List

- Stop hook의 `transcript_path` 포맷은 Claude Code 내부 구조에 의존 — Claude Code 버전 업그레이드 시 깨질 수 있어 plugin.log에서 `stop logged` 로그 누락 여부를 정기 확인.
- `IMPRINT_BYPASS_HOOKS` 가드가 빠진 새 hook 추가 시 ingestion 무한 재귀 재발 위험 — hook 추가 시 가드 한 줄 누락 점검.

## 다음 세션 시작 시 추천 픽업 지점

1. **남은 인터뷰 라운드** — TODO 1·2를 별도 세션에서 `/ouroboros:interview ...`로 재개. Seed v0.6이 immutable spec이므로 새 결정은 D25부터. 보안·운영 인터뷰(TODO 2)는 redaction이 도입된 지금 더 자연스러운 시점.
2. **사용자 환경 검증** — TODO 3을 iOS 팀에 위임하고 plugin.log에서 `WARN: claude -p` 빈도 모니터링.
3. **Phase 5 진입 (Workflow skill)** — `/commit-message`, `/pr-draft`, `/recap`, `/handoff`. Phase 3 마무리·advisor 제거가 끝났으니 다음은 사용자가 매일 트리거할 새 명령군.
4. **Chunk 분류 2단계** — 검색 체감 저하 시 진입(metadata generated column + 인덱스).
