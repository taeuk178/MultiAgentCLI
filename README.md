# multi-agent-cli-v2

Warp 류 PTY 기반 멀티 에이전트 CLI GUI. claude / codex / gemini를 살아있는 PTY 프로세스로 호스팅해 한 창에서 대화형으로 운용한다.

## 위치

- 본 repo는 SwiftUI 기반 [`MultiAgentCLI`](../MultiAgentCLI)의 후속 버전이다.
- v1은 비대화형(`-p`, `exec`) 모드로 매 턴마다 CLI를 1회용 spawn했다 — 슬래시 명령(`/compact` 등)을 못 쓰는 한계가 있었다.
- v2는 PTY 기반 인터랙티브로 전환해 그 한계를 푼다.

## Stack

- **Backend**: Tauri 2 (Rust) + `portable-pty` crate
- **Frontend**: React 18 + TypeScript + Vite + Tailwind CSS + `xterm.js`
- **Storage**: SQLite via `tauri-plugin-sql`

## Status

설계 단계. `PLAN.md` 참고.

다음 작업: M0 — Tauri 프로젝트 부팅 (Sonnet 4.6이 진행 예정).
