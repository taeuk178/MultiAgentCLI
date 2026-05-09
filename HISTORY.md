# imprint 결정 사유 로그

**문서 책임**
- 본 문서는 **왜 이렇게 했는가**를 남긴다. 코드만 보면 알 수 없는 트레이드오프, 폐기된 대안, 결정 시점의 제약을 사실 위주로 기록한다.
- 큰 그림(비전·Phase 정의·아키텍처): `LoadMap.md`
- 단기 픽업(즉시 검토·deferred TODO·미완 Phase): `HANDOFF.md`
- hook 단계별 시스템 의존·운영 환경 변수: `flow.md`
- 사용·설치: `README.md`

기록 순서는 **최신이 위**. 항목당 한 단락 안에 변경/사유/대안 폐기 근거를 묶는다.

## 2026-05-09 — 외부 source `chunk_type` 분리 (`note` → `spec`/`message`/`thread`)

**무엇:** `memory_chunks.chunk_type`에 `spec`(Notion), `message`(Slack 단발), `thread`(Slack thread)를 추가하고 `ingestion.py`의 5개 INSERT 자리(`fetch_slack_url` URL/keyword, `fetch_notion_url` URL/keyword, `cmd_refresh`)에서 hardcoded `"note"`를 source별로 분기. `migrations.sh`에 backfill 함수(`backfill_external_chunk_types`) 추가 — `chunk_type='note'` 필터로 멱등성 보장. `search_memory` fallback 쿼리에 새 타입 포함.

**왜:** DB를 까보니 28건 전부 `note × source=notion` 한 칸에 통밥된 상태(`HANDOFF.md` 2026-05-09 검토). 9개 enum이 의미를 못 살리고, 같은 Notion 페이지 N개 섹션·Slack thread reply·단발 메시지가 한 타입 안에 섞여 있어 `/memory list --type` 같은 필터가 무력. `chunk_type`은 enum이라 자유 텍스트화는 일관성을 무너뜨리므로 enum에 3개를 추가하는 쪽을 선택.

**폐기한 대안:**
- 외부 source 별도 테이블(`external_chunks`) — 28건 규모에 union/trigger/FTS 두 벌 운영비가 분류 이득보다 큼. 향후 row 수가 만 단위로 갈 때 재검토.
- `metadata.source` 인덱스 승격(generated column + index) — 같은 검토에 묶여 있던 2단계. 검색 체감이 느려진 시점에 점진 도입 권장(`HANDOFF.md` 2단계 제안).

**타이밍 근거:** schema migration이 사용자 머신마다 한 번 돌아야 하지만, 데이터 양 28건일 때가 부담이 가장 작은 시점. 현재 시점(2026-05-09) 외 다른 시점에는 backfill 비용이 선형 증가.

**범위 노트:** LLM 추출 enum(`CHUNK_TYPES` 9개)은 그대로 두고, 외부 source 전용 enum을 `EXTERNAL_CHUNK_TYPES = ("spec", "message", "thread")`로 분리. `EXTRACT_PROMPT`(Stop hook이 응답에서 추출)는 9개만 유지 — 응답 본문에서 spec/message/thread를 추출하는 의미는 없음.

## 2026-05-?? 이전 — 누락 항목

이 문서는 2026-05-09에 신설됐다. 이전 결정(Phase 4.5 ingestion, Tauri 폐기, FTS5 trigram 채택, IMPRINT_BYPASS_HOOKS 가드 도입 등)의 사유는 `LoadMap.md`·`HANDOFF.md`·각 파일 상단 docstring과 git log에 분산되어 있다. 신설 이후 결정만 본 문서에 누적한다.
