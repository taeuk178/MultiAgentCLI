# imprint Load Map

**문서 책임**
- 본 문서는 **큰 그림**: 비전·아키텍처·남은 단계·위험 요소·최종 목표.
- 단기적인 다음 세션 픽업 안건(즉시 검토, deferred TODO, 측정 후 캘리브레이션 항목)은 `HANDOFF.md` 참조.
- 결정 사유 로그(왜 그렇게 바꿨는지·폐기한 대안)는 `HISTORY.md` 참조.
- hook 단계별 시스템 의존·운영 환경 변수는 `flow.md` 참조.
- 구현된 동작·설치·사용·전체 플로우 다이어그램은 `README.md` 참조.

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

### 6. 자동 산출물 생성 (후순위)

- 커밋 메시지 후보
- PR description 초안
- 작업 회고
- 다음 작업 리스트

각각 별도 skill로 구현. 다만 현재 우선순위는 기능 확장이 아니라 RAG 기본 동작(저장·검색·참조)의 안정화이므로, workflow skill 은 기본 루프 검증 이후로 둡니다.

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

### Memory 스키마 (초기 설계)

Phase 1~3 의 핵심 테이블 — `events` (raw I/O log), `memory_chunks` (Stop hook 추출 + ingestion). FTS5 는 trigram tokenizer 로 한국어 부분 매칭.

```sql
projects(id, root_path, name, created_at, updated_at)
events(id, project_id, conversation_id, source, kind, text_clean, metadata_json, created_at)
memory_chunks(id, project_id, source_event_id, chunk_type, text, metadata_json, created_at, pinned)
-- chunk_type: decision/error/fix/command/test_result/summary/todo/code_context/note (LLM 추출)
--           + spec/message/thread (외부 source ingestion)

create virtual table events_fts using fts5(text_clean, ..., tokenize='trigram');
create virtual table memory_chunks_fts using fts5(text, ..., tokenize='trigram');
```

Phase 7a/7b 머지 후 추가 — `documents`, `chunks_v2` (이중 chunk_type + versioning), `entities` / `entity_aliases` / `chunk_entities`, `ingest_queue` (priority sorted), `summaries` / `summary_links`, `contradictions`. 자세한 컬럼 정의는 `scripts/imprint/lib/schema.sql` 참조.

### Hook 통합 (초기 설계)

핵심 컨셉:

- **UserPromptSubmit hook (prefill)** — stdin 으로 유저 입력 + stdout 추가 컨텍스트 → Claude Code 가 [원본 + 컨텍스트] 를 LLM 에 전달. 프로젝트별 최근 `memory_chunks` 조회(FTS + 최근성) 후 `[Project memory context]` 블록 prepend.
- **Stop hook (응답 추출)** — stdin 으로 LLM 응답 → `claude -p haiku` 로 chunk_type 별 추출 → `memory_chunks` INSERT.

실제 구현은 `scripts/imprint/{session-start,user-prompt-submit,stop}.sh` + `scripts/imprint/lib/ingestion.py` 참조. 현재 자동 hook 경로는 `memory_chunks` 를 저장·prefill 하고, `/retrieve` 디스패처는 별도 `chunks_v2`/`summaries` 경로를 사용합니다. 두 경로의 현재 구조는 `README.md` "전체 플로우 다이어그램" 참조.

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

## 단계별 로드맵

> 과거 phase 와 결정 사유는 `HISTORY.md` 참조. 이 문서에는 앞으로의 방향과 미완료 우선순위만 둡니다.

### RAG 기본 동작 안정화

#### RAG-1. 안전한 저장 경로

- user prompt, assistant response, extracted chunk, external source chunk 가 DB/FTS 에 들어가기 전 redaction 적용
- default redact 룰셋 보강
- 과거 raw row 청소는 사용자 승인 액션으로 분리

#### RAG-2. 자동 memory loop 검증

- `SessionStart → UserPromptSubmit → Stop → 다음 UserPromptSubmit` 를 임시 DB와 fixture 로 직접 검증
- `memory_chunks` INSERT, FTS trigger, `[Project memory context]` prepend, `/memory search/inject` 확인
- 실패해도 hook 이 세션을 끊지 않는지 확인

#### RAG-3. 읽기 경로 정합성

- 현재 `memory_chunks` 기반 자동 prefill 과 `chunks_v2` 기반 `/retrieve` 의 역할을 명확히 분리
- 단기 문서화: 기본 사용자 RAG는 자동 prefill + `/memory` 검색으로 안내
- 중기 구현: `memory_chunks → chunks_v2` bridge 또는 `/retrieve` 의 legacy fallback 검토

#### RAG-4. 검색 품질 최소 기준

- 한국어 부분일치, pinned 우선순위, chunk_type/source 필터, external source section metadata 를 fixture 로 검증
- "저장됐는데 못 찾는" 문제를 먼저 줄이고, rerank/summary 품질 개선은 그 다음 단계로 둠

#### RAG-5. 외부 source 신뢰성

- URL cap 초과, fetch 실패, stale `fetched_at` 을 사용자에게 보이게 함
- 자동 refresh 보다 stale 표시와 명시 refresh 를 우선

### 후순위 확장

#### Phase 5. Workflow skill

- `/commit-message`, `/pr-draft`, `/recap`, `/handoff`
- git porcelain + memory 결합
- RAG 기본 루프가 안정된 뒤 진입

#### Phase 6. 레지스트리

- GitHub 기반 skill 레지스트리
- `imprint skill add/remove/list/publish`
- manifest.json 포맷 정의
- 로컬 override 우선순위

### 영구 deferred

- Full knowledge graph DB / GraphRAG / HippoRAG 풀스택
- Graph traversal 기반 multi-hop reasoning
- 자동 belief revision 엔진
- 완전 자동 supersede 확정 (사용자 명시만 confirmed)
- Linux/Windows 호환 (요청 시 별도 Phase)

## Tauri 앱 경계

본 repo는 Claude Code plugin 단일 책임입니다. Dev PTY 모드가 필요한 사용자는 SwiftUI 버전 [`MultiAgentCLI`](../MultiAgentCLI)를 사용하고, 신규 LoadMap 기능은 어느 쪽에도 포팅하지 않습니다.

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
- 자동 주입 chunk 수 상한 (primary prefill 8, legacy fallback 5)
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

### 7. events 무한 누적과 노이즈 turn

raw `events` 테이블이 모든 turn 의 사용자 prompt 와 assistant 응답을 무필터로 저장 — "응", "맞아" 같은 backchannel/confirm turn 도 그대로 누적. 직접 영향은 (a) 디스크 단조 증가, (b) 짧은 confirm 에도 사용자가 token / 비밀번호를 붙여 넣으면 위험 1번(민감정보 저장)과 결합해 누출 표면 확대.

학계 표준은 "raw 보존 + soft filter / 감쇠 점수" — MemGPT(virtual context), MemoryBank(Ebbinghaus forgetting curve), Generative Agents(importance × recency × relevance), LongMemEval/LoCoMo(distractor session) 모두 archival vs recall 2-tier 또는 가중 retrieval 기반. imprint 의 `memory_chunks` (LLM 필터) + `events` (raw) 구조는 이 표준에 이미 부합, events tier 에 soft filter 한 겹만 추가하면 됨.

대응:
- **Stage 1 (즉시)**: backchannel rule filter — 정규식 + 길이 + chunk 0 개 동시 만족 시 `events.noise=1` 플래그 (삭제 아님, Yngve/Schegloff 언어학 전통과 부합).
- **Stage 2 (경량)**: forgetting curve — `events.score` 자연 감쇠 + 미접근 노이즈만 cron 으로 hard delete. 의미 있는 raw 는 reinforce 로 영구 보존.
- **Stage 3 (선택, 보류 우세)**: Stop hook LLM 호출에 importance scoring piggyback — `memory_chunks` 가 이미 의미 추출 중이라 ROI 낮음.
- 보류: LLMLingua / recursive summarization (turn 단위 보존 철학과 결이 다름), A-MEM dynamic linking (단일 사용자 규모에서 과잉).

자세한 후보 분석·trade-off·다음 액션·학술 레퍼런스는 `HANDOFF.md` "events 노이즈 누적 갭" 섹션 참조.

## 설계상 병목 후보·대응 플랜

미래 병목으로 발현 가능한 3축을 사전 식별 — A) Stop hook 의 transcript JSONL 재파싱, B) 외부 fetch payload 폭주, C) 동시 백그라운드 부하. 각 축은 `IMPRINT_PROFILE=1` env-gated 계측 hook 이 박혀 있고(평소 OFF, 추가 비용 env 검사 1회), 활성화 시 측정값이 `~/.claude/imprint/profile.jsonl` 에 누적됩니다.

각 축의 무엇/왜/임계점/대안/다음 액션은 `HANDOFF.md` "성능 병목 진단 — 3축" 참조. Phase 7a/7b 의 single-writer ingest queue 가 C축 #3 (단일 writer 큐) 를 자연 흡수해 retrieval ingestion path 는 이미 직렬 commit, 기존 `memory_chunks` 직접 INSERT path 만 진단 대상으로 남음.

```bash
# 측정 활성화
export IMPRINT_PROFILE=1
```

## 우선순위 — 남은 단계

1. **RAG-1 안전한 저장 경로** — redaction coverage 부터 닫기. 민감정보가 raw DB/FTS 로 들어가면 실제 프로젝트 사용이 불가능합니다.
2. **RAG-2 자동 memory loop 검증** — hook 직접 호출 fixture 로 저장·추출·다음 turn prefill 을 확인합니다.
3. **RAG-3 읽기 경로 정합성** — `memory_chunks` 와 `chunks_v2` 가 분리된 현재 구조를 사용자 경로 기준으로 정리합니다.
4. **RAG-4 검색 품질 최소 기준** — 한국어 FTS, pinned, type/source 필터, inject 를 fixture 로 고정합니다.
5. **RAG-5 외부 source 신뢰성** — stale/누락/실패를 관찰 가능하게 만듭니다.
6. **측정 후 캘리브레이션** — latency budget, contradiction 임계, daemon 분리, summary 품질은 1주 데이터 뒤 판단합니다.
7. **후순위 기능 확장** — Workflow skill, registry, entity merge/split UI 는 RAG 기본 동작이 안정된 뒤 진행합니다.

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
