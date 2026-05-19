# Handoff — 다음 세션 픽업

**문서 책임**
- 본 문서는 단기 실행 문서입니다. 다음 세션에서 바로 확인할 항목, 운영 관찰 체크리스트, 측정 후 결정할 보류 안건만 둡니다.
- 큰 그림·아키텍처·장기 로드맵은 `LoadMap.md` 를 봅니다.
- 결정 사유와 폐기한 대안은 `HISTORY.md` 를 봅니다.
- 설치와 사용자 명령은 `README.md`, 상세 플로우와 의존성은 `flow.md` 를 봅니다.

최종 업데이트: 2026-05-16.

## 현재 기준선

RAG 기본 기능과 1차 운영 관측성은 적용 완료된 상태입니다.

- 자동 hook 루프: `SessionStart → UserPromptSubmit → Stop → 다음 UserPromptSubmit`.
- 첫 turn 가시성: user prompt 를 working mini-chunk 로 즉시 저장하고 prefill/retrieve query context 로 사용.
- RAG context sections: query context, session memory, retrieved memory, external source context 분리.
- 수동 memory: `/memory search/list/show/inject/remember/refresh/stats/profile/status`.
- 명시 retrieval: `/retrieve` 는 `chunks_v2`/`summaries` 우선, 저신뢰 또는 빈 후보면 `memory_chunks` read-only fallback.
- 관찰성: source status marker, events noise flag, profile JSONL, retrieve JSON trace, candidate provenance, text_hash dedup.
- 안전성: user/assistant/external/manual memory 저장 전 redaction.

최근 검증 기준:

```text
python3 scripts/imprint/tests/run_tests.py
TOTAL  19 PASS / 0 FAIL
```

테스트는 임시 `IMPRINT_HOME=/tmp/...` 방식으로 격리합니다. 사용자 홈 `~/.claude/imprint` 직접 수정은 명시 동의 전까지 하지 않습니다.

## 다음 우선순위

1. **실제 프로젝트 사용성 테스트**
   저장한 기억이 다음 turn, `/memory`, `/retrieve --json` 에서 실제 답변 근거로 충분히 보이는지 확인합니다.

2. **작은 eval 세트 구성**
   자주 쓸 질문 20~30개를 고정하고 `/retrieve_json` trace 를 비교합니다. 예: UI 동작, 설정 동기화, Slack/Notion 실패, 짧은 backchannel, contradiction.

3. **운영 정책 캘리브레이션**
   `IMPRINT_PROFILE=1` 로 1~2주 데이터를 모아 gate, MEMFB threshold, rerank 조건, working TTL/cap, stale 기준을 조정합니다.

4. **후순위 기능 확장 판단**
   workflow skill, registry, entity merge/split UI, unified storage 는 RAG 기본 루프가 실제 사용에서 안정된 뒤 진입합니다.

## 사용성 테스트 체크리스트

- 새 세션 시작 시 `SessionStart` 가 스키마 적용과 `soul.md` prepend 를 조용히 수행하는지.
- “A 버튼 클릭 동작 알려줘” 같은 질문 직후 `[Query context]` 가 prefill 되는지.
- 다음 turn 에 Stop extract 또는 external lazy-fetch 결과가 `[Retrieved memory]` / `[External source context]` 로 보이는지.
- `/memory search <키워드>` 가 한국어 짧은 토큰 fallback 포함해 기대 chunk 를 찾는지.
- `/memory show --json <id>` 에서 metadata, `source_status`, `text_hash`, provenance 를 이해할 수 있는지.
- `/memory status --json` 이 DB/log/profile 상태와 working 정책을 보여주는지.
- `/retrieve --routed --json <질문>` 의 `trace` 와 candidate context section/provenance 가 기대대로 남는지.
- 문서 chunk 가 있으면 `/retrieve` 가 `chunks_v2` 를 우선하고, 저신뢰일 때만 `memory_chunks` fallback 을 여는지.
- Slack/Notion fetch 실패, URL cap 초과, stale 외부 chunk 가 `/memory list/show/status` 에서 관찰 가능한지.

## 관찰할 지표

`IMPRINT_PROFILE=1` 로 `~/.claude/imprint/profile.jsonl` 을 누적한 뒤 `/memory profile --json` 과 `/memory status --json` 으로 봅니다.

- `cmd_prefill`: working/retrieved count, retrieved-memory search skip 사유, context section count.
- `retrieve_done`: query surface 수, fallback 여부와 이유, rerank gate 사유.
- `stop.transcript_reparse`: 긴 세션에서 증가하는지.
- `call_claude`: Haiku 호출 RTT 와 timeout 빈도.
- `fetch_notion_url.payload`, `fetch_slack_url.payload`: 큰 payload 반복 여부.
- `cmd_lazy_fetch.enter/exit`, `cmd_extract.enter/exit`: enter 만 있고 exit 가 없는 작업 여부.

DB 관찰:

```sql
SELECT noise, COUNT(*) FROM events GROUP BY noise;
SELECT chunk_type, COUNT(*) FROM memory_chunks GROUP BY chunk_type;
SELECT json_extract(metadata_json, '$.status'), COUNT(*)
FROM memory_chunks
WHERE chunk_type = 'source_status'
GROUP BY 1;
```

## 측정 후 결정할 안건

- `IMPRINT_STALE_DAYS` 기본값이 실제 Notion/Slack 사용 주기에 맞는지.
- `source_status` marker 를 얼마나 오래 보관할지, TTL 또는 dedup 이 필요한지.
- `events.noise=1` row 를 계속 보존할지, 감쇠/삭제 정책을 둘지.
- working TTL/cap 이 실제 세션 길이에 맞는지.
- `LOW_CONFIDENCE_TOP1`, `RG_MIN_CANDIDATES`, `RG_TOP1_THRESHOLD` 를 조정할지.
- `memory_chunks` fallback 이 충분한지, 아니면 `memory_chunks → chunks_v2` bridge 또는 unified storage 가 필요한지.
- `stop.transcript_reparse`, `QEMB`, `HYB`, `RR` 중 daemon 분리가 필요한 병목이 있는지.
- plugin.log 회전 정책과 반복 실패 사용자 알림을 둘지.

## 단기 Watch List

- `Stop` hook 의 `transcript_path` 포맷은 Claude Code 내부 구조에 의존합니다. Claude Code 업데이트 후 `stop logged` 로그 누락 여부를 확인합니다.
- 새 hook 또는 background worker 추가 시 `IMPRINT_BYPASS_HOOKS` 가드를 반드시 확인합니다.
- `claude -p haiku` 호출은 10초 이상 걸릴 수 있으므로 동기 경로에 넣지 않습니다.
- 선택 ML 의존성 미설치 상태에서도 FTS-only / rule fallback 이 정상이어야 합니다.
- 운영 피드백은 바로 기능 추가로 옮기기보다 `/retrieve_json` trace 와 profile 데이터로 먼저 확인합니다.

## 다음 세션 시작 순서

1. `git status -sb` 로 작업 상태 확인.
2. `python3 scripts/imprint/tests/run_tests.py` 로 기준선 확인.
3. 실제 프로젝트에서 1~2개 turn 사용성 테스트.
4. `/memory status --json`, `/memory profile --json`, `plugin.log` 로 실패/지연 신호 확인.
5. 데이터가 충분히 쌓인 뒤 운영 정책 캘리브레이션 PR 로 진입.
