# imprint Load Map

**문서 책임**
- 본 문서는 **큰 그림**: 비전·아키텍처·Phase 정의·미시작 단계·위험 요소·최종 목표만 담는다.
- 단기적인 다음 세션 픽업 안건(즉시 검토, deferred TODO, 직전 Phase 마무리)은 `HANDOFF.md` 참조.
- 결정 사유 로그(왜 그렇게 바꿨는지·폐기한 대안)는 `HISTORY.md` 참조.
- hook 단계별 시스템 의존·운영 환경 변수는 `flow.md` 참조.
- 구현된 동작·설치·사용은 `README.md` 참조.

이 문서는 imprint(이전 코드명: `multi-agent-cli-v2` / 더 이전 세대: SwiftUI `MultiAgentCLI`)의 방향을 **Claude Code plugin**으로 정의합니다. 기존 Tauri 데스크톱 앱 청사진을 폐기하고, Claude Code의 hook·skill·subagent 시스템 위에 로컬 개발 작업 기억 시스템을 구축합니다.

## 방향 전환 요약

| 항목 | 이전 (Tauri 앱) | 현재 (Claude Code plugin) |
| --- | --- | --- |
| 실행 환경 | macOS 데스크톱 앱 | Claude Code 세션 안 |
| LLM 호출 | provider CLI 비대화형 실행 | Claude Code 본체 + hook이 보강 |
| 인증 | provider별 CLI 인증 | OAuth 구독 그대로 사용 |
| Memory | 앱 SQLite | `~/.claude/imprint/` SQLite + 마크다운 |
| UI | React + Tailwind 데스크톱 창 | Claude Code 세션 (skill 출력, hook 컨텍스트) |
| Dev PTY 모드 | xterm.js 기반 인터랙티브 터미널 | 폐기 (Claude Code가 대신함) |
| 스킬 공유 | 앱 내장 | GitHub 기반 레지스트리 (OMC 패턴) |

## 핵심 가치

Claude Code 세션은 LLM 호출의 **prefill 단계**와 **응답 종료 단계**에 hook을 걸 수 있습니다. 이 위치는 이전 세대 SwiftUI 앱(`MultiAgentCLI`)이 원래 노리던 "I/O 경계"와 정확히 같습니다.

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

API key 없이 구독 인증만으로 동작합니다. Hook 안에서 추가 LLM 호출이 필요하면 백그라운드에서 `claude -p haiku`(prefill 분석·외부 source fetch·Stop chunk 추출)를 호출합니다.

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
~/.claude/imprint/                    # 글로벌 (모든 프로젝트 공유)
  app.sqlite                              # 이벤트 로그 + memory chunks
  hooks/
    user-prompt-submit.sh                 # prefill 단계 컨텍스트 주입
    stop.sh                               # 응답에서 memory 추출
  skills/                                 # 글로벌 skill
    memory/SKILL.md
    commit-message/SKILL.md
  config.json                             # 사용자 설정

<project>/.claude/imprint/             # 프로젝트 로컬 (override)
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
  -- LLM 추출(Stop hook): decision, error, fix, command, test_result, summary, todo, code_context, note
  -- 외부 source(ingestion): spec(notion), message(slack 단발), thread(slack thread)
  chunk_type text not null,
  text text not null,
  metadata_json text not null default '{}',
  created_at text not null,
  pinned integer not null default 0
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
# ~/.claude/imprint/hooks/user-prompt-submit.sh
# stdin으로 유저 입력을 받고, stdout으로 추가 컨텍스트를 출력하면
# Claude Code가 [원본 + 컨텍스트]를 LLM에 보냄.

USER_INPUT=$(cat)
PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)

# 1. 이벤트 로그에 입력 저장
sqlite3 ~/.claude/imprint/app.sqlite "
  insert into events (id, project_id, source, kind, text_clean, created_at)
  values (...)
"

# 2. 프로젝트별 최근 memory_chunks 조회 (FTS + 최근성)
RELEVANT=$(sqlite3 ~/.claude/imprint/app.sqlite "
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
# ~/.claude/imprint/hooks/stop.sh
# stdin으로 LLM 응답을 받고, 추출 결과를 SQLite에 저장.

RESPONSE=$(cat)
PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)

# 1. 이벤트 로그에 응답 저장
# 2. 패턴 감지로 chunk 추출 (단순 grep + 사용자 정의 룰)
# 3. 더 정교한 추출이 필요하면 claude -p로 OAuth 구독 호출
EXTRACTED=$(echo "$RESPONSE" | claude -p "다음 응답에서 결정/오류/수정/TODO를 chunk_type과 함께 JSON 라인으로 추출해줘.")

# 4. SQLite에 chunk 저장
echo "$EXTRACTED" | while read line; do
  sqlite3 ~/.claude/imprint/app.sqlite "insert into memory_chunks ..."
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
GitHub repo (imprint-skills)
  ├─ skills/
  │   └─ <skill-name>/SKILL.md
  └─ manifest.json

설치:
  imprint skill add <github-url-or-name>
    -> ~/.claude/imprint/skills/<skill-name>/

로컬 우선:
  <project>/.claude/imprint/skills/  override
  ~/.claude/imprint/skills/          글로벌
```

업로드 흐름:
- 유저 A: `imprint skill publish <name>` → GitHub에 PR 또는 push
- 유저 B: `imprint skill add <name>` → 같은 skill 사용

권한·서명 검증은 Phase 후반에 추가.

## 단계별 로드맵 — 미시작

> 완료된 phase(1 Memory 저장소 / 2 Hook 통합 / 3 Memory skill / 4.5 사내 컨텍스트 ingestion)와 폐기된 phase(4 Advisor skill)의 결정 사유는 `HISTORY.md` 참조.

### Phase 5. Workflow skill (1주)

- `/commit-message`, `/pr-draft`, `/recap`, `/handoff`
- git porcelain + memory 결합
- 출력은 사용자가 검토 후 그대로 사용 가능한 형태

### Phase 6. 레지스트리 (2주)

- GitHub 기반 skill 레지스트리
- `imprint skill add/remove/list/publish`
- manifest.json 포맷 정의
- 로컬 override 우선순위

### Phase 7a. Chunk-level retrieval 정밀도 (의미 검색 + 엔티티 + 버전)

7개 결정(2026-05-10)에 따라 다음 컴포넌트를 한 사이클 안에 묶음:

- **SQLite + FTS5 + sqlite-vec** — 단일 파일 정체성 유지
- **로컬 multilingual 임베딩** (multilingual-e5 / BGE 계열) — 외부 API key 의존 없음
- **contextual prefix + retrieval_text** 분리 저장 (Anthropic contextual retrieval 방식)
- **entity alias canonicalization** — 자동 추출 + review queue (오탐 방지)
- **versioning 필드** (`valid_from` / `valid_to` / `is_current` / `supersedes_chunk_id`) — 사용자 명시 기본 + 자동 제안 보조
- **hybrid retrieval (RRF) + 로컬 cross-encoder rerank**
- **inline-first + daemon-ready abstraction** — `retrieve(query)` 시그니처 추상화

상세 명세·결정 사항·후속 결정·구현 우선순위는 `HANDOFF.md` 의 **"Phase 7a — 청크 + 의미 검색 + 엔티티 정규화 + 버전"** 참조. 결정 사유는 `HISTORY.md` 2026-05-10 참조.

### Phase 7b. 계층 요약 + 충돌 감지 (검색 결과를 프로젝트 수준에서 해석)

Phase 7a 가 안정적으로 운용된 뒤 진입. **그래프 DB 도입이 아니라**, 1단계 retrieval 엔진 위에 **질문 해상도에 맞는 요약 계층** 과 **충돌 감지 계층** 을 얹는 단계. 단계 정의:

- **1단계 (7a)**: 검색을 잘하게 만든다
- **2단계 (7b)**: 검색된 결과를 프로젝트 수준에서 해석하게 만든다

핵심 컴포넌트:

- **RAPTOR 형 계층 요약** — feature / document / project 3계층, leaf 변경이 상위로 incremental 전파
- **query scope classifier** — local / feature / global 분류, retrieval 단위를 질문 해상도에 맞춤
- **경량 contradiction awareness** — 같은 entity 의 상충 decision 을 candidate 로 잡고 NLI / LLM 으로 정밀 판정, confirmed 만 답변에 노출
- **resolution-aware answer assembly** — summary + 근거 chunk + 충돌 표시

상세 명세·후속 결정·구현 우선순위·완료 조건은 `HANDOFF.md` 의 **"Phase 7b — 계층 요약 + 충돌 감지 (2단계 명세)"** 참조.

**영구 deferred** (Phase 7b 에서도 도입 안 함): full knowledge graph DB · GraphRAG / HippoRAG 풀스택 · graph traversal multi-hop · 자동 belief revision · 완전 자동 supersede 확정.

## Tauri 앱 처리

**폐기 완료.** 본 repo는 Claude Code plugin 단일 책임. Dev PTY 모드가 필요한 사용자는 SwiftUI 버전 [`MultiAgentCLI`](../MultiAgentCLI)를 사용하고, 신규 LoadMap 기능은 어느 쪽에도 포팅하지 않습니다.

## 위험 요소

### 1. 민감정보 저장

터미널 출력·prompt에는 API key·token·내부 코드가 포함될 수 있습니다.

대응:
- secret redaction 룰셋 (정규식 기반)
- 프로젝트별 memory on/off
- 저장 제외 패턴 설정
- `imprint memory purge --project <path>`

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

### 5. claude CLI 출력 포맷 변경

`claude -p haiku` 출력 포맷이 바뀌면 prefill 분석·외부 source fetch·Stop chunk 추출 결과 파싱이 깨집니다.

대응:
- JSON-only 강제 프롬프트 + `parse_json_relaxed`(코드펜스/주변 텍스트 제거 후 첫 JSON 객체 추출)
- 모든 호출이 graceful degradation — 파싱 실패 시 silent skip + 기존 chunk만 prepend

### 6. 환경 가정과 시스템 의존

- macOS 기본 환경 가정 — Linux/Windows 호환은 확인 안 함.
- `python3`, `sqlite3`, `uuidgen` 시스템 의존 — 누락 시 hook이 silent skip 처리하지만 기능은 비활성화됨.
- 동일 프로젝트에서 여러 Claude Code 세션이 동시에 돌면 SQLite WAL이 처리하지만 완전한 동시성 검증은 없음.

대응:
- WAL + busy_timeout으로 일반 동시성 흡수
- 의존 누락 시 `IMPRINT_DISABLE_*` 환경 변수로 부분 비활성화 가능
- Linux/Windows 호환은 사용자 요청 시 별도 Phase로 다룸

## 설계상 병목 후보·대응 플랜

README의 mermaid가 그리는 hook/ingestion 파이프라인에서 미래 병목으로 발현 가능한 3축을 사전 식별합니다. 각 축은 `IMPRINT_PROFILE=1` env-gated 계측 hook이 박혀 있고(`scripts/imprint/lib/common.sh:profile_emit`, `scripts/imprint/lib/ingestion.py:_profile_emit/_profile_span`), 활성화 시 측정값이 `~/.claude/imprint/profile.jsonl`에 JSONL로 누적됩니다. 평소 OFF — hook 추가 비용은 env 검사 1회.

### A. transcript JSONL 재파싱 (stage `stop.transcript_reparse`)

- **위치**: `scripts/imprint/stop.sh` 의 transcript 추출 블록. 매 turn마다 JSONL 전체를 line-by-line 재파싱해 마지막 assistant text 추출.
- **시나리오**: 세션이 길어질수록 O(n). turn마다 동기 경로에 누적 → 사용자 입력 직후 1초 보장이 깨질 수 있음.
- **실측** (각 5회 median, 같은 머신·콜드/워밍 캐시 구분 없음):

  | file size | lines | assistants | last bytes | median ms | max ms |
  | ---: | ---: | ---: | ---: | ---: | ---: |
  | 36.6 KB | 11 | 4 | 3,665 | 0.2 | 1.2 |
  | 553.7 KB | 217 | 106 | 109 | 2.7 | 3.1 |
  | 3,603.3 KB | 1,199 | 498 | 1,933 | 12.1 | 14.2 |

  선형 모델 ≈ `0.2 + 0.0101 × lines` ms (≈ `3.4 ms / MB`).
- **임계점 후보**:
  - 동기 추가 지연 100 ms → ~10,000 lines / ~30 MB / ~4,000 assistants
  - 동기 추가 지연 500 ms → ~50,000 lines / ~150 MB / ~20,000 assistants
- **대안** (단순 → 복잡):
  1. **tail-only seek**: 파일 끝에서 ~64 KB만 `f.seek`로 읽고 앞쪽 incomplete line만 버린 뒤 마지막 assistant 추출. 50 MB 세션에서도 ~3 ms.
  2. **incremental offset 저장**: `~/.claude/imprint/transcript-offsets/<session_id>.txt`에 마지막 read offset 기록, 다음 turn은 그 위치부터 read.
- **probe lifecycle**: env_gated (`IMPRINT_PROFILE=1`)

### B. 외부 fetch payload 폭주 (stages `fetch_slack_url`, `fetch_notion_url`, `fetch_slack_keywords`, `fetch_notion_keywords`, `cmd_lazy_fetch.*`, `call_claude`)

- **위치**: `scripts/imprint/lib/ingestion.py` 의 `fetch_slack_url` / `fetch_slack_keywords` / `fetch_notion_url` / `fetch_notion_keywords` + `lazy_fetch` 오케스트레이터 + `cmd_lazy_fetch` 진입점.
- **시나리오**:
  - 큰 Notion 페이지(H1/H2/H3 다수)는 sectioning 시 chunk 수십 개 + `claude -p haiku` 응답이 길어 `CLAUDE_TIMEOUT_FETCH=45 s` 임박.
  - 긴 Slack thread는 reply selection이 무거움.
  - prompt 내 URL이 4개 이상이면 처음 3개만 처리(`[:3]`)하고 silent skip — 사용자 모르게 누락.
  - dedup이 `metadata_json.url` 기준이라 같은 URL의 원본 갱신은 영구 stale, 명시적 `/memory refresh`로만 새로고침.
- **실측**: 운영 환경 OAuth + MCP 의존이라 격리 측정 불가. `IMPRINT_PROFILE=1` 시 다음이 자동 수집됨 — 각 fetch stage의 `dur_ms` + `payload_bytes` + `chunks`, `call_claude`의 `dur_ms` + `rc` + `stdout_bytes` + `timeout`.
- **임계점 후보** (코드 분석 기반, 실측으로 갱신 예정):
  - 단일 fetch payload > 50 KB → `claude -p haiku` 응답에 담기 어려움, sectioning 실패율 ↑
  - 단일 `fetch_*_url` wall clock > 30 s → 45 s 타임아웃의 67%, 다음 turn에 chunk 비노출 위험
  - prompt 내 URL > 3 → 현 구현에서 silent skip 발생
  - chunk `fetched_at` age > 14 d → stale 위험, refresh 권유 대상
- **대안**:
  1. URL 개수 cap을 silent 대신 `plugin.log` warn으로 노출.
  2. `fetched_at` TTL: N일 지난 url-dedup chunk는 stale flag로 마킹, `/memory list`/`show`가 표시.
  3. 큰 Notion 페이지의 chunking을 H1 단위로 단순화하고 H2·H3는 본문에 inline — chunk 수 절감.
- **probe lifecycle**: env_gated

### C. 동시 백그라운드 부하 (stages `ups.spawn`, `cmd_lazy_fetch.enter|exit`, `stop.spawn`, `cmd_extract.enter|exit`, `call_claude`)

- **위치**: `scripts/imprint/user-prompt-submit.sh` 의 백그라운드 spawn 블록 + `scripts/imprint/stop.sh` 의 extract spawn 블록 + ingestion.py `cmd_lazy_fetch` / `cmd_extract`.
- **시나리오**:
  - 빠른 turn cycle에서 turn N의 `cmd_extract`와 turn N+1의 `cmd_lazy_fetch`가 동시 실행 → `claude -p haiku` 프로세스 2개 + OAuth refresh + SQLite write 두 군데.
  - 단일 `cmd_lazy_fetch`가 외부 fetch까지 가면 최대 45 s. 그 시간 안에 turn N+2가 시작되면 spawn 누적.
  - 노트북 슬립/재개 시 좀비 spawn — `enter`만 남고 `exit` 없는 상태로 profile에 누적.
- **이미 있는 보호**: `schema.sql` 의 `PRAGMA journal_mode = WAL` + `PRAGMA busy_timeout = 5000`, `IMPRINT_BYPASS_HOOKS=1` 재귀 가드, `IMPRINT_DISABLE_EXTRACT=1` escape hatch.
- **실측**: 운영 환경 의존. `IMPRINT_PROFILE=1` 시 위 stage들이 PID·timestamp와 함께 자동 수집되어 enter↔exit 짝짓기로 동시성 + 좀비 분석 가능.
- **임계점 후보**:
  - 5분 윈도에서 enter(exit 미도달) > 2건 → CPU·OAuth 부하 알림
  - `call_claude` 동시성 > 2 → API 큐잉 대기
  - profile.jsonl 의 enter ↔ exit 짝이 30 s 초과 미매칭 → 좀비 후보
- **대안**:
  1. lazy-fetch 단일 실행 lockfile(`~/.claude/imprint/locks/lazy-fetch.lock`) — 이미 도는 spawn 있으면 skip.
  2. 좀비 detection: `/memory stats`가 profile.jsonl 을 분석해 "stale spawn N건" 노출.
  3. SQLite write 단일 writer 큐로 직렬화 — WAL + busy_timeout 으로 부족할 때만. 우선 측정 후 결정.
- **probe lifecycle**: env_gated

### 측정 활성화

```bash
export IMPRINT_PROFILE=1
# Claude Code 세션을 평소처럼 사용 → 측정값이 ~/.claude/imprint/profile.jsonl 에 누적
```

기본 OFF. 비활성 시 hook 추가 비용 = env 검사 1회. 활성 시 stage당 file append 1줄 (sub-ms). 모든 probe는 env_gated 라이프사이클이며, 영구 fix는 별도 사이클로 분리합니다.

## 우선순위 — 남은 단계

1. **Phase 5 (Workflow skill)** — 매일 트리거할 사용자-facing 명령 4개. memory + git porcelain + `claude -p` 합성. 다음에 만들 가치가 가장 큼.
2. **Phase 6 (레지스트리)** — 사용자 수가 늘어 skill 공유 수요가 생기는 시점에 시작.
3. **Phase 7a (Chunk-level retrieval 정밀도)** — FTS5 trigram 의 한계(의미 검색 필요·외래어 매칭·paraphrase 미스)가 보일 때 진입. 결정 사항·후속 결정은 `HANDOFF.md` 참조.
4. **Phase 7b (Project-level graph)** — Phase 7a 가 안정적으로 운용된 뒤. 프로젝트가 길어질수록 ROI 가 시간에 비례해 커짐.

## 최종 목표

```text
Claude Code 세션
  + UserPromptSubmit hook (memory 주입)
  + Stop hook (memory 추출)
  + memory/workflow skill
  + 글로벌 + 프로젝트 SQLite memory
  + GitHub 기반 skill 레지스트리
  -> 구독 OAuth만으로 동작하는 로컬 개발 작업 기억 시스템
```
