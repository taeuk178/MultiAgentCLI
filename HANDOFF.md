# Handoff — claude-plugin 브랜치

다음 세션에서 이어서 작업할 때 참고하는 문서입니다. 작성 시점: 2026-05-07.

> 완료된 Phase 1·2·3(부분)·4(부분)·HUD·플러그인 설치 항목은 README.md에 반영되어 본 문서에서는 제거함. 구현된 내용은 README의 사용/구조/데이터 위치 섹션 참조.

## 남은 작업

### Phase 3 마무리 (Memory skill 정교화)

**Stop hook 청크 추출**
- 현재 `stop.sh`는 응답 전체를 `llm_response` 이벤트로만 저장.
- 응답에서 `chunk_type`별로 추출 필요.
- 두 가지 방식 비교 후 채택:
  1. 정규식/키워드 기반 추출 (빠름, 단순)
  2. `claude -p`로 LLM 추출 (정확, 비용은 구독)
- 시작점: `scripts/multiagent/stop.sh` 마지막 부분에 추출 단계 추가.

**Redaction**
- `memory.sh remember --redact` 플래그 미구현.
- `~/.claude/multiagent/redact-rules.json` 형식으로 정규식 룰셋 정의.
- 시작점: `scripts/multiagent/lib/common.sh`에 `redact_text()` 함수 추가.

**memory list 필터 보강**
- 현재 `--recent`, `--pinned`, `--type` 만 지원.
- 추가 필요: `--since <date>`, `--limit <n>`, `--project <path>` (다른 프로젝트 검색).

### Phase 4 마무리 (Advisor skill 검증)

**End-to-end 테스트**
- `bash scripts/multiagent/advisor.sh codex "test"` 직접 실행 → codex CLI 인증 흐름과 출력 캡처 확인.
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
- 위치 제안: `skills/workflow/SKILL.md` + `scripts/multiagent/workflow.sh`.

### Phase 6. 외부 레지스트리 (미시작)

- `multiagent skill add <github-url>` — GitHub repo에서 SKILL.md 다운로드 후 `~/.claude/multiagent/skills/`에 배치.
- `multiagent skill publish <name>` — 본인 GitHub repo에 PR 또는 push.
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

본 multiagent plugin과 별개로 **`oh-my-claudecode` (omc) plugin**이 동일 Claude Code 환경에 설치되어 있을 수 있고, 자체 메모리 시스템을 운영함. 두 plugin이 각자 메모리 저장소를 갖는 구조이므로 충돌·중복 주입 가능성에 유의.

- **저장 위치**: `<project>/.omc/project-memory.json` (per-project, JSON)
  - vs multiagent: `~/.claude/multiagent/app.sqlite` (per-user, SQLite + FTS5)
- **주입 시점**: omc의 `project-memory-session.mjs` hook이 SessionStart에서 별도 컨텍스트로 prepend (multiagent의 `[Project memory context]` 블록과는 별개 채널)
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

1. **빠른 검증**: `bash scripts/multiagent/advisor.sh codex "ping"` 실행해서 OAuth advisor 흐름 확인.
2. **Phase 3 마무리**: `stop.sh`에 청크 추출 단계 추가가 가장 가치 큼. 현재 응답이 events에는 쌓이지만 memory_chunks로 자동 누적되지 않음.
3. **Phase 5 시작**: `/commit-message` 스킬은 즉시 활용도 높음. 작은 단위로 시작 가능.

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
scripts/multiagent/
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
d9fc100 multiagent HUD 스킬과 statusline 스크립트 추가
89d7297 다음 세션 픽업용 HANDOFF 문서 추가
736b55e Claude Code plugin 골격 추가
5ba9034 LoadMap을 Claude Code plugin 방향으로 재정의
```
