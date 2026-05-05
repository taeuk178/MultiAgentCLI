# multi-agent-cli-v2

Claude Code, Codex CLI, Gemini CLI를 한 데스크톱 앱에서 전환하며 쓰기 위한 Tauri 기반 멀티 에이전트 클라이언트입니다. 목표는 “일반 채팅 UI”와 “실제 회사 개발에서 쓰는 CLI 세션”을 한 앱 안에서 같이 다루는 것입니다.

## 현재 청사진

앱은 크게 두 가지 사용 모드를 가집니다.

| 모드 | 목적 | 동작 방식 |
| --- | --- | --- |
| Quick | 짧은 질문, 빠른 응답, advisor 검토 흐름 | Tauri IPC로 provider CLI를 한 번 실행하고 결과를 채팅 메시지로 받습니다. |
| Dev | 실제 개발 작업용 대화형 CLI 세션 | 앱이 PTY를 띄우고 Claude/Codex/Gemini CLI를 계속 실행합니다. 입력은 앱 Composer에서 보내고 출력은 xterm 화면으로 봅니다. |

`New Chat`을 만들기 전에 사이드바 하단에서 `Quick / Dev` 모드를 선택합니다. 생성된 conversation은 자기 모드를 고정해서 가지며, conversations 목록에도 모드 배지가 표시됩니다.

## 주요 기능

- **멀티 provider 전환**
  - Claude, Codex, Gemini provider를 HUD 카드에서 전환합니다.
  - provider별 라벨, 색상, glyph, context window 정보는 `src/lib/types.ts`의 `PROVIDERS` 테이블에서 관리합니다.

- **Quick 채팅**
  - React Composer에서 메시지를 보내면 `src/lib/chatFlow.ts`가 프롬프트를 만들고 `src/lib/ipc.ts`를 통해 Rust `provider_chat`을 호출합니다.
  - Rust는 provider별 CLI를 현재 프로젝트 폴더에서 실행하고 stdout 결과를 앱으로 반환합니다.

- **Advisor orchestration**
  - 주 provider가 초안을 작성합니다.
  - advisor provider가 초안을 검토합니다.
  - 주 provider가 검토 내용을 반영해 최종 답변을 합성합니다.
  - 이 흐름은 Quick 모드에서만 사용합니다. Dev 모드는 실제 CLI 세션을 직접 다루므로 advisor를 비활성화합니다.

- **Dev PTY 세션**
  - Rust `pty_manager.rs`가 provider CLI 프로세스를 PTY 안에서 실행합니다.
  - 프론트엔드 `TerminalPane`은 xterm.js로 PTY 출력을 표시합니다.
  - 한글 IME 문제를 피하기 위해 xterm에 직접 타이핑하지 않고, 앱 Composer에서 입력을 받아 PTY로 전송합니다.
  - `/resume`처럼 CLI 내부 선택 UI가 뜨는 경우를 위해 Composer가 비어 있을 때 방향키, Enter, Esc, Tab을 raw key sequence로 PTY에 전달합니다.

- **프로젝트 폴더 컨텍스트**
  - conversation별로 프로젝트 폴더를 선택합니다.
  - Quick 모드는 해당 경로에서 one-shot CLI를 실행합니다.
  - Dev 모드는 해당 경로에서 PTY 세션을 시작합니다.

- **Provider 상태 HUD**
  - CLI 설치 여부, 설정된 모델명, 5시간 사용량, context 사용량 추정치를 표시합니다.
  - 단, Dev 모드에서 실제 현재 세션 context는 PTY 내부 CLI 표시가 기준입니다. HUD의 context는 로그 기반 최근 사용량 또는 앱 메시지 기반 추정치입니다.

- **대화 관리**
  - 새 대화 생성, conversation 선택, 삭제, 채팅 내용 초기화를 지원합니다.
  - conversation은 provider, advisor, project, mode, messages, provider tab 정보를 가집니다.

## 기술 스택

| 영역 | 기술 | 역할 |
| --- | --- | --- |
| Desktop shell | Tauri 2 | macOS 데스크톱 앱 shell, Rust 명령 IPC |
| Backend | Rust | provider 실행, PTY 관리, usage/model 상태 조회 |
| PTY | `portable-pty` | 대화형 CLI 프로세스 유지, stdin/stdout 연결 |
| Frontend | React 19, TypeScript, Vite | 앱 UI, 상태 관리, 채팅/터미널 화면 |
| Terminal UI | `@xterm/xterm`, `@xterm/addon-fit` | PTY 출력 렌더링과 리사이즈 |
| Styling | CSS variables, CSS modules style layer | 다크 UI 토큰과 hover/상태 스타일 |
| Tauri plugins | dialog, opener | 프로젝트 폴더 선택, OS 연동 |
| Type sync | custom generator | Rust provider 타입을 TS 타입으로 생성 |

## 디렉터리 구조

```text
src/
  App.tsx                       # 앱 컨테이너: active conversation, Quick/Dev 분기
  components/
    Sidebar.tsx                 # conversation 목록, 새 대화 모드 선택
    ProjectRow.tsx              # 프로젝트 폴더, 현재 대화 모드 표시, advisor
    HUD.tsx                     # provider 상태 카드
    Composer.tsx                # Quick 메시지 입력, Dev PTY 입력
    TerminalPane.tsx            # xterm 출력 전용 터미널 패널
  hooks/
    useConversations.ts         # conversation CRUD와 활성 대화 관리
    usePendingChat.ts           # Quick 응답 대기 상태
    useProviderRuntime.ts       # provider 상태 조회
  lib/
    chatFlow.ts                 # Quick/advisor 프롬프트 빌더와 실행 흐름
    conversations.ts            # conversation/message factory
    ipc.ts                      # Tauri invoke/event wrapper
    types.ts                    # provider metadata와 앱 도메인 타입
    generated/providerTypes.ts  # Rust에서 생성된 provider 타입

src-tauri/src/
  lib.rs                        # Tauri command 등록
  pty_manager.rs                # PTY 세션 생성/입력/리사이즈/종료 이벤트
  providers/
    mod.rs                      # provider status/run_chat 공개 API
    registry.rs                 # Provider trait 구현과 provider dispatch
    claude_usage.rs             # Claude OAuth/keychain/log usage 조회
    codex_usage.rs              # Codex JSONL usage 조회
    model_name.rs               # 모델명 정규화
    util/                       # curl, iso8601, json, jsonl helper
```

## 동작 흐름

### Quick 모드

```text
Composer
  -> handleSend()
  -> chatFlow.ts
  -> ipc.providerChat()
  -> Rust provider_chat
  -> provider.run_chat()
  -> CLI one-shot 실행
  -> stdout을 ChatPane 메시지로 표시
```

Quick 모드는 “명령 하나 보내고 응답을 받는” 비대화형 흐름입니다. 이전 CLI 세션의 TUI 상태나 `/resume` 선택 UI를 직접 다루는 용도는 아닙니다.

### Dev 모드

```text
New Chat 생성
  -> mode = develop
  -> active provider PTY 생성
  -> Rust ptyCreate()
  -> provider CLI 프로세스 유지
  -> pty-output event
  -> TerminalPane xterm 출력

Composer 입력
  -> ptyWrite(tabId, text + Enter)
  -> CLI stdin
```

Dev 모드는 “CLI를 앱 안에서 계속 켜두는” 대화형 흐름입니다. 한글 입력은 Composer에서 처리하고, xterm은 출력 전용에 가깝게 사용합니다.

## Context 숫자를 보는 기준

Dev 모드에서는 PTY 화면과 HUD의 context가 다르게 보일 수 있습니다. 정상입니다.

- **PTY context**
  - 현재 CLI 세션이 직접 표시하는 값입니다.
  - 새 PTY 세션은 context가 0부터 시작합니다.
  - `/resume`으로 기존 세션을 선택하면 그 세션의 context로 바뀝니다.
  - 현재 작업 세션 기준으로는 이 값이 가장 정확합니다.

- **HUD Context Used**
  - provider 로그나 JSONL에서 읽은 최근 사용량, 또는 앱 메시지 길이 기반 추정치입니다.
  - 특정 PTY 세션과 1:1로 묶인 값이 아닙니다.
  - Dev 모드에서는 “현재 세션 context”가 아니라 “최근 provider 사용량 참고값”으로 봐야 합니다.

## 필요 조건

- Node.js
- pnpm
- Rust toolchain
- Tauri 2 개발 환경
- 사용할 provider CLI
  - `claude`
  - `codex`
  - `gemini`

각 CLI는 앱 실행 전에 로컬에서 설치 및 인증되어 있어야 합니다.

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

## 검증 명령

변경 후 기본 검증은 아래 순서로 합니다.

```bash
pnpm build
cd src-tauri && cargo check
cd src-tauri && cargo fmt --check
git diff --check
```

## 현재 설계상 주의점

- Dev 모드 PTY는 provider별 실제 CLI 출력 포맷에 의존합니다.
- xterm 직접 입력은 한글 IME 이슈가 있어 현재는 Composer 입력을 우선합니다.
- Quick 모드와 Dev 모드는 같은 conversation UI를 공유하지만, 실행 모델은 다릅니다.
- HUD context는 Dev PTY 세션의 실시간 context와 다를 수 있습니다.
- provider 추가 시 Rust `Provider` trait 구현, TS `PROVIDERS` 테이블, CLI 상태 조회 경로를 함께 확인해야 합니다.
