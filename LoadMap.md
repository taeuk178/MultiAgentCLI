# MultiAgentCLI Load Map

이 문서는 MultiAgentCLI를 단순한 멀티 CLI 실행기가 아니라, 로컬 개발 작업 기억 시스템으로 확장하기 위한 방향성을 정리합니다.

## 핵심 방향

MultiAgentCLI는 사용자의 입력과 provider의 출력을 모두 관찰할 수 있는 위치에 있습니다.

```text
User input
  -> MultiAgentCLI
  -> Claude / Codex / Gemini
  -> MultiAgentCLI
  -> User output
```

이 I/O 경계에 있기 때문에 앱은 대화, PTY 입력, PTY 출력, provider 응답, 프로젝트 경로, 실행 시점, 작업 결과를 로컬에 저장할 수 있습니다. 이 저장 데이터는 이후 검색, 요약, 재개, provider 간 맥락 공유, prompt context injection에 사용할 수 있습니다.

## 해결하려는 문제

### 1. 작업 재개 비용

개발 작업은 보통 하루 안에 끝나지 않습니다. 며칠 뒤 다시 열었을 때 다음 정보가 필요합니다.

- 어디까지 진행했는지
- 어떤 접근이 실패했는지
- 어떤 테스트가 통과했는지
- 어떤 파일을 수정했는지
- 남은 TODO가 무엇인지

I/O를 저장하면 앱이 프로젝트별 작업 요약을 만들고, 다음 세션 시작 시 이어서 작업할 수 있는 상태를 제공할 수 있습니다.

### 2. Provider 간 맥락 단절

Claude, Codex, Gemini는 서로의 대화를 모릅니다. 사용자는 provider를 바꿀 때마다 같은 설명을 반복해야 합니다.

로컬 memory가 있으면 앱이 provider와 무관한 project memory를 유지할 수 있습니다.

```text
Claude에서 논의한 설계 결정
Codex가 수정한 코드 요약
Gemini가 지적한 리뷰 포인트
  -> 같은 project memory로 통합
```

이렇게 하면 provider를 전환해도 필요한 맥락을 다시 설명하는 비용을 줄일 수 있습니다.

### 3. 반복 설명

프로젝트에는 매번 설명해야 하는 배경이 있습니다.

- 기술 스택
- 폴더 구조
- 검증 명령
- 코딩 규칙
- 설계상 주의점
- 현재 미해결 이슈

이런 정보는 conversation마다 새로 입력하기보다 project memory에서 가져와 prompt에 자동 또는 수동으로 넣는 편이 효율적입니다.

### 4. 과거 해결책 검색

개발 중 같은 에러를 반복해서 만나는 경우가 많습니다.

저장된 I/O를 검색할 수 있으면 다음 질문에 답할 수 있습니다.

- 이 에러 전에 어떻게 해결했는가?
- 어떤 명령이 실패했는가?
- 어떤 patch가 통과했는가?
- 비슷한 문제를 어떤 provider가 더 잘 해결했는가?

초기에는 vector DB 없이 SQLite FTS만으로도 충분히 유용할 수 있습니다.

### 5. 의사결정 로그

코드만 보면 왜 그렇게 구현했는지 알기 어렵습니다.

예를 들어 이 프로젝트에는 다음 같은 결정이 있습니다.

- 한글 IME 문제 때문에 xterm 직접 입력 대신 Composer 입력을 사용한다.
- Quick 모드는 one-shot 실행으로 둔다.
- Dev 모드는 PTY 세션을 유지한다.
- Dev 모드의 실제 context 기준은 HUD가 아니라 PTY 화면이다.
- conversation mode는 생성 후 고정한다.

I/O와 요약을 저장하면 이런 결정 근거를 나중에 다시 확인할 수 있습니다.

### 6. 자동 산출물 생성

저장 데이터는 개발 산출물 생성에도 사용할 수 있습니다.

- 커밋 메시지 후보
- PR 설명 초안
- 오늘 작업 요약
- 변경 파일별 요약
- 회귀 위험 목록
- 다음 작업 리스트

이 기능은 실제 개발 workflow에 바로 연결됩니다.

### 7. 감사와 추적성

회사 개발 환경에서는 AI가 어떤 입력을 받았고 어떤 출력을 냈는지 추적하는 것도 중요합니다.

로컬 저장은 다음 질문에 답할 수 있게 합니다.

- 어떤 요청을 모델에게 보냈는가?
- 어떤 provider가 어떤 제안을 했는가?
- 어떤 제안이 실제 코드 변경으로 이어졌는가?
- 민감정보가 input/output에 포함됐는가?

## 저장 대상

초기에는 모든 것을 벡터화하기보다 원본 event log를 먼저 안정적으로 저장합니다.

저장 후보:

- conversation metadata
- user message
- provider response
- Dev mode PTY input
- Dev mode PTY output
- provider id
- mode: Quick / Dev
- project path
- timestamp
- command result
- git diff summary
- test result summary
- 사용자가 명시적으로 기억하라고 한 내용

PTY output은 raw와 clean text를 분리하는 것이 좋습니다.

```text
raw output
  -> 원본 ANSI/TUI 출력 보존

clean text
  -> 검색, 요약, chunking용 정제 텍스트
```

## 저장 구조 제안

초기 구현은 SQLite를 권장합니다.

```text
~/Library/Application Support/MultiAgentCLI/
  app.sqlite
  attachments/
  indexes/
```

예상 테이블:

```text
projects
conversations
messages
pty_events
memory_chunks
summaries
provider_runs
```

embedding은 처음부터 필수는 아닙니다. 원본 저장과 FTS 검색이 먼저입니다.

## 검색과 활용

### 1. Keyword Search

SQLite FTS5로 시작합니다.

지원할 수 있는 필터:

- project
- provider
- mode
- date range
- conversation
- message type

### 2. Memory Chunk

긴 대화와 PTY output은 검색과 prompt injection에 적합한 단위로 나눕니다.

chunk type 예시:

- decision
- error
- fix
- command
- test_result
- summary
- todo
- code_context

### 3. Retrieval Injection

Quick 모드에서는 prompt 생성 전에 관련 memory를 검색해 context로 삽입할 수 있습니다.

```text
사용자 질문
  -> project memory 검색
  -> 관련 chunk 선택
  -> prompt에 "Relevant local memory"로 삽입
  -> providerChat 실행
```

Dev 모드에서는 자동 삽입보다 수동 제어가 우선입니다.

예:

- `/memory search <query>`
- `/memory inject <chunk>`
- `현재 작업 요약 삽입`
- `최근 실패한 테스트 삽입`

대화형 CLI 세션에 과거 memory를 자동으로 넣으면 context 오염이 생길 수 있기 때문입니다.

## Vector화 전략

vector search는 2단계 이후 도입합니다.

초기에는 다음 순서가 현실적입니다.

```text
Event Log
  -> Clean Text
  -> FTS Search
  -> Chunking
  -> Summaries
  -> Embedding
  -> Vector Search
```

후보 기술:

- SQLite FTS5
- sqlite-vec
- LanceDB
- Qdrant local
- 외부 embedding API
- 로컬 embedding model

로컬 우선 앱이므로, 장기적으로는 로컬 embedding 옵션을 열어두는 것이 좋습니다. 다만 초기에는 구현 난이도와 앱 크기를 고려해 FTS부터 시작합니다.

## 위험 요소

### 1. 민감정보 저장

터미널 출력에는 API key, token, env, 회사 코드, 파일 경로가 포함될 수 있습니다.

필요한 대응:

- secret redaction
- 저장 제외 패턴
- project별 memory on/off
- raw PTY output 저장 여부 설정
- 데이터 삭제 UI

### 2. Context 오염

관련 없는 과거 memory가 prompt에 들어가면 모델 품질이 떨어집니다.

필요한 기준:

- 같은 project 우선
- 최근성 반영
- 명시적 user intent 반영
- 자동 삽입 개수 제한
- Dev 모드는 수동 삽입 우선

### 3. PTY 노이즈

PTY output에는 status line, progress bar, TUI redraw, ANSI escape가 많습니다.

필요한 처리:

- raw와 clean 분리
- ANSI strip
- 반복 line 압축
- status line 필터링
- command boundary 추정

### 4. Provider별 출력 포맷 변경

Claude/Codex/Gemini CLI의 출력 포맷은 바뀔 수 있습니다.

따라서 PTY output 파서는 느슨하게 유지하고, provider별 강한 파싱에 지나치게 의존하지 않는 것이 좋습니다.

## 단계별 로드맵

### Phase 1. Local Persistence

목표: 원본 데이터를 잃지 않고 로컬에 저장합니다.

- SQLite 저장소 추가
- conversation 저장
- Quick messages 저장
- Dev PTY input 저장
- PTY output raw/clean 저장 구조 설계
- project별 저장 on/off 설정
- 데이터 삭제 기능

### Phase 2. Search Panel

목표: 저장된 데이터를 사람이 다시 찾을 수 있게 합니다.

- SQLite FTS5 적용
- 우측 패널에 local memory search 추가
- project/provider/date 필터
- 검색 결과에서 원본 conversation으로 이동
- error/fix/test result 중심 검색 UX

### Phase 3. Summaries

목표: 저장된 I/O를 작업 단위로 요약합니다.

- conversation summary 생성
- project daily summary 생성
- 마지막 작업 상태 요약
- 남은 TODO 추출
- 실패한 접근과 성공한 접근 분리

### Phase 4. Prompt Context

목표: memory를 provider 호출에 활용합니다.

- Quick 모드 prompt에 관련 memory 삽입
- 삽입된 memory를 UI에 표시
- 사용자가 memory 삽입 여부를 승인할 수 있게 처리
- Dev 모드에서는 수동 inject 명령 또는 버튼 제공

### Phase 5. Vector Memory

목표: 의미 기반 검색과 유사 작업 추천을 지원합니다.

- chunking pipeline 추가
- embedding provider 추상화
- local/API embedding 선택
- vector index 저장
- hybrid search: FTS + vector

### Phase 6. Workflow Automation

목표: 저장된 작업 흐름을 산출물로 전환합니다.

- 커밋 메시지 생성
- PR description 생성
- 작업 회고 생성
- 회귀 위험 보고서 생성
- provider별 성능/성공률 분석

## 우선순위

가장 먼저 만들 가치가 큰 것은 다음 세 가지입니다.

1. Project별 local event log
2. Search panel
3. 작업 재개용 summary

embedding과 vector search는 그 다음입니다. 원본 데이터가 안정적으로 쌓이지 않으면 vector search도 신뢰하기 어렵기 때문입니다.

## 최종 목표

MultiAgentCLI의 장기 목표는 provider CLI를 한 화면에 모으는 것을 넘어서, 로컬 개발 작업의 기억과 흐름을 관리하는 앱이 되는 것입니다.

```text
CLI 실행기
  -> 멀티 provider 작업 공간
  -> 로컬 개발 memory
  -> 작업 재개/검색/요약/자동 산출물 시스템
```
