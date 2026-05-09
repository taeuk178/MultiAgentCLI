# Handoff — claude-plugin 브랜치

다음 세션에서 이어서 작업할 때 참고하는 문서입니다. 최종 업데이트: 2026-05-08.

> 완료된 Phase 1·2·3(부분)·4(부분)·HUD·플러그인 설치 항목은 README.md에 반영되어 본 문서에서는 제거함. 구현된 내용은 README의 사용/구조/데이터 위치 섹션 참조.

## Context Ingestion 확장 — 인터뷰 마무리 (2026-05-08)

Ouroboros Socratic 인터뷰로 사내 프로젝트 컨텍스트(Slack 대화, Notion 기획 정의서)를 lazy fetch로 흡수하고 prefill에서 LLM에 자동 보강하는 파이프라인을 spec 단계까지 동결.

**산출물:**
- Seed YAML — [`.ouroboros/seeds/context-ingestion.yaml`](.ouroboros/seeds/context-ingestion.yaml) v0.6.0-draft (24개 decisions, 17개 acceptance_criteria, 7 risks, ambiguity_score 0.08)
- README — `## 계획된 확장: 사내 컨텍스트 ingestion` 섹션에 narrative + 결정 표 + sources.json/metadata 예시 모두 반영
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

### TODO 3. 구현 시작 (Seed v0.6 기준)

PR break는 별도 PR agent로 처리 — 본 인터뷰 scope에서 제외.

가장 작은 첫 PR 후보 (위험도 ↓ 순):
1. **schema.sql tokenizer migration** (D16) — `tokenize='trigram'`으로 변경 + SessionStart에서 unicode61 감지 시 DROP/REBUILD. 새 기능 0, DDL만
2. **`.imprint/sources.json` 시드 + 안내** (D6) — defaults에 빈 sample + SessionStart에서 부재 시 안내 메시지 prepend
3. **stop.sh chunk 추출 (claude -p haiku)** (D8, D12, D17, D19) — 응답을 haiku에 넘겨 9개 chunk_type 후보로 분류 + keywords 배열, JSON line schema validation, memory_chunks insert
4. **user-prompt-submit.sh 모호도 분석** (D2, D7, D19) — claude -p haiku로 ambiguity_score + keywords + refined_prompt JSON, 임계치 초과 시 [Refined prompt suggestion] 블록 prepend
5. **Slack/Notion lazy fetch** (D5, D20–D24) — URL 감지 + dedup + selection+summary 적용
6. **`/memory refresh` 명령** (D24) — DELETE+INSERT 덮어쓰기

각 PR은 다른 단계가 미구현이어도 graceful degradation으로 동작 (D9).

진입 명령: `git pull` 후 위 1번부터 시작 — schema.sql 변경 + SessionStart migration 단계 추가가 가장 안전.

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
