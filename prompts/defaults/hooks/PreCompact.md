<!--
이 파일은 Claude Code의 PreCompact hook 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: 컨텍스트 자동/수동 압축이 시작되기 직전
무엇을 함: 압축 전 transcript 백업, 사용자 알림, 압축 차단
사용자 손길이 닿는 곳: 본 plugin은 등록하지 않습니다 — 참고 문서
주의: 압축 알고리즘 자체는 통제 불가 — allow/deny만
-->

# PreCompact

> 🔵 본 plugin은 이 hook을 현재 등록하지 않습니다.

## 무엇

컨텍스트가 압축되기 직전에 발화. 페이로드의 `reason`으로 `manual` / `auto` 구분.

## 어떻게 활용

- 압축 전 transcript 사본을 디스크에 백업
- 압축이 너무 잦으면 사용자에게 경고
- 자동 압축은 허용하되, 수동 압축만 한 번 더 확인 받기

## 간단한 예시

```bash
# scripts/imprint/pre-compact.sh (미구현 예시)
INPUT=$(cat)
TID=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("transcript_path",""))')
[[ -f "$TID" ]] && cp "$TID" "$HOME/.claude/imprint/precompact-$(date +%s).jsonl"
```

## 주의

- 압축 알고리즘 자체를 통제할 수 없다 — 어떤 청크가 살아남을지 선택 불가.
- exit 2로 압축 차단 가능. 하지만 자주 차단하면 컨텍스트 한도 초과로 세션 자체가 깨질 수 있음.
- 핵심 컨텍스트 재주입은 `PostCompact` 또는 `SessionStart matcher=compact`에서.
