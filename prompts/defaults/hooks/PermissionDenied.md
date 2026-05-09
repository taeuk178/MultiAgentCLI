<!--
이 파일은 Claude Code의 PermissionDenied hook 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: auto-mode 분류기가 도구 호출을 거부했을 때 (사용자 인터랙션 없이)
무엇을 함: 거부 패턴 로깅, 선택적 재시도 신호
사용자 손길이 닿는 곳: 본 plugin은 등록하지 않습니다 — 참고 문서
주의: 거부 자체를 직접 뒤집을 수 없음 — retry 신호만 보낼 수 있음
-->

# PermissionDenied

> 🔵 본 plugin은 이 hook을 현재 등록하지 않습니다.

## 무엇

자동 분류기가 도구 호출을 거부한 직후 발화. 사용자 다이얼로그 없이 정책으로 끊긴 경우.

## 어떻게 활용

- 거부 패턴 통계 누적 → 화이트리스트 보강 근거
- 특정 안전 거부에 대해 `{"retry": true}`를 돌려 모델이 재시도하도록 유도

## 간단한 예시

```bash
# scripts/imprint/permission-denied.sh (미구현 예시)
INPUT=$(cat)
TOOL=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_name",""))')
echo "$(date -u +%FT%TZ) denied $TOOL" >> ~/.claude/imprint/denials.log
```

## 주의

- 거부 결정은 직접 뒤집을 수 없다 — `{"retry": true}` 신호만 보낼 수 있음.
- 잘못 retry 신호를 남발하면 무한 루프 위험.
- 거부 사유는 `denial_reason` 필드로 페이로드에 들어옴.
