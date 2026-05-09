<!--
이 파일은 Claude Code의 SessionEnd hook 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: 세션이 종료될 때 (사용자 종료 / 타임아웃 / 수동 stop)
무엇을 함: 세션 마무리 작업 (archive, 알림, cleanup)
사용자 손길이 닿는 곳: 본 plugin은 등록하지 않습니다 — 참고 문서
주의: 종료를 막을 수 없음, 정리 작업은 짧게 끝내야 함
-->

# SessionEnd

> 🔵 본 plugin은 이 hook을 현재 등록하지 않습니다. 활용하려면 `hooks/hooks.json`에 추가하고 dispatcher 스크립트를 작성하세요.

## 무엇

세션이 끝나는 마지막 순간에 한 번 발화. archive·알림·cleanup용 슬롯.

## 어떻게 활용

- 대화 transcript을 외부 저장소로 업로드
- Slack에 "세션 종료" 알림
- 임시 파일·PTY 자원 정리

## 간단한 예시

```bash
# scripts/imprint/session-end.sh (미구현 예시)
INPUT=$(cat)
TID=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("transcript_path",""))')
[[ -f "$TID" ]] && cp "$TID" "$HOME/.claude/imprint/archive/$(date +%s).jsonl"
```

## 주의

- 세션이 이미 닫히는 중 — 모델에 추가 prompt나 사용자 인터랙션을 강제할 수 없다.
- 종료 자체를 막을 방법이 없다. exit 2는 stderr만 노출.
- 무거운 작업은 외부 프로세스(`nohup`)로 던져서 hook 자체는 빠르게 끝내는 게 안전.
