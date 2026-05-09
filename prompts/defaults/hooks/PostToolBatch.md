<!--
이 파일은 Claude Code의 PostToolBatch hook 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: 한 모델 응답이 발행한 모든 병렬 도구 호출이 resolve된 직후, 다음 모델 호출 전
무엇을 함: 배치 단위 일관성 검증, 집계, 차단
사용자 손길이 닿는 곳: 본 plugin은 등록하지 않습니다 — 참고 문서
주의: 공식 문서 등재 여부 모호 — 사용 전 직접 확인
-->

# PostToolBatch

> 🟡 본 plugin은 이 hook을 등록하지 않으며, 공식 docs 등재 여부가 모호합니다. 사용 전 최신 docs 확인 권장.

## 무엇

한 turn에서 모델이 발행한 여러 개의 병렬 도구 호출이 모두 끝난 시점에 한 번 발화. 페이로드에 `tool_calls` 배열로 모든 호출의 input/output이 들어온다.

## 어떻게 활용

- 같은 turn에서 schema 변경 + migration 동시 수정을 강제하는 일관성 검증
- 여러 파일 수정의 일괄 lint
- 배치 결과 요약을 메모리로 적재

## 간단한 예시

```bash
# scripts/imprint/post-tool-batch.sh (미구현 예시)
INPUT=$(cat)
COUNT=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("tool_calls",[])))')
echo "batch of $COUNT tool calls" >> ~/.claude/imprint/batches.log
```

## 주의

- 모든 도구는 이미 실행됨 — 개별 호출을 막으려면 `PreToolUse`로.
- 배치 크기에 따라 페이로드가 매우 클 수 있음 — 무거운 파싱은 외부 프로세스로.
- exit 2 또는 `decision: "block"`으로 다음 모델 호출을 차단 가능.
