# multiagent — Claude Code plugin

로컬 작업 기억(SQLite + FTS5), advisor orchestration, statusline HUD를 Claude Code의 hook · skill · subagent 시스템으로 제공하는 plugin입니다.

> 이전 세대(`MultiAgentCLI` SwiftUI / `multi-agent-cli-v2` Tauri 데스크톱 앱)는 **폐기되었습니다.** 본 repo는 Claude Code plugin 단일 책임을 가집니다. 이전 데스크톱 앱이 필요하다면 `MultiAgentCLI` 원본 repo를 참고하세요.

## 무엇을 하는가

| 영역 | 역할 |
|---|---|
| Soul (persona) | `SessionStart` hook이 `<project>/.multiagent/soul.md` 내용을 컨텍스트 시작에 prepend. 압축 후에도 `compact` matcher로 자동 재주입 |
| Routing | `UserPromptSubmit` hook이 `<project>/.multiagent/UserPromptSubmit.md`의 키워드 → agent 룰을 평가, 매칭 시 권고 메시지 prepend (예: "PR" → `pr-agent` 호출 권고) |
| Memory | 프롬프트·응답·메타데이터를 `~/.claude/multiagent/app.sqlite`에 누적, FTS5 기반 검색·pin·자동 주입 (`UserPromptSubmit` hook이 `[Project memory context]` 블록 prepend) |
| Advisor | `codex`, `gemini`를 advisor로 호출하고 `claude -p`로 합성. 각 호출은 `provider_runs`에 기록 |
| HUD | Claude Code statusline에 `5h: 25% (1h 49m) │ wk: 3% (1d 9h) │ ctx: 12% │ skills: 17 │ agents: 1` 형태로 잔여 시간과 활성 plugin의 skills/agents 수 표시 |

## 설치

자세한 절차는 [`INSTALL.md`](INSTALL.md). 요약:

```bash
# 이 repo가 marketplace로 등록되어 있다면
claude plugin marketplace add <this-repo>
claude plugin install multiagent@multiagent
```

설치 후 Claude Code 세션을 새로 열면 `SessionStart` hook이 SQLite 스키마를 idempotent하게 생성하고 프로젝트 row를 upsert합니다.

statusline 활성화는 별도 단계입니다.

```bash
bash scripts/multiagent/hud-setup.sh install         # 기존 statusLine 백업 후 교체
bash scripts/multiagent/hud-setup.sh layout focused  # minimal | focused | full
bash scripts/multiagent/hud-setup.sh uninstall       # 백업 복원
```

## 사용

### Memory

```bash
multiagent memory remember "Claude Code plugin 전환 결정"  # 수동 저장
multiagent memory search "PTY 한글 IME"                   # FTS5 검색
multiagent memory pin <chunk-id>                          # 우선 노출
multiagent memory list --recent --limit 20
```

`UserPromptSubmit` hook이 매 prompt마다 pinned + recent 청크를 `[Project memory context]` 블록으로 자동 prepend합니다.

### Routing (옵션)

`UserPromptSubmit` hook은 `<project>/.multiagent/UserPromptSubmit.md`(없으면 plugin defaults)에서 라우팅 표를 읽어 매칭된 권고를 prepend합니다. 본 plugin은 라우팅 룰 markdown을 ship하지 않으므로, 사용하려면 사용자가 다음 형식으로 직접 작성합니다.

```markdown
| 패턴                       | Agent      | 권고 메시지                  |
|---------------------------|------------|------------------------------|
| `\b(PR\|pull\s*request)\b` | pr-agent   | PR 작업 — pr-agent 호출 권장 |
```

작성 시 주의:
- 한국어 키워드엔 `\b` 사용 금지(한글이 word character로 인식되어 boundary 안 잡힘) — 영어 약어에만 `\b`.
- 정규식 alternation `|`는 `\|`로 escape — markdown 셀 구분자와 충돌하기 때문.
- 매칭된 agent가 실제 호출되려면 해당 subagent 정의가 plugin 또는 사용자 영역에 등록돼 있어야 합니다.

### Advisor

`/advisor <질문>` 같이 skill로 호출하면 codex/gemini를 병렬 advisor로 돌리고 합성된 답변을 반환합니다. 단일 advisor만 쓰려면 `--advisor codex` 식으로 지정.

### HUD

statusline은 `hud-setup.sh install` 이후 자동 갱신됩니다. 데이터는 Claude Code가 매 갱신마다 stdin으로 넘기는 세션 JSON(`rate_limits.*.resets_at`, `context_window.used_percentage` 등)을 그대로 사용합니다.

## 구조

```
.claude-plugin/
  plugin.json              플러그인 매니페스트
  marketplace.json         로컬 marketplace entry
hooks/hooks.json           SessionStart / UserPromptSubmit / Stop 등록
skills/
  memory/SKILL.md
  advisor/SKILL.md
  hud/SKILL.md
prompts/defaults/          첫 SessionStart에서 <project>/.multiagent/로 시드되는 기본 콘텐츠
  soul.md                  persona·동작 규칙
  hooks/                   Claude Code의 22개 hook 카탈로그(사람용 가이드, OpenClaw 스타일)
scripts/multiagent/
  lib/common.sh            DB·project·로그 헬퍼
  lib/schema.sql           SQLite 스키마 (FTS5 trigger 포함)
  session-start.sh         SessionStart hook (DB 보장 + .multiagent/ 시드 + soul.md emit)
  user-prompt-submit.sh    UserPromptSubmit hook (라우팅 평가 + 메모리 주입)
  stop.sh                  Stop hook (assistant 응답 archive)
  memory.sh                /memory dispatcher
  advisor.sh               /advisor dispatcher
  hud.sh                   statusline body
  hud-setup.sh             statusLine install/status/uninstall/layout
LifeCycle.md               LLM 턴 생애주기 ↔ Claude Code hook 매핑 + 깊이 있는 카탈로그
```

## 데이터 위치

| 경로 | 내용 |
|---|---|
| `<project>/.multiagent/soul.md` | 세션 시작·압축 후 자동 prepend되는 persona·동작 규칙. 사용자 자유 편집. (plugin defaults에서 자동 시드) |
| `<project>/.multiagent/UserPromptSubmit.md` | 매 prompt마다 평가되는 키워드 → agent 라우팅 룰. 사용자 자유 편집. |
| `<project>/.multiagent/hooks/*.md` | Claude Code의 22개 hook 카탈로그 + 본 plugin이 등록한 hook(✅) 표시. OpenClaw 스타일 짧은 가이드(무엇 / 어떻게 활용 / 간단한 예시 / 주의). Claude Code가 직접 읽진 않는 사람용 참고 문서. |
| `~/.claude/multiagent/app.sqlite` | projects · conversations · events · memory_chunks · provider_runs (FTS5 포함) |
| `~/.claude/multiagent/plugin.log` | hook · dispatcher 로그 |
| `~/.claude/multiagent/previous-statusline.json` | hud-setup install 시 백업된 이전 statusLine 설정 |

`.multiagent/` 폴더는 SessionStart hook이 처음 실행될 때 자동 생성되며 기존 파일은 절대 덮어쓰지 않습니다. 시드를 막고 싶다면 `MULTIAGENT_NO_SEED=1` 환경 변수를 설정하세요.

## 의존

- `bash`, `python3`, `sqlite3`, `uuidgen` (macOS 기본 포함)
- 사용할 provider CLI(`claude`, `codex`, `gemini`)는 별도 설치·인증 필요

## 진행 상황·로드맵

- 구현 상세와 다음 작업: [`HANDOFF.md`](HANDOFF.md)
- 단계별 방향: [`LoadMap.md`](LoadMap.md)
- LLM 턴 생애주기와 Claude Code hook 활용 카탈로그: [`LifeCycle.md`](LifeCycle.md)
