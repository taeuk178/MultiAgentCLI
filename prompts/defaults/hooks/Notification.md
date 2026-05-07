<!--
이 파일은 Claude Code의 Notification hook 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: 권한 prompt, idle, auth 성공, elicitation 등 시스템 알림 발생 시
무엇을 함: 데스크톱 알림, 사운드 알람, 외부 push
사용자 손길이 닿는 곳: 본 plugin은 등록하지 않습니다 — 참고 문서
주의: 차단 불가, 알림 내용 수정 불가
-->

# Notification

> 🔵 본 plugin은 이 hook을 현재 등록하지 않습니다.

## 무엇

권한 prompt가 떴거나, idle 상태가 됐거나, auth 흐름이 성공했을 때 등 시스템 차원 알림 발생 시 발화. 페이로드에 `notification_type`, `message`.

## 어떻게 활용

- macOS: `osascript -e 'display notification "..." with title "Claude Code"'`
- Linux: `notify-send`
- 외부 push (Slack, Pushover, Telegram)

## 간단한 예시

```bash
# scripts/multiagent/notification.sh (미구현 예시)
INPUT=$(cat)
TYPE=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("notification_type",""))')
MSG=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("message",""))')
osascript -e "display notification \"$MSG\" with title \"Claude Code [$TYPE]\""
```

## 주의

- 차단 불가 — exit 2는 stderr만 노출.
- 알림 내용도 수정 불가.
- 종류별로 다른 알림이 필요하면 `notification_type`으로 분기.
