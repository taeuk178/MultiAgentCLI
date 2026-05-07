# Handoff — claude-plugin 브랜치

다음 세션에서 이어서 작업할 때 참고하는 문서입니다. 작성 시점: 2026-05-07.

## 완료된 부분

### Phase 1. Memory 저장소

- `scripts/multiagent/lib/schema.sql` — SQLite 스키마 (projects, conversations, events, memory_chunks, provider_runs, FTS5 triggers)
- `scripts/multiagent/lib/common.sh` — DB 헬퍼, project_root/project_id, 로깅
- `scripts/multiagent/session-start.sh` — 스키마 idempotent 적용, 프로젝트 row upsert
- 데이터 위치: `~/.claude/multiagent/app.sqlite`, `~/.claude/multiagent/plugin.log`

### Phase 2. Hook 통합

- `scripts/multiagent/user-prompt-submit.sh` — 입력을 events에 저장, pinned + recent 청크를 `[Project memory context]` 블록으로 stdout 출력
- `scripts/multiagent/stop.sh` — `transcript_path`에서 마지막 assistant 응답 추출 후 events에 저장 (현재는 청크 추출 없이 raw 저장만)
- `hooks/hooks.json` — UserPromptSubmit, Stop, SessionStart 등록

### Phase 3 (부분). Memory skill

- `skills/memory/SKILL.md`
- `scripts/multiagent/memory.sh` — search, remember, inject, pin, unpin, list, forget 동작
- 검증된 동작: remember/list/search/pin

### Phase 4 (부분). Advisor skill 골격

- `skills/advisor/SKILL.md`
- `scripts/multiagent/advisor.sh` — codex/gemini/ccg dispatcher 작성, provider_runs 저장 로직 포함
- 미검증: 실제 `codex exec`, `gemini -p`, `claude -p` 호출이 OAuth 구독으로 정상 동작하는지 end-to-end 확인 필요

### HUD (statusline)

- `skills/hud/SKILL.md`
- `scripts/multiagent/hud.sh` — Claude Code stdin의 `rate_limits.{five_hour,seven_day}.used_percentage`, `context_window.used_percentage`를 직접 읽어 5h/wk/ctx 표시. skill/agent 수는 `~/.claude/plugins/cache` 트리에서 카운트.
- `scripts/multiagent/hud-setup.sh` — `~/.claude/settings.json`의 `statusLine`을 multiagent HUD로 교체하고 이전 값을 `~/.claude/multiagent/previous-statusline.json`에 백업. minimal/focused/full layout 전환 지원.
- 검증된 동작: 3개 layout 모두 정상 출력. 단, install/uninstall은 현재 OMC HUD가 활성 상태라 사용자 동의 후 진행.

### 플러그인 설치

- `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` 작성
- `claude plugin marketplace add <repo>` + `claude plugin install multiagent@multiagent`로 user scope 설치 검증 완료
- 설치 후 enabled 상태 확인됨

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

- 신규 개발 중단 상태. Phase 5 이후 사용자 피드백을 보고 결정:
  - 별도 repo로 분리해 PTY 전용 도구로 유지
  - 폐기
- 결정 보류 중. 본 repo에는 Tauri 코드(`src/`, `src-tauri/`)가 그대로 남아 있음.

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
736b55e Claude Code plugin 골격 추가
5ba9034 LoadMap을 Claude Code plugin 방향으로 재정의
```
