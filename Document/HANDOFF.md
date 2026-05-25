# Handoff — 다음 세션 픽업

**문서 책임**
- 다음 세션에서 바로 볼 실행 항목과 운영 체크만 남깁니다.
- 큰 그림은 `LoadMap.md`, 결정 사유는 `HISTORY.md`, 상세 흐름과 테이블 역할은 `flow.md` 를 봅니다.

최종 업데이트: 2026-05-24.

## 현재 기준선

RAG 기본 루프와 1차 운영 관측성은 적용 완료된 상태입니다.

- 자동 hook 루프: `SessionStart → UserPromptSubmit → Stop → 다음 UserPromptSubmit`.
- 수동 저장/검색: `/remember`, `/search`, `/memory search/list/show/inject/refresh/stats/profile/status`.
- persistent memory 는 `search_entries` 단일 인덱스에 저장됩니다. legacy `memory_chunks + chunks_v2` bridge 는 제거됐습니다.
- 구현 중 여러 turn 에 걸친 decision/code_context/summary/note 는 delta/rollup 으로 `search_entries` 에 정제 저장되고, `/search` 는 `reason/files/symbols/tests/event_range` detail 을 출력합니다.
- `/search` 는 같은 주제의 `/remember` 와 rollup row 가 함께 있을 때 역할을 분리합니다. 큰 틀/정책/요약 질문은 `manual_remember` 를 `canonical_memory` 로 앞세우고, 왜/어떻게/구현/파일/테스트 질문은 rollup row 를 `rollup_evidence` 로 앞세웁니다.
- vector 검색은 `imprint setup vector --backfill` 로 `search_entries.embedding` 을 채운 뒤 참여합니다.
- 선택 ML 의존성이 없어도 FTS5/LIKE fallback 으로 동작해야 합니다.

최근 검증 기준:

```text
python3 scripts/imprint/tests/run_tests.py
TOTAL  32 PASS / 0 FAIL
```

테스트는 임시 `IMPRINT_HOME=/tmp/...` 에서 실행합니다. 사용자 홈 `~/.imprint` 직접 수정은 명시 동의 전까지 하지 않습니다.

## 다음 우선순위

1. **개념 질의 eval 세트 구성**
   "로그인 feature 의 공유하기는 어떻게 구현됐었지" 같은 자연어 질문 20~30개를 고정합니다. `/remember` 로 선별 저장한 기억이 `/search` 에서 어떻게 회수되는지 보고, 내부 retrieval JSON trace 의 `embedding_used`, `vector_rank`, top1 score, fallback 이유를 같이 기록합니다.

2. **`/search` confidence 표시 기준**
   현재 confidence 는 확률이 아니라 내부 휴리스틱입니다. `/search` 는 세부 근거 detail 을 이미 출력하므로, eval 결과를 본 뒤 `evidence_strength=strong|medium|weak` 또는 calibrated numeric score 로 표현할지 결정합니다. 출력에는 숫자만 두지 말고 weak/medium 의 이유도 함께 보여줘야 합니다.

3. **운영 피드백 수집**
   vector setup, migration/backfill, FTS fallback, profile 로그에서 반복 실패나 지연 신호가 있는지 확인합니다. 바로 기능을 늘리기보다 trace/profile 데이터로 먼저 판단합니다.

## 확인 체크리스트

- 새 세션 시작과 compact 직후 `SessionStart` 가 스키마 적용과 `Guardrail.md` prepend 를 조용히 수행하는지.
- 질문 직후 `[Project memory context]` 가 query/session/retrieved/external section 으로 나뉘는지.
- Stop extract 또는 external lazy-fetch 결과가 다음 turn 의 후보로 보이는지.
- `/search` 가 `search_entries` 를 primary 로 읽고 `source_status` marker 를 제외하는지.
- rollup decision 후보가 `/search` 에서 `reason/files/symbols/tests/event_range` 를 함께 보여주는지.
- 같은 주제의 `/remember` 와 rollup 후보가 공존할 때 큰 틀 질문은 `canonical_memory`, 구현 질문은 `rollup_evidence` 를 먼저 보여주는지.
- `imprint migrate search-entries` 후 과거 `memory_chunks` 가 `search_entries` 후보로 회수되는지.
- `imprint setup vector --status/--install/--warmup/--backfill` 이 한국어 진행 로그와 실패 힌트를 화면과 `plugin.log` 양쪽에 남기는지.

## 관찰 지표

`IMPRINT_PROFILE=1` 로 `~/.imprint/profile.jsonl` 을 누적한 뒤 `/memory profile --json` 과 `/memory status --json` 으로 확인합니다.

- `cmd_prefill`: working/retrieved count, retrieved-memory search skip 사유, context section count.
- `retrieve_done`: query surface 수, fallback 여부와 이유, rerank gate 사유.
- `stop.transcript_reparse`: 긴 세션에서 증가하는지.
- `call_claude`: background 모델 호출 RTT 와 timeout 빈도.
- `fetch_notion_url.payload`, `fetch_slack_url.payload`: 큰 payload 반복 여부.

DB 관찰:

```sql
SELECT noise, COUNT(*) FROM events GROUP BY noise;
SELECT raw_type, COUNT(*) FROM search_entries GROUP BY raw_type;
SELECT json_extract(metadata_json, '$.status'), COUNT(*)
FROM search_entries
WHERE raw_type = 'source_status'
GROUP BY 1;
```

## 다음 세션 시작 순서

1. `git status -sb` 로 작업 상태 확인.
2. `python3 scripts/imprint/tests/run_tests.py` 로 기준선 확인.
3. `imprint setup vector --status` 로 벡터 런타임 상태 확인.
4. 실제 프로젝트에서 개념 질의 1~2개로 `/search` 출력과 trace 의 `embedding_used` 확인.
5. `/memory status --json`, `/memory profile --json`, `plugin.log` 로 실패/지연 신호 확인.
