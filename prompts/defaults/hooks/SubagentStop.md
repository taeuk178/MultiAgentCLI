<!--
이 파일은 Claude Code의 SubagentStop hook 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: subagent가 종료된 직후
무엇을 함: 결과 archive, 후속 task 트리거, 메트릭 집계
사용자 손길이 닿는 곳: 본 plugin은 등록하지 않습니다 — 참고 문서
주의: agent는 이미 종료됨 — 결과 수정 불가
-->

# SubagentStop

> 🔵 본 plugin은 이 hook을 현재 등록하지 않습니다.

## 무엇

subagent가 작업을 마치고 종료될 때 발화. 페이로드에 `exit_code`, `agent_type` 포함.

## 어떻게 활용

- subagent 결과를 SQLite events로 archive
- 실패한 agent에 대해 자동 재시도 task 생성
- agent 평균 실행 시간/성공률 메트릭

## 간단한 예시

```bash
# scripts/multiagent/subagent-stop.sh (미구현 예시)
INPUT=$(cat)
EXIT=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("exit_code",-1))')
TYPE=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("agent_type",""))')
echo "$(date -u +%FT%TZ) stop $TYPE exit=$EXIT" >> ~/.claude/multiagent/agents.log
```

## 주의

- agent는 이미 종료 — 결과를 수정할 수 없다.
- exit 2로 완료 차단 가능하지만 reason이 모델로 환류되어 재시도 시도 가능.
- 페이로드에 agent의 출력 텍스트 전체가 들어오는지 여부는 버전 의존.
