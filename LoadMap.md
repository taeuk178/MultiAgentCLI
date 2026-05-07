# MultiAgentCLI Load Map

이 문서는 MultiAgentCLI의 방향을 **Claude Code plugin**으로 재정의합니다. 기존 Tauri 데스크톱 앱 청사진을 폐기하고, Claude Code의 hook·skill·subagent 시스템 위에 로컬 개발 작업 기억 시스템을 구축합니다.

## 방향 전환 요약

| 항목 | 이전 (Tauri 앱) | 현재 (Claude Code plugin) |
| --- | --- | --- |
| 실행 환경 | macOS 데스크톱 앱 | Claude Code 세션 안 |
| LLM 호출 | provider CLI 비대화형 실행 | Claude Code 본체 + hook이 보강 |
| 인증 | provider별 CLI 인증 | OAuth 구독 그대로 사용 |
| Advisor | 앱 내 prompt orchestration | `claude -p`, `codex exec`, `gemini -p` hook 호출 |
| Memory | 앱 SQLite | `~/.claude/multiagent/` SQLite + 마크다운 |
| UI | React + Tailwind 데스크톱 창 | Claude Code 세션 (skill 출력, hook 컨텍스트) |
| Dev PTY 모드 | xterm.js 기반 인터랙티브 터미널 | 폐기 (Claude Code가 대신함) |
| 스킬 공유 | 앱 내장 | GitHub 기반 레지스트리 (OMC 패턴) |

## 핵심 가치

Claude Code 세션은 LLM 호출의 **prefill 단계**와 **응답 종료 단계**에 hook을 걸 수 있습니다. 이 위치는 MultiAgentCLI가 원래 노리던 "I/O 경계"와 정확히 같습니다.

```text
유저 입력
  -> UserPromptSubmit hook
       memory 조회, 질문 보강, 컨텍스트 주입
  -> Claude Code (OAuth 구독으로 LLM 호출)
  -> 응답
  -> Stop hook
       응답에서 decision/error/fix 추출, memory 저장
  -> 유저 표시
```

API key 없이 구독 인증만으로 동작합니다. Hook 안에서 추가 LLM 호출이 필요하면 `claude -p`, `codex exec`, `gemini -p`를 그대로 씁니다.

## 해결하려는 문제

### 1. 작업 재개 비용

며칠 만에 다시 연 프로젝트의 진행 상황·실패한 접근·통과한 테스트·남은 TODO를 Claude Code 세션 시작 시점에 자동 주입합니다. UserPromptSubmit hook이 첫 입력 직전에 프로젝트별 최근 memory를 컨텍스트로 넣습니다.

### 2. Provider 간 맥락 단절

Claude/Codex/Gemini를 같은 SQLite memory에 누적합니다. Claude Code 세션 안에서 `codex exec` 또는 `gemini -p`를 hook이 호출하면, 결과를 같은 memory에 저장합니다. 다음 provider 전환 시점에 그 memory가 컨텍스트로 주입됩니다.

### 3. 반복 설명

기술 스택·폴더 구조·검증 명령·코딩 규칙·미해결 이슈를 project memory에서 끌어옵니다. UserPromptSubmit hook이 프로젝트 경로 기준으로 자동 주입.

### 4. 과거 해결책 검색

저장된 I/O를 SQLite FTS5로 검색합니다. Skill로 노출:

```text
/memory search <query>
/memory inject <chunk-id>
/memory recent --error
```

### 5. 의사결정 로그

설계 결정을 `decision` chunk type으로 저장합니다. Stop hook이 응답에서 `결정:`, `선택:` 같은 패턴을 감지하거나, 사용자가 명시적으로 `/memory remember decision <text>`로 등록.

### 6. 자동 산출물 생성

- 커밋 메시지 후보
- PR description 초안
- 작업 회고
- 다음 작업 리스트

각각 별도 skill로 구현. Claude Code 세션에서 `/commit-message`, `/pr-draft` 등으로 호출. Skill 안에서 memory 기반 컨텍스트 + `claude -p`로 합성.

### 7. 감사와 추적성

모든 user input, hook 주입 컨텍스트, LLM 응답을 SQLite event log에 누적. 어떤 memory가 어떤 prompt에 들어갔는지 추적 가능.

## 시스템 구성

### 디렉터리 구조

```text
~/.claude/multiagent/                    # 글로벌 (모든 프로젝트 공유)
  app.sqlite                              # 이벤트 로그 + memory chunks
  hooks/
    user-prompt-submit.sh                 # prefill 단계 컨텍스트 주입
    stop.sh                               # 응답에서 memory 추출
  skills/                                 # 글로벌 skill
    memory/SKILL.md
    advisor/SKILL.md
    commit-message/SKILL.md
  config.json                             # 사용자 설정

<project>/.claude/multiagent/             # 프로젝트 로컬 (override)
  config.json
  skills/                                 # 프로젝트 전용 skill
```

### Memory 스키마

```sql
projects(
  id text primary key,
  root_path text not null unique,
  name text,
  created_at text not null,
  updated_at text not null
);

conversations(
  id text primary key,
  project_id text references projects(id),
  source text not null,            -- claude_code, codex, gemini
  title text,
  created_at text not null,
  updated_at text not null
);

events(
  id text primary key,
  project_id text references projects(id),
  conversation_id text references conversations(id),
  source text not null,            -- claude_code, hook, skill, codex, gemini
  kind text not null,              -- user_message, llm_response, hook_inject, tool_result
  text_clean text not null,
  metadata_json text not null default '{}',
  created_at text not null
);

memory_chunks(
  id text primary key,
  project_id text references projects(id),
  source_event_id text references events(id),
  chunk_type text not null,        -- decision, error, fix, command, test_result, summary, todo, code_context, note
  text text not null,
  metadata_json text not null default '{}',
  created_at text not null,
  pinned integer not null default 0
);

provider_runs(
  id text primary key,
  conversation_id text references conversations(id),
  project_id text references projects(id),
  provider text not null,          -- claude, codex, gemini
  phase text not null,             -- single, advisor_draft, advisor_review, advisor_synthesize
  prompt_event_id text references events(id),
  output_event_id text references events(id),
  status text not null,
  started_at text not null,
  finished_at text
);

-- FTS
create virtual table events_fts using fts5(text_clean, content='events', content_rowid='rowid');
create virtual table memory_chunks_fts using fts5(text, content='memory_chunks', content_rowid='rowid');
```

### Hook 통합

#### UserPromptSubmit hook (prefill)

목적: 유저 입력 직전에 관련 memory를 컨텍스트로 주입.

```bash
#!/bin/bash
# ~/.claude/multiagent/hooks/user-prompt-submit.sh
# stdin으로 유저 입력을 받고, stdout으로 추가 컨텍스트를 출력하면
# Claude Code가 [원본 + 컨텍스트]를 LLM에 보냄.

USER_INPUT=$(cat)
PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)

# 1. 이벤트 로그에 입력 저장
sqlite3 ~/.claude/multiagent/app.sqlite "
  insert into events (id, project_id, source, kind, text_clean, created_at)
  values (...)
"

# 2. 프로젝트별 최근 memory_chunks 조회 (FTS + 최근성)
RELEVANT=$(sqlite3 ~/.claude/multiagent/app.sqlite "
  select text from memory_chunks
  where project_id = ? and chunk_type in ('decision','fix','todo')
  order by pinned desc, created_at desc
  limit 5
")

# 3. 모호도 판단: 단어 수, 키워드, 코드 참조 여부 등
# 모호하면 [Memory context] 블록을 stdout으로 출력
if [[ -n "$RELEVANT" ]]; then
  echo "[Project memory context]"
  echo "$RELEVANT"
fi
```

#### Stop hook (응답 추출)

목적: LLM 응답에서 chunk type별로 memory 추출 후 저장.

```bash
#!/bin/bash
# ~/.claude/multiagent/hooks/stop.sh
# stdin으로 LLM 응답을 받고, 추출 결과를 SQLite에 저장.

RESPONSE=$(cat)
PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)

# 1. 이벤트 로그에 응답 저장
# 2. 패턴 감지로 chunk 추출 (단순 grep + 사용자 정의 룰)
# 3. 더 정교한 추출이 필요하면 claude -p로 OAuth 구독 호출
EXTRACTED=$(echo "$RESPONSE" | claude -p "다음 응답에서 결정/오류/수정/TODO를 chunk_type과 함께 JSON 라인으로 추출해줘.")

# 4. SQLite에 chunk 저장
echo "$EXTRACTED" | while read line; do
  sqlite3 ~/.claude/multiagent/app.sqlite "insert into memory_chunks ..."
done
```

### Skill 시스템

skill은 Claude Code의 `Skill` 도구로 호출되는 명령. 각 skill은 SKILL.md + 선택적 보조 스크립트로 구성.

#### memory skill

```text
/memory search <query>     project FTS 검색
/memory inject <chunk-id>  특정 chunk를 현재 컨텍스트로 주입
/memory remember <text>    명시적 memory 등록 (chunk_type 포함)
/memory pin <chunk-id>     항상 prefill에 포함되도록 고정
/memory list --recent      최근 chunk 표시
/memory forget <chunk-id>  삭제
```

#### advisor skill (CCG 패턴)

```text
/advisor codex <prompt>    codex exec로 의견
/advisor gemini <prompt>   gemini -p로 의견
/advisor ccg <prompt>      codex + gemini 병렬, 결과를 Claude가 합성
```

advisor 결과는 `provider_runs` 테이블과 `events` 테이블에 함께 저장. 다음 prefill에 컨텍스트로 사용 가능.

#### workflow skill

```text
/commit-message            현재 staged 변경 + 최근 memory로 커밋 메시지 후보
/pr-draft                  현재 브랜치 커밋들 + memory로 PR 본문
/recap                     오늘 작업 요약
/handoff                   다음 세션 시작용 자동 brief
```

### 외부 레지스트리

OMC 패턴 그대로 사용.

```text
GitHub repo (multiagent-skills)
  ├─ skills/
  │   └─ <skill-name>/SKILL.md
  └─ manifest.json

설치:
  multiagent skill add <github-url-or-name>
    -> ~/.claude/multiagent/skills/<skill-name>/

로컬 우선:
  <project>/.claude/multiagent/skills/  override
  ~/.claude/multiagent/skills/          글로벌
```

업로드 흐름:
- 유저 A: `multiagent skill publish <name>` → GitHub에 PR 또는 push
- 유저 B: `multiagent skill add <name>` → 같은 skill 사용

권한·서명 검증은 Phase 후반에 추가.

## 단계별 로드맵

### Phase 1. Memory 저장소 (1주)

- `~/.claude/multiagent/` 디렉터리 생성 로직
- SQLite 스키마 마이그레이션
- 이벤트 append API (Bash 또는 Python 헬퍼)
- 기본 chunk type
- `multiagent` CLI 진입점 (skill에서 호출하기 위함)

### Phase 2. Hook 통합 (1주)

- UserPromptSubmit hook 스크립트
- Stop hook 스크립트
- 프로젝트 식별 (git root 기반)
- 모호도 판단 단순 룰
- 컨텍스트 주입 포맷 표준화 (`[Project memory context]` 블록)

### Phase 3. Memory skill (1주)

- `/memory search/inject/remember/pin/list/forget`
- FTS5 적용
- chunk_type별 검색 필터
- 결과 포맷이 Claude Code 컨텍스트에 그대로 들어가도록 설계

### Phase 4. Advisor skill (1주)

- `/advisor codex/gemini/ccg`
- `claude -p`, `codex exec`, `gemini -p` 통합
- 결과를 `provider_runs`에 저장
- 합성 로직: Claude가 두 의견을 받아 `claude -p` 한 번 더로 최종 답변

### Phase 5. Workflow skill (1주)

- `/commit-message`, `/pr-draft`, `/recap`, `/handoff`
- git porcelain + memory 결합
- 출력은 사용자가 검토 후 그대로 사용 가능한 형태

### Phase 6. 레지스트리 (2주)

- GitHub 기반 skill 레지스트리
- `multiagent skill add/remove/list/publish`
- manifest.json 포맷 정의
- 로컬 override 우선순위

### Phase 7. Vector / 고급 추출 (선택)

- sqlite-vec 또는 LanceDB
- chunk embedding pipeline
- hybrid search (FTS + vector)
- LLM 기반 chunk 추출 정교화

## Tauri 앱 처리

기존 Tauri 코드는 보존하지만 신규 개발은 중단합니다. 이미 동작하는 기능 중 plugin으로 재현하기 어려운 것은 다음과 같습니다.

- Dev PTY 모드 (xterm.js + portable-pty)

이 기능이 본인 워크플로에 필수인 사용자에게는 Tauri 앱이 그대로 유효합니다. 신규 LoadMap 기능은 Tauri에 다시 포팅하지 않습니다.

장기적으로 Tauri 앱은 다음 중 한 방향으로 갑니다.

- 별도 repo로 분리해 PTY 전용 도구로 유지
- 폐기

이 결정은 Phase 5 이후 사용자 피드백을 보고 정합니다.

## 위험 요소

### 1. 민감정보 저장

터미널 출력·prompt에는 API key·token·내부 코드가 포함될 수 있습니다.

대응:
- secret redaction 룰셋 (정규식 기반)
- 프로젝트별 memory on/off
- 저장 제외 패턴 설정
- `multiagent memory purge --project <path>`

### 2. 컨텍스트 오염

관련 없는 memory가 prefill에 들어가면 모델 품질이 떨어집니다.

대응:
- 같은 project 우선
- 최근성 + pin 가중치
- 자동 주입 chunk 수 상한 (기본 5)
- 사용자가 hook 동작을 끌 수 있는 토글

### 3. Hook 실행 실패

hook 스크립트 오류는 Claude Code 세션을 차단할 수 있습니다.

대응:
- hook 스크립트는 항상 exit 0으로 종료
- 오류는 stderr와 별도 로그에만 기록
- timeout (기본 3초)

### 4. SQLite 동시성

여러 Claude Code 세션이 동시에 같은 DB에 쓸 수 있습니다.

대응:
- WAL 모드
- busy_timeout
- append-only 패턴
- 단일 writer는 필요 시 도입

### 5. provider CLI 출력 포맷 변경

`claude -p`, `codex exec`, `gemini -p` 출력 포맷은 바뀔 수 있습니다.

대응:
- 강한 파싱 회피
- chunk 추출은 패턴 + LLM 보조의 이중 구조
- skill 단위로 provider 호출 캡슐화

## 우선순위

가장 먼저 만들 가치가 큰 것은 다음입니다.

1. Phase 1 + 2 (memory 저장소 + hook)
2. Phase 3 (memory skill)
3. Phase 4 (advisor skill)

이 세 단계만 갖춰도 "유저 input이 memory에 등록되고, 모호한 질문이 보강되며, 응답에서 자동으로 chunk가 누적되고, codex/gemini 의견을 OAuth 구독으로 받는" Hermes-agent 스타일이 동작합니다.

레지스트리(Phase 6)는 사용자 수가 늘어 공유 수요가 생길 때 시작합니다.

## 최종 목표

```text
Claude Code 세션
  + UserPromptSubmit hook (memory 주입)
  + Stop hook (memory 추출)
  + memory/advisor/workflow skill
  + 글로벌 + 프로젝트 SQLite memory
  + GitHub 기반 skill 레지스트리
  -> 구독 OAuth만으로 동작하는 로컬 개발 작업 기억 시스템
```
