# imprint Load Map

**문서 책임**
- 본 문서는 큰 그림 문서입니다. 제품 방향, 아키텍처, 단계별 로드맵, 장기 위험 요소를 정리합니다.
- 다음 세션에서 바로 볼 체크리스트와 운영 관찰 항목은 `HANDOFF.md` 를 봅니다.
- 결정 사유와 폐기한 대안은 `HISTORY.md` 를 봅니다.
- 설치와 사용자 명령은 `INSTALL.md`, 상세 hook/retrieval 플로우는 `flow.md` 를 봅니다.

최종 업데이트: 2026-07-15.

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
   세션이 끝나면 "왜 이렇게 구현했는가" 의 맥락이 사라집니다. "로그인 feature 의 공유하기는 어떻게 구현됐었지" 같은 자연어 질문에 단어가 정확히 겹치지 않아도 관련 구현 맥락과 결정을 떠올려야 합니다. 키워드(FTS) 만으로는 어휘 불일치로 약하고, 의미(벡터) 검색이 필요한 영역입니다. 제품의 핵심 사용 시나리오입니다.

7. **팀 차원 지식 공유 (장기)** *(2026-05-21 명시)*
   한 개발자의 작업 기억이 다른 개발자에게도 참고되도록 합니다. 로컬 SQLite RAG(개인 세션 연속성)와는 다른 축이며, 사람이 읽고 git 으로 공유·리뷰 가능한 산출물(ADR 등)이 필요합니다. 검색 메커니즘이 아니라 영속화·공유 인프라 문제로 다룹니다.

## 현재 아키텍처

상세 hook 단계, 테이블 역할, 환경 변수는 `flow.md` 가 기준입니다. 여기서는 계층 구분만 요약합니다.

- **Hook 계층** — `SessionStart`(스키마 적용, Guardrail prepend, stale session background rollup — Codex 는 compact 때 idle 조건 하에 current session 도 1 batch), `UserPromptSubmit`(redaction·archive, working surface 저장, 경량 prefill, opt-in lazy-fetch spawn), `Stop`(응답 redaction·archive). 동기 hook 은 사용자 turn 을 막지 않는 경량 작업만 수행하고, LLM 호출은 background 로 분리합니다.
- **Memory 계층** — `events` 는 redacted raw archive(노이즈는 `noise=1` soft flag). `search_entries` 는 `/remember`, rollup extract, source document chunk, opt-in external fetch 가 공유하는 단일 검색 인덱스이며 prefill 후보와 `/search` 후보의 원천입니다. `search_summaries` 는 feature/document/project 요약. working overlay 는 영구 entry 로 만들지 않고 `events.metadata_json` 을 검색 시점에 읽습니다.
- **Retrieval 계층** — local 은 multi-rewrite → hybrid search(FTS5 + optional vector) → RRF → boost/penalty → optional rerank. feature/global 은 summary 검색 + grounding + contradiction check. 같은 주제의 `/remember`(canonical_memory) 와 rollup row(rollup_evidence) 는 질문 의도에 따라 우선순위를 나눕니다. 저신뢰여도 raw events 자동 fallback 은 열지 않습니다.
- **External Source 계층** — Slack/Notion 은 opt-in cache. `IMPRINT_ENABLE_LAZY_FETCH=1` 또는 `/memory refresh <url>` 로만 동작하고, 실패/stale/cap 초과는 `source_status` marker 로 남습니다.
- **Queue 계층** — 명시 문서 ingestion 후속 작업(`summary_regen`, `contradiction_scan`, `ner_extract`)만 `ingest_queue` 를 탑니다. `/remember` 와 rollup 직접 저장은 queue 를 거치지 않습니다.

embedding 은 hook 동기 경로에서 만들지 않습니다. 새 rollup entry 는 background 에서 write transaction 밖 배치 embedding 으로 생성하고, 기존 entry 는 `imprint setup vector --backfill` 로 명시적으로 채웁니다. 기존 DB 는 `imprint migrate search-entries` 로 명시 migration 합니다.

## 목표별 현재 일치도

| 목표 | 현재 일치도 | 장기 방향 |
|---|---|---|
| 세션 종료 후 문맥 저장 | 상당 부분 일치. raw archive 는 `events`, 정제 기억은 rollup 과 `/remember` 를 통해 `search_entries` 로 모입니다. | 실제 프로젝트 eval 로 추출 품질과 stale rollup 운영성을 측정합니다. |
| Codex / Claude Code 간 동일 문맥 | 방향 일치. 기본 저장소는 `~/.imprint` 로 통합됐습니다. | 설치/manifest/hook 검증을 양 host 회귀 테스트로 고정합니다. |
| 큰 틀·개념 질문으로 맥락 상기 | 부분 개선. `/remember` 는 canonical memory, rollup entry 는 구현 evidence 로 역할을 나눠 `/search` 에 노출됩니다. embedding eval 은 남았습니다. | `imprint setup vector --backfill` 기반 의미 검색 검증 후 feature/project summary 로 끌어올립니다. |
| 다른 개발자도 참고하는 공유 기록 | 장기 미구현. 로컬 SQLite 는 팀 지식 공유에 부적합합니다. | decision/summary chunk 를 ADR/Markdown 으로 export 해 git/PR review 에 얹습니다. |

## 로드맵

### 1. persistent memory 의미 검색 검증

`search_entries` 기반 검색 품질을 실제 프로젝트 질문으로 검증합니다.

- embedding 가용 시 vector path 품질을 검증합니다.
- rollup decision entry 의 `reason/files/symbols/tests/event_range` 가 실제 답변에 충분한 근거가 되는지 확인합니다.
- 같은 주제의 `/remember` 와 rollup row 가 공존할 때 질문 의도별 canonical/evidence 우선순위가 적절한지 확인합니다.
- 확장 가능성: `/search` 유사도 품질과 latency 가 충분히 검증되면 명시 검색 결과를 prefill 자동 주입으로 연결할 수 있습니다. 현재는 가능성만 남기고 기본 동작으로 두지 않습니다.

### 2. RAG 사용성 검증과 confidence 표현

- 실제 프로젝트에서 `/remember` 로 선별 저장한 기억이 `/search` 에서 충분히 유용한지 확인.
- 명시 검색 trace 가 사용자의 "근거 확인" 기대를 만족하는지 확인.
- 작은 eval 세트로 `embedding_used`, `vector_rank`, top1 score, fallback reason 을 관찰.
- `/search` 의 `confidence` 를 확률처럼 보이지 않게 `evidence_strength=strong|medium|weak` 또는 calibration 된 수치로 표현할지 결정.
- `IMPRINT_PROFILE=1` 로 latency, payload, background worker 상태를 측정.

구체 체크리스트는 `HANDOFF.md` 에 둡니다.

### 3. Workflow skill

RAG 기본 루프가 안정된 뒤 진입합니다. staged diff, 최근 memory, 테스트 결과를 결합해 `/commit-message`, `/pr-draft`, `/recap`, `/handoff` 같은 개발 워크플로 산출물을 만듭니다.

### 4. Skill registry

후순위 확장입니다. GitHub 기반 skill registry, `imprint skill add/remove/list/publish`, project-local override, manifest 신뢰/서명 정책.

### 5. Retrieval 고도화

필요성이 실사용에서 확인될 때만 진행합니다.

- 벡터 검색 setup 경험 개선: 실제 설치 실패 사례를 모아 HF Hub 인증, Python 환경 정책, "키워드 폴백 중" 신호를 더 분명히 다듬기.
- entity merge/split UI, chunk lifecycle 정책, contradiction threshold calibration, summary 품질 평가.
- 자동 hook memory 와 ingest_queue 후속 작업의 정렬.

### 6. 팀 공유 / 지식 영속화

로컬 RAG 가 개인 세션에서 안정된 뒤 진행합니다. RAG 검색이 아니라 "사람이 읽고 git 으로 공유 가능한 산출물" 이 핵심입니다.

- `decision`/`summary` chunk 를 ADR 같은 Markdown 으로 export 해 git/PR 리뷰에서 참조.
- 결정 chunk 에 feature/파일/커밋·날짜 메타데이터를 연결해 코드와 stale 관계를 추적.
- 역할 분리 원칙: (A) 개인 세션 연속성 = 로컬 RAG, (B) 팀 지식베이스 = 공유 문서. 한 메커니즘으로 합치지 않습니다.
- 팀 공용 저장소/벡터DB 동기화는 실수요 확인 전까지 보류(영구 deferred 후보).

## 원칙

- **로컬 우선**: 기본 데이터는 SQLite 에 저장합니다.
- **실패해도 세션 차단 금지**: hook 실패는 silent fail + log 로 처리합니다.
- **측정 후 최적화**: daemon, TTL, queue 통합은 profile 데이터가 쌓인 뒤 결정합니다.
- **삭제보다 표식 우선**: noise, stale, fetch failure 는 먼저 표시하고, 삭제 정책은 나중에 정합니다.
- **working 은 query context, retrieved/external 은 retrieved context**: raw 질문을 근거처럼 과신하지 않도록 context section 을 분리합니다.
- **민감정보는 저장 전 redaction**: raw token-shaped 문자열이 DB/FTS 에 들어가지 않도록 진입점에서 방어합니다.
- **개인 기억과 팀 지식은 분리**: 로컬 RAG 는 개인 세션 연속성, Markdown/ADR export 는 팀 공유를 담당합니다.

## 장기 위험

| 위험 | 대응 |
|---|---|
| 민감정보 저장 (prompt/terminal/external source 에 secret 혼입) | Guardrail 저장 금지 기준, default + 사용자 custom redaction rule. 과거 DB 청소는 사용자 승인 후 별도 작업. |
| 컨텍스트 오염 (무관한 memory prefill) | project_id·context section 분리, working TTL/cap, source_status 분리, 수동 `/memory inject` 로 명시 근거 주입. |
| 외부 source 신뢰성 (fetch 실패·stale 을 사용자가 모름) | `source_status` marker, stale 표시, `/memory refresh`. 자동 refresh 는 측정 전 보류. |
| 성능 병목 (긴 transcript 재파싱, 큰 payload, 동시 worker) | `IMPRINT_PROFILE=1` 계측 + `/memory profile/status`. 측정 후 tail-only parse, lockfile, daemon 분리 중 최소 대응 선택. |
| 선택 ML 의존성 부재 | FTS-only/LIKE/LLM judge fallback 으로 동작은 유지. 단, 미설치 시 의미(벡터) 검색이 꺼져 "개념 질문으로 맥락 상기" 라는 핵심 목적이 키워드 수준으로 떨어집니다. graceful fallback 이 곧 "기능 동일" 은 아님을 사용자에게 명확히 알립니다(2026-05-21 실측에서 오해 확인). |

## 영구 deferred

명확한 사용자 요구나 실측 필요성이 생기기 전까지 보류합니다.

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
