# Handoff — 다음 세션 픽업

**문서 책임**
- 본 문서는 단기 실행 문서입니다. 다음 세션에서 바로 확인할 항목, 운영 관찰 체크리스트, 측정 후 결정할 보류 안건만 둡니다.
- 큰 그림·아키텍처·장기 로드맵은 `LoadMap.md` 를 봅니다.
- 결정 사유와 폐기한 대안은 `HISTORY.md` 를 봅니다.
- 설치와 사용자 명령은 `README.md`, 상세 플로우와 의존성은 `flow.md` 를 봅니다.

최종 업데이트: 2026-05-23.

## 현재 기준선

RAG 기본 기능과 1차 운영 관측성은 적용 완료된 상태입니다.

- 자동 hook 루프: `SessionStart → UserPromptSubmit → Stop → 다음 UserPromptSubmit`.
- 첫 turn 가시성: user prompt 를 working mini-chunk 로 즉시 저장하고 prefill/search query context 로 사용.
- RAG context sections: query context, session memory, retrieved memory, external source context 분리.
- 수동 memory: `/remember` 로 명시 저장, `/memory search/list/show/inject/refresh/stats/profile/status`.
- 명시 검색 경로는 `chunks_v2`/`summaries` 우선, 저신뢰 또는 빈 후보면 `memory_chunks` read-only fallback.
- memory bridge: persistent `memory_chunks` 는 synthetic `documents`/`chunks_v2` row 로 승격됩니다. working raw turn 과 `source_status` marker 는 제외합니다.
- 관찰성: source status marker, events noise flag, profile JSONL, retrieve JSON trace, candidate provenance, text_hash dedup.
- 안전성: user/assistant/external/manual memory 저장 전 redaction.

최근 검증 기준:

```text
python3 scripts/imprint/tests/run_tests.py
TOTAL  22 PASS / 0 FAIL
```

테스트는 임시 `IMPRINT_HOME=/tmp/...` 방식으로 격리합니다. 사용자 홈 `~/.imprint` 직접 수정은 명시 동의 전까지 하지 않습니다.

## 실측 관찰 (2026-05-21, NudgeEAP-iOS 세션)

실제 사용 프로젝트에서 retrieval JSON trace 를 직접 돌려 확인한 사실입니다.

- **벡터 검색이 꺼진 채 동작 중**: `embedding.is_available()` 이 `False`, `retrieve_json` 응답의 `embedding_used` 도 `False`. 즉 `sentence-transformers` 미설치로 `BAAI/bge-m3` 가 로드되지 않아 FTS-only 키워드 검색으로 폴백되어 있습니다. 설계상 의도된 graceful fallback 이지만, 사용자는 자신이 벡터 검색을 쓰고 있다고 오해하기 쉽습니다.
- **FTS-only 폴백의 변별력 한계**: 한국어 자연어 질문으로 검색 시 상위 후보의 `rrf_score` 가 0.003 대로 촘촘하게 붙어 변별력이 약했고, 의미상 덜 관련된 청크(`fetchStepPerHourList` 등)도 "현재/저장" 같은 단어 매칭만으로 상위에 진입했습니다.
- **핵심 목적과의 미스매치**: "로그인 feature 의 공유하기는 어떻게 구현됐었지" 류 큰 틀·개념 질문은 청크에 `share`/`deeplink`/`초대 링크` 등 다른 단어로 저장돼 있을 가능성이 커, 키워드만으로는 어휘 불일치로 놓치기 쉽습니다. 이 영역이 제품 핵심 목적인데 현재 가장 약합니다.
- **[핵심 결함, 2026-05-22 1차 대응] persistent memory 는 임베딩을 켜도 벡터 검색이 안 됐음**: `memory_chunks` 테이블에는 embedding 컬럼이 없고, 과거 명시 search 의 memory fallback 도 FTS5 키워드만 사용했습니다. 2026-05-22에 `memory_chunks → chunks_v2` bridge 와 backfill 명령을 추가해 persistent memory 가 `chunks_v2` 후보로 보이게 했습니다. 다만 기본 bridge 는 embedding 을 생성하지 않으므로, 실제 vector 품질 검증은 `--embed` backfill 또는 `IMPRINT_MEMORY_BRIDGE_EMBEDDING=1` 이후 진행해야 합니다.
- **재현 메모**: `embedding_used` 와 변별력은 `python3 -m retrieval.cli retrieve_json <project_id> "<자연어 질문>" 5` 로 언제든 재확인할 수 있습니다. memory_chunks 스키마는 `sqlite3 ~/.imprint/app.sqlite ".schema memory_chunks"` 로 embedding 컬럼 부재를 직접 확인할 수 있습니다.

## 목표별 현재 일치도

사용자가 이 프로젝트를 만든 원래 목적 기준의 단기 판단입니다.

| 목표 | 현재 상태 | 다음 액션 |
|---|---|---|
| 세션 종료 후 대화 맥락 저장 | **부분 충족**. `events` 에 raw I/O archive, `memory_chunks` 에 working/extracted/manual chunk 를 저장합니다. 다만 실제 재사용은 추출 chunk 와 `/remember` 로 선별 저장한 기억 중심입니다. | Stop extract 품질과 `/remember` 저장 품질을 eval 에서 같이 확인. |
| 큰 틀·개념 질문으로 맥락 상기 | **부분 개선**. persistent memory 는 `chunks_v2` 후보가 되고, setup 경로로 embedding/backfill 도 실행할 수 있습니다. 아직 실제 프로젝트 eval 은 부족합니다. | 개념 질의 eval 세트를 만들어 키워드/벡터 결과를 비교. |
| 다른 개발자에게 공유 가능한 기록 | **장기 미구현**. 로컬 SQLite 는 개인 세션 연속성에는 맞지만, 팀 공유에는 사람이 읽고 리뷰 가능한 Markdown/ADR export 가 필요합니다. | 로컬 RAG 안정화 후 `decision`/`summary` export, git commit/PR 참조 흐름 설계. |

## 다음 우선순위

> 정렬 원칙: **벡터·의미 검색 결과를 명시 검색으로 확인하는 것(제품 핵심 목적) → confidence 표현 → 운영 피드백 수집** 순. 큰 기능 확장은 이 문서의 즉시 우선순위에서 제외합니다.

1. **개념 질의 eval 세트 구성**
   "로그인 feature 의 공유하기는 어떻게 구현됐었지" 류 자연어 질문 20~30개를 고정하고 `/remember` 로 선별 저장한 기억이 `/search` 에서 어떻게 회수되는지 확인합니다. `/search` 출력과 내부 retrieval JSON trace 를 비교해 키워드와 벡터가 각각 어떤 후보를 회수하는지, `embedding_used`, `vector_rank`, top1 score, fallback 이유를 같이 기록합니다. bridge row 를 summary/entity/contradiction queue 에 자동 연결할지는 이 eval 에서 검색 품질과 운영 비용을 본 뒤 판단합니다. *(측정 기반 — 벡터가 실제로 도움 되는지 먼저 확인해야 다음 투자가 정당화되므로 최상위.)*

2. **[미구현] `/search` confidence 수치화와 표시 기준**
   현재 `confidence` 는 확률값이 아니라 `final_score`, `LOW_CONFIDENCE_TOP1`, `fallback_reasons`, `rerank_gate_reason`, `embedding_used`, `vector_rank` 를 조합한 내부 휴리스틱입니다. 사용자에게 그대로 0~1 확률처럼 노출하면 오해가 생기므로, 먼저 eval 세트에서 top1 score 분포와 fallback 사유를 모아 `evidence_strength=strong|medium|weak` 또는 calibrated numeric score 를 정의합니다. 출력에는 숫자만 두지 말고 "왜 weak 인지"(예: `top1_below_threshold`, `memory_fallback`, `entity_mismatch`) 를 함께 보여줍니다.

3. **setup UX 보강 여부 판단**
   `imprint setup vector` 실사용 중 HF Hub 인증, 네트워크 실패, PEP 668 pip 실패, Claude Code skill 동기화에서 막히는 지점을 기록합니다. 필요하면 `HF_TOKEN` 안내와 실패 복구 메시지를 보강합니다.

## 사용성 테스트 체크리스트

- 새 세션 시작 시 `SessionStart` 가 스키마 적용과 `soul.md` prepend 를 조용히 수행하는지.
- “A 버튼 클릭 동작 알려줘” 같은 질문 직후 `[Query context]` 가 prefill 되는지.
- 다음 turn 에 Stop extract 또는 external lazy-fetch 결과가 `[Retrieved memory]` / `[External source context]` 로 보이는지.
- `/memory search <키워드>` 가 한국어 짧은 토큰 fallback 포함해 기대 chunk 를 찾는지.
- `/memory show --json <id>` 에서 metadata, `source_status`, `text_hash`, provenance 를 이해할 수 있는지.
- `/memory status --json` 이 DB/log/profile 상태와 working 정책을 보여주는지.
- 명시 검색 경로가 기대 context 를 사람이 읽을 수 있게 반환하는지.
- 문서 chunk 가 있으면 명시 검색 경로가 `chunks_v2` 를 우선하고, 저신뢰일 때만 `memory_chunks` fallback 을 여는지.
- bridge/backfill 후, 자동 저장된 과거 `memory_chunks` 가 `chunks_v2` 후보로 회수되는지. 선택 ML 환경에서는 `--embed` 후 vector 후보로도 회수되는지.

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
- working TTL/cap 이 실제 세션 길이에 맞는지.
- `LOW_CONFIDENCE_TOP1`, `RG_MIN_CANDIDATES`, `RG_TOP1_THRESHOLD` 를 조정할지.
- `memory_chunks → chunks_v2` bridge 후속 pipeline 을 어디까지 자동화할지.
- `stop.transcript_reparse`, `QEMB`, `HYB`, `RR` 중 daemon 분리가 필요한 병목이 있는지.
- plugin.log 회전 정책과 반복 실패 사용자 알림을 둘지.

## 단기 Watch List

- `Stop` hook 의 `transcript_path` 포맷은 Claude Code 내부 구조에 의존합니다. Claude Code 업데이트 후 `stop logged` 로그 누락 여부를 확인합니다.
- 새 hook 또는 background worker 추가 시 `IMPRINT_BYPASS_HOOKS` 가드를 반드시 확인합니다.
- host CLI background 모델 호출은 10초 이상 걸릴 수 있으므로 동기 경로에 넣지 않습니다.
- 선택 ML 의존성 미설치 상태에서도 FTS-only / rule fallback 이 정상이어야 합니다.
- `IMPRINT_MEMORY_BRIDGE_EMBEDDING=1` 상시 활성화가 hook latency 를 얼마나 늘리는지 profile 로 확인하기 전에는 기본값으로 켜지 않습니다.
- 운영 피드백은 바로 기능 추가로 옮기기보다 내부 retrieval trace 와 profile 데이터로 먼저 확인합니다.

## 다음 세션 시작 순서

1. `git status -sb` 로 작업 상태 확인.
2. `python3 scripts/imprint/tests/run_tests.py` 로 기준선 확인.
3. `imprint setup vector --status` 로 벡터 런타임 상태 확인.
4. 실제 프로젝트에서 개념 질의 1~2개로 명시 검색 출력과 내부 trace 의 `embedding_used` 확인.
5. `/memory status --json`, `/memory profile --json`, `plugin.log` 로 실패/지연 신호 확인.
