# multi-agent-cli-v2 — Claude 세션 가이드

이 repo에서 동작하는 Claude 세션이 알아야 할 기본 프로토콜.

## 프로젝트 요지

[`MultiAgentCLI`](../MultiAgentCLI)(SwiftUI)의 후속 버전. Claude, Codex, Gemini CLI를 단일 Tauri GUI에서 운용하고, provider 전환과 advisor orchestration을 제공한다.

현재 동작과 실행 방법은 `README.md`를 기준으로 한다.

## Stack

- **Tauri 2**: Rust core + WebView (macOS는 WKWebView). macOS sandbox는 v1처럼 OFF로 시작 — 외부 CLI를 spawn해야 하기 때문.
- **Provider runner**: Rust backend가 `claude`, `codex`, `gemini` CLI를 비대화형 명령으로 실행하고 결과를 Tauri IPC로 반환한다.
- **portable-pty (Rust crate)**: 인터랙티브 터미널 세션을 위한 기반 코드. 세션 생성·입출력·resize IPC가 준비되어 있다.
- **xterm.js**: 프런트엔드 터미널 위젯. 현재 채팅 UI와 별도로 `TerminalPane`에서 사용한다.
- **React + Vite + TS + Tailwind**: 프런트 SPA.

## 코드·도구 관례

### 디렉토리 구조

```
multi-agent-cli-v2/
├── src-tauri/        Rust backend (provider runner, PtyManager, IPC commands)
│   ├── src/
│   └── Cargo.toml
├── src/              React frontend
│   ├── components/   재사용 컴포넌트 (Sidebar, HUD, TerminalPane, Composer 등)
│   ├── lib/          IPC wrapper, 도메인 타입, 순수 헬퍼
│   ├── index.css     전역 CSS와 디자인 토큰
│   └── App.tsx
├── package.json
└── vite.config.ts
```

### 순수 함수 + 독립 컴포넌트

v1의 `coding-convention.md` 정신을 그대로 가져온다.
- 결정적 로직(메타데이터 추출, prompt 합성, 외형 함수)은 순수 함수로 분리
- 컴포넌트는 입력만 받아 그림을 그린다
- 부작용(IPC 호출, 외부 CLI 실행, PTY 명령)은 가장자리(서비스 레이어)에 모은다

### 커밋 메시지

- **전부 한국어.** 제목과 본문 모두. Co-Authored-By 트레일러만 영어 유지.
- 제목은 50자 이내, 본문은 "왜 그랬는지" 중심으로 2~4줄.
- 기능 단위로 쪼개서 커밋. 포맷팅·리팩토링·기능 추가를 한 커밋에 섞지 않는다.

### 빌드·검증

- `pnpm dev` — Vite dev server
- `pnpm tauri dev` — Tauri dev 모드
- `pnpm build` — TypeScript + Vite build
- `pnpm tauri build` — 릴리즈 빌드 (macOS 배포 시 codesign·notarization 설정 필요)

## 금지 사항

- v1 SwiftUI 코드를 이 repo로 끌어오지 않는다. 도메인 로직만 TypeScript/Rust로 새로 작성한다.
- macOS sandbox를 다시 켜지 않는다. 외부 프로세스 spawn이 막힌다.
- frontend에서 claude/codex/gemini CLI를 직접 호출하지 말고 항상 backend IPC wrapper를 거친다.

## 사용자 개입 지점

- 패키징·notarization 관련 Apple Developer 계정 설정은 사용자 직접 단계.
