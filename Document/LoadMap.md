# imprint Load Map

**문서 책임**
- 본 문서는 큰 그림 문서입니다. 제품 방향, 아키텍처, 단계별 로드맵, 장기 위험 요소를 정리합니다.
- 다음 세션에서 바로 볼 체크리스트와 운영 관찰 항목은 `HANDOFF.md` 를 봅니다.
- 결정 사유와 폐기한 대안은 `HISTORY.md` 를 봅니다.
- 설치와 사용자 명령은 `README.md`, 상세 hook/retrieval 플로우는 `flow.md` 를 봅니다.

최종 업데이트: 2026-05-25.

## 방향

imprint 는 Claude Code/Codex hook·skill 시스템 위에서 동작하는 로컬 개발 작업 기억 plugin 입니다. 이전 Tauri 데스크톱 앱 방향은 폐기했고, 현재 repo 는 plugin 단일 책임을 가집니다.

핵심 목표는 기능을 많이 붙이는 것이 아니라, 실제 프로젝트에서 다음 루프가 믿을 만하게 동작하게 하는 것입니다.

```text
사용자 입력
  -> UserPromptSubmit hook
       event archive, working surface metadata, gate, context section prefill
  -> Claude Code / Codex 응답
  -> Stop hook
       response archive
  -> delta/rollup
       stale 또는 명시 session 단위 events를 decision-rich search_entries 로 정리
  -> 다음 turn
       search_entries가 prefill/search 후보가 될 수 있음
```

API key 없이 host 의 OAuth 구독을 그대로 사용합니다. 무거운 LLM 작업(rollup extract, summary/contradiction judge)은 background 에서 host CLI(`claude` 또는 `codex`)로 분리합니다. Slack/Notion fetch 는 opt-in 보조 경로입니다.

## 해결하려는 문제

1. **작업 재개 비용**
   며칠 뒤 다시 연 프로젝트에서도 진행 상황, 실패한 접근, 남은 TODO, 중요한 결정이 자동으로 떠올라야 합니다.

2. **반복 설명**
   폴더 구조, 검증 명령, 기술 스택, 최근 결정 사항을 매번 다시 설명하지 않게 합니다.

3. **근거 있는 답변**
   모델이 기억을 느낌상 말하는 것이 아니라, 사용자가 `/memory show`, `/memory inject`, 명시 검색 trace 로 근거 chunk 를 확인할 수 있어야 합니다.

4. **외부 문서 RAG (opt-in)**
   Slack/Notion 같은 외부 source 는 기본 RAG 루프가 아니라 명시 opt-in cache 로 가져옵니다. 켠 경우에는 실패·stale·cap 초과 상태를 사용자가 볼 수 있어야 합니다.

5. **로컬 우선 운영**
   SQLite + FTS5 기반으로 동작하고, 선택 ML 의존성은 없어도 graceful fallback 해야 합니다.

6. **개념적 코드 히스토리 상기** *(2026-05-21 명시)*
   세션이 끝나면 "왜 이렇게 구현했는가" 의 맥락이 사라집니다. 코드만으로는 의도와 폐기한 대안이 남지 않으므로, "로그인 feature 의 공유하기는 어떻게 구현됐었지" 같은 큰 틀·자연어 질문에 단어가 정확히 겹치지 않아도 관련 구현 맥락과 결정을 떠올려야 합니다. 이는 키워드(FTS) 만으로는 어휘 불일치로 약하고, 의미(벡터) 검색이 필요한 영역입니다. 제품의 핵심 사용 시나리오입니다.

7. **팀 차원 지식 공유 (장기)** *(2026-05-21 명시)*
   한 개발자의 작업 기억이 다른 개발자에게도 참고되도록 합니다. 단 이는 로컬 SQLite RAG(개인 세션 연속성)와는 다른 축이며, 사람이 읽고 git 으로 공유·리뷰 가능한 산출물(ADR 등)이 필요합니다. 검색 메커니즘 문제가 아니라 영속화·공유 인프라 문제로 다룹니다.

## 현재 아키텍처

### Hook 계층

- `SessionStart`: 스키마 적용, 프로젝트 row upsert, `.imprint/Guardrail.md` prepend. `startup|resume|clear|compact` matcher 로 세션 시작과 compact 이후 모두 Guardrail 을 다시 주입합니다. 기본적으로 현재 session_id 를 제외한 stale session rollup 을 background 로 보완합니다. Codex App 에서는 long-lived thread 를 고려해 `compact` 때 current session 이 idle 조건을 만족하면 1 batch guarded rollup 을 추가로 수행합니다. Claude Code 는 compact 라도 current session 을 제외합니다.
- `UserPromptSubmit`: prompt redaction, `events.user_message` 저장, working surface metadata 저장, routing rule 평가, need-retrieval gate, context section prefill. `IMPRINT_ENABLE_LAZY_FETCH=1` 일 때만 external lazy-fetch worker 를 spawn 합니다.
- `Stop`: assistant 응답 redaction, `events.llm_response` archive 및 session_id metadata 저장. 검색용 구현 기억은 rollup 이 `events` 에서 추출합니다.

동기 hook 은 사용자 turn 을 막지 않는 경량 작업만 수행합니다. Haiku 기반 추출은 background 로 분리합니다. 외부 fetch 는 opt-in 보조 경로로만 둡니다.

### Memory 계층

`events` 는 raw I/O archive 입니다. redaction 후 저장하고, 짧은 backchannel turn 은 `noise=1` 로 soft flag 만 붙입니다.

`search_entries` 는 기본 사용자 RAG 기억이자 명시 검색 단일 인덱스입니다. delta/rollup rich 추출, `/remember`, source document chunk 가 여기에 저장됩니다. opt-in external fetch 도 같은 테이블을 쓰지만 기본 RAG 루프에는 포함하지 않습니다. 다음 turn prefill 은 이 테이블을 가볍게 읽어 후보가 있을 때만 주입하고, `/memory search/list/show/inject`, `/search` 는 명시적으로 이 테이블을 읽습니다.

`source_documents` / `search_entries` / `search_summaries` 는 retrieval 문서 RAG 계층입니다. PRD/ADR/file 같은 명시 ingestion 원본 문서는 `source_documents` 에 저장되고, chunking 된 검색 단위는 `search_entries(origin=source_document)` 로 들어가며, feature/document/project 요약은 `search_summaries` 로 관리합니다. opt-in Slack/Notion lazy fetch 는 보통 `source_documents` 를 만들지 않고 `search_entries(origin=external_fetch)` 로 직접 들어갑니다.

working overlay 는 영구 entry 로 만들지 않습니다. 현재 세션 query surface 는 `events.metadata_json` 에 저장하고 `/search` 시점에 soft union 합니다. 기존 entry 의 vector embedding 은 `imprint setup vector --backfill` 로 명시적으로 채웁니다. 새 rollup entry 는 vector 런타임이 설치되어 있으면 transaction 밖에서 배치 embedding 한 뒤 저장하므로 hook 동기 경로를 막지 않습니다.

### Retrieval 계층

`/memory` 는 `search_entries` 를 직접 읽고 쓰는 수동 개입 도구입니다.

명시 검색 경로는 `search_entries`/`search_summaries` 를 검색합니다.

- local: multi-rewrite → hybrid search → RRF → working overlay → BOOST/penalty → optional rerank → CTX.
- feature/global: summary 검색 + chunk retrieval + grounding + contradiction check.
- rollup 이 저장한 `reason/files/symbols/tests/event_range` metadata 는 `/search` 출력의 세부 근거로 함께 노출합니다.
- 같은 주제의 `/remember` 와 rollup row 가 함께 검색되면, 큰 틀/정책/요약 질문은 `/remember` 의 `canonical_memory` 를 우선하고 왜/어떻게/구현/파일/테스트 질문은 rollup 의 `rollup_evidence` 를 우선합니다.
- 저신뢰이면 trace 에 이유를 남기지만 raw events 자동 fallback 은 열지 않습니다.
- `source_status` marker 는 primary retrieved context 후보에서 제외합니다.
- JSON mode 는 trace, context section, provenance, penalty, fallback/rerank 이유를 노출합니다.

### External Source 계층

Slack/Notion fetch 는 기본 RAG 루프가 아니라 opt-in external source cache 입니다. `IMPRINT_ENABLE_LAZY_FETCH=1` 일 때 사용자 prompt URL 또는 `<project>/.imprint/sources.json` 을 기반으로 background 에서 동작하고, 명시 `/memory refresh <url>` 로도 갱신할 수 있습니다.

- 성공 chunk: `spec`, `message`, `thread`.
- 실패/관찰 marker: `source_status` (`fetch_failed`, `fetch_empty`, `skipped_by_cap`, stale 계산).
- dedup: `source_uri/url + provenance(evidence_level) + text_hash` 기준.
- 자동 refresh 는 하지 않고, `/memory refresh` 로 명시 갱신합니다.
- 현재 turn 답변의 근거로 즉시 보장하지 않습니다. 다음 turn prefill 또는 명시 `/search` 후보로만 봅니다.

### Queue 계층

retrieval v2 ingestion 은 `ingest_queue` 를 통해 후속 작업을 순차 처리합니다.

- `summary_regen`: priority 5.
- `contradiction_scan`: priority 5.
- `ner_extract`: priority 9.

`/remember` 와 rollup 의 직접 `search_entries` 저장 경로는 현재 queue 를 거치지 않습니다. WAL + busy_timeout 으로 일반 동시성은 흡수하고, summary/entity/contradiction queue 통합은 필요해질 때만 검토합니다.

## 현재 기준선

2026-05-24 기준 RAG 기본 기능, 1차 운영 관측성, `search_entries` 통합 스키마, `/search`, `/remember`, delta/rollup extract, vector setup dispatcher 는 적용 완료입니다.

- redaction coverage.
- hook memory loop smoke test.
- 첫 turn working overlay.
- context section 기반 prefill.
- `/remember` 명시 저장과 `/memory` 기본 검색/list/show/inject/refresh/profile/status.
- 한국어 2자 토큰 fallback.
- external source 상태 가시화.
- events noise soft flag.
- 명시 검색 JSON trace.
- delta/rollup 기반 구현 결정 arc 저장과 `/search` 세부 근거 출력.
- `/search` 의 manual memory(`canonical_memory`) 와 rollup 근거(`rollup_evidence`) 역할 분리.
- `search_entries` migration/backfill.
- text_hash 기반 dedup.
- 테스트 기준선: `33 PASS / 0 FAIL`.

완료된 결정과 이유는 `HISTORY.md` 에 남깁니다.

## 알려진 핵심 갭 (2026-05-21 발견, 2026-05-24 구조 정리)

persistent memory 와 의미(벡터) 검색이 연결돼 있지 않았던 문제가 제품 핵심 목적의 직접 병목이었습니다. 2026-05-24 에 bridge 를 폐기하고 persistent memory, rollup extract, source document chunk 를 `search_entries` 단일 인덱스로 통합했습니다.

- `search_entries` 에 embedding 컬럼이 있으므로 bridge 복제 없이 같은 row 가 FTS/vector 양쪽에 참여할 수 있습니다.
- hook 동기 경로에서는 embedding 을 만들지 않습니다. 선택 ML cold-load 가 사용자 turn 을 느리게 만들 수 있기 때문입니다. 새 rollup entry 의 embedding 은 background rollup 프로세스에서 write transaction 밖 배치 처리로만 생성합니다.
- 기존 DB는 `imprint migrate search-entries` 로 명시 migration 하고, 벡터 검색 검증은 `imprint setup vector --backfill` 로 기존 entry embedding 을 채운 뒤 진행합니다. 이후 새 rollup entry 는 vector 설치 환경에서 자동 embedding 됩니다.
- 아직 summary/entity/contradiction pipeline 자동 연결은 직접 저장 entry 전체에 강제하지 않습니다. 검색 품질과 운영 비용을 먼저 측정합니다.

## 목표별 현재 일치도

원래 제품 목적 기준의 장기 판단입니다.

| 목표 | 현재 일치도 | 장기 방향 |
|---|---|---|
| 세션 종료 후 문맥 저장 | 상당 부분 일치. raw event archive 는 `events`, 정제 기억은 delta/rollup rich extract 와 `/remember` 를 통해 `search_entries` 로 모입니다. | 실제 프로젝트 eval 로 추출 품질과 stale rollup 운영성을 측정합니다. |
| Codex / Claude Code 간 동일 문맥 | 방향 일치. 기본 저장소는 `~/.imprint` 로 통합됐습니다. | 설치/manifest/hook 검증을 양 host 회귀 테스트로 고정합니다. |
| 큰 틀·개념 질문으로 맥락 상기 | 부분 개선. `/remember` 는 canonical memory 로, rollup decision entry 는 구현 evidence 로 역할을 나눠 `/search` 에 노출됩니다. embedding/backfill 과 eval 은 아직 남았습니다. | `imprint setup vector --backfill` 기반 의미 검색 검증 후 feature/project summary 로 끌어올립니다. |
| 다른 개발자도 참고하는 공유 기록 | 장기 미구현. 로컬 SQLite 는 개인 기억에 적합하지만 팀 지식 공유에는 부적합합니다. | decision/summary chunk 를 ADR/Markdown 으로 export 해 git/PR review 에 얹습니다. |

## 로드맵

### 1. persistent memory 의미 검색 검증

`search_entries` 통합과 `/search` UX 1차 개선은 완료됐습니다. 남은 작업은 embedding 채움과 검색 품질 검증입니다.

- Rollup extract, `/remember`, source document ingest 는 `search_entries` 에 직접 저장됩니다. opt-in external fetch 도 같은 저장 경로를 재사용합니다.
- 기존 사용자 DB는 `imprint migrate search-entries` 로 명시 migration 합니다.
- `imprint setup vector --backfill` 은 현재 프로젝트의 기존 `search_entries.embedding` 을 채웁니다. 새 rollup entry 는 vector 설치 환경에서 자동 embedding 됩니다.
- 신규/기존 memory 가 명시 검색 경로에서 `search_entries` 후보로 보이는 것은 테스트로 고정했습니다. 다음은 embedding 가용 시 vector path 품질 검증입니다.
- rollup decision entry 의 `reason/files/symbols/tests/event_range` 가 `/search` 출력에 보이는 것은 테스트로 고정했습니다.
- 같은 주제의 `/remember` 와 rollup row 가 공존할 때 질문 의도별로 canonical/evidence 우선순위가 바뀌는 것은 테스트로 고정했습니다.
- 확장 가능성: `/search` 유사도 품질과 latency 가 충분히 검증되면, 명시 검색 결과를 prefill 자동 주입으로 연결할 수 있습니다. 현재 로드맵에서는 가능성만 남기고 기본 동작으로 두지 않습니다.

### 2. RAG 사용성 검증과 confidence 표현

`search_entries` 통합 스키마 기준으로 진행합니다.

- 실제 프로젝트에서 `/remember` 로 선별 저장한 기억이 `/search` 에서 충분히 유용한지 확인.
- 명시 검색 trace 가 사용자의 “근거 확인” 기대를 만족하는지 확인.
- 작은 eval 세트로 `embedding_used`, `vector_rank`, top1 score, fallback reason 을 관찰.
- `/search` 결과의 `confidence` 를 확률처럼 보이지 않게 `evidence_strength=strong|medium|weak` 또는 calibration 된 수치로 표현할지 결정.
- `IMPRINT_PROFILE=1` 로 latency, payload, background worker 상태를 측정.

구체 체크리스트는 `HANDOFF.md` 에 둡니다.

### 3. Workflow skill

RAG 기본 루프가 안정된 뒤 진입합니다.

- `/commit-message`
- `/pr-draft`
- `/recap`
- `/handoff`

목표는 staged diff, 최근 memory, 테스트 결과를 결합해 개발 워크플로 산출물을 만드는 것입니다.

### 4. Skill registry

후순위 확장입니다.

- GitHub 기반 skill registry.
- `imprint skill add/remove/list/publish`.
- project-local override 와 global skill 우선순위.
- manifest 포맷과 신뢰/서명 정책.

### 5. Retrieval 고도화

필요성이 실사용에서 확인될 때만 진행합니다.

- 벡터 검색 setup 경험: `imprint setup vector` 는 단계별 진행 로그와 실패 힌트를 남깁니다. 다음은 실제 설치 실패 사례를 모아 HF Hub 인증, Python 환경 정책, 현재 "키워드 폴백 중" 신호를 더 분명히 다듬는 일입니다.
- entity merge/split UI.
- chunk lifecycle 정책.
- contradiction threshold calibration.
- summary 품질 평가.
- 자동 hook memory 와 ingest_queue 후속 작업의 정렬.

### 6. 팀 공유 / 지식 영속화

로컬 RAG 가 개인 세션에서 안정된 뒤, 다른 개발자도 참고할 수 있는 형태로 확장합니다. RAG 검색 자체보다 "사람이 읽고 git 으로 공유 가능한 산출물" 이 핵심입니다.

- `decision`/`summary` chunk 를 사람이 읽는 Markdown(ADR, Architecture Decision Record) 으로 export.
- export 산출물을 git 에 커밋해 PR·코드 리뷰에서 자연스럽게 참조.
- 결정 chunk 에 대상 feature/파일/커밋·날짜 메타데이터를 연결해 코드와 stale 관계를 추적.
- 역할 분리 원칙: (A) 개인 세션 연속성 = 로컬 RAG, (B) 팀 지식베이스 = 공유 문서. 한 메커니즘으로 합치지 않습니다.
- 팀 공용 저장소/벡터DB 동기화는 실수요가 확인되기 전까지 보류(영구 deferred 후보).

## 원칙

- **로컬 우선**: 기본 데이터는 SQLite 에 저장합니다.
- **실패해도 세션 차단 금지**: hook 실패는 silent fail + log 로 처리합니다.
- **측정 후 최적화**: daemon, TTL, queue 통합은 profile 데이터가 쌓인 뒤 결정합니다.
- **삭제보다 표식 우선**: noise, stale, fetch failure 는 먼저 표시하고, 삭제 정책은 나중에 정합니다.
- **working 은 query context, retrieved/external 은 retrieved context**: raw 질문을 근거처럼 과신하지 않도록 context section 을 분리합니다.
- **민감정보는 저장 전 redaction**: raw token-shaped 문자열이 DB/FTS 에 들어가지 않도록 진입점에서 방어합니다.
- **개인 기억과 팀 지식은 분리**: 로컬 RAG 는 개인 세션 연속성, Markdown/ADR export 는 팀 공유를 담당합니다.

## 장기 위험

### 민감정보 저장

prompt, terminal output, external source 에 secret 이 섞일 수 있습니다.

대응:
- Guardrail 에 민감정보 저장 금지 기준을 둡니다.
- default redaction rule.
- 사용자 custom redaction rule.
- 과거 DB 청소는 사용자 승인 후 별도 작업.

### 컨텍스트 오염

관련 없는 memory 가 prefill 되면 답변 품질이 떨어집니다.

대응:
- project_id 분리.
- context section 분리.
- working TTL/cap.
- source_status/working surface 를 primary retrieved context 에서 분리.
- 수동 `/memory inject` 로 명시 근거 주입.

### 외부 source 신뢰성

opt-in Slack/Notion fetch 를 켠 경우, fetch 실패, stale, URL cap 초과를 사용자가 모르면 RAG 신뢰가 떨어집니다.

대응:
- `source_status` marker.
- stale 표시.
- `/memory refresh`.
- 자동 refresh 는 측정 전 보류.

### 성능 병목

긴 transcript 재파싱, 큰 Notion payload, 동시 background worker 가 병목이 될 수 있습니다.

대응:
- `IMPRINT_PROFILE=1` 계측.
- `/memory profile`.
- `/memory status`.
- 측정 후 tail-only parse, lockfile, daemon 분리, queue 통합 중 최소 대응 선택.

### 선택 ML 의존성

`sentence_transformers`, `transformers`, `sqlite-vec` 가 없을 수 있습니다.

대응:
- FTS-only fallback.
- LIKE fallback.
- LLM judge fallback.
- optional requirements 로 분리.
- 단, 미설치 시 의미(벡터) 검색이 꺼져 "개념·자연어 질문으로 맥락 상기" 라는 핵심 목적이 키워드 수준으로 떨어집니다. graceful fallback 이 곧 "기능 동일" 은 아니라는 점을 사용자에게 명확히 알립니다(2026-05-21 실측에서 사용자 오해 확인).
- persistent memory 는 `search_entries` 후보가 되지만, embedding BLOB 이 없으면 여전히 FTS 중심입니다. 기존 entry 는 `imprint setup vector --backfill` 로 embedding 을 채운 뒤 vector path 에 참여하고, 새 rollup entry 는 vector 설치 환경에서 자동 embedding 됩니다.

## 영구 deferred

아래 항목은 명확한 사용자 요구나 실측 필요성이 생기기 전까지 보류합니다.

- Full GraphRAG / HippoRAG / knowledge graph DB.
- 자동 belief revision engine.
- 완전 자동 supersede confirmed 처리.
- LLMLingua / recursive summarization 기반 event 압축.
- A-MEM style dynamic linking.
- Linux/Windows 호환성 보장.

## 최종 목표

```text
Claude Code / Codex 세션
  + UserPromptSubmit hook
  + Stop hook
  + shared local SQLite memory (~/.imprint)
  + /memory skill
  + explicit grounding
  + optional external source fetch
  + optional workflow skills
  -> 구독 OAuth만으로 동작하는 로컬 개발 작업 기억 시스템
```
