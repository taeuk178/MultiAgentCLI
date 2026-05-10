
- 기본적으로 한국어 사용 및 존댓말을 사용할 것.

## 1. Think Before Coding
- 코드를 작성하기 전에 문제를 글로 정리하고, 현재 동작과 원하는 변경점을 설명하라.
- 변경하려는 파일/함수의 역할을 먼저 요약하고, 이해가 불완전하면 질문하거나 관련 코드를 더 살펴보라.
- 모호함이나 불확실성이 있으면 스스로 가정하지 말고, 질문을 통해 명확히 하라.
- 큰 변경 전에는 간단한 설계(알고리즘, 데이터 흐름, 인터페이스)를 텍스트로 먼저 제안하라.

## 2. Simplicity First
- 가장 단순한 해결책부터 제안하고, 불필요한 추상화나 새로운 레이어를 만들지 마라.
- 기존 패턴, 기존 함수, 기존 타입을 재사용할 수 있는지 먼저 확인하라.
- 새로 추가하는 코드의 길이와 복잡도를 줄이고, 이해하기 쉬운 구조를 우선하라.
- “멋진” 코드보다 읽기 쉬운 코드, 유지보수 쉬운 코드를 선택하라.

## 3. Surgical Changes
- 요청된 변경 범위만 최소한으로 수정하고, 관련 없는 주변 코드는 건드리지 마라.
- 동작 중인 코드, 검증된 코드, 스타일만 다른 코드까지 “정리”하겠다고 변경하지 마라.
- 리팩터링이 필요하다고 판단되면, 왜 필요한지 설명하고 별도의 단계/커밋으로 분리하라.
- diff 가독성을 고려해, 하나의 PR/커밋에는 한 가지 논리적 변경만 담으려고 노력하라.

## 4. Goal-Driven Execution
- “버그 고치기”처럼 모호한 목표 대신, 테스트/검증 기준이 있는 구체적인 목표를 정의하라.
- 가능한 경우, 실패하는 테스트를 먼저 제안하고, 그 테스트를 통과하도록 코드를 수정하라.
- 목표 달성 여부를 스스로 체크리스트로 정리하고, 작업 완료 시 각 항목을 검토하라.
- 구현 후에는 요약과 함께, 남은 리스크나 추가로 검토할 포인트를 명시하라.

# imprint — Codex 세션 가이드

이 repo에서 동작하는 Codex 세션이 알아야 할 기본 프로토콜.

## 프로젝트 요지

이 repo는 Codex plugin입니다. 로컬 작업 기억(SQLite + FTS5), 외부 소스(Slack·Notion) lazy fetch, statusline HUD를 hook·skill·subagent 형태로 제공합니다.

이전에는 [`MultiAgentCLI`](../MultiAgentCLI)(SwiftUI)의 후속으로 Tauri 데스크톱 앱(이전 코드명 `multi-agent-cli-v2`)을 청사진으로 잡았으나, **Tauri 방향은 폐기**하고 Codex plugin(`imprint`)으로 전환했습니다. 본 repo에는 더 이상 Rust/React 코드가 없습니다.

현재 동작과 설치 방법은 `README.md`, `INSTALL.md`, 방향성은 `LoadMap.md`를 기준으로 합니다.

## Stack

- **Plugin manifest**: `.Codex-plugin/plugin.json`, `.Codex-plugin/marketplace.json`
- **Hooks (Bash)**: `hooks/hooks.json`이 `SessionStart`, `UserPromptSubmit`, `Stop`을 `scripts/imprint/*.sh`에 연결
- **Skills**: `skills/{memory,hud}/SKILL.md` — Codex가 필요할 때 dispatcher 스크립트를 호출
- **데이터**: `~/.Codex/imprint/app.sqlite` (FTS5 포함), `~/.Codex/imprint/plugin.log`
- **Statusline**: `scripts/imprint/hud.sh`가 Codex stdin의 세션 JSON을 읽어 5h/wk/ctx + 잔여 시간과 활성 plugin의 skills/agents 수를 출력

런타임 의존: `bash`, `python3`, `sqlite3`, `uuidgen`. 백그라운드 LLM 호출(prefill 분석, Slack/Notion lazy fetch, Stop chunk 추출)은 OAuth 구독으로 인증된 `Codex` CLI를 사용합니다.

## 디렉토리 구조

```
imprint/
├── .Codex-plugin/
│   ├── plugin.json
│   └── marketplace.json
├── hooks/
│   └── hooks.json
├── skills/
│   ├── memory/SKILL.md
│   └── hud/SKILL.md
├── scripts/imprint/
│   ├── lib/
│   │   ├── common.sh        DB·project·redact·로그 헬퍼
│   │   ├── ingestion.py     prefill 분석·Slack/Notion lazy fetch·Stop 추출·refresh
│   │   ├── migrations.sh    schema migration · backfill
│   │   ├── redact-rules.default.json  플러그인 default redact 룰셋
│   │   └── schema.sql       SQLite 스키마 (idempotent)
│   ├── session-start.sh     SessionStart hook
│   ├── user-prompt-submit.sh UserPromptSubmit hook
│   ├── stop.sh              Stop hook
│   ├── memory.sh            /memory dispatcher
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
- 통합 검증은 plugin을 user scope에 설치한 뒤 실제 Codex 세션에서 statusline·hook 동작을 확인합니다.

## 금지 사항

- v1 SwiftUI 코드, v2 Tauri 코드를 다시 끌어오지 않습니다. 이 repo는 Codex plugin 단일 책임을 가집니다.
- hook이 사용자 세션을 끊는 식의 에러로 종료하지 않게 합니다 — 실패해도 silent fail + 로그.
- 사용자/프로젝트의 `~/.Codex` 설정을 동의 없이 직접 수정하지 않습니다 (HUD install 등은 명시적 사용자 액션을 거쳐야 함).

## 사용자 개입 지점

- 외부 CLI 인증 (`Codex` OAuth, Slack/Notion MCP) — 사용자 직접 단계.
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
