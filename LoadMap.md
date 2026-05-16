# imprint Load Map

**문서 책임**
- 본 문서는 큰 그림 문서입니다. 제품 방향, 아키텍처, 단계별 로드맵, 장기 위험 요소를 정리합니다.
- 다음 세션에서 바로 볼 체크리스트와 운영 관찰 항목은 `HANDOFF.md` 를 봅니다.
- 결정 사유와 폐기한 대안은 `HISTORY.md` 를 봅니다.
- 설치와 사용자 명령은 `README.md`, 상세 hook/retrieval 플로우는 `flow.md` 를 봅니다.

최종 업데이트: 2026-05-16.

## 방향

imprint 는 Claude Code hook·skill 시스템 위에서 동작하는 로컬 개발 작업 기억 plugin 입니다. 이전 Tauri 데스크톱 앱 방향은 폐기했고, 현재 repo 는 plugin 단일 책임을 가집니다.

핵심 목표는 기능을 많이 붙이는 것이 아니라, 실제 프로젝트에서 다음 루프가 믿을 만하게 동작하게 하는 것입니다.

```text
사용자 입력
  -> UserPromptSubmit hook
       event archive, working mini-chunk, gate, lane prefill
  -> Claude Code 응답
  -> Stop hook
       response archive, durable memory extract
  -> 다음 turn
       저장된 기억이 다시 prefill/search/retrieve 후보가 됨
```

API key 없이 Claude Code OAuth 구독을 그대로 사용합니다. 무거운 LLM 작업(prompt 분석, Slack/Notion fetch, response extract)은 background 에서 `claude -p haiku` 로 분리합니다.

## 해결하려는 문제

1. **작업 재개 비용**
   며칠 뒤 다시 연 프로젝트에서도 진행 상황, 실패한 접근, 남은 TODO, 중요한 결정이 자동으로 떠올라야 합니다.

2. **반복 설명**
   폴더 구조, 검증 명령, 기술 스택, 최근 결정 사항을 매번 다시 설명하지 않게 합니다.

3. **근거 있는 답변**
   모델이 기억을 느낌상 말하는 것이 아니라, 사용자가 `/memory show`, `/memory inject`, `/retrieve --json` 으로 근거 chunk 와 trace 를 확인할 수 있어야 합니다.

4. **외부 문서 RAG**
   Slack/Notion 같은 외부 source 를 read-only 로 가져오되, 실패·stale·cap 초과 상태를 사용자가 볼 수 있어야 합니다.

5. **로컬 우선 운영**
   SQLite + FTS5 기반으로 동작하고, 선택 ML 의존성은 없어도 graceful fallback 해야 합니다.

## 현재 아키텍처

### Hook 계층

- `SessionStart`: 스키마 적용, 프로젝트 row upsert, `.imprint/soul.md` prepend.
- `UserPromptSubmit`: prompt redaction, `events.user_message` 저장, working mini-chunk 저장, routing rule 평가, need-retrieval gate, lane prefill, lazy-fetch worker spawn.
- `Stop`: assistant 응답 redaction, `events.llm_response` archive, response extract worker spawn.

동기 hook 은 사용자 turn 을 막지 않는 경량 작업만 수행합니다. 외부 fetch 와 Haiku 기반 추출은 background 로 분리합니다.

### Memory 계층

`events` 는 raw I/O archive 입니다. redaction 후 저장하고, 짧은 backchannel turn 은 `noise=1` 로 soft flag 만 붙입니다.

`memory_chunks` 는 기본 사용자 RAG 기억입니다. working mini-chunk, Stop hook 추출, external lazy-fetch, `/memory remember` 가 여기에 저장합니다. 다음 turn prefill, `/memory search/list/show/inject`, `/retrieve` fallback 이 이 테이블을 읽습니다.

`documents` / `chunks_v2` / `summaries` 는 retrieval v2 문서 RAG 계층입니다. 명시 ingestion 된 문서는 chunking, versioning, summary, contradiction, entity alias pipeline 을 탑니다.

### Retrieval 계층

`/memory` 는 `memory_chunks` 를 직접 읽고 쓰는 수동 개입 도구입니다.

`/retrieve` 는 `chunks_v2`/`summaries` 를 우선 검색합니다.

- local: multi-rewrite → hybrid search → RRF → working overlay → BOOST/penalty → low-confidence MEMFB → optional rerank → CTX.
- feature/global: summary 검색 + chunk retrieval + grounding + contradiction check.
- 문서 후보가 없거나 저신뢰이면 `memory_chunks` 를 read-only fallback 으로 조회합니다.
- `source_status` marker 와 working chunk 는 fallback evidence 후보에서 제외합니다.
- JSON mode 는 trace, lane, provenance, penalty, fallback/rerank 이유를 노출합니다.

### External Source 계층

Slack/Notion lazy-fetch 는 사용자 prompt URL 또는 `<project>/.imprint/sources.json` 을 기반으로 background 에서 동작합니다.

- 성공 chunk: `spec`, `message`, `thread`.
- 실패/관찰 marker: `source_status` (`fetch_failed`, `fetch_empty`, `skipped_by_cap`, stale 계산).
- dedup: `source_uri/url + evidence_level + text_hash` 기준.
- 자동 refresh 는 하지 않고, `/memory refresh` 로 명시 갱신합니다.

### Queue 계층

retrieval v2 ingestion 은 `ingest_queue` 를 통해 후속 작업을 순차 처리합니다.

- `summary_regen`: priority 5.
- `contradiction_scan`: priority 5.
- `ner_extract`: priority 9.

자동 hook 의 `memory_chunks` 직접 INSERT 경로는 현재 queue 를 거치지 않습니다. WAL + busy_timeout 으로 일반 동시성은 흡수하고, 필요해질 때만 통합을 검토합니다.

## 현재 기준선

2026-05-16 기준 RAG 기본 기능과 1차 운영 관측성은 적용 완료입니다.

- redaction coverage.
- hook memory loop smoke test.
- 첫 turn working overlay.
- lane 기반 prefill.
- `/memory` 기본 검색/list/show/inject/remember/refresh/profile/status.
- 한국어 2자 토큰 fallback.
- external source 상태 가시화.
- events noise soft flag.
- `/retrieve` memory fallback + JSON trace.
- text_hash 기반 dedup.
- 테스트 기준선: `17 PASS / 0 FAIL`.

완료된 결정과 이유는 `HISTORY.md` 에 남깁니다.

## 로드맵

### 1. RAG 사용성 검증과 운영 캘리브레이션

현재 최우선 단계입니다.

- 실제 프로젝트에서 자동 prefill 과 수동 `/memory` 경로가 충분히 유용한지 확인.
- `/retrieve --json` trace 가 사용자의 “근거 확인” 기대를 만족하는지 확인.
- 작은 eval 세트로 gate, fallback, rerank, contradiction penalty 를 관찰.
- `IMPRINT_PROFILE=1` 로 latency, payload, background worker 상태를 측정.
- `events.noise`, `source_status`, stale chunk 누적량을 보고 운영 정책 결정.

구체 체크리스트는 `HANDOFF.md` 에 둡니다.

### 2. 운영 정책 정착

측정 데이터가 모인 뒤 아래 정책을 확정합니다.

- stale 기준(`IMPRINT_STALE_DAYS`) 조정.
- `source_status` marker TTL 또는 dedup.
- noise row 감쇠/삭제 여부.
- working TTL/cap 조정.
- low-confidence MEMFB threshold 와 rerank gate 조정.
- plugin.log 회전과 반복 실패 알림.
- daemon 분리 필요 여부.
- 과거 사용자 DB raw secret 청소 정책.

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

- `memory_chunks → chunks_v2` bridge 또는 unified storage.
- entity merge/split UI.
- chunk lifecycle 정책.
- contradiction threshold calibration.
- summary 품질 평가.
- 자동 hook memory 와 ingest_queue 후속 작업의 정렬.

## 원칙

- **로컬 우선**: 기본 데이터는 SQLite 에 저장합니다.
- **실패해도 세션 차단 금지**: hook 실패는 silent fail + log 로 처리합니다.
- **측정 후 최적화**: daemon, TTL, queue 통합은 profile 데이터가 쌓인 뒤 결정합니다.
- **삭제보다 표식 우선**: noise, stale, fetch failure 는 먼저 표시하고, 삭제 정책은 나중에 정합니다.
- **working 은 clue, durable/external 은 evidence**: raw 질문을 근거처럼 과신하지 않도록 lane 을 분리합니다.
- **민감정보는 저장 전 redaction**: raw token-shaped 문자열이 DB/FTS 에 들어가지 않도록 진입점에서 방어합니다.

## 장기 위험

### 민감정보 저장

prompt, terminal output, external source 에 secret 이 섞일 수 있습니다.

대응:
- default redaction rule.
- 사용자 custom redaction rule.
- 저장 전 redaction.
- 과거 DB 청소는 사용자 승인 후 별도 작업.

### 컨텍스트 오염

관련 없는 memory 가 prefill 되면 답변 품질이 떨어집니다.

대응:
- project_id 분리.
- lane 분리.
- working TTL/cap.
- source_status/working 제외 fallback.
- 수동 `/memory inject` 로 명시 근거 주입.

### 외부 source 신뢰성

Slack/Notion fetch 실패, stale, URL cap 초과를 사용자가 모르면 RAG 신뢰가 떨어집니다.

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
Claude Code 세션
  + UserPromptSubmit hook
  + Stop hook
  + local SQLite memory
  + /memory skill
  + /retrieve grounding
  + optional external source fetch
  + optional workflow skills
  -> 구독 OAuth만으로 동작하는 로컬 개발 작업 기억 시스템
```
