<!--
이 파일은 Claude Code의 Elicitation hook 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: MCP 서버가 사용자 입력을 요청할 때 (예: 도구가 선택지를 물음)
무엇을 함: 자동 응답, 입력 source 변경, 로깅
사용자 손길이 닿는 곳: 본 plugin은 등록하지 않습니다 — 참고 문서
주의: MCP 서버 prompt 자체는 막을 수 없음
-->

# Elicitation

> 🔵 본 plugin은 이 hook을 현재 등록하지 않습니다.

## 무엇

MCP 서버가 도구 실행 중에 사용자 입력을 요청할 때(예: browser automation의 선택지 prompt) 발화. 페이로드에 `mcp_server`, `message`.

## 어떻게 활용

- 반복적인 동의 prompt를 자동 응답
- 외부 input source(파일, env)에서 답을 끌어옴
- 사용자 prompt 빈도 통계

## 간단한 예시

```bash
# scripts/imprint/elicitation.sh (미구현 예시)
INPUT=$(cat)
SERVER=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("mcp_server",""))')
[[ "$SERVER" == "trusted-server" ]] && printf '%s' '{"input":"yes"}'
```

## 주의

- MCP 서버가 발신한 prompt 자체를 수정·막을 수는 없다.
- 자동 응답을 너무 광범위하게 잡으면 의도치 않은 동의가 일어남.
- 응답 검증은 `ElicitationResult`에서.
