<!--
이 파일은 Claude Code의 PostToolUse hook 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: 도구 호출이 성공으로 끝난 직후
무엇을 함: 자동 포맷, 결과 로깅, 후속 트리거
사용자 손길이 닿는 곳: 본 plugin은 등록하지 않습니다 — 참고 문서
주의: 도구는 이미 실행됨, 출력만 모델 시야에서 가릴 수 있음
-->

# PostToolUse

> 🔵 본 plugin은 이 hook을 현재 등록하지 않습니다.

## 무엇

도구 호출이 성공한 직후 발화. 페이로드에 `tool_input`과 `tool_output` 모두 포함.

## 어떻게 활용

- `Edit`/`Write` 직후 자동 포맷터(prettier, black, gofmt) 호출
- 빌드/테스트 자동 트리거
- 도구 결과에서 의미 있는 청크 추출 → memory_chunks로 적재

## 간단한 예시

```bash
# scripts/imprint/post-tool-use.sh (미구현 예시)
INPUT=$(cat)
TOOL=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_name",""))')
case "$TOOL" in
  Edit|Write)
    FILE=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))')
    [[ "$FILE" == *.py ]] && black "$FILE" >/dev/null 2>&1
    ;;
esac
```

## 주의

- 도구는 이미 실행됨 — 디스크 변경을 되돌릴 수 없다.
- JSON으로 `{"decision": "block"}`을 반환하면 도구 출력을 모델 시야에서만 가린다(파일 변경은 그대로 남음).
- 매 도구 호출마다 발화하므로 무거운 작업은 비동기로(`async: true` 또는 `nohup &`).
