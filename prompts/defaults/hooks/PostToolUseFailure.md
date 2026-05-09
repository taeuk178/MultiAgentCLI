<!--
이 파일은 Claude Code의 PostToolUseFailure hook 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: 도구 호출이 실패(non-zero exit 또는 에러)한 직후
무엇을 함: 실패 로깅, 패턴 분석, 자동 재시도 신호
사용자 손길이 닿는 곳: 본 plugin은 등록하지 않습니다 — 참고 문서
주의: 공식 문서 등재 여부 모호 — 사용 전 직접 확인
-->

# PostToolUseFailure

> 🟡 본 plugin은 이 hook을 등록하지 않으며, 공식 docs 페이지에서 명시 항목으로 검증되지 않았습니다. 사용 전 최신 docs를 확인하세요. PostToolUse가 실패 상황도 같이 받는 구현일 가능성도 있습니다.

## 무엇

도구 호출이 실패로 끝났을 때 발화한다고 알려진 hook. 페이로드에 `error` 필드 포함.

## 어떻게 활용

- 같은 명령이 N회 연속 실패하면 외부 알림
- 실패 패턴 통계 누적
- 특정 실패 종류만 자동 재시도 신호 반환

## 간단한 예시

```bash
# scripts/multiagent/post-tool-use-failure.sh (미구현 예시)
INPUT=$(cat)
ERR=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("error",""))')
echo "$(date -u +%FT%TZ) $ERR" >> ~/.claude/multiagent/tool-failures.log
```

## 주의

- 실패 자체를 되돌리거나 재실행할 수 없다.
- 페이로드 키는 docs 직접 확인 권장 — 본 가이드는 추정에 기반.
- PostToolUse와 분리되어 있는지, 통합 발화인지 환경마다 다를 수 있음.
