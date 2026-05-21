# Handoff — 다음 세션 픽업

**문서 책임**
- 본 문서는 단기 실행 문서입니다. 다음 세션에서 바로 확인할 항목, 운영 관찰 체크리스트, 측정 후 결정할 보류 안건만 둡니다.
- 큰 그림·아키텍처·장기 로드맵은 `LoadMap.md` 를 봅니다.
- 결정 사유와 폐기한 대안은 `HISTORY.md` 를 봅니다.
- 설치와 사용자 명령은 `README.md`, 상세 플로우와 의존성은 `flow.md` 를 봅니다.

최종 업데이트: 2026-05-21.

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

테스트는 임시 `IMPRINT_HOME=/tmp/...` 방식으로 격리합니다. 사용자 홈 `~/.imprint` 직접 수정은 명시 동의 전까지 하지 않습니다.

## 실측 관찰 (2026-05-21, NudgeEAP-iOS 세션)

실제 사용 프로젝트에서 `/retrieve_json` 을 직접 돌려 확인한 사실입니다.

- **벡터 검색이 꺼진 채 동작 중**: `embedding.is_available()` 이 `False`, `retrieve_json` 응답의 `embedding_used` 도 `False`. 즉 `sentence-transformers` 미설치로 `BAAI/bge-m3` 가 로드되지 않아 FTS-only 키워드 검색으로 폴백되어 있습니다. 설계상 의도된 graceful fallback 이지만, 사용자는 자신이 벡터 검색을 쓰고 있다고 오해하기 쉽습니다.
- **FTS-only 폴백의 변별력 한계**: 한국어 자연어 질문으로 검색 시 상위 후보의 `rrf_score` 가 0.003 대로 촘촘하게 붙어 변별력이 약했고, 의미상 덜 관련된 청크(`fetchStepPerHourList` 등)도 "현재/저장" 같은 단어 매칭만으로 상위에 진입했습니다.
- **핵심 목적과의 미스매치**: "로그인 feature 의 공유하기는 어떻게 구현됐었지" 류 큰 틀·개념 질문은 청크에 `share`/`deeplink`/`초대 링크` 등 다른 단어로 저장돼 있을 가능성이 커, 키워드만으로는 어휘 불일치로 놓치기 쉽습니다. 이 영역이 제품 핵심 목적인데 현재 가장 약합니다.
- **[핵심 결함] 자동 저장 메모리는 임베딩을 켜도 벡터 검색이 안 됨**: `memory_chunks` 테이블에는 embedding 컬럼이 아예 없고(`schema.sql:42`), `/retrieve` 의 `_memory_chunks_fallback_search` 도 FTS5 키워드만 사용합니다(`retrieve.py:316`). 즉 대화 자동 저장·`/memory remember` 로 쌓인 청크는 `sentence-transformers` 를 설치해도 벡터 유사도 측정 대상이 아닙니다. 벡터 검색은 명시 ingestion 된 `chunks_v2` 에만 존재하며, 그조차 백필/reindex 명령이 없어 모델 설치 후에도 기존 데이터는 재 ingest 해야 채워집니다. **결론: 임베딩을 옵션으로 두든 말든, 자동 메모리에는 의미 검색이 제공된 적이 없습니다.** 이는 단순 미설치 문제가 아니라 선결 구현 과제입니다.
- **재현 메모**: `embedding_used` 와 변별력은 `python3 -m retrieval.cli retrieve_json <project_id> "<자연어 질문>" 5` 로 언제든 재확인할 수 있습니다. memory_chunks 스키마는 `sqlite3 ~/.imprint/app.sqlite ".schema memory_chunks"` 로 embedding 컬럼 부재를 직접 확인할 수 있습니다.

## 목표별 현재 일치도

사용자가 이 프로젝트를 만든 원래 목적 기준의 단기 판단입니다.

| 목표 | 현재 상태 | 다음 액션 |
|---|---|---|
| 세션 종료 후 대화 맥락 저장 | **부분 충족**. `events` 에 raw I/O archive, `memory_chunks` 에 working/extracted/manual chunk 를 저장합니다. 다만 실제 재사용은 추출된 chunk 중심이라 response extract 실패나 누락 시 recall 이 약합니다. | Stop extract 품질 eval, raw event 를 장기 요약/백필 대상으로 삼는 경로 검토. |
| Codex / Claude Code 간 동일 문맥 공유 | **대체로 방향 일치**. 기본 DB 는 `~/.imprint/app.sqlite` 로 통합됐고 legacy Claude DB migration 도 있습니다. 단 양쪽 host 에서 hook 이 실제 동일하게 설치·실행되는지 통합 검증이 필요합니다. | Codex/Claude 각각에서 같은 project_id 로 user/assistant/memory chunk 가 쌓이는 smoke test 추가. |
| 큰 틀·개념 질문으로 맥락 상기 | **핵심 미충족**. 자동 저장 메모리(`memory_chunks`)는 FTS/LIKE 기반이라 `공유하기` vs `deeplink/share/invite link` 같은 어휘 불일치에 약합니다. 임베딩 설치만으로는 해결되지 않습니다. | `memory_chunks → chunks_v2` bridge 또는 `memory_chunks` embedding + 백필을 먼저 구현. |
| 다른 개발자에게 공유 가능한 기록 | **장기 미구현**. 로컬 SQLite 는 개인 세션 연속성에는 맞지만, 팀 공유에는 사람이 읽고 리뷰 가능한 Markdown/ADR export 가 필요합니다. | 로컬 RAG 안정화 후 `decision`/`summary` export, git commit/PR 참조 흐름 설계. |

## 다음 우선순위

1. **[선결] 자동 메모리 의미 검색 경로 구현** *(2026-05-21, 최우선)*
   현재 자동 저장 메모리는 임베딩을 설치해도 의미 검색이 안 됩니다. 우선안은 **`memory_chunks → chunks_v2` bridge** 입니다. 자동 hook/`/memory remember` 로 쌓인 memory 를 문서 RAG 계층에 복제하면 기존 embedding, hybrid retrieval, summary/entity/contradiction 후속 작업을 재사용할 수 있습니다.
   - 최소 수용 기준: 신규 `memory_chunks` 가 `chunks_v2` 검색 후보로도 보임.
   - 기존 데이터 기준: 과거 `memory_chunks` 를 bridge/backfill 하는 명령이 있음.
   - 회귀 기준: `/retrieve --json "로그인 feature 공유하기 어떻게 구현됐었지"` 류 어휘 불일치 질문에서 memory 후보가 키워드 없이도 회수됨.
   - 대안: `memory_chunks` 에 embedding 컬럼 추가 + 저장 시 embedding 생성 + 백필. 국소적이지만 retrieval v2 와 저장소가 계속 이중화됩니다.

2. **임베딩(벡터) 검색 활성화 및 개념 질의 검증** *(2026-05-21 추가)*
   1번 선결 후 의미가 있습니다. `sentence-transformers` + `BAAI/bge-m3`(약 2GB) 를 설치해 벡터 검색을 켜고, "로그인 feature 의 공유하기는 어떻게 구현됐었지" 류 개념·자연어 질문이 키워드 폴백 대비 실제로 더 나은 근거를 끌어오는지 같은 질문으로 비교합니다.

3. **Codex/Claude 공유 smoke test**
   같은 프로젝트에서 Codex 와 Claude Code 를 번갈아 열고 동일한 `~/.imprint/app.sqlite` 에 `events`/`memory_chunks` 가 쌓이는지 확인합니다. 설치 manifest 차이로 hook 이 한쪽에서 빠지는지 확인합니다.

4. **실제 프로젝트 사용성 테스트**
   저장한 기억이 다음 turn, `/memory`, `/retrieve --json` 에서 실제 답변 근거로 충분히 보이는지 확인합니다.

5. **작은 eval 세트 구성**
   자주 쓸 질문 20~30개를 고정하고 `/retrieve_json` trace 를 비교합니다. 예: UI 동작, 설정 동기화, Slack/Notion 실패, 짧은 backchannel, contradiction. 키워드 vs 벡터(하이브리드) 결과 차이도 함께 기록합니다.

6. **운영 정책 캘리브레이션**
   `IMPRINT_PROFILE=1` 로 1~2주 데이터를 모아 gate, MEMFB threshold, rerank 조건, working TTL/cap, stale 기준을 조정합니다.

7. **후순위 기능 확장 판단**
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
- bridge/backfill 구현 후, 자동 저장된 과거 `memory_chunks` 가 `chunks_v2`/vector 후보로도 회수되는지.
- Codex 와 Claude Code 에서 같은 프로젝트를 열었을 때 동일한 `~/.imprint/app.sqlite` 와 project_id 를 공유하는지.
- Slack/Notion fetch 실패, URL cap 초과, stale 외부 chunk 가 `/memory list/show/status` 에서 관찰 가능한지.

## 관찰할 지표

`IMPRINT_PROFILE=1` 로 `~/.imprint/profile.jsonl` 을 누적한 뒤 `/memory profile --json` 과 `/memory status --json` 으로 봅니다.

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
- `memory_chunks → chunks_v2` bridge 를 기본 경로로 둘지, 장기적으로 unified storage 로 합칠지.
- `stop.transcript_reparse`, `QEMB`, `HYB`, `RR` 중 daemon 분리가 필요한 병목이 있는지.
- plugin.log 회전 정책과 반복 실패 사용자 알림을 둘지.

## 단기 Watch List

- `Stop` hook 의 `transcript_path` 포맷은 Claude Code 내부 구조에 의존합니다. Claude Code 업데이트 후 `stop logged` 로그 누락 여부를 확인합니다.
- 새 hook 또는 background worker 추가 시 `IMPRINT_BYPASS_HOOKS` 가드를 반드시 확인합니다.
- host CLI background 모델 호출은 10초 이상 걸릴 수 있으므로 동기 경로에 넣지 않습니다.
- 선택 ML 의존성 미설치 상태에서도 FTS-only / rule fallback 이 정상이어야 합니다.
- 선택 ML 의존성 설치 여부와 별개로, bridge/backfill 전에는 자동 메모리가 vector 검색 대상이 아니라는 점을 사용자 문서에 계속 명시합니다.
- 운영 피드백은 바로 기능 추가로 옮기기보다 `/retrieve_json` trace 와 profile 데이터로 먼저 확인합니다.

## 다음 세션 시작 순서

1. `git status -sb` 로 작업 상태 확인.
2. `python3 scripts/imprint/tests/run_tests.py` 로 기준선 확인.
3. `memory_chunks → chunks_v2` bridge/backfill 설계와 테스트 범위를 먼저 확정.
4. 실제 프로젝트에서 개념 질의 1~2개로 `/retrieve --json` trace 확인.
5. `/memory status --json`, `/memory profile --json`, `plugin.log` 로 실패/지연 신호 확인.
