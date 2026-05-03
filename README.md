# multi-agent-cli-v2

Claude, Codex, Gemini CLI를 한 창에서 전환하며 사용할 수 있는 Tauri 기반 멀티 에이전트 데스크톱 앱입니다. 각 provider의 CLI를 로컬 프로젝트 경로에서 실행하고, 필요하면 보조 모델(advisor)이 초안을 검토한 뒤 최종 답변을 합성하는 흐름을 제공합니다.

## 주요 기능

- **멀티 provider 채팅**: Claude, Codex, Gemini 중 하나를 선택해 메시지를 보낼 수 있습니다.
- **Advisor orchestration**: 선택한 주 provider가 초안을 만들고, 다른 provider가 검토한 뒤 주 provider가 최종 답변을 작성합니다.
- **프로젝트 폴더 컨텍스트**: 대화별로 로컬 폴더를 지정해 해당 경로에서 CLI 명령을 실행합니다.
- **Provider 상태 HUD**: CLI 설치 여부, 모델명, 컨텍스트 사용량 추정치, Claude 5시간 사용량 정보를 표시합니다.
- **대화 관리 UI**: 새 대화 생성, provider 전환, 대화 삭제, 대화 내용 초기화를 지원합니다.
- **로컬 PTY 기반 준비 코드**: `portable-pty`와 `xterm.js` 기반 터미널 세션 생성/입출력/리사이즈 IPC가 포함되어 있어 인터랙티브 CLI 화면으로 확장할 수 있습니다.

## 기술 스택

- **Desktop shell**: Tauri 2
- **Backend**: Rust, `portable-pty`
- **Frontend**: React 19, TypeScript, Vite, Tailwind CSS
- **Terminal**: `xterm.js`
- **Tauri plugins**: dialog, opener

## 필요 조건

- Node.js, pnpm
- Rust toolchain
- Tauri 2 개발 환경
- 사용할 provider CLI
  - `claude`
  - `codex`
  - `gemini`

각 CLI는 앱 실행 전에 로컬에서 인증되어 있어야 합니다.

## 실행

의존성을 설치합니다.

```bash
pnpm install
```

웹 개발 서버만 실행합니다.

```bash
pnpm dev
```

Tauri 앱으로 실행합니다.

```bash
pnpm tauri dev
```

프로덕션 빌드를 생성합니다.

```bash
pnpm build
pnpm tauri build
```

## 동작 방식

프론트엔드는 React로 대화 목록, provider HUD, 프로젝트 선택, advisor 설정, composer를 렌더링합니다. 메시지를 보내면 Tauri IPC를 통해 Rust 백엔드의 `provider_chat` 명령을 호출하고, 백엔드는 선택된 CLI를 현재 프로젝트 경로에서 실행해 결과를 반환합니다.

현재 채팅 흐름은 provider별 비대화형 CLI 호출을 사용합니다. PTY manager와 `TerminalPane`은 인터랙티브 CLI 세션을 위한 기반 코드로 포함되어 있습니다.
