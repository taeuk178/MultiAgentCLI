# imprint — Claude 세션 가이드

이 repo에서 동작하는 Claude 세션이 알아야 할 기본 프로토콜.

## 프로젝트 요지

이 repo는 Claude Code plugin입니다. 로컬 작업 기억(SQLite + FTS5)과 advisor orchestration, statusline HUD를 hook·skill·subagent 형태로 제공합니다.

이전에는 [`MultiAgentCLI`](../MultiAgentCLI)(SwiftUI)의 후속으로 Tauri 데스크톱 앱(이전 코드명 `multi-agent-cli-v2`)을 청사진으로 잡았으나, **Tauri 방향은 폐기**하고 Claude Code plugin(`imprint`)으로 전환했습니다. 본 repo에는 더 이상 Rust/React 코드가 없습니다.

현재 동작과 설치 방법은 `README.md`, `INSTALL.md`, 방향성은 `LoadMap.md`를 기준으로 합니다.

## Stack

- **Plugin manifest**: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`
- **Hooks (Bash)**: `hooks/hooks.json`이 `SessionStart`, `UserPromptSubmit`, `Stop`을 `scripts/imprint/*.sh`에 연결
- **Skills**: `skills/{memory,advisor,hud}/SKILL.md` — Claude가 필요할 때 dispatcher 스크립트를 호출
- **데이터**: `~/.claude/imprint/app.sqlite` (FTS5 포함), `~/.claude/imprint/plugin.log`
- **Statusline**: `scripts/imprint/hud.sh`가 Claude Code stdin의 세션 JSON을 읽어 5h/wk/ctx + 잔여 시간과 활성 plugin의 skills/agents 수를 출력

런타임 의존: `bash`, `python3`, `sqlite3`, `uuidgen`. provider 호출은 별도로 설치된 `claude`, `codex`, `gemini` CLI를 사용합니다.

## 디렉토리 구조

```
imprint/
├── .claude-plugin/
│   ├── plugin.json
│   └── marketplace.json
├── hooks/
│   └── hooks.json
├── skills/
│   ├── memory/SKILL.md
│   ├── advisor/SKILL.md
│   └── hud/SKILL.md
├── scripts/imprint/
│   ├── lib/
│   │   ├── common.sh        DB·project·로그 헬퍼
│   │   └── schema.sql       SQLite 스키마 (idempotent)
│   ├── session-start.sh     SessionStart hook
│   ├── user-prompt-submit.sh UserPromptSubmit hook
│   ├── stop.sh              Stop hook
│   ├── memory.sh            /memory dispatcher
│   ├── advisor.sh           /advisor dispatcher
│   ├── hud.sh               statusline body
│   └── hud-setup.sh         statusLine install/status/uninstall/layout
├── INSTALL.md
├── LoadMap.md
├── HANDOFF.md
└── README.md
```

## 코드·도구 관례

### 순수 함수 + 결정적 로직 분리

- 결정적 로직(메모리 청크 추출, prompt 합성, 포맷 함수)은 가능하면 인라인 Python 또는 별도 헬퍼로 분리합니다.
- 부작용(SQLite write, 외부 CLI 실행, 파일 I/O)은 dispatcher 스크립트의 가장자리에 모읍니다.
- hook 스크립트는 절대 사용자 세션을 차단해서는 안 됩니다 — 실패 시에도 stdout은 항상 정상 흐름을 출력합니다.

### 커밋 메시지

- **전부 한국어.** 제목과 본문 모두. Co-Authored-By 트레일러만 영어 유지.
- 제목은 50자 이내, 본문은 "왜 그랬는지" 중심으로 2~4줄.
- 기능 단위로 쪼개서 커밋. 포맷팅·리팩토링·기능 추가를 한 커밋에 섞지 않습니다.

### 검증

- 단위 검증은 가능한 한 hook을 직접 호출해 확인합니다 (예: `bash scripts/imprint/hud.sh < sample.json`).
- 통합 검증은 plugin을 user scope에 설치한 뒤 실제 Claude Code 세션에서 statusline·hook 동작을 확인합니다.

## 금지 사항

- v1 SwiftUI 코드, v2 Tauri 코드를 다시 끌어오지 않습니다. 이 repo는 Claude Code plugin 단일 책임을 가집니다.
- hook이 사용자 세션을 끊는 식의 에러로 종료하지 않게 합니다 — 실패해도 silent fail + 로그.
- 사용자/프로젝트의 `~/.claude` 설정을 동의 없이 직접 수정하지 않습니다 (HUD install 등은 명시적 사용자 액션을 거쳐야 함).

## 사용자 개입 지점

- 외부 CLI 인증 (Claude/Codex/Gemini OAuth) — 사용자 직접 단계.
- statusLine 교체 시 기존 statusline 백업/복원 확인.

<!-- ooo:START -->
<!-- ooo:VERSION:0.36.0 -->
# Ouroboros — Specification-First AI Development

> Before telling AI what to build, define what should be built.
> As Socrates asked 2,500 years ago — "What do you truly know?"
> Ouroboros turns that question into an evolutionary AI workflow engine.

Most AI coding fails at the input, not the output. Ouroboros fixes this by
**exposing hidden assumptions before any code is written**.

1. **Socratic Clarity** — Question until ambiguity ≤ 0.2
2. **Ontological Precision** — Solve the root problem, not symptoms
3. **Evolutionary Loops** — Each evaluation cycle feeds back into better specs

```
Interview → Seed → Execute → Evaluate
    ↑                           ↓
    └─── Evolutionary Loop ─────┘
```

## ooo Commands

Each command loads its agent/MCP on-demand. Details in each skill file.

| Command | Loads |
|---------|-------|
| `ooo` | — |
| `ooo interview` | `ouroboros:socratic-interviewer` |
| `ooo seed` | `ouroboros:seed-architect` |
| `ooo run` | MCP required |
| `ooo evolve` | MCP: `evolve_step` |
| `ooo evaluate` | `ouroboros:evaluator` |
| `ooo unstuck` | `ouroboros:{persona}` |
| `ooo status` | MCP: `session_status` |
| `ooo setup` | — |
| `ooo help` | — |

## Agents

Loaded on-demand — not preloaded.

**Core**: socratic-interviewer, ontologist, seed-architect, evaluator,
wonder, reflect, advocate, contrarian, judge
**Support**: hacker, simplifier, researcher, architect
<!-- ooo:END -->

## git

- commit할 때 Co-Authored-By는 작성하지 말 것.
