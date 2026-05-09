# imprint — Claude Code plugin

로컬 작업 기억(SQLite + FTS5), advisor orchestration, statusline HUD를 Claude Code의 hook · skill · subagent 시스템으로 제공하는 plugin입니다.

> 이 repo는 `imprint`로 리네임되었습니다. 이전 정체성이었던 Tauri 데스크톱 앱 청사진(코드명 `multi-agent-cli-v2`)과 더 이전 세대 SwiftUI 앱(`MultiAgentCLI`)은 **폐기되었습니다.** 본 repo는 Claude Code plugin 단일 책임을 가집니다. 이전 SwiftUI 앱이 필요하다면 [`MultiAgentCLI`](../MultiAgentCLI) 원본 repo를 참고하세요.

## 무엇을 하는가

| 영역 | 역할 |
|---|---|
| Soul (persona) | `SessionStart` hook이 `<project>/.imprint/soul.md` 내용을 컨텍스트 시작에 prepend. 압축 후에도 `compact` matcher로 자동 재주입 |
| Routing | `UserPromptSubmit` hook이 `<project>/.imprint/UserPromptSubmit.md`의 키워드 → agent 룰을 평가, 매칭 시 권고 메시지 prepend (예: "PR" → `pr-agent` 호출 권고) |
| Memory | 프롬프트·응답·메타데이터를 `~/.claude/imprint/app.sqlite`에 누적, FTS5 기반 검색·pin·자동 주입 (`UserPromptSubmit` hook이 `[Project memory context]` 블록 prepend) |
| Advisor | `codex`, `gemini`를 advisor로 호출하고 `claude -p`로 합성. 각 호출은 `provider_runs`에 기록 |
| HUD | Claude Code statusline에 `5h: 25% (1h 49m) │ wk: 3% (1d 9h) │ ctx: 12% │ skills: 17 │ agents: 1` 형태로 잔여 시간과 활성 plugin의 skills/agents 수 표시 |

## 설치

자세한 절차는 [`INSTALL.md`](INSTALL.md). 요약:

```bash
# 이 repo가 marketplace로 등록되어 있다면
claude plugin marketplace add <this-repo>
claude plugin install imprint@imprint
```

설치 후 Claude Code 세션을 새로 열면 `SessionStart` hook이 SQLite 스키마를 idempotent하게 생성하고 프로젝트 row를 upsert합니다.

statusline 활성화는 별도 단계입니다.

```bash
bash scripts/imprint/hud-setup.sh install         # 기존 statusLine 백업 후 교체
bash scripts/imprint/hud-setup.sh layout focused  # minimal | focused | full
bash scripts/imprint/hud-setup.sh uninstall       # 백업 복원
```

## 사용

### Memory

```bash
imprint memory remember "Claude Code plugin 전환 결정"  # 수동 저장
imprint memory search "PTY 한글 IME"                   # FTS5 검색
imprint memory pin <chunk-id>                          # 우선 노출
imprint memory list --recent --limit 20
```

`UserPromptSubmit` hook이 매 prompt마다 pinned + recent 청크를 `[Project memory context]` 블록으로 자동 prepend합니다.

### Routing (옵션)

`UserPromptSubmit` hook은 `<project>/.imprint/UserPromptSubmit.md`(없으면 plugin defaults)에서 라우팅 표를 읽어 매칭된 권고를 prepend합니다. 본 plugin은 라우팅 룰 markdown을 ship하지 않으므로, 사용하려면 사용자가 다음 형식으로 직접 작성합니다.

```markdown
| 패턴                       | Agent      | 권고 메시지                  |
|---------------------------|------------|------------------------------|
| `\b(PR\|pull\s*request)\b` | pr-agent   | PR 작업 — pr-agent 호출 권장 |
```

작성 시 주의:
- 한국어 키워드엔 `\b` 사용 금지(한글이 word character로 인식되어 boundary 안 잡힘) — 영어 약어에만 `\b`.
- 정규식 alternation `|`는 `\|`로 escape — markdown 셀 구분자와 충돌하기 때문.
- 매칭된 agent가 실제 호출되려면 해당 subagent 정의가 plugin 또는 사용자 영역에 등록돼 있어야 합니다.

### Advisor

`/advisor <질문>` 같이 skill로 호출하면 codex/gemini를 병렬 advisor로 돌리고 합성된 답변을 반환합니다. 단일 advisor만 쓰려면 `--advisor codex` 식으로 지정.

### HUD

statusline은 `hud-setup.sh install` 이후 자동 갱신됩니다. 데이터는 Claude Code가 매 갱신마다 stdin으로 넘기는 세션 JSON(`rate_limits.*.resets_at`, `context_window.used_percentage` 등)을 그대로 사용합니다.

## 구조

```
.claude-plugin/
  plugin.json              플러그인 매니페스트
  marketplace.json         로컬 marketplace entry
hooks/hooks.json           SessionStart / UserPromptSubmit / Stop 등록
skills/
  memory/SKILL.md
  advisor/SKILL.md
  hud/SKILL.md
prompts/defaults/          첫 SessionStart에서 <project>/.imprint/로 시드되는 기본 콘텐츠
  soul.md                  persona·동작 규칙
  hooks/                   Claude Code의 22개 hook 카탈로그(사람용 가이드, OpenClaw 스타일)
scripts/imprint/
  lib/common.sh            DB·project·로그 헬퍼
  lib/schema.sql           SQLite 스키마 (FTS5 trigger 포함)
  session-start.sh         SessionStart hook (DB 보장 + .imprint/ 시드 + soul.md emit)
  user-prompt-submit.sh    UserPromptSubmit hook (라우팅 평가 + 메모리 주입)
  stop.sh                  Stop hook (assistant 응답 archive)
  memory.sh                /memory dispatcher
  advisor.sh               /advisor dispatcher
  hud.sh                   statusline body
  hud-setup.sh             statusLine install/status/uninstall/layout
LifeCycle.md               LLM 턴 생애주기 ↔ Claude Code hook 매핑 + 깊이 있는 카탈로그
```

## 데이터 위치

| 경로 | 내용 |
|---|---|
| `<project>/.imprint/soul.md` | 세션 시작·압축 후 자동 prepend되는 persona·동작 규칙. 사용자 자유 편집. (plugin defaults에서 자동 시드) |
| `<project>/.imprint/UserPromptSubmit.md` | 매 prompt마다 평가되는 키워드 → agent 라우팅 룰. 사용자 자유 편집. |
| `<project>/.imprint/hooks/*.md` | Claude Code의 22개 hook 카탈로그 + 본 plugin이 등록한 hook(✅) 표시. OpenClaw 스타일 짧은 가이드(무엇 / 어떻게 활용 / 간단한 예시 / 주의). Claude Code가 직접 읽진 않는 사람용 참고 문서. |
| `~/.claude/imprint/app.sqlite` | projects · conversations · events · memory_chunks · provider_runs (FTS5 포함) |
| `~/.claude/imprint/plugin.log` | hook · dispatcher 로그 |
| `~/.claude/imprint/previous-statusline.json` | hud-setup install 시 백업된 이전 statusLine 설정 |

`.imprint/` 폴더는 SessionStart hook이 처음 실행될 때 자동 생성되며 기존 파일은 절대 덮어쓰지 않습니다. 시드를 막고 싶다면 `IMPRINT_NO_SEED=1` 환경 변수를 설정하세요.

## 의존

- `bash`, `python3`, `sqlite3`, `uuidgen` (macOS 기본 포함)
- 사용할 provider CLI(`claude`, `codex`, `gemini`)는 별도 설치·인증 필요

## 계획된 확장: 사내 컨텍스트 ingestion

> ⚠️ 아래 흐름은 **Ouroboros 인터뷰로 합의된 설계 (미구현)**. iOS 팀의 사내 프로젝트 컨텍스트(Slack 대화, Notion 기획 정의서)를 메모리에 흡수해 prefill 단계에서 LLM에 자동 보강하는 다음 단계입니다.

### 흐름 한 장 요약

```
유저 prompt
  ↓
UserPromptSubmit hook
  ├─ 1. 매번 claude -p 호출 → 모호도 점수 + 키워드 추출
  ├─ 2. 키워드로 .imprint/sources.json의 Slack 채널·Notion 페이지 lazy fetch
  ├─ 3. fetched 청크 + 기존 memory_chunks를 [Project memory context]에 prepend
  └─ 4. 모호도 임계치 초과 시 [Refined prompt suggestion: ...] 블록 추가 prepend
  ↓
Claude (메인 응답)
  ↓
Stop hook
  └─ claude -p로 응답에서 decision/error/fix/todo/code_context chunk 자동 추출 → memory_chunks 누적
```

### 핵심 결정사항 (인터뷰 산출)

| # | 항목 | 결정 |
|---|------|------|
| 1 | 사용 시나리오 | iOS 팀 BYO 로컬 + 프로젝트별 메모리 분리 (서버 미사용) |
| 2 | "다듬기" 정의 | 평소 컨텍스트 prepend, 모호 감지 시 refined prompt suggestion 블록 추가 |
| 3 | 사용자 가시성 | 자동 움직임(silent), suggestion이 컨텍스트에 표시 |
| 4 | Rewrite 메커니즘 | hook은 prompt 자체 교체 불가 → suggestion 블록 prepend로 우회 |
| 5 | Ingestion 트리거 | Lazy fetch (prefill 시점 on-demand, 메모리 누적은 사용자 체감 없게) |
| 6 | Source 정의 위치 | `<project>/.imprint/sources.json` (git-share 가능) |
| 7 | 모호도 + 키워드 추출 | 매 prompt마다 claude -p 호출 (정확도 우선) |
| 8 | Stop hook 처리 | claude -p로 LLM 응답에서 chunk 자동 추출 + events archive |
| 9 | First milestone scope | 전체 파이프라인 + Slack/Notion/소스 없음 모두 graceful degradation |

### 메모리 저장 방식 (D10–D13)

기존 SQLite schema (`scripts/imprint/lib/schema.sql`)를 **DDL 변경 없이** 그대로 사용합니다. 외부 소스 청크는 다음 규칙으로 들어갑니다.

| # | 결정 | 내용 |
|---|------|------|
| D10 | 출처 표시 위치 | `memory_chunks.metadata_json`에 `source` 필드. 새 chunk_type·새 컬럼 추가 없음 |
| D11 | events 테이블 포함 | **Skip** — 외부 소스는 `memory_chunks`에만 직접 insert (`source_event_id IS NULL`). events는 user/LLM/hook/skill 자체 I/O 전용 의미 보존 |
| D12 | chunk_type 분류 | claude -p가 기존 9개(`decision`/`error`/`fix`/`command`/`test_result`/`summary`/`todo`/`code_context`/`note`) 중 자유 선택. 소스별 후보군 분기 없음 |
| D13 | metadata 표준 필드 | 공통 `source`·`url`·`fetched_at` + Slack `channel`·`author`·`posted_at` / Notion `page_id`·`page_title`·`section_title` |

`memory_chunks.metadata_json` 예시 (Slack 메시지):

```json
{
  "source": "slack",
  "url": "https://team.slack.com/archives/C0123/p1709876543",
  "channel": "#ios-payment",
  "author": "@kim",
  "posted_at": "2026-04-20T14:23:00+09:00",
  "fetched_at": "2026-05-08T15:14:00+09:00"
}
```

Notion 섹션:

```json
{
  "source": "notion",
  "url": "https://www.notion.so/...",
  "page_id": "a1b2c3d4-payment-prd",
  "page_title": "Payment PRD v3",
  "section_title": "결제 흐름 / 3DS 처리",
  "fetched_at": "2026-05-08T15:14:00+09:00"
}
```

### `.imprint/sources.json` 형식 (예정)

```json
{
  "slack": {
    "channels": ["#ios-payment", "#ios-bugs"]
  },
  "notion": {
    "pages": ["a1b2c3d4-payment-prd"]
  }
}
```

파일이 없거나 일부 소스만 정의돼 있어도 plugin은 동작합니다 — 누락된 소스는 silent skip, claude -p 실패 시도 fallback으로 기존 prepend만 수행합니다 (graceful degradation).

### 비용·실패 모드

매 user-LLM 사이클마다 claude -p가 두 번 추가됩니다 (prefill 분석 1회 + stop chunk 추출 1회). OAuth 구독으로 비용은 잡히지만 latency 1-3초가 누적되므로:

- claude -p 실패 → silent fail, 기존 컨텍스트 prepend만 진행
- Slack MCP 다운 → 해당 소스만 skip, Notion·기존 memory는 그대로
- Notion 페이지 인증 만료 → 동일 패턴

### 검색 인프라 (D16–D18)

first milestone은 **SQLite FTS5만** 사용합니다. 단 한국어 형태 변화·부분문자열 매칭을 보강하기 위해 tokenizer를 `trigram`으로 변경합니다 (`tokenize='trigram'`). SessionStart hook은 기존 인덱스가 `unicode61`이면 DROP + REBUILD migration을 수행합니다 (AC10).

claude -p가 chunk 추출 시 응답 schema에 `keywords: string[]`을 포함시켜 한·영 동의어를 함께 보존합니다 (`metadata_json.keywords`). prefill 검색은 FTS5 MATCH + keywords 배열 hit을 union으로 묶어 ranking합니다 (AC11).

**Vector DB는 Phase 2 후순위** — chunk 누적이 수천 단위에 도달 + FTS5(trigram) 한계가 실증된 뒤 `sqlite-vec` extension + 로컬 임베딩 모델(Ollama 또는 sentence-transformers)을 추가합니다. 임베딩 생성은 chunk insert 시 비동기 background로.

**PageIndex 스타일 reasoning-based tree retrieval은 비채택** — Slack 단편·짧은 Notion 섹션은 트리 navigation의 가정(장문 구조화 단일 자료)과 맞지 않고, 매 prefill에서 트리 navigate LLM 호출이 추가되면 OAuth rate-limit 위험이 큽니다. Notion 구조는 metadata의 `page_id` + `section_title`로 path만 보존해 후일 트리 reconstruct는 가능성으로 둡니다.

### 팀 멤버 간 메모리 공유 (D14–D15)

기본은 **격리** — `~/.claude/imprint/app.sqlite`는 멤버별 로컬 only이고, `<project>/.imprint/sources.json`만 git-share합니다. 신규 멤버가 합류해 sources.json만 git pull로 받아도 lazy fetch가 외부 source-of-truth(Slack/Notion)에서 컨텍스트를 자연 재구성하므로 모호 prompt 흐름이 동일하게 동작합니다 (AC9).

LLM 응답에서 Stop hook이 추출한 내부 chunk(decision/todo/fix 등)는 작성자의 작업 기억으로 두고 자동 공유하지 않습니다 — chunk엔 디버그 출력·코드 fragment·외부 API 응답이 섞여 있어 자동 push가 위험합니다.

**Migration (후순위 milestone)**: 휴가자 인계·신규 멤버 합류 같은 의식적 순간을 위해 `/memory export <project>` → JSON dump, `/memory import <file>` → 수동 검토 후 적용을 후속 milestone에서 추가합니다. redaction은 export 시점 사용자 책임이며 자동 git commit은 절대 없습니다.

### 운영 변수 · 외부 인터페이스 (D19–D21)

- **D19 — claude -p 모델**: 모호도 분석(prefill)·chunk 추출(stop)·Slack thread reply selection 모두 **Haiku** (`claude -p --model haiku`). 메인 응답만 Sonnet
- **D20 — Slack lazy fetch 두 모드 공존**:
  - **URL 명시**: prompt에 Slack permalink 감지 시 즉시 fetch. **thread permalink** → 전체 reply paginated fetch 후 claude -p가 prompt 관련 reply만 selection + summary → 1~3 chunk. **single message permalink** → 1 chunk
  - **키워드 검색**: URL 없을 때만 `.imprint/sources.json` 채널에서 매칭
- **D21 — Notion fetch**: 사용자 환경의 **Notion MCP** 사용 (마크다운 다운로드 파일 의존 없음). 페이지 URL 또는 `page_id`로 fetch, 섹션 단위 chunk화

### Lazy fetch 캐시 (D22–D24)

- **D22 — dedup**: 외부 소스 chunk의 dedup key는 `metadata_json.url`. 이미 존재하는 url은 fetch API 호출 자체를 **skip** (Slack/Notion 트래픽 0). 기존 chunk가 prefill 검색에 자연 hit
- **D23 — timestamp 보존**: Notion `last_edited_at` (API 응답 그대로), Slack `edited_at` (수정된 경우만). 현재는 stale 감지 미사용, 미래 활용 위해 보존
- **D24 — force-refresh**: TTL 무한, 자동 갱신 없음. 사용자 명시 명령만:
  - `/memory refresh <url>` — 단일 URL chunk 갱신
  - `/memory refresh source slack|notion` — 소스 전체 갱신
  - `/memory refresh project` — 외부 소스 chunk 전체 갱신
  - 동작: 대상 chunk DELETE → 재 fetch → INSERT (덮어쓰기). history는 Slack/Notion 원본이 source-of-truth

### Seed (결정 동결)

위 결정사항(D1–D24)은 [`.ouroboros/seeds/context-ingestion.yaml`](.ouroboros/seeds/context-ingestion.yaml)에 immutable Seed YAML로 결정화되어 있습니다 (goal · constraints · 17개 acceptance_criteria · ontology_schema · 24개 decisions · evaluation_principles · risks · deferred_topics). 구현 단계에서 이 spec과 drift가 발생하면 README와 함께 명시적으로 update합니다.

**Deferred (다음 인터뷰 라운드 후보):**
- chunk lifecycle (dedup·자동 pin·ranking 가중치)
- 보안·운영 (redaction 정규식·log 회전·에러 알림)

## 진행 상황·로드맵

- 구현 상세와 다음 작업: [`HANDOFF.md`](HANDOFF.md)
- 단계별 방향: [`LoadMap.md`](LoadMap.md)
- LLM 턴 생애주기와 Claude Code hook 활용 카탈로그: [`LifeCycle.md`](LifeCycle.md)
