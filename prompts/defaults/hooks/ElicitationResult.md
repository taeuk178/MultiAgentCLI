<!--
이 파일은 Claude Code의 ElicitationResult hook 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: 사용자가 MCP elicitation에 응답한 직후, 응답이 MCP 서버로 가기 전
무엇을 함: 응답 검증, 민감 정보 redact, 로깅
사용자 손길이 닿는 곳: 본 plugin은 등록하지 않습니다 — 참고 문서
주의: 사용자 응답이 이미 입력됨 — 재요청 불가
-->

# ElicitationResult

> 🔵 본 plugin은 이 hook을 현재 등록하지 않습니다.

## 무엇

사용자가 elicitation에 응답한 직후, 그 응답이 MCP 서버로 전달되기 전에 발화. 페이로드에 `user_input`.

## 어떻게 활용

- 응답에 token·key 같은 민감 패턴이 있으면 차단
- 응답을 normalize(공백 제거, 소문자화)
- 응답 history 저장

## 간단한 예시

```bash
# scripts/multiagent/elicitation-result.sh (미구현 예시)
INPUT=$(cat)
ANS=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("user_input",""))')
if echo "$ANS" | grep -qE 'sk-[A-Za-z0-9]{20,}'; then
  printf '%s' '{"decision":"block","reason":"API key가 응답에 포함됨"}'
  exit 0
fi
```

## 주의

- 사용자가 이미 입력함 — 재 prompt 불가.
- 응답을 수정해서 MCP 서버로 보내는 건 가능하지만, MCP 서버가 변형된 응답을 거부할 수도 있음.
