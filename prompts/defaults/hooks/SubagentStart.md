<!--
이 파일은 Claude Code의 SubagentStart hook 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: subagent (Agent tool로 spawn되는 sub-thread) 시작 직전
무엇을 함: 동시 agent rate limit, spawn 로깅, 외부 모니터링
사용자 손길이 닿는 곳: 본 plugin은 등록하지 않습니다 — 참고 문서
주의: 공식 문서 등재 여부 모호 — 사용 전 직접 확인
-->

# SubagentStart

> 🟡 본 plugin은 이 hook을 등록하지 않으며, 공식 docs 등재 여부가 모호합니다. 사용 전 최신 docs 확인 권장.

## 무엇

`Agent` tool로 subagent가 spawn되는 시점에 발화. 페이로드에 `agent_id`, `agent_type` 포함.

## 어떻게 활용

- 동시에 돌릴 수 있는 subagent 수 제한
- spawn 시점·종류 로깅 (debugging, billing 추적)
- 특정 agent type을 외부 모니터링 시스템에 보고

## 간단한 예시

```bash
# scripts/imprint/subagent-start.sh (미구현 예시)
INPUT=$(cat)
TYPE=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("agent_type",""))')
echo "$(date -u +%FT%TZ) spawn $TYPE" >> ~/.claude/imprint/agents.log
```

## 주의

- spawn 자체를 차단하려면 exit 2.
- agent에게 instruction을 주입하거나 type을 바꿀 수는 없다.
- subagent 결과 후처리는 `SubagentStop`에서.
