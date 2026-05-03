# multi-agent-cli-v2 — 전환 계획

[`MultiAgentCLI`](../MultiAgentCLI)(SwiftUI, 비대화형 wrapping)을 PTY 기반 인터랙티브 GUI로 전면 재작성한다.

## 0. 결정 사항

- **신규 repo**: `/Users/taeuk/Desktop/Dev/multi-agent-cli-v2/` (현재). v1은 동결만 하고 일단 보존.
- **Stack**: Tauri 2 + Rust(`portable-pty`) + React + TypeScript + Vite + Tailwind + xterm.js + SQLite(`tauri-plugin-sql`).
- **이유**: macOS notarization 친화 + Electron보다 가벼움 + xterm.js로 ANSI/커서/색을 위임해 우리 코드 부담 최소.

## 1. 아키텍처

```
┌────────────────────────────────────────────────────┐
│  Frontend (React + xterm.js)                       │
│  ─ Sidebar │ Title bar │ Provider HUD │ Tabs │     │
│  ─ Center  : xterm.js terminal (per active tab)    │
│  ─ Composer: input → IPC.write(tabId, bytes)       │
│  ─ Logs    : IPC events stream                     │
└──────────────┬─────────────────────────────────────┘
               │ Tauri invoke / events (JSON)
┌──────────────▼─────────────────────────────────────┐
│  Backend (Rust)                                    │
│  ─ PtyManager: HashMap<TabId, PtySession>          │
│  ─ PtySession: { master, child, reader_task }      │
│  ─ Each session reads stdout → emits "pty://data"  │
│  ─ MetadataExtractor: tee stdout → ANSI strip →    │
│      regex/JSON heuristics for model/session/usage │
│  ─ HealthChecker: spawn `claude auth status` etc   │
│  ─ SqliteStore: conversations, messages            │
└────────────────────────────────────────────────────┘
```

핵심 결정: 메인 채팅 영역은 **xterm.js 터미널**(Warp의 "block" 개념을 단순화). v1의 채팅 bubble은 폐기. 메타데이터(model name, usage tokens, session id)는 stdout을 백엔드에서 한 번 더 tap해 stream-json/ANSI에서 추출 → HUD에 노출.

## 2. 마일스톤

| M | 목표 | 산출물 | 검증 |
|---|------|-------|------|
| **M0** | Tauri 프로젝트 부팅 | `pnpm dev`로 빈 창 | 윈도우 뜸 |
| **M1** | Rust PTY core | `PtyManager` + 단일 zsh PTY 띄워 frontend xterm.js로 echo 왕복 | 입력→출력 동작 |
| **M2** | Provider PTY abstraction | `Provider` trait (Claude/Codex/Gemini), 각 CLI를 PTY로 spawn | 3개 모두 띄움 |
| **M3** | Frontend shell | Sidebar(240px) + 메인 영역 + composer (디자인 토큰 포팅) | 시각 검수 |
| **M4** | Tabs + 활성 PTY 전환 | 각 conversation = 한 set of PTY tabs (3 provider) | 탭 클릭 시 화면 전환 |
| **M5** | SQLite persistence | conversation/message CRUD, Tauri command 노출 | 앱 재시작 후 복원 |
| **M6** | Metadata extractor | stdout 백엔드 tap, ANSI 제거, model/usage 정규식 추출 → HUD 갱신 | 토큰 카운터 라이브 |
| **M7** | Health badges + login | 백엔드 healthcheck (`claude auth status` 등), 결과를 HUD pill로 | 3개 상태 표시 |
| **M8** | Multi-provider orchestration | 기존 Swift `ChatViewModel.runOrchestrated` 로직을 TS로 포팅 — advisor는 별도 비대화형 PTY 인스턴스 1회용 spawn | draft→review→synth 동작 |
| **M9** | Logs panel + settings | 백엔드 events → 하단 logs slide-up, settings 화면 | 패널 토글 |
| **M10** | Polish + packaging | macOS codesign, notarization, .dmg 빌드 스크립트 | 다운로드해서 설치 |

총 작업량 추정: 단독 4–5주 (M6/M8이 가장 risky).

## 3. 디자인

- v1 UI 톤(다크, provider 색 강조, 240px 사이드바, HUD pills)을 그대로 가져옴 — Tailwind config에 v1의 `DesignTokens` 색을 1:1 이전.
- 채팅 bubble은 사라지고 그 자리에 xterm.js terminal pane (배경 `bg-content`, JetBrains Mono).
- Warp 참고 요소: 상단 탭바, 명령 팔레트(⌘P) — 명령 팔레트는 M10 이후 stretch.
- Composer는 그대로 두되, 송신 버튼이 PTY의 stdin으로 prompt + `\r`을 흘려보냄.

## 4. 사전 검증 필요 (M0 시작 전)

1. **Claude/Codex CLI 인터랙티브 모드에서 stream-json output을 동시에 켤 수 있나?**
   - 안 되면 메타데이터 추출은 ANSI 본문 regex로만 가능 → 정확도 떨어짐
   - 안 되면 fallback: 인터랙티브 PTY + 별도 비대화형 호출로 메타 fetch (overhead 발생)
2. **`portable-pty`가 macOS Sonoma+ Hardened Runtime / sandbox 환경에서 신뢰성 있게 동작하나?**
   - v1의 `ENABLE_APP_SANDBOX = NO`와 같은 이유. Tauri도 sandbox off로 시작.
3. **Gemini CLI의 인터랙티브 모드에서 stream-json output 지원 여부 확인**
   - Gemini는 비대화형에서도 stream-json 스키마가 미공개라 인터랙티브는 더 불확실.

## 5. 위험 / 트레이드오프

- **메타데이터 추출 정확도** 떨어질 수 있음 — 인터랙티브 ANSI 본문 + 부분 stream-json mix 환경에서. 최악의 경우 token usage HUD가 비활성화될 수 있음.
- **다중 conversation × 다중 provider** = 동시 PTY 인스턴스 수가 빠르게 늘어남 → idle 탭은 PTY 종료하고 활성 시 재기동 같은 LRU 정책 필요(M5 즈음).
- **Packaging**: macOS notarization은 Tauri 2가 잘 지원하지만 처음 한 번 Apple Developer ID + p12 설정 필요.

## 6. 진행 순서

1. M0~M2를 1주에 끝내 PTY 위에 claude 대화형이 떠있는 데모를 가장 빨리 보여줌.
2. M3~M5 디자인·persistence 옮기고 일상 사용 가능 수준.
3. M6 메타데이터·M8 advisor — 가장 어려운 부분을 마지막에 안정화.

## 7. v1에서 가져올 자산

- 도메인 enum: `ProviderID`, `MessageRole`, `MessageStatus`, `OrchestrationPhase` → TypeScript 포팅.
- 순수 헬퍼: `PromptBuilder` (advisor/synth prompt 합성), `StreamLineBuffer`, `ProviderModelLabel`, `ProviderContextWindow` → TypeScript 포팅.
- 디자인 토큰: `DesignTokens.swift`의 색·radius·spacing → Tailwind config로 1:1 이전.
- 매핑된 모델 ↔ context window 테이블, 매핑된 모델 ↔ 짧은 라벨 테이블 그대로 사용.

새 코드(SwiftUI 의존)는 일절 가져오지 않는다.
