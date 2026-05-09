<!--
이 파일은 Claude Code의 PreToolUse hook 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: 모델이 도구 호출을 결정한 직후, 권한 평가 직전
무엇을 함: 위험 명령 차단, 인자 변형, 권한 자동 결정
사용자 손길이 닿는 곳: 본 plugin은 등록하지 않습니다 — 참고 문서
주의: bypassPermissions 모드도 우회해 적용됨, hook 자체가 깨지면 모든 도구 호출이 막힘
-->

# PreToolUse

> 🔵 본 plugin은 이 hook을 현재 등록하지 않습니다.

## 무엇

도구 호출이 실제로 실행되기 전에 발화. 매 도구 호출마다 한 번. matcher로 도구명 필터링 가능(`Bash`, `Edit`, `Write` 등).

## 어떻게 활용

- 파괴적 명령(`rm -rf /`, `git push --force` to main) 자동 차단
- 실행 전 명령 로깅 (감사 추적)
- 인자 변형(예: 위험 flag 제거 후 진행)

## 간단한 예시

```bash
# scripts/imprint/pre-tool-use.sh (미구현 예시)
INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("command",""))')
if echo "$CMD" | grep -qE 'rm -rf /|chmod -R 777'; then
  printf '%s' '{"hookSpecificOutput":{"permissionDecision":"deny"}}'
  exit 0
fi
```

## 주의

- `bypassPermissions` 모드도 무시하고 적용된다 — 보안엔 좋지만 자동화 워크플로에선 의도치 않은 차단 위험.
- 이 hook이 exit 1로 깨지면 **모든 도구 호출이 막힌다**. 실패해도 silent allow하도록 방어 코딩 필수.
- streaming 출력이 보이지 않으므로 도구 시작 후의 동작은 PostToolUse로.
