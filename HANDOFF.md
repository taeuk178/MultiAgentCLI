# Handoff — 다음 세션 픽업

**문서 책임**
- 본 문서는 **단기**: 즉시 다음에 손댈 검토 안건, deferred TODO, 직전 작업의 미완 Phase, 다음 세션 시작 시 픽업 지점만 담는다.
- **큰 그림**(비전·Phase 정의·아키텍처·위험 요소·미시작 Phase 5/6/7)은 `LoadMap.md` 참조.
- **결정 사유 로그**(왜 그렇게 바꿨는지)는 `HISTORY.md` 참조.
- 구현 완료된 Phase 1·2·3(부분)·4(부분)·HUD·플러그인 설치는 `README.md`의 사용/구조/데이터 위치 섹션 참조.

최종 업데이트: 2026-05-09.

## Chunk 분류 세분화 — 1단계 완료 (2026-05-09)

**1단계: 외부 source `chunk_type` 분리.** Notion → `spec`, Slack 단발 → `message`, Slack thread → `thread`. `ingestion.py`의 5개 INSERT 자리에서 hardcoded `"note"`를 source별 분기로 교체, `migrations.sh`에 멱등 backfill 추가. 사유는 `HISTORY.md` 2026-05-09 항목 참조.

**2단계: metadata 키 generated column + 인덱스 승격 (대기).** 검색 체감이 느려진 시점에 점진 도입.

```sql
ALTER TABLE memory_chunks ADD COLUMN
  meta_source TEXT GENERATED ALWAYS AS (json_extract(metadata_json,'$.source')) VIRTUAL;
ALTER TABLE memory_chunks ADD COLUMN
  meta_page_id TEXT GENERATED ALWAYS AS (json_extract(metadata_json,'$.page_id')) VIRTUAL;
CREATE INDEX idx_chunks_source ON memory_chunks(project_id, meta_source);
CREATE INDEX idx_chunks_page ON memory_chunks(project_id, meta_page_id);
```

진입 조건: `chunk_url_exists` / `cmd_refresh` / prefill 검색에서 row-level `json_extract` 비용이 체감될 때. 현재 28건 규모에서는 측정 가능한 차이가 없어 보류.

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
- **plugin.log 회전**: 크기·날짜 기반 회전 정책. 압축? 며칠 보관?
- **반복 실패 사용자 알림**: silent fail이 누적될 때 statusline·session-start prepend로 보고할지. 임계치?
- **conversation_id 관리**: 한 SessionStart마다 새 conversation? idle 시간 기준 분리?

진입 명령: `/ouroboros:interview 보안·운영 (redaction·log 회전·에러 알림·conversation_id)`

### TODO 3. 사용자 환경 검증

1. iOS 팀 멤버 1명이 브랜치 checkout 후 자기 사내 프로젝트에서 1주 정성 검증 (AC5)
2. `IMPRINT_ALLOWED_TOOLS_FETCH` 가 사용자 등록 Slack/Notion MCP 이름과 일치하는지 확인 (각자 다를 수 있음)
3. plugin.log에서 `WARN: claude -p` 빈도 모니터링 — 일정 임계 초과 시 timeout 조정

## 직전 작업의 미완 — Phase 3·4 마무리

### Phase 3 마무리 (Memory skill 정교화)

**Redaction**
- `memory.sh remember --redact` 플래그 미구현.
- `~/.claude/imprint/redact-rules.json` 형식으로 정규식 룰셋 정의.
- 시작점: `scripts/imprint/lib/common.sh`에 `redact_text()` 함수 추가.

**memory list 필터 보강**
- 현재 `--recent`, `--pinned`, `--type`, `--source`만 지원.
- 추가 필요: `--since <date>`, `--limit <n>`, `--project <path>` (다른 프로젝트 검색).

### Phase 4 마무리 (Advisor skill 검증)

**End-to-end 테스트**
- `bash scripts/imprint/advisor.sh codex "test"` 직접 실행 → codex CLI 인증 흐름과 출력 캡처 확인.
- Gemini는 `GEMINI_CLI_TRUST_WORKSPACE=true` 환경변수 의존 — 사용자 머신 정책에 따라 실패 가능.
- CCG 합성 단계에서 `claude -p`가 비대화형 OAuth로 동작하는지 확인.

**Timeout / cancellation**
- 현재 `advisor.sh`는 백그라운드 wait만 사용 — 무한 대기 위험.
- `timeout 60s` 명령 또는 trap 기반 취소 추가.

**Partial failure 저장**
- 한쪽 advisor 실패해도 다른 쪽 결과는 `provider_runs`에 status='succeeded'로 남김.
- 합성 단계에서 빈 입력 처리 필요 (현재는 둘 다 비어 있을 때만 에러).

## 단기 Watch List

- Stop hook의 `transcript_path` 포맷은 Claude Code 내부 구조에 의존 — Claude Code 버전 업그레이드 시 깨질 수 있어 plugin.log에서 `stop logged` 로그 누락 여부를 정기 확인.
- `IMPRINT_BYPASS_HOOKS` 가드가 빠진 새 hook 추가 시 ingestion 무한 재귀 재발 위험 — hook 추가 시 가드 한 줄 누락 점검.

## 다음 세션 시작 시 추천 픽업 지점

1. **Phase 3·4 마무리** — 위 "직전 작업의 미완" 섹션. Redaction(`memory.sh remember --redact` + `redact-rules.json`), `memory list` 필터 보강, advisor timeout/cancellation, partial failure 저장. 사용자 손에 닿는 부분이라 가장 가시적인 가치.
2. **남은 인터뷰 라운드** — TODO 1·2를 별도 세션에서 `/ouroboros:interview ...`로 재개. Seed v0.6이 immutable spec이므로 새 결정은 D25부터.
3. **사용자 환경 검증** — TODO 3을 iOS 팀에 위임하고 plugin.log에서 `WARN: claude -p` 빈도 모니터링.
4. **빠른 검증** — `bash scripts/imprint/advisor.sh codex "ping"`으로 OAuth advisor 흐름 확인 (별도 트랙).
5. **Chunk 분류 2단계** — 위 1단계 완료 후 대기. 검색 체감 저하 시 진입.
