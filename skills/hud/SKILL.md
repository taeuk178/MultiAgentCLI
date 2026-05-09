---
name: hud
description: Customize the imprint statusline HUD via natural language. Use when the user asks to change HUD fields (e.g. "HUD에 cost 추가", "HUD 5h만 보이게", "HUD 켜줘", "HUD 어떤 옵션 있어?"). Translates the request into hud-setup.sh commands; asks for clarification with AskUserQuestion only when truly ambiguous.
level: 2
---

# Imprint HUD

`scripts/imprint/hud.sh`가 statusline body를 출력하고, `scripts/imprint/hud-setup.sh`가 그 동작을 설정하는 dispatcher입니다. 이 skill의 역할은 사용자가 HUD 필드 구성을 빠르게 바꿀 수 있게 해주는 것입니다.

## 호출 흐름 — 두 갈래

이 skill이 호출됐을 때 첫 단계에서 갈래를 결정하세요.

### A. 자연어 요청에 매핑이 있으면 즉시 실행

사용자가 "HUD에 cost 추가", "HUD 5h만", "HUD 꺼줘" 같이 의도를 명시했으면 **아래 매핑 표를 보고 바로 dispatcher 명령을 실행**하세요. 옵션 질문을 다시 던지지 마세요. 실행 후 결과 한 줄과 재시작 안내만 보고.

### B. 의도가 모호하면 곧장 12 필드 선택 wizard 시작

사용자가 단순히 "/imprint:hud", "HUD 커스텀해줘", "HUD 바꿔줘"처럼 어떤 필드인지 단서 없이 호출하면, **"기본 유지/풀스펙/직접 고르기" 같은 메타 옵션을 만들지 말고** 곧장 `AskUserQuestion`으로 12 필드 multiSelect를 호출하세요. AskUserQuestion은 옵션 4개 제한이 있으니 아래 3개 질문 그룹으로 묶고, **세 그룹을 같은 한 번의 AskUserQuestion 호출**에 `questions` 배열로 함께 보내야 사용자가 한 번에 답할 수 있습니다. 따로 호출하면 사용자가 3 turn을 대기.

```
질문 1 (multiSelect, 4개): rate/context 그룹
  - 5h    : 5시간 rate limit %(used) + 잔여 시간
  - wk    : 7일 rate limit %(used) + 잔여
  - ctx   : 컨텍스트 윈도우 사용 %
  - tokens: 입력+출력 토큰 / 컨텍스트 크기

질문 2 (multiSelect, 4개): 모델/세션/시간 그룹
  - model : 모델 표시명 (Opus 등)
  - effort: reasoning effort + thinking 플래그
  - style : output style 이름
  - dur   : 세션 wall-clock 경과 시간

질문 3 (multiSelect, 4개): 비용/skills/시각 그룹
  - cost  : 세션 추정 비용 USD
  - skills: 로드된 skill 파일 수
  - agents: 로드된 agent 파일 수
  - time  : 현재 시각 HH:MM
```

질문 직전에 **현재 활성 필드**(`hud-setup.sh fields list`)를 한 줄로 보여줘서 사용자가 무엇이 켜져 있는지 인지하고 답하게 하세요. 예: "현재: `5h ctx time`. 새로 고르세요."

세 답이 모이면 합쳐 `bash hud-setup.sh fields set <id1> <id2> ...`로 통째 덮어쓰고 적용 결과 한 줄 + 재시작 안내. 표시 순서는 사용자가 선택한 순서가 아니라 **`5h, wk, ctx, tokens, model, effort, style, dur, cost, skills, agents, time`**의 캐논 순서로 정렬해 set하면 시각적으로 가장 자연스럽습니다.

### Scope 처리

사용자 요청에 "이 프로젝트만", "여기서만", "여기만"이 포함되면 모든 dispatcher 호출에 `--project` 플래그를 붙이세요. 명시 없으면 user scope.

## 사용자 요청 → 명령 매핑 (갈래 A에서 사용)

| 사용자 요청 | 실행 명령 |
| --- | --- |
| "HUD 켜줘" / "statusline 활성화" | `hud-setup.sh install` |
| "HUD 꺼줘" / "이전 statusline으로 되돌려" | `hud-setup.sh uninstall` |
| "HUD 지금 어떻게 돼 있어?" / "HUD 상태" | `hud-setup.sh status` 와 `hud-setup.sh fields list` |
| "HUD 어떤 필드 있어?" / "옵션 알려줘" | `hud-setup.sh fields list` |
| "HUD에 X 추가" (X가 12개 ID 중 하나) | `hud-setup.sh fields enable X` |
| "HUD에서 X 빼" / "X 숨겨" | `hud-setup.sh fields disable X` |
| "HUD를 X·Y만 보이게" / "X·Y만 띄워" | `hud-setup.sh fields set X Y` |
| "HUD 기본값" / "최소 구성" | `hud-setup.sh fields set 5h ctx time` |
| "HUD 풀스펙" / "다 보여줘" | `hud-setup.sh fields set 5h wk ctx skills agents time` |
| "프리셋 minimal/focused/full" | `hud-setup.sh layout <name>` (backward-compat) |

## 가용 필드 12개

사용자가 모르는 ID를 말하면 (예: "사용량 보여줘", "토큰 카운트") 아래 표를 참조해서 가장 가까운 ID로 매핑하세요.

| ID | 표시 형태 | 의미 |
| --- | --- | --- |
| `5h` | `5h: 25% (1h 49m)` | 5시간 rate limit 사용률 + reset 잔여 |
| `wk` | `wk: 3% (1d 9h)` | 7일 rate limit 사용률 + reset 잔여 |
| `ctx` | `ctx: 12%` | 컨텍스트 윈도우 사용 % |
| `tokens` | `tok: 24k/200k` | 입력+출력 토큰 / 컨텍스트 크기 |
| `model` | `Opus` | model.display_name |
| `effort` | `effort: high+thk` | reasoning effort + thinking 플래그 |
| `style` | `style: explanatory` | output style 이름 |
| `cost` | `$0.42` | 세션 추정 비용 (client-side) |
| `dur` | `dur: 1h 12m` | 세션 wall-clock 경과 시간 |
| `skills` | `skills: 17` | 로드된 skill 파일 수 |
| `agents` | `agents: 1` | 로드된 agent 파일 수 |
| `time` | `19:42` | 현재 시각 |

자주 등장할 자연어 매핑 예:
- "사용량" / "rate limit" / "남은 시간" → `5h`, `wk`
- "컨텍스트" / "context" → `ctx`
- "토큰" / "tokens" → `tokens`
- "비용" / "돈" / "USD" → `cost`
- "시간" / "얼마나 걸렸어" / "duration" → `dur`
- "모델" → `model`

## Scope: user vs project

| 어디 | 경로 | 언제 |
| --- | --- | --- |
| **project** (우선) | `<git-root>/.imprint/hud-config.json` | 사용자가 "이 프로젝트만", "여기서만", "여기에서는" 같은 표현을 쓸 때 — 명령에 `--project` 추가 |
| **user** | `~/.claude/imprint/hud-config.json` | 기본. 모든 프로젝트에서 같은 HUD를 원할 때 |

project가 user보다 항상 우선합니다.

## 실행 후 안내

명령을 실행했으면 사용자에게:
1. 무엇을 바꿨는지 한 줄 (예: "fields = `5h ctx cost time` (user scope)")
2. **Claude Code를 재시작하거나 `/reload-plugins`해야 새 statusline이 보인다**는 점

uninstall이 아닌 한, 새 statusline은 다음 turn부터가 아니라 Claude Code 자체가 statusLine을 재실행해야 적용됩니다.

## Implementation 참고

```bash
DISPATCHER="$CLAUDE_PLUGIN_ROOT/scripts/imprint/hud-setup.sh"

# 가장 자주 쓰는 호출들
bash "$DISPATCHER" fields list                       # 가용 + 활성
bash "$DISPATCHER" fields set 5h ctx time            # 통째 덮어쓰기
bash "$DISPATCHER" fields enable cost dur            # 추가
bash "$DISPATCHER" fields disable wk                 # 제거
bash "$DISPATCHER" fields set 5h ctx --project       # 프로젝트만

# 설치/상태/제거
bash "$DISPATCHER" install
bash "$DISPATCHER" status
bash "$DISPATCHER" uninstall
```

dispatcher가 직접 ID 검증, scope 분기, JSON 파일 읽기/쓰기를 처리합니다 — 이 skill에서 수동 JSON 편집은 하지 마세요.

## 트러블슈팅

- **statusline에 raw `\033[2m...`이 보임**: hud.sh의 ANSI escape 인코딩 버그. 최신 버전에서는 `printf '\033[..]'`를 command substitution으로 감싸 진짜 ESC byte를 박았으니, 이 증상이 보이면 plugin 캐시를 새 버전으로 동기화 + Claude Code 재시작.
- **`5h` / `wk` / `ctx` / `cost` / `dur`이 `-`로 표시**: Claude Code가 그 필드를 session JSON에 안 실어준 상태. 모델/세션 종류에 따라 일부 필드는 비어 있을 수 있음. HUD는 값을 만들어내지 않습니다.
- **새 fields가 안 보임**: `hud-config.json`은 즉시 갱신되지만 statusline 자체는 Claude Code 재시작 또는 `/reload-plugins` 후에 재실행됩니다.
