<!--
이 파일은 Claude Code의 TaskCompleted hook 사용자 가이드입니다 (실험 단계).
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: Claude Code UI에서 task/checklist 항목이 완료 처리될 때
무엇을 함: 외부 PM 도구 동기화, 메트릭 집계
사용자 손길이 닿는 곳: 본 plugin은 등록하지 않습니다 — 참고 문서
주의: 실험 단계 — 이름·페이로드가 향후 변경될 수 있음
-->

# TaskCompleted (Experimental)

> 🟡 본 plugin은 이 hook을 등록하지 않으며, **실험 단계**입니다. 이벤트명·페이로드 구조가 향후 변경될 수 있습니다. 사용 전 최신 docs 확인 필수.

## 무엇

Claude Code UI에서 task/checklist 항목이 완료 처리될 때 발화. 페이로드에 `task_id`, `task_name`.

## 어떻게 활용

- 외부 PM 도구(Linear, Notion, Jira) 동기화
- 완료 시점 메트릭 누적
- 완료 알림 → Slack push

## 간단한 예시

```bash
# scripts/imprint/task-completed.sh (미구현 예시)
INPUT=$(cat)
NAME=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("task_name",""))')
echo "$(date -u +%FT%TZ) done $NAME" >> ~/.claude/imprint/tasks.log
```

## 주의

- **실험 단계** — 페이로드 키와 hook 이름이 안정적이지 않다.
- task가 이미 완료 처리됨 — 되돌릴 수 없다.
- exit 2로 완료 차단 가능하다는 보고가 있지만 동작은 버전 의존.
