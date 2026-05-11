# Handoff — 다음 세션 픽업

**문서 책임**
- 본 문서는 **단기**: 즉시 다음에 손댈 검토 안건, deferred TODO, 측정 후 캘리브레이션 항목, 다음 세션 시작 시 픽업 지점만 담는다.
- **큰 그림**(비전·Phase 정의·아키텍처·완료/미시작 단계·위험 요소)은 `LoadMap.md` 참조.
- **결정 사유 로그**(왜 그렇게 바꿨는지·폐기한 대안)는 `HISTORY.md` 참조.
- 구현된 동작·설치·전체 플로우 다이어그램은 `README.md` 참조.

최종 업데이트: 2026-05-11.

## 완료된 retrieval 인프라 (Phase 7a/7b 요약)

`refactor/phase_7a` 와 `refactor/phase_7b` 브런치에 머지된 retrieval + ingestion 파이프라인. 결정 사유와 폐기한 대안은 `HISTORY.md` 의 다음 항목 참조:

- 2026-05-10 Phase 7a 7개 결정 (스택·임베딩·chunk_type·alias·supersedes·hosting·rerank)
- 2026-05-10 Phase 7a 후속 결정 7건 락인 (BGE-M3 1024 / 매핑표 / 정규식 / Python module / lazy spawn / LRU 64 / SQLite queue)
- 2026-05-10 Phase 7b 후속 결정 4건 락인 (mDeBERTa-v3 / rule-based scope / 즉시 sync / 0.8·0.4 임계)
- 2026-05-10 Phase 7b 우선순위 11 완료 (NLI primary + LLM judge fallback chain)

스키마는 `scripts/imprint/lib/schema.sql` 한 파일 안에 모두 idempotent. `SessionStart` hook 이 매 세션마다 적용.

ML 의존성(transformers / sentence-transformers / sqlite-vec) 은 모두 lazy 로더 + opt-in. 미설치 시 `claude -p haiku` LLM judge / FTS-only 검색으로 안전 fallback. 자세한 설치는 `INSTALL.md` "선택: ML 의존성" 참조.

## 보안 — Redaction coverage 갭 (2026-05-11 관찰)

**현상**. 사용자가 GitHub token 관련 대화를 한 turn 에서 token 문자열이 events 테이블에 raw 로 저장된 사례가 관찰됨. 토큰 형식(`gh[pousr]_...`)이 `redact-rules.default.json` 의 default 룰에 일치함에도 불구하고 redaction 이 적용되지 않음.

**원인**. `redact_text` (`lib/common.sh:96`) 가 호출되는 곳은 `/memory remember --redact` 옵트인 경로 한 군데뿐 (`memory.sh:85`). raw 저장하는 두 INSERT path 는 redaction 을 거치지 않음.

- `user-prompt-submit.sh:47-50` — `events.kind='user_message'` INSERT (사용자 prompt 원문)
- `stop.sh:120-123` — `events.kind='llm_response'` INSERT (assistant 응답 원문)
- `stop.sh:131` 뒤의 chunk extraction path 도 raw 텍스트를 stdin 으로 넘김 — `lib/ingestion.py extract` 가 자체 redaction 을 하지 않으면 chunk 단계까지 누출 전파.

`sql_escape` 는 SQL injection 방지(작은 따옴표 escaping)이지 redaction 이 아님.

**우선순위**. 실제 token 누출이 관찰된 회귀이므로 Phase 5 진입과 무관하게 별도 패치로 처리. TODO 2 의 "보안·운영 인터뷰" 라운드 안건이지만, 인터뷰 없이 결정 가능한 단순 갭 (호출 지점 추가 + 패턴 보강) 부분만 먼저 진입 가능.

**대응 후보**.

1. **자동 redaction 진입점 통합** *(가장 단순)*

   `user-prompt-submit.sh` 와 `stop.sh` 에서 `db_exec` INSERT 직전에 `text=$(redact_text "$text")` 한 줄 추가. ingestion.py extract 진입 직전(`stop.sh:128-129` 의 `TMP_BG` 작성) 에도 같은 줄 추가. 호출 비용은 python3 spawn 1 회 / turn — 동기 hook 안에서 이미 다른 python3 spawn (transcript 재파싱) 이 일어나므로 추가 영향은 ms 단위.

   - **왜 이 안인가**: 코드 변경 ~3 줄, 회귀 위험 0 (모든 raw 경로가 같은 룰셋을 통과). simplicity first.
   - **트레이드오프**: 정규식 false positive 로 정상 문자열이 마스킹될 수 있음 — 룰셋이 보수적인 패턴(접두사 + 길이) 만 잡고 있어 실 사용에서 false positive 는 드묾.

2. **default 룰셋 보강** *(병행)*

   현재 default 룰셋(`lib/redact-rules.default.json`) 에 누락:
   - **GitHub fine-grained PAT**: `github_pat_[A-Za-z0-9_]{80,}` — 현 `gh[pousr]_` 룰이 못 잡음.
   - **비밀번호 키워드 컨텍스트**: `(password|pw|비밀번호|passwd)\s*[:=]\s*\S+` — 자유 텍스트 안의 비밀번호 노출.
   - **신용카드 16자리 + Luhn 검증**: 네 묶음 4자리 (`\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}`) + Python re.sub callback 에서 Luhn 체크로 false positive 억제.
   - **한국 주민등록번호**: `\d{6}-\d{7}`.
   - **bearer / authorization 헤더**: `(?i)bearer\s+[A-Za-z0-9._-]{20,}` · `(?i)authorization:\s*\S+`.

   사용자 정의 추가 경로(`~/.claude/imprint/redact-rules.json` 우선) 는 이미 있어 룰 파일만 갱신.

3. **schema-side trigger** *(보류, 측정 후)*

   SQLite trigger 로 `events` / `memory_chunks` INSERT 시 redaction 강제. 호출 경로 누락에 대한 영구 방어지만, SQLite 안에서 정규식 호출은 추가 확장(`sqlite3_create_function`) 이 필요해 의존성 증가. 1+2 로 충분히 흡수되면 영구 보류.

**다음 액션**.

- 1번(`user-prompt-submit.sh`, `stop.sh`, `ingestion.py extract` 진입 직전 `redact_text` 호출) 을 patch 한 PR 한 건.
- 2번(default 룰셋 보강) 을 별도 PR 한 건 — 룰 추가는 코드 변경 0, JSON 갱신만.
- 두 PR 모두 머지 후 `events` 테이블의 token-shaped 문자열을 grep 으로 한 번 청소 (사용자 권한 액션, plugin 이 자동 청소하지 않음).

## 다음 액션

다음 PR 단위로 분해 가능한 즉시 픽업 후보:

1. **Phase 5 (Workflow skill)** — `/commit-message`, `/pr-draft`, `/recap`, `/handoff`. retrieval 인프라가 안정 운용되는 지금이 워크플로 skill 만들 자연스러운 시점.
2. **남은 인터뷰 라운드** — TODO 1 (chunk lifecycle: dedup / 자동 pin / 검색 가중치) · TODO 2 (보안·운영: redaction / log 회전 / 에러 알림 / conversation_id). 본문 "TODO" 참조.
3. **retrieval 측정 → 캘리브레이션** — `IMPRINT_PROFILE=1` 활성화 후 한 주 데이터 수집 → contradiction 임계 (`HIGH=0.8`, `MID=0.4`) · daemon 분리 시점 · summary LLM vs deterministic 비교.
4. **사용자 환경 검증** — iOS 팀 멤버 1명이 사내 프로젝트에서 1주 정성 검증, plugin.log 의 `WARN: claude -p` 빈도 모니터링.
5. **entity merge / split UI** — `entities` CLI 가 confirm/reject 만 지원. NER 이 같은 entity 를 분리 등록한 케이스(예: `test_button` vs `debug_toggle`)를 합치는 명령 필요.
6. **Chunk 분류 2단계** — 검색 체감 저하 시 진입. 본문 "Chunk 분류 2단계" 참조.

## 다이어그램 노드 ↔ 구현 매핑

`README.md` 의 "전체 플로우 다이어그램" 노드와 실제 구현 위치 정리. 미구현 노드 0개.

**동기 경로 (User Prompt → Claude 응답):**

| 노드 | 의미 | 구현 |
|---|---|---|
| `LOG` | events.user_message 기록 | 기존 `scripts/imprint/user-prompt-submit.sh` |
| `QN` | query normalize | `retrieval/normalize.py::normalize_query` |
| `SC` | scope classifier | `retrieval/scope.py::classify` |
| `RES` | entity alias resolve | `retrieval/entity.py::resolve_in_query` |
| `QEMB` | query embedding | `retrieval/embedding.py::embed_text` |
| `SCOPE` | scope 분기 | `retrieval/routing.py::routed_retrieve` |
| `HYB1` | chunk hybrid retrieval | `retrieval/retrieve.py::_fts_search` + `_vector_search` |
| `HYB2` | feature summary retrieval | `retrieval/routing.py::_retrieve_summaries(level='feature')` |
| `HYB3` | project/document summary | `retrieval/routing.py::_retrieve_summaries(level=...)` |
| `RRF` | RRF fusion | `retrieval/retrieve.py::retrieve` (RRF 단계) + `routing.py::_retrieve_summaries` |
| `BOOST` | is_current + recency + entity coverage | `retrieval/retrieve.py::retrieve` (BOOST 단계) |
| `RG` | rerank 게이트 | `retrieval/retrieve.py::retrieve` (RG 게이트) |
| `RR` | cross-encoder rerank | `retrieval/rerank.py::rerank` |
| `RROK` | rerank timeout 분기 | `retrieval/rerank.py::rerank` (200ms watcher) |
| `GROUND` | summary_links drill-down | `retrieval/routing.py::_ground_drilldown` |
| `CCHECK` | confirmed contradiction read-only | `retrieval/routing.py::_ccheck` |
| `CTX` | 구조화 context prepend | `retrieval/assembly.py::format_for_claude` / `format_routed_for_claude` |

**비동기 ingestion (BG side):**

| 노드 | 의미 | 구현 |
|---|---|---|
| `J1` | lazy fetch (Slack/Notion) | 기존 `scripts/imprint/lib/ingestion.py` |
| `J2` | response extract | 기존 `scripts/imprint/lib/ingestion.py` |
| `J3` | retrieval warm cache | `retrieval/embedding.py::_try_load_model` lazy spawn |
| `J4` | entity NER | `retrieval/ner.py::extract_for_document` + `refresh_aliases` |
| `J5` | summary rebuild | `retrieval/dispatch.py::handle_payload(kind=summary_regen)` → `summary.regenerate_for_document` |
| `J6` | contradiction detection | `retrieval/dispatch.py::handle_payload(kind=contradiction_scan)` → `contradiction.scan_and_store` |
| `WC` | warm cache manager | `retrieval/embedding.py::_try_load_model` (process-wide 싱글톤) |
| `ANL` / `EX` | claude haiku 분류 | 기존 `lib/ingestion.py` |
| `URL` / `FETCH` / `KW` | URL 추출 → MCP fetch / 키워드 검색 | 기존 `lib/ingestion.py` |
| `SPL1` / `SPL2` | chunk split | `retrieval/chunking.py::split_document` |
| `CP1` / `CP2` | context_prefix 생성 | `retrieval/ingest.py::_generate_context_prefix` |
| `EMB1` / `EMB2` | chunk embedding | `retrieval/embedding.py::embed_texts` |
| `NEREXT` | chunk → entity mention | `retrieval/ner.py::extract_for_chunk` |
| `PACK1` / `PACK2` | chunk payload | `retrieval/ingest.py::ingest_document` |
| `PACK3` | entity candidate payload | `retrieval/ner.py::extract_for_chunk` (entity_aliases status=pending) |
| `PACK4` | summary payload | `retrieval/summary.py::_upsert_summary` |
| `PACK5_CAND` / `PACK5_NEUT` | contradiction payload | `retrieval/contradiction.py::scan_and_store` (status 분기) |
| `ENQ` | ingest queue | `retrieval/ingest_queue.py::enqueue` (priority 별) |

**single-writer commit chain:**

| 노드 | 의미 | 구현 |
|---|---|---|
| `DEDUPE` | hash dedupe | `retrieval/ingest.py::upsert_document` (checksum 비교) |
| `VRES` | version resolver | `retrieval/version.py::find_supersede_candidates` + `mark_superseded` |
| `RTYPE` | record type 분기 | `retrieval/dispatch.py::handle_payload` (kind 별 라우팅) |
| `CONF` | entity confidence 분기 | `retrieval/ner.py::extract_for_chunk` (`AUTO_CONFIRM_THRESHOLD=0.9`) |
| `W1` | single writer commit | `retrieval/ingest_queue.py::drain` + `dispatch.py::handle_payload` |
| `W2` | entity review queue | `retrieval/entity.py::add_alias` (status='pending') |
| `ENTS` | entities skill | `retrieval/cli.py::cmd_entities` (list-pending / confirm / reject) |

**판정 노드 (contradiction):**

| 노드 | 의미 | 구현 |
|---|---|---|
| `CDCAND` | contradiction candidate 생성 | `retrieval/contradiction.py::candidate_pairs_for_project` |
| `CDJUDGE` | NLI / LLM judge | `retrieval/contradiction.py::_judge_pair` (NLI primary → LLM fallback → rule retry) |
| `CDCONF` | score 3구간 분기 | `retrieval/contradiction.py::_classify_status` |

**환경 변수 (lifecycle 라벨):**

| 라벨 | 노드 | 비활성화 환경변수 |
|---|---|---|
| `(sync)` 가벼움 | `QN` · `SC` · `RES` · `RRF` · `BOOST` · `GROUND` · `CCHECK` · `CTX` | (항상 ON) |
| `(sync/daemon-ready)` | `QEMB` · `HYB*` · `RR` | `IMPRINT_DISABLE_EMBEDDING=1` · `IMPRINT_DISABLE_RERANK=1` |
| `(async)` BG | `J1`~`J6` 와 그 하위 노드 | inline 모드는 ingest_queue drain 으로 처리 |
| `(async/single-writer)` | `DEDUPE` · `VRES` · `W1` | (항상 ON, single-writer 직렬 commit) |
| ML 옵션 | `QEMB` (BGE-M3) · `RR` (cross-encoder) · `CDJUDGE` (NLI / LLM) · `NEREXT` (LLM NER) | `IMPRINT_DISABLE_EMBEDDING/RERANK/NLI/LLM_JUDGE/NER_LLM/SQLITE_VEC=1` |

## 동기 경로 latency budget 위반 대응

표 자체는 `README.md` 의 동일 표. 위반 감지·대응:

- `IMPRINT_PROFILE=1` 시 모든 `(sync)` / `(sync/daemon-ready)` 노드가 진입/탈출 wall clock 을 `~/.claude/imprint/profile.jsonl` 에 기록.
- 같은 budget 위반이 5분 윈도에 3회 이상 → 가장 무거운 노드부터 daemon 분리 (`QEMB` / `HYB*` / `RR`). inline-first + daemon-ready abstraction 이 이미 박혀 있어 호출 측 코드 변경 없이 swap.
- `QEMB` 콜드 로드는 `J3` warm cache 가 1차 방어, daemon 분리가 2차.

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
   둘 다 `memory_chunks` 에 INSERT 합니다. 이미 schema.sql 에 `PRAGMA journal_mode = WAL` + `PRAGMA busy_timeout = 5000` 가 켜져 있어 일반 동시 INSERT 는 흡수됩니다 — 즉 즉각적 위험은 낮습니다. 다만 5 s busy_timeout 안에 못 끝나는 long write 가 있으면 그 turn 의 INSERT 는 silent fail 하고 다음 turn 부터 그 chunk 가 검색 대상에서 빠집니다. **참고**: Phase 7a 의 single-writer ingest queue (`PACK* → ENQ → DEDUPE → VRES → CONF → W1`) 가 이 축의 영구 대응으로 자연 흡수되어, 새 retrieval ingestion 경로는 직렬 commit. 다만 기존 `memory_chunks` 직접 INSERT path 는 여전히 두 hook 이 별도로 쓰는 구조라 이 진단은 유효.

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
- Phase 7a single-writer ingest queue — retrieval ingestion path 는 직렬 commit (기존 memory_chunks 직접 INSERT 와 별개).

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

3. **단일 writer 큐 — 기존 memory_chunks path 도** *(보류, 측정 후)*

   retrieval ingestion 은 이미 single-writer 큐를 거치지만, 기존 `memory_chunks` 직접 INSERT path (Phase 1~3) 는 여전히 두 hook 이 별도 write. WAL + busy_timeout 만으로 부족하다고 판단되는 경우에만 같은 큐로 통합 검토.

#### 다음 액션

- IMPRINT_PROFILE=1 활성화 후 enter ↔ exit 짝짓기 데이터로 (a) 동시 실행 빈도, (b) 좀비 빈도, (c) BUSY 빈도를 한 주씩 모음.
- 동시 실행이 5분 윈도에 2건 이상 관찰되면 1번(lockfile) 진입.
- 좀비가 한 번이라도 관찰되면 2번(`/memory stats` 표시) 진입.
- BUSY 가 한 번도 안 나면 3번(memory_chunks 직접 INSERT path 통합) 는 영구 보류.

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
- **redaction 호출 경로 갭 (2026-05-11 관찰)**: 단순 결정 가능 부분은 "보안 — Redaction coverage 갭" 섹션으로 분리. 인터뷰가 필요한 잔여 질문 — (a) FTS 인덱싱 전후 어디에서 redact 해야 검색이 깨지지 않는지, (b) 이미 raw 로 저장된 과거 events 행을 일괄 redact / 삭제 / 방치 중 어느 정책으로 갈지, (c) IP·email·전화번호 같은 PII 는 default 룰에 넣을지 사용자 opt-in 으로 갈지.
- **plugin.log 회전**: 크기·날짜 기반 회전 정책. 압축? 며칠 보관?
- **반복 실패 사용자 알림**: silent fail이 누적될 때 statusline·session-start prepend로 보고할지. 임계치?
- **conversation_id 관리**: 한 SessionStart마다 새 conversation? idle 시간 기준 분리?

진입 명령: `/ouroboros:interview 보안·운영 (redaction·log 회전·에러 알림·conversation_id)`

### TODO 3. 사용자 환경 검증

1. iOS 팀 멤버 1명이 브랜치 checkout 후 자기 사내 프로젝트에서 1주 정성 검증 (AC5)
2. `IMPRINT_ALLOWED_TOOLS_FETCH` 가 사용자 등록 Slack/Notion MCP 이름과 일치하는지 확인 (각자 다를 수 있음)
3. plugin.log에서 `WARN: claude -p` 빈도 모니터링 — 일정 임계 초과 시 timeout 조정

### TODO 4. retrieval 측정 → 캘리브레이션 (deferred, 1주 데이터 후)

- contradiction 임계 (`HIGH=0.8`, `MID=0.4`) — 첫 100~200 쌍 측정 후 캘리브레이션
- summary LLM (claude haiku) vs deterministic concat 정확도 비교
- chunk_entities 자동 link 가 안정화되면 contradiction 후보 그룹화가 entity 기준으로 정확해짐
- entity merge / split UI — `entities` CLI 가 confirm/reject 만 지원, canonical 합치기는 별도 명령 필요
- daemon 분리 시점 — `(sync/daemon-ready)` 노드의 budget 위반 누적 시 inline → daemon backend 전환

## 단기 Watch List

- Stop hook의 `transcript_path` 포맷은 Claude Code 내부 구조에 의존 — Claude Code 버전 업그레이드 시 깨질 수 있어 plugin.log에서 `stop logged` 로그 누락 여부를 정기 확인.
- `IMPRINT_BYPASS_HOOKS` 가드가 빠진 새 hook 추가 시 ingestion 무한 재귀 재발 위험 — hook 추가 시 가드 한 줄 누락 점검.
- ML 의존성(transformers / sentence-transformers / sqlite-vec) 의 모델 캐시가 `~/.cache/huggingface` 에 누적 — 디스크 사용량 모니터링. `IMPRINT_MODEL_CACHE_DIR` 로 위치 변경 가능.
- `claude -p haiku` RTT 가 11~28 s 라 LLM judge / NER 의 inline 호출은 BG side 전제. 동기 경로에 끌고 가면 budget 위반.

## 다음 세션 시작 시 추천 픽업 지점

1. **Phase 5 진입 (Workflow skill)** — `/commit-message`, `/pr-draft`, `/recap`, `/handoff`. retrieval 인프라가 안정 운용되는 지금이 워크플로 skill 만들 자연스러운 시점.
2. **남은 인터뷰 라운드** — TODO 1·2 를 별도 세션에서 `/ouroboros:interview ...` 로 재개.
3. **사용자 환경 검증** — TODO 3 을 iOS 팀에 위임하고 plugin.log에서 `WARN: claude -p` 빈도 모니터링.
4. **retrieval 측정** — TODO 4 의 데이터 수집 후 임계 캘리브레이션 / daemon 분리 결정.
5. **Chunk 분류 2단계** — 검색 체감 저하 시 진입(metadata generated column + 인덱스).
