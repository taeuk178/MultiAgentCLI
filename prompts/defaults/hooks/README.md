<!--
이 폴더(.multiagent/hooks/)는 Claude Code의 hook 카탈로그 + multiagent plugin의 활용 가이드입니다.
Claude Code가 직접 읽지 않는 사람용 참고 문서입니다.

- ✅ 표시: multiagent plugin이 현재 등록한 hook (실제 동작 중)
- 🔵 표시: 등록 가능하지만 본 plugin이 아직 사용하지 않는 hook (참고)
- 🟡 표시: 공식 문서 등재 여부가 모호하거나 실험 단계 (사용 전 직접 확인 권장)
-->

# .multiagent/hooks/ — hook 카탈로그

Claude Code가 노출하는 hook들을 한 줄씩 정리한 인덱스. 클릭해 들어가면 OpenClaw 스타일 짧은 가이드(무엇 / 어떻게 활용 / 간단한 예시 / 주의)가 나온다.

## 본 plugin이 등록한 hook

| 파일 | 발화 시점 | 사용자 편집 지점 |
|---|---|---|
| ✅ [`SessionStart.md`](./SessionStart.md) | 세션 시작·재개·`/clear`·압축 직후 | `<project>/.multiagent/soul.md` |
| ✅ [`UserPromptSubmit.md`](./UserPromptSubmit.md) | 매 사용자 prompt 직전 | `<project>/.multiagent/UserPromptSubmit.md` |
| ✅ [`Stop.md`](./Stop.md) | 모델 응답 직후 | (편집 지점 없음 — archive 전용) |

## 세션 라이프사이클

| 파일 | 발화 시점 |
|---|---|
| 🔵 [`SessionEnd.md`](./SessionEnd.md) | 세션 종료 직전 |
| 🔵 [`PreCompact.md`](./PreCompact.md) | 컨텍스트 압축 직전 |
| 🔵 [`PostCompact.md`](./PostCompact.md) | 컨텍스트 압축 직후 |

## 도구 호출 사이클

| 파일 | 발화 시점 |
|---|---|
| 🔵 [`PreToolUse.md`](./PreToolUse.md) | 도구 호출 직전 (권한 평가 전) |
| 🔵 [`PostToolUse.md`](./PostToolUse.md) | 도구 호출 성공 직후 |
| 🟡 [`PostToolUseFailure.md`](./PostToolUseFailure.md) | 도구 호출 실패 직후 |
| 🟡 [`PostToolBatch.md`](./PostToolBatch.md) | 병렬 도구 batch 모두 resolve 직후 |
| 🔵 [`PermissionRequest.md`](./PermissionRequest.md) | 권한 다이얼로그 표시 직전 |
| 🔵 [`PermissionDenied.md`](./PermissionDenied.md) | auto-mode 분류기가 거부했을 때 |

## Subagent 생애주기

| 파일 | 발화 시점 |
|---|---|
| 🟡 [`SubagentStart.md`](./SubagentStart.md) | subagent spawn 시점 |
| 🔵 [`SubagentStop.md`](./SubagentStop.md) | subagent 종료 시점 |

## 환경 변화

| 파일 | 발화 시점 |
|---|---|
| 🔵 [`CwdChanged.md`](./CwdChanged.md) | cwd 변경 시 |
| 🔵 [`ConfigChange.md`](./ConfigChange.md) | settings/skills/rules 파일 외부 변경 시 |
| 🔵 [`FileChanged.md`](./FileChanged.md) | matcher가 지정한 파일 변경 시 |

## MCP 상호작용

| 파일 | 발화 시점 |
|---|---|
| 🔵 [`Elicitation.md`](./Elicitation.md) | MCP 서버가 사용자 입력 요청 시 |
| 🔵 [`ElicitationResult.md`](./ElicitationResult.md) | 사용자 응답 직후 |

## 알림 / 메타

| 파일 | 발화 시점 |
|---|---|
| 🔵 [`Notification.md`](./Notification.md) | 권한 prompt·idle·auth 성공 등 |
| 🔵 [`InstructionsLoaded.md`](./InstructionsLoaded.md) | CLAUDE.md / .claude/rules 로드 시 |
| 🟡 [`TaskCompleted.md`](./TaskCompleted.md) | task/checklist 완료 처리 시 (실험 단계) |

## 깊이 있는 카탈로그

위 표는 짧은 사용자 가이드. 각 hook의 메커니즘·동작 통제·한계·플러그인 활용 사례 4축으로 정리된 깊은 레퍼런스는 plugin repo의 [`LifeCycle.md`](../LifeCycle.md)에 있다.

## 이 폴더의 .md를 편집해도 되나

자유롭게 편집해도 plugin 동작에는 영향이 없다 — Claude Code가 읽지 않는 사람용 문서다. plugin defaults는 `${CLAUDE_PLUGIN_ROOT}/prompts/defaults/hooks/`에 보존된다.
