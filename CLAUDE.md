# multi-agent-cli-v2 — Claude 세션 가이드

이 repo에서 동작하는 Claude 세션이 알아야 할 기본 프로토콜.

## 프로젝트 요지

[`MultiAgentCLI`](../MultiAgentCLI)(SwiftUI, 비대화형 wrapping)의 후속 버전. 같은 도메인(claude/codex/gemini를 단일 GUI에서 운용)을 풀되, **PTY 호스팅 기반 인터랙티브 모드**로 전환해 슬래시 명령·인터랙티브 인증·자동 compact 같은 기능을 사용 가능하게 한다.

큰 그림은 `PLAN.md` 참고. v1과의 차이/이전 자산은 `README.md` 참고.

## Stack

- **Tauri 2**: Rust core + WebView (macOS는 WKWebView). macOS sandbox는 v1처럼 OFF로 시작 — 외부 CLI를 spawn해야 하기 때문.
- **portable-pty (Rust crate)**: PTY 생성·관리. macOS·Linux·Windows 추상화.
- **xterm.js**: 프런트엔드 터미널 위젯. ANSI escape·커서·색상·resize 등 터미널 시퀀스를 처리.
- **React + Vite + TS + Tailwind**: 프런트 SPA. 디자인 토큰은 v1의 `DesignTokens.swift`를 1:1로 Tailwind config에 옮긴다.
- **SQLite via `tauri-plugin-sql`**: Conversation/ChatMessage 영속.

## 마일스톤 흐름

`PLAN.md`의 M0–M10 순서를 따른다. 각 마일스톤이 끝날 때마다 빌드 가능한 상태를 유지하고, M2까지는 가장 빨리 "PTY 위에 claude 인터랙티브가 떠 있는 데모"를 만들어내는 것이 우선순위다.

## 코드·도구 관례

### 디렉토리 구조 (예정)

```
multi-agent-cli-v2/
├── src-tauri/        Rust backend (PtyManager, Provider trait, DB, IPC commands)
│   ├── src/
│   └── Cargo.toml
├── src/              React frontend
│   ├── components/   재사용 컴포넌트 (Sidebar, HUD, TerminalPane, Composer 등)
│   ├── lib/          IPC wrapper, 도메인 타입, 순수 헬퍼
│   ├── styles/       Tailwind config·전역 CSS
│   └── App.tsx
├── package.json
└── vite.config.ts
```

### 순수 함수 + 독립 컴포넌트

v1의 `coding-convention.md` 정신을 그대로 가져온다.
- 결정적 로직(메타데이터 추출, prompt 합성, 외형 함수)은 순수 함수로 분리
- 컴포넌트는 입력만 받아 그림을 그린다
- 부작용(IPC 호출, DB 쓰기, PTY 명령)은 가장자리(서비스 레이어)에 모은다

### 커밋 메시지

- **전부 한국어.** 제목과 본문 모두. Co-Authored-By 트레일러만 영어 유지.
- 제목은 50자 이내, 본문은 "왜 그랬는지" 중심으로 2~4줄.
- 기능 단위로 쪼개서 커밋. 포맷팅·리팩토링·기능 추가를 한 커밋에 섞지 않는다.

### 빌드·검증

- `pnpm dev` — Vite dev server + Tauri dev 모드
- `pnpm tauri build` — 릴리즈 빌드 (macOS는 codesign·notarization 필요, M10에 정리)

## 금지 사항

- v1 SwiftUI 코드를 이 repo로 끌어오지 않는다. 도메인 로직만 TypeScript/Rust로 새로 작성한다.
- macOS sandbox를 다시 켜지 않는다. 외부 프로세스 spawn이 막힌다.
- claude/codex/gemini CLI를 직접 호출하지 말고 항상 backend의 `Provider` trait을 거친다.

## 사용자 개입 지점

- 디자인 결정(Warp 어떤 요소를 채택할지, 명령 팔레트 도입 시점 등)은 사용자 확인을 받고 진행한다.
- 패키징·notarization 관련 Apple Developer 계정 설정은 사용자 직접 단계.
