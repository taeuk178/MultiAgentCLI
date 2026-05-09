# Handoff — claude-plugin 브랜치

다음 세션에서 이어서 작업할 때 참고하는 문서입니다. 최종 업데이트: 2026-05-09.

> 완료된 Phase 1·2·3(부분)·4(부분)·HUD·플러그인 설치 항목은 README.md에 반영되어 본 문서에서는 제거함. 구현된 내용은 README의 사용/구조/데이터 위치 섹션 참조.

## Context Ingestion 구현 — feat/context-ingestion 브랜치 (2026-05-09)

Seed v0.6의 17개 acceptance criteria + 24개 decisions를 구현. `feat/context-ingestion` 브랜치에서 wiring 완료. spec YAML은 구현 동결 후 제거 — 결정 내역은 README의 `## 사내 컨텍스트 ingestion` 섹션과 본 브랜치 커밋 히스토리에 보존됨.

**구현 산출물:**

| 책임 | 파일 |
|------|------|
| FTS5 trigram 마이그레이션 | `scripts/imprint/lib/migrations.sh` (D16, AC10) |
| Schema (trigram tokenizer) | `scripts/imprint/lib/schema.sql` |
| Lazy fetch · 모호도 분석 · 검색 · refresh | `scripts/imprint/lib/ingestion.py` (단일 Python 모듈, 모든 LLM 호출은 `claude -p --model haiku`) |
| `.imprint/sources.json` 시드 | `prompts/defaults/sources.json` |
| Prefill (UserPromptSubmit) | `scripts/imprint/user-prompt-submit.sh` |
| Stop chunk 추출 | `scripts/imprint/stop.sh` |
| `/memory refresh` | `scripts/imprint/memory.sh` |
| skill 문서 | `skills/memory/SKILL.md` |
| README narrative | `README.md` `## 사내 컨텍스트 ingestion` 섹션 |

**검증 통과:**
- AC1·AC4·AC7·AC10·AC11·AC15·AC16: smoke test로 graceful degradation 경로 확인 (broken claude CLI / sources.json 부재 / 외부 chunk only DELETE 등)
- 한국어 부분문자열 검색 — `더스트` 가 `더스트가/더스트의`에 hit (AC10) — 단, trigram tokenizer 특성상 검색어는 ≥3자여야 매칭됨
- unicode61 → trigram DROP+REBUILD migration 정상 동작
- `/memory refresh <url>|source slack|source notion|project` 정확히 외부 chunk만 삭제 (내부 decision/todo/note 보존)

**미검증 (사용자 환경 의존):**
- AC5: iOS 팀 정성 검증 1주
- claude -p haiku 호출 (실제 OAuth 환경에서만 검증 가능)
- Slack/Notion MCP 비-대화형 fetch (`--allowed-tools` 가 사용자 등록 MCP 이름과 일치하는지)

**hook timeout** — `hooks/hooks.json`의 UserPromptSubmit·Stop을 5/10초 → 30/30초로 상향. 실제 latency는 claude -p 내부 timeout (`IMPRINT_CLAUDE_TIMEOUT_*`)이 결정.

## (이력) Context Ingestion 인터뷰 마무리 (2026-05-08)

Ouroboros Socratic 인터뷰로 사내 프로젝트 컨텍스트(Slack 대화, Notion 기획 정의서)를 lazy fetch로 흡수하고 prefill에서 LLM에 자동 보강하는 파이프라인을 spec 단계까지 동결.

**산출물:**
- Seed v0.6.0-draft (24개 decisions, 17개 acceptance_criteria, 7 risks, ambiguity_score 0.08) — 구현 동결 후 spec YAML은 제거, narrative만 README/HANDOFF/LoadMap에 보존
- README — `## 사내 컨텍스트 ingestion` 섹션에 narrative + 결정 표 + sources.json/metadata 예시 모두 반영
- 인터뷰 세션: `interview_20260508_054044`

**핵심 결정 한 줄 요약:**
- 메모리: 기존 SQLite + FTS5 그대로(DDL 변경 없음), tokenizer만 trigram으로 (D16)
- 외부 소스: events skip + memory_chunks에 직접 insert, 9개 chunk_type 자유 선택, metadata로 출처 보존 (D10–D13)
- Prefill: claude -p haiku로 모호도+키워드 분석, 모호 시 [Refined prompt suggestion] 블록 prepend (D7, D19)
- Slack: URL 명시 + 키워드 검색 hybrid, thread는 selection+summary로 압축 (D20)
- Notion: 사용자 환경 Notion MCP 사용 (D21)
- 캐시: url 기반 dedup, TTL ∞, `/memory refresh` 명시 명령으로만 갱신 (D22–D24)
- 공유: SQLite는 BYO 로컬 격리, sources.json만 git-share, migration은 Phase 2 (D14–D15)
- Vector: Phase 2 후순위, PageIndex 스타일은 비채택 (D18)

## Chunk 분류 세분화 검토 (2026-05-09)

청크 데이터가 한 테이블·9개 chunk_type enum + `metadata_json` 한 봉지에 모두 들어가는데, 실제 DB를 보면 **28건이 모두 `note` × `source=notion` 한 칸에 통밥**된 상태(외부 source chunk를 일괄 `note`로 INSERT). 9개 enum이 의미를 못 살리고 있고, 자주 쓰는 metadata 키(`source`, `page_id`, `url`)는 인덱스 없이 row마다 `json_extract`로 파싱됨.

**현 schema 핵심 (`scripts/imprint/lib/schema.sql:39-54`)**

- 분류 축 3개: `chunk_type` enum(9), `metadata.source` JSON, `pinned`
- 인덱스: `(project_id, pinned DESC, created_at DESC)`, `(project_id, chunk_type)` — metadata 인덱스 없음
- 검색: FTS5 trigram(text) ∪ `metadata.keywords` 배열 hit ranking

**제안 — 두 단계로 끊어서 진행**

1. 외부 source `chunk_type` 분리 (작은 의미 변경)
   - `note(notion)` → `spec`, `note(slack 단발)` → `message`, `note(slack thread)` → `thread`
   - `fetch_notion_url` / `fetch_slack_*`의 INSERT 자리에서 chunk_type만 변경
   - 기존 28건 backfill 1줄: `UPDATE memory_chunks SET chunk_type='spec' WHERE json_extract(metadata_json,'$.source')='notion';`

2. metadata 키 generated column + 인덱스 승격 (검색 성능)
   ```sql
   ALTER TABLE memory_chunks ADD COLUMN
     meta_source TEXT GENERATED ALWAYS AS (json_extract(metadata_json,'$.source')) VIRTUAL;
   ALTER TABLE memory_chunks ADD COLUMN
     meta_page_id TEXT GENERATED ALWAYS AS (json_extract(metadata_json,'$.page_id')) VIRTUAL;
   CREATE INDEX idx_chunks_source ON memory_chunks(project_id, meta_source);
   CREATE INDEX idx_chunks_page ON memory_chunks(project_id, meta_page_id);
   ```
   - `chunk_url_exists`, `cmd_refresh`, prefill 검색이 즉시 빨라짐
   - 같은 Notion 페이지 N개 섹션의 page-level 그룹화 쿼리 정상화

**가지 말아야 할 길**

- 외부 source 별도 테이블 (`external_chunks` 등) — 현재 28건 규모에 union/trigger/FTS 두 벌 운영비가 분류 이득보다 큼
- `chunk_type` enum 자유 텍스트화 — 일관성 상실

**트레이드오프 한 줄**

schema migration이 사용자 머신마다 한 번씩 돌아야 한다(`scripts/imprint/lib/migrations.sh`에 추가). 다만 데이터 양이 28건일 때가 마이그레이션 부담이 가장 작은 시점이라 분류 도입은 지금이 적기. 1번만 먼저 가고, 2번은 검색 체감이 느려졌을 때 추가하는 점진 전략 권장.

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

### TODO 3. ~~구현 시작~~ → 사용자 환경 검증 (Seed v0.6 → 구현 완료)

`feat/context-ingestion` 브랜치에서 6개 후보 단계가 모두 구현됨. 위 "Context Ingestion 구현" 섹션 참조.

다음 액션:
1. iOS 팀 멤버 1명이 brunch checkout 후 자기 사내 프로젝트에서 1주 정성 검증 (AC5)
2. `IMPRINT_ALLOWED_TOOLS_FETCH` 가 사용자 등록 Slack/Notion MCP 이름과 일치하는지 확인 (각자 다를 수 있음)
3. plugin.log에서 `WARN: claude -p` 빈도 모니터링 — 일정 임계 초과 시 timeout 조정

## 남은 작업

### Phase 3 마무리 (Memory skill 정교화)

**Stop hook 청크 추출**
- 현재 `stop.sh`는 응답 전체를 `llm_response` 이벤트로만 저장.
- 응답에서 `chunk_type`별로 추출 필요.
- 두 가지 방식 비교 후 채택:
  1. 정규식/키워드 기반 추출 (빠름, 단순)
  2. `claude -p`로 LLM 추출 (정확, 비용은 구독)
- 시작점: `scripts/imprint/stop.sh` 마지막 부분에 추출 단계 추가.

**Redaction**
- `memory.sh remember --redact` 플래그 미구현.
- `~/.claude/imprint/redact-rules.json` 형식으로 정규식 룰셋 정의.
- 시작점: `scripts/imprint/lib/common.sh`에 `redact_text()` 함수 추가.

**memory list 필터 보강**
- 현재 `--recent`, `--pinned`, `--type` 만 지원.
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

### Phase 5. Workflow skill (미시작)

- `/commit-message` — `git diff --cached` + 최근 memory로 커밋 메시지 후보 생성.
- `/pr-draft` — `git log <base>..HEAD` + memory로 PR 본문.
- `/recap` — 오늘의 작업 요약.
- `/handoff` — 다음 세션용 자동 brief (이 문서 재생성).
- 위치 제안: `skills/workflow/SKILL.md` + `scripts/imprint/workflow.sh`.

### Phase 6. 외부 레지스트리 (미시작)

- `imprint skill add <github-url>` — GitHub repo에서 SKILL.md 다운로드 후 `~/.claude/imprint/skills/`에 배치.
- `imprint skill publish <name>` — 본인 GitHub repo에 PR 또는 push.
- manifest.json 포맷 정의 필요.
- 권한·서명 검증은 Phase 6.5 이후.

### Phase 7. Vector / 고급 추출 (미시작)

- sqlite-vec 또는 LanceDB 도입.
- chunk embedding pipeline.
- hybrid search (FTS + vector).

### Tauri 앱 처리 결정

- **폐기 완료.** Tauri/React/Vite 관련 파일과 빌드 산출물을 본 repo에서 모두 삭제했고, plugin 단일 책임으로 재정의함.
- 제거 대상: `src/`, `src-tauri/`, `dist/`, `node_modules/`, `index.html`, `vite.config.ts`, `tsconfig*.json`, `package.json`, `pnpm-lock.yaml`, `scripts/generate-provider-types.mjs`.
- 문서 갱신: `README.md`, `CLAUDE.md`, `LoadMap.md`를 plugin 기준으로 재작성하고 `.gitignore`에서 Tauri/Node 관련 라인 제거.
- Dev PTY 모드가 필요한 사용자는 SwiftUI 버전 `MultiAgentCLI`를 사용하도록 안내.

## 공존하는 외부 plugin: oh-my-claudecode (omc)

본 imprint plugin과 별개로 **`oh-my-claudecode` (omc) plugin**이 동일 Claude Code 환경에 설치되어 있을 수 있고, 자체 메모리 시스템을 운영함. 두 plugin이 각자 메모리 저장소를 갖는 구조이므로 충돌·중복 주입 가능성에 유의.

- **저장 위치**: `<project>/.omc/project-memory.json` (per-project, JSON)
  - vs imprint: `~/.claude/imprint/app.sqlite` (per-user, SQLite + FTS5)
- **주입 시점**: omc의 `project-memory-session.mjs` hook이 SessionStart에서 별도 컨텍스트로 prepend (imprint의 `[Project memory context]` 블록과는 별개 채널)
- **자동 갱신**: omc의 `project-memory-posttool.mjs` (PostToolUse)가 Read/Write/Edit/Bash 후 `hotPaths`, `lastAccessed` 등 자동 누적 / `project-memory-precompact.mjs`(PreCompact)가 압축 직전 보존
- **저장 데이터**:
  - 자동 스캔: `techStack`, `build`, `conventions`, `directoryMap`, `hotPaths`
  - 사용자 입력: `customNotes`(학습된 사실), `userDirectives`(작업 시 따라야 할 지시)
- **MCP tool**: `project_memory_read` / `project_memory_write` / `project_memory_add_note` / `project_memory_add_directive`
- **plugin 본체 위치**: `~/.claude/plugins/cache/omc/oh-my-claudecode/<ver>/`

설계 시 고려사항 — 우리 plugin의 Memory 청크 주입과 omc의 project-memory 주입이 겹쳐 컨텍스트가 비대해질 수 있음. 향후 두 시스템을 결합하거나 사용자가 한쪽을 비활성화하도록 안내하는 옵션을 고려할 만함.

## 알려진 제약

- macOS 기본 환경 가정. Linux/Windows 호환은 확인 안 함.
- `python3`, `sqlite3`, `uuidgen` 시스템 의존.
- Stop hook의 `transcript_path` 포맷은 Claude Code 내부 구조에 의존 — 버전 변경 시 깨질 수 있음.
- 동일 프로젝트에서 여러 Claude Code 세션이 동시에 돌면 SQLite WAL이 처리하지만, 완전한 동시성 검증은 안 함.

## 다음 세션 시작 시 추천 픽업 지점

1. **현재 우선순위 — Context Ingestion 확장 (Seed v0.6)**: 위 "TODO 3. 구현 시작" 섹션의 1번(schema.sql trigram migration)부터 점진적으로. Stop hook chunk 추출(Phase 3 마무리)도 이 Seed의 일부로 흡수됨.
2. **남은 인터뷰 라운드**: TODO 1·2를 다른 노트북·세션에서 `/ouroboros:interview ...`로 재개. Seed v0.6이 immutable spec이므로 새 결정은 D25부터 추가.
3. **빠른 검증**: `bash scripts/imprint/advisor.sh codex "ping"`으로 OAuth advisor 흐름 확인 (별도 트랙).
4. **Phase 5 (workflow skill)**: `/commit-message` 등 — Context Ingestion이 안정된 뒤로 미룸.

## 파일 인덱스

```
.claude-plugin/
  plugin.json              플러그인 매니페스트
  marketplace.json         로컬 마켓플레이스 entry
hooks/hooks.json           hook 등록
skills/
  memory/SKILL.md
  advisor/SKILL.md
  hud/SKILL.md
scripts/imprint/
  lib/common.sh            DB·project·로그 헬퍼
  lib/schema.sql           SQLite 스키마 (idempotent)
  session-start.sh         SessionStart hook
  user-prompt-submit.sh    UserPromptSubmit hook
  stop.sh                  Stop hook
  memory.sh                /memory dispatcher
  advisor.sh               /advisor dispatcher
  hud.sh                   statusline body
  hud-setup.sh             statusLine install/status/uninstall/layout
INSTALL.md                 설치 가이드
LoadMap.md                 방향성·로드맵
HANDOFF.md                 이 문서
```

## 커밋 히스토리 (claude-plugin 브랜치)

```
f75f39b HANDOFF에 HUD 개선과 최신 커밋 히스토리 반영
b50cfa0 HUD에 잔여 시간 표시와 활성 플러그인 카운트 반영
8f15837 HANDOFF에 HUD 스킬 완료 내역 반영
d9fc100 imprint HUD 스킬과 statusline 스크립트 추가
89d7297 다음 세션 픽업용 HANDOFF 문서 추가
736b55e Claude Code plugin 골격 추가
5ba9034 LoadMap을 Claude Code plugin 방향으로 재정의
```
