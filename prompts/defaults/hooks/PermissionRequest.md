<!--
이 파일은 Claude Code의 PermissionRequest hook 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: 권한 다이얼로그가 떠야 할 때 (도구 호출이 명시 승인 필요)
무엇을 함: 자동 승인/거부, 정책 기반 결정 자동화
사용자 손길이 닿는 곳: 본 plugin은 등록하지 않습니다 — 참고 문서
주의: claude -p 같은 비대화 모드에서는 발화하지 않음
-->

# PermissionRequest

> 🔵 본 plugin은 이 hook을 현재 등록하지 않습니다.

## 무엇

특정 도구 호출이 사용자 승인을 요구할 때, 다이얼로그가 표시되기 직전에 발화.

## 어떻게 활용

- 안전한 명령(`git status`, `ls`, `cat`)은 자동 allow
- 정책 위반 패턴은 자동 deny
- 의심스러운 명령만 사용자에게 ask로 격상

## 간단한 예시

```bash
# scripts/multiagent/permission-request.sh (미구현 예시)
INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))')
case "$CMD" in
  "git status"*|"git log"*|"ls"*)
    printf '%s' '{"hookSpecificOutput":{"decision":{"behavior":"allow"}}}'
    ;;
esac
```

## 주의

- **비대화 모드(`claude -p`)에서는 발화하지 않는다** — 자동화 워크플로엔 `PreToolUse`를 써야 한다.
- 자동 allow를 너무 넓게 잡으면 의도치 않은 명령이 통과한다 — 화이트리스트 방식이 안전.
- `additionalContext` 필드로 결정 사유를 모델에 전달 가능.
