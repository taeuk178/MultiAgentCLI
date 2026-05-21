# LifeCycle — LLM 턴 생애주기와 Claude Code Hook 매핑

이 문서는 LLM 한 턴이 어떤 단계를 거치는지(LLM lifecycle)와, 각 단계마다 Claude Code가 노출하는 hook을 어떻게 활용할 수 있는지 정리한다. 메커니즘 / 동작 / 한계 순서로 적는다.

> 본 문서의 hook 페이로드 필드와 동작은 공식 docs(<https://code.claude.com/docs/en/hooks>) 기준이지만, 실제 페이로드는 Claude Code 버전에 따라 달라질 수 있다. 새 hook을 작성할 땐 stdin을 임시 파일로 캡처해 직접 확인하는 것을 권장한다.

---

## 1. LLM 턴 생애주기

한 번의 사용자 입력이 모델 응답으로 이어지는 사이에는 다음 단계가 있다.

```
[세션 시작]
  ├─ 환경 로드, 시스템 프롬프트 구성, 사전 컨텍스트 주입
  ▼
[사용자 입력 도착]
  ├─ 입력 검증, 컨텍스트 prepend, 외부 정보 fetch
  ▼
[모델 입력 조립]
  ├─ 시스템 + 메모리 + 도구 정의 + 사용자 메시지
  ▼
[모델 추론]
  ├─ 텍스트 생성 + 도구 호출 결정
  ▼
[도구 실행 사이클 (반복)]
  ├─ 권한 평가 → 도구 실행 → 결과 캡처 → 모델로 환류
  ▼
[응답 종료]
  ├─ 사용자에게 출력 노출, 후처리(저장/포맷/알림)
  ▼
[다음 입력 대기 또는 세션 종료]
  ├─ 압축, 백업, 리소스 정리
```

각 단계에 부착할 수 있는 Claude Code hook이 다르다. hook은 본질적으로 **표준 입력으로 JSON을 받고 표준 출력/종료 코드로 다음 흐름을 통제하는 외부 프로세스**다.

---

## 2. 단계 ↔ Hook 매핑 한눈에 보기

| LLM lifecycle 단계 | 부착 가능한 hook |
|---|---|
| 세션 시작 / 재개 / 압축 후 재로드 | `SessionStart`, `InstructionsLoaded` |
| 사용자 프롬프트 도착 직후 | `UserPromptSubmit` |
| 도구 호출 직전 | `PreToolUse`, `PermissionRequest` |
| 도구 호출 직후 | `PostToolUse`, `PostToolUseFailure`, `PostToolBatch` |
| Subagent 생애주기 | `SubagentStart`, `SubagentStop` |
| 응답 완료 후 (대기 진입) | `Stop` |
| 컨텍스트 압축 전후 | `PreCompact`, `PostCompact` |
| 환경 변화 (cwd / 설정 / 파일) | `CwdChanged`, `ConfigChange`, `FileChanged` |
| MCP 사용자 입력 요청 | `Elicitation`, `ElicitationResult` |
| 알림 / 작업 완료 / 세션 종료 | `Notification`, `TaskCompleted`, `SessionEnd` |

---

## 3. Hook 상세 카탈로그

각 hook은 **메커니즘 / 동작 통제 / 한계 / 플러그인 활용 사례** 4축으로 정리한다.

### 3.1 세션 진입 / 종료

#### `SessionStart`

- **메커니즘**: 세션이 처음 열리거나, `--resume`으로 재개되거나, `/clear`로 초기화되거나, 컨텍스트 압축 직후에 한 번 실행. 페이로드의 `matcher` 값으로 어떤 경로인지 구분(`startup | resume | clear | compact`).
- **동작 통제**: stdout으로 출력한 텍스트는 시스템 프롬프트 직후 컨텍스트로 들어간다. exit 0이면 silent, exit 2이면 stderr를 사용자에게 보여주되 세션은 진행. `CLAUDE_ENV_FILE` 환경 변수가 주어지므로 거기 export 문을 적으면 이후 모든 Bash 호출에 환경 변수가 전파된다.
- **한계**: streaming 컨텍스트가 아니므로 stdout이 너무 크면 잘릴 수 있다. 기본 동기 실행이라 무거운 작업은 세션 시작 자체를 지연시킨다 — `"async": true` 옵션으로 백그라운드화 가능.
- **활용**: SQLite 스키마 idempotent 적용(현재 `scripts/imprint/session-start.sh`), 프로젝트 row upsert, direnv 환경 로드, 압축 후 핵심 컨텍스트 재주입.

#### `SessionEnd`

- **메커니즘**: 사용자 종료 / 타임아웃 / 수동 stop으로 세션이 종료될 때 한 번 실행.
- **동작 통제**: 종료를 막을 수는 없다. exit 2는 stderr만 노출.
- **한계**: 세션이 이미 닫히는 중이라 응답을 추가로 모델에 보내거나 사용자에게 인터랙션을 강제할 수 없다.
- **활용**: 대화 아카이브, 외부 분석 시스템에 로그 업로드, OS 알림.

### 3.2 사용자 입력 단계

#### `UserPromptSubmit`

- **메커니즘**: 모든 사용자 메시지가 모델로 가기 직전에 실행. 매 턴 동기 실행.
- **동작 통제**:
  - exit 0 → 통과
  - exit 2 → 차단 + stderr 표시
  - JSON 출력으로 `{"decision": "block", "reason": "..."}`을 돌려보내면 사용자에게 reason을 보여주며 차단
  - JSON 출력의 `additionalContext`로 모델 입력에 주입 가능 (현재 imprint 플러그인은 stdout 직접 출력 방식으로 `[Project memory context]` 블록을 prepend)
- **한계**: 매 턴 실행되므로 비용/지연이 누적된다. 사용자에게 "주입이 일어났다"는 가시적 표시가 없으므로 디버깅이 까다롭다. matcher가 없어서 모든 prompt에 무조건 걸린다.
- **활용**: 메모리 컨텍스트 자동 주입, 민감 명령어 검출 후 차단, 현재 git branch · 환경 정보 주입, 플러그인 강제 directive 주입(시스템 프롬프트 대용).

### 3.3 도구 호출 사이클

#### `PreToolUse`

- **메커니즘**: 도구 호출이 결정된 직후, 권한 평가 직전에 실행. matcher로 도구명 필터링(`Bash`, `Edit`, `Write` 등). 페이로드에 `tool_name`, `tool_input` 포함.
- **동작 통제**:
  - exit 0 → 진행
  - exit 2 → 거부
  - JSON 출력의 `hookSpecificOutput.permissionDecision`으로 `allow | deny | ask | defer` 결정
  - `hookSpecificOutput.updatedInput`으로 도구 입력 수정 가능 (예: 위험 인자 strip)
- **한계**: `bypassPermissions` 모드도 우회해 적용된다 — 이 점은 보안 측면에서 강점이지만, 자동화 워크플로에서 의도치 않게 막힐 수 있다.
- **활용**: 파괴적 명령(`rm -rf`, `dd`, force-push) 자동 차단, 실행 전 명령 로깅, 정책에 따라 인자 변형.

#### `PostToolUse` / `PostToolUseFailure`

- **메커니즘**: 도구 실행 직후(성공/실패) 실행. 페이로드에 `tool_output` 또는 `error` 포함.
- **동작 통제**: 도구는 이미 실행됐으므로 결과를 되돌릴 수 없다. JSON으로 `{"decision": "block"}`을 돌려보내면 도구 출력을 모델 시야에서 가릴 수 있고, `additionalContext`로 추가 정보 주입 가능.
- **한계**: 재실행 / 롤백 불가. 출력을 모델에서만 숨길 뿐 디스크 변경은 그대로.
- **활용**: 코드 자동 포맷(prettier, black), 빌드/테스트 자동 트리거, 실패 통계 수집, 같은 명령 반복 실패 시 사용자 알림.

#### `PostToolBatch`

- **메커니즘**: 한 모델 응답이 발행한 모든 병렬 도구 호출이 resolve된 직후, 다음 모델 호출 전에 실행.
- **동작 통제**: exit 2 또는 `decision: "block"`으로 다음 모델 호출을 막고 reason을 모델에 환류 가능.
- **한계**: 개별 도구 단위 제어는 `PreToolUse`/`PostToolUse`로만 가능. 배치 단위 일관성 검증에만 적합.
- **활용**: 같은 턴에서 발생한 여러 파일 수정의 일관성 검증(예: schema 변경 + migration 동시 수정 강제).

#### `PermissionRequest` / `PermissionDenied`

- **메커니즘**: 권한 다이얼로그가 떠야 할 때(`PermissionRequest`) 또는 자동 모드 분류기가 거부했을 때(`PermissionDenied`) 실행.
- **동작 통제**: JSON으로 `decision.behavior` (`allow | deny | ask`) 반환. `PermissionDenied`는 `{"retry": true}`로 재시도 신호를 보낼 수 있다.
- **한계**: `claude -p` 같은 비대화 모드에서는 `PermissionRequest`가 발생하지 않으므로, 자동화 워크플로에는 `PreToolUse`를 써야 한다.
- **활용**: 안전 명령 자동 승인(예: `git status`, `git diff`만 자동 allow), 정책 위반 패턴 알림.

### 3.4 응답 종료 단계

#### `Stop`

- **메커니즘**: 모델이 응답을 마치고 다음 사용자 입력을 기다리기 직전에 실행.
- **동작 통제**: JSON으로 `{"decision": "block", "reason": "..."}`를 돌려보내면 모델이 멈추지 않고 reason을 받아 작업을 이어간다 — auto-continuation 패턴.
- **한계**: streaming 응답을 보지 못한다. 응답 완료 후 시점이라 본문 검증/수정은 불가.
- **활용**: 응답에서 chunk_type 추출 후 `memory_chunks` 적재(현재 imprint 플러그인은 `stop.sh`에서 raw 저장만 함, 추출은 phase 3 잔여 작업), 작업이 미완으로 보이면 자동 재요청, transcript에서 결정사항 추출.

### 3.5 Subagent 생애주기

#### `SubagentStart` / `SubagentStop`

- **메커니즘**: Agent 도구로 subagent가 spawn되거나 종료될 때 실행. 페이로드에 `agent_id`, `agent_type` 포함.
- **동작 통제**: `SubagentStart`는 exit 2로 spawn 차단 가능, `SubagentStop`은 결과 후처리만.
- **한계**: agent에게 instruction을 주입하거나 결과를 수정할 수는 없다. 시작/끝 신호만 받는다.
- **활용**: 동시 agent 수 rate limit, agent 실행 타임라인 로깅, agent 결과 자동 archiving, 외부 모니터링 시스템 연동.

### 3.6 컨텍스트 압축

#### `PreCompact` / `PostCompact`

- **메커니즘**: 컨텍스트 압축 직전(`manual | auto`) / 직후 실행. 압축 사유가 페이로드에 포함.
- **동작 통제**: `PreCompact`는 exit 2로 압축 차단 가능. `PostCompact`는 `additionalContext`로 핵심 컨텍스트 재주입 가능.
- **한계**: 압축 알고리즘 자체는 통제 불가. 어떤 청크가 살아남을지 선택할 수 없다.
- **활용**: 압축 전 transcript 백업, 압축 후 pinned memory 재주입(`SessionStart matcher: "compact"`와 묶어서 사용).

### 3.7 환경 변화

#### `CwdChanged`

- **메커니즘**: 모델이 `cd`를 실행하거나 cwd가 바뀔 때마다 실행.
- **동작 통제**: `CLAUDE_ENV_FILE`에 export 문을 적어 환경 변수 갱신 가능.
- **한계**: matcher 없음, 모든 cd에 걸린다.
- **활용**: direnv·nvm·pyenv 자동 reload, 프로젝트 진입 시 SQLite project row 갱신.

#### `ConfigChange`

- **메커니즘**: settings/skills/rules 파일이 외부에서 변경될 때 실행.
- **동작 통제**: exit 2로 reload 차단(파일 자체는 이미 디스크에 쓰여 있음). JSON으로 `decision: "block"`과 reason 반환.
- **한계**: 디스크 변경을 되돌리지 못한다 — reload만 막는다.
- **활용**: 무단 정책 수정 감사 로깅, 설정 syntax pre-validation.

#### `FileChanged`

- **메커니즘**: matcher로 지정한 파일이 디스크에서 바뀔 때 실행.
- **동작 통제**: `CLAUDE_ENV_FILE`로 환경 갱신 가능.
- **한계**: matcher가 정규식이 아닌 리터럴 파일명만 받는다(예: `.envrc|.env`처럼 OR로 나열). 디렉토리 패턴 watch는 못 한다.
- **활용**: `.env` 변경 시 환경 자동 reload, 설정 파일 동기화.

### 3.8 MCP 상호작용

#### `Elicitation` / `ElicitationResult`

- **메커니즘**: MCP 서버가 사용자 입력을 요청할 때(`Elicitation`) / 사용자가 응답을 보낸 직후(`ElicitationResult`) 실행.
- **동작 통제**: `Elicitation`은 JSON으로 `input`을 반환해 사용자 대신 자동 응답 가능. `ElicitationResult`는 응답 검증/필터링.
- **한계**: MCP 서버가 발신한 prompt 자체를 수정하거나 막을 수는 없다.
- **활용**: 반복적인 동의 prompt 자동 응답, 민감 정보 응답 차단.

### 3.9 알림 / 메타

#### `Notification`

- **메커니즘**: 권한 prompt, idle, auth 성공 등 시스템 알림이 발생할 때 실행.
- **동작 통제**: 차단 불가. exit 2는 stderr만.
- **한계**: 알림 내용 수정 불가.
- **활용**: macOS `osascript` 데스크톱 알림, 슬랙 push, 사운드 알람.

#### `InstructionsLoaded`

- **메커니즘**: `CLAUDE.md`나 `.claude/rules/*.md`가 컨텍스트에 로드될 때마다 실행. 세션 시작·nested traversal·lazy load·include·**압축 직후** 모두에서 발생 (`reason` 필드로 구분: `session_start | nested_traversal | path_glob_match | include | compact`).
- **동작 통제**: exit 2로 로드 차단 가능(파일이 컨텍스트에 들어가지 않음).
- **한계**: 파일 내용 자체를 수정할 수 없다 — 통째로 allow/block만.
- **활용**: 어떤 instruction이 활성됐는지 감사, 민감 rule 필터.
- **압축 내성에 관한 함의**: `reason="compact"` 발화가 존재한다는 사실 자체가, Claude Code가 압축 직후 CLAUDE.md를 자동 재첨부함을 시사한다. 즉 `SessionStart` hook stdout과 달리 CLAUDE.md 콘텐츠는 plugin이 별도 재주입 hook을 등록하지 않아도 압축 후 다시 컨텍스트에 들어온다. plugin이 강제하는 persona는 SessionStart로 직접 발화시키는 게 좋고, 사용자 자유 영역의 규칙은 CLAUDE.md에 두는 분업이 자연스럽다.

#### `TaskCompleted` (Experimental)

- **메커니즘**: Claude Code UI에서 task/checklist 항목이 완료 처리될 때 실행.
- **동작 통제**: exit 2로 완료 차단 가능.
- **한계**: 실험 단계, 페이로드/이름이 향후 변경될 수 있다.
- **활용**: 외부 PM 도구 동기화(Linear, Notion), 메트릭 집계.

---

## 4. 플러그인 활용 패턴

### 4.1 "강제 시스템 프롬프트" 흉내 — `SessionStart` + markdown

진짜 시스템 프롬프트 필드는 plugin spec에 없다. 가장 유사한 효과는 `SessionStart` hook이 markdown 파일 하나를 stdout으로 emit하는 패턴이다. `.sh` 스크립트가 사실상 `cat` 한 줄이라 사용자는 markdown만 편집하면 persona가 바뀐다 (OpenClaw의 SOUL.md 컨벤션과 거의 동등한 경험).

```json
// hooks/hooks.json — matcher에 startup|resume|clear|compact 모두 포함
{
  "SessionStart": [{
    "matcher": "startup|resume|clear|compact",
    "hooks": [{
      "type": "command",
      "command": "cat \"$CLAUDE_PLUGIN_ROOT\"/prompts/defaults/soul.md"
    }]
  }]
}
```

본 plugin은 더 나아가서 **plugin defaults를 사용자 영역으로 한 번 시드**한다 — 첫 SessionStart에서 `<project>/.imprint/soul.md`로 복사하고, 이후엔 사용자 편집을 우선 사용한다. 사용자 입장에선 `.imprint/soul.md`만 편집하면 되고, plugin 업데이트로 defaults가 바뀌어도 사용자 편집이 보존된다.

장단점:
- ✅ 토큰 소모는 세션당 1회 + 압축마다 1회
- ✅ "markdown만 편집하면 동작"이라는 직관성
- ⚠️ 일반 대화 메시지로 들어가므로 모델 attention이 약해질 수 있음 — 강한 단일 규칙(예: "한국어 응답")은 `UserPromptSubmit`에 짧게 더 두는 하이브리드가 안전
- ⚠️ 모델이 거부 가능 — 시스템 프롬프트가 아니라 "권고"

`UserPromptSubmit` 단독으로 매 턴 prepend하는 방식은 토큰이 누적되고 attention 집중이 강하지만, 정적 persona에는 과한 비용이다. 동적 컨텍스트(메모리 청크, git branch, 시간) 주입에만 사용하는 게 권장 패턴.

### 4.2 키워드 → agent 라우팅 — `UserPromptSubmit` + markdown 표

`UserPromptSubmit`에서 prompt 텍스트를 정규식 표와 매칭해, 매칭된 행의 권고 메시지를 prepend한다. plugin은 권고만 할 수 있고 실제 `Agent` tool 호출은 모델이 결정한다 — 강제는 불가, 강한 권고만 가능.

```markdown
| 패턴                       | Agent      | 권고 메시지                                  |
|---------------------------|------------|----------------------------------------------|
| `\b(PR\|pull\s*request)\b\|풀\s*리퀘스트` | pr-agent   | PR 작업으로 보입니다. pr-agent 호출 권장.    |
| `\bcommit\b\|커밋`        | commit-agent | 커밋 작업으로 보입니다. commit-agent 호출 권장. |
```

본 plugin은 `<project>/.imprint/UserPromptSubmit.md`에 이 표를 두고, `scripts/imprint/user-prompt-submit.sh`가 표를 파싱해 매칭된 행만 prepend한다.

함정:
- markdown 표 안에서 정규식 alternation `|`은 `\|`로 escape 필요 (셀 구분자와 충돌)
- 한국어 키워드에 `\b`(word boundary) 사용 금지 — Python `re` 가 한글을 word character로 봐서 "커밋해줘"의 끝 boundary를 인식하지 못함. 한국어는 boundary 없이 substring 매칭 권장
- 매 turn 평가되어 토큰을 소모하므로 룰 수는 적게 유지

### 4.3 메모리 자동 적재 → 자동 주입 사이클

```
UserPromptSubmit  →  events 테이블에 user_input 저장 + pinned/recent 청크를 컨텍스트로 prepend
       ↓
PostToolUse       →  도구 결과(파일 변경, bash 출력)에서 의미 있는 청크 추출
       ↓
Stop              →  마지막 assistant 응답에서 결정/오류/명령 청크 추출 후 memory_chunks 적재
       ↓
SessionStart      →  새 세션이 열리면 위에서 쌓인 메모리가 다시 prepend됨
```

### 4.4 컨텍스트 압축 안전망

`PreCompact`에서 transcript 백업 → 압축 진행 → `PostCompact`에서 pinned memory와 핵심 결정사항을 `additionalContext`로 재주입 → `SessionStart`(matcher=compact)에서 추가 환경 컨텍스트 보강.

### 4.5 안전 가드

`PreToolUse`에 정규식 기반 차단 룰셋(`rm -rf`, `git push --force` to main, secret-looking string echo 등)을 두면 권한 모드와 무관하게 막을 수 있다. 단, 이 hook 자체가 깨지면 모든 도구 호출이 막히므로 — 실패해도 절대 exit 1로 끝내지 말고, 오류 시엔 silent allow하도록 방어 코딩.

---

## 5. Hook 작성 시 공통 주의

1. **세션을 끊지 마라** — 어떤 hook도 사용자 세션 흐름을 막아선 안 된다. 예외가 발생하면 stderr에만 적고 exit 0으로 빠진다(`set -e`보다는 `|| true` 폴백).
2. **stdout은 컨텍스트로 들어간다** — 디버그 print를 stdout에 흘리면 모델 입력이 오염된다. 디버그는 stderr 또는 별도 로그 파일로.
3. **stdin을 한 번에 다 읽어라** — 여러 번 read 시도하면 빈 페이로드를 받는다. `INPUT=$(cat)` 한 번이 안전.
4. **타임아웃을 가정하라** — 동기 hook이 오래 걸리면 Claude Code가 죽인다. 외부 호출은 `timeout 5s` 등으로 감싼다.
5. **실제 페이로드는 캡처해서 확인하라** — 새 hook 작업 시 임시로 `printf '%s' "$INPUT" > /tmp/<event>-last.json`을 한 번 흘려 실제 필드를 본 뒤 처리 코드를 짠다. 작업이 끝나면 캡처 라인은 반드시 제거.

---

## 6. 참고

- 공식 hooks reference: <https://code.claude.com/docs/en/hooks>
- Plugin reference: <https://code.claude.com/docs/en/plugins-reference>
- 본 plugin이 실제로 등록한 hook: `hooks/hooks.json`
- 본 plugin이 실제로 사용하는 hook script: `scripts/imprint/{session-start,user-prompt-submit,stop}.sh`
- 사용자 편집 영역(자동 시드): `<project>/.imprint/{soul.md,UserPromptSubmit.md}`
- plugin defaults(소스 진실): `prompts/defaults/{soul.md,UserPromptSubmit.md}`
