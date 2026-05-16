# Handoff — 다음 세션 픽업

**문서 책임**
- 본 문서는 **단기 실행 문서**입니다. 다음 세션에서 바로 확인할 항목, 운영 관찰 체크리스트, 측정 후 결정할 보류 안건만 둡니다.
- 큰 그림·아키텍처·장기 로드맵은 `LoadMap.md` 를 봅니다.
- 결정 사유와 폐기한 대안은 `HISTORY.md` 를 봅니다.
- 현재 동작·설치·전체 플로우 다이어그램은 `README.md` 를 봅니다.

최종 업데이트: 2026-05-16.

## 현재 기준선

RAG 기본 기능 1차 적용은 완료된 상태입니다.

- 저장 안전성: user prompt, assistant response, external chunk, extracted chunk, `/memory remember` redaction 적용.
- 자동 루프: `SessionStart → UserPromptSubmit → Stop → 다음 UserPromptSubmit` smoke test 통과.
- 수동 확인: `/memory search/list/show/inject/remember` 기본 경로 동작.
- 명시 조회: `/retrieve` 는 `chunks_v2`/`summaries` 우선, 후보 0개면 `memory_chunks` read-only fallback.
- 관찰성: `source_status` marker, `events.noise`, `/memory profile` 추가.
- 문서: README 전체 플로우와 Mermaid가 현재 구현 흐름을 반영.

최근 검증 기준:

- 로컬 테스트: `python3 scripts/imprint/tests/run_tests.py` 에서 신규 TC-14 통과. 환경에 따라 TC-08 LLM judge 는 fail 가능.
- Claude 격리 테스트: `14 PASS / 0 FAIL`.
- 사용자 홈 DB를 건드리지 않는 임시 `IMPRINT_HOME=/tmp/...` 방식으로 검증.

## 다음 우선순위

1. **실제 프로젝트 사용성 테스트**
   자동 prefill, `/memory search/inject`, `/retrieve` fallback 이 실제 답변 근거로 충분한지 확인합니다. 기능 추가보다 “저장한 기억을 믿고 다시 꺼낼 수 있는가”를 먼저 봅니다.

2. **운영 정책 캘리브레이션**
   `IMPRINT_PROFILE=1` 을 켠 상태로 1~2주 데이터를 모아 `source_status` 누적량, `events.noise` 비율, stage latency, fetch payload 를 확인합니다.

3. **후순위 기능 확장 판단**
   Workflow skill(`/commit-message`, `/pr-draft`, `/recap`, `/handoff`), registry, entity merge/split UI 는 RAG 기본 루프가 실제 사용에서 안정된 뒤 진입합니다.

## 사용성 테스트 체크리스트

실제 프로젝트에서 아래 흐름을 한 번씩 확인합니다.

- 새 세션 시작 시 `SessionStart` 가 스키마 적용과 soul prepend 를 조용히 수행하는지.
- “A 버튼 클릭 동작 알려줘” 같은 질문 후 다음 turn 에 `[Project memory context]` 가 관련 chunk 를 prepend 하는지.
- `/memory search <키워드>` 가 2자 한글 fallback 포함해 기대 chunk 를 찾는지.
- `/memory show --json <id>` 에서 `source_status`, metadata, text 를 사용자가 이해할 수 있는지.
- `/memory inject <id>` 로 특정 근거를 현재 turn 에 넣을 수 있는지.
- `/retrieve --routed <질문>` 이 문서 chunk 가 없을 때 `memory_chunks` fallback 을 보여주는지.
- 문서 chunk 가 있으면 `/retrieve` 가 `chunks_v2` 를 우선하고 fallback 이 덮지 않는지.
- Slack/Notion fetch 실패, URL cap 초과, stale 외부 chunk 가 `/memory list/show` 에서 보이는지.

## 관찰할 지표

`IMPRINT_PROFILE=1` 로 `~/.claude/imprint/profile.jsonl` 을 누적한 뒤 `/memory profile` 로 봅니다.

- `cmd_prefill`: 50 ms 안팎 유지 여부.
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
- `source_status` marker 를 얼마나 오래 보관할지, TTL 또는 dedupe 가 필요한지.
- `events.noise=1` row 를 계속 보존할지, 감쇠/삭제 정책을 둘지.
- `stop.transcript_reparse`, `QEMB`, `HYB`, `RR` 중 daemon 분리가 필요한 병목이 있는지.
- `memory_chunks` fallback 이 충분한지, 아니면 `memory_chunks → chunks_v2` bridge 또는 unified storage 가 필요한지.
- 기존 사용자 DB에 과거 raw token-shaped 문자열이 있다면, 사용자 승인 하에 청소할지.
- plugin.log 회전 정책과 반복 실패 사용자 알림을 둘지.

## 단기 Watch List

- `Stop` hook 의 `transcript_path` 포맷은 Claude Code 내부 구조에 의존합니다. Claude Code 업데이트 후 `stop logged` 로그 누락 여부를 확인합니다.
- 새 hook 또는 background worker 추가 시 `IMPRINT_BYPASS_HOOKS` 가드를 반드시 확인합니다.
- `sentence_transformers`, `transformers`, `sqlite-vec` 는 선택 의존성입니다. 미설치 시 FTS-only fallback 이 정상이어야 합니다.
- `claude -p haiku` 호출은 10초 이상 걸릴 수 있으므로 동기 경로에 넣지 않습니다.
- 사용자 홈 `~/.claude/imprint` 를 직접 수정하는 작업은 반드시 사용자 동의 후 진행합니다.

## 다음 세션 시작 시 추천 순서

1. `git status -sb` 로 작업 상태 확인.
2. `README.md` 전체 플로우와 실제 테스트 대상 프로젝트의 기대 동작 비교.
3. 임시 `IMPRINT_HOME` 가 아닌 실제 프로젝트에서 1~2개 turn 사용성 테스트.
4. `/memory profile --json` 과 `plugin.log` 로 실패/지연 신호 확인.
5. 데이터가 충분히 쌓인 뒤 운영 정책 캘리브레이션 PR 로 진입.
