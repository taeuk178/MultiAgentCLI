<!--
이 파일은 Claude Code의 FileChanged hook 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: matcher가 지정한 파일이 디스크에서 변경됐을 때
무엇을 함: .env 자동 reload, 설정 동기화, 알림
사용자 손길이 닿는 곳: 본 plugin은 등록하지 않습니다 — 참고 문서
주의: matcher는 정규식이 아닌 리터럴 파일명만
-->

# FileChanged

> 🔵 본 plugin은 이 hook을 현재 등록하지 않습니다.

## 무엇

watch 대상 파일이 디스크에서 변경되면 발화. matcher에 파일명을 명시.

## 어떻게 활용

- `.env` 변경 시 환경 자동 reload
- 빌드 산출물 변경 시 인덱스 갱신
- 디자인 토큰 파일 변경 시 캐시 invalidation

## 간단한 예시

```bash
# scripts/multiagent/file-changed.sh (미구현 예시)
INPUT=$(cat)
P=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("file_path",""))')
case "$(basename "$P")" in
  .env|.envrc) cat "$P" >> "$CLAUDE_ENV_FILE" ;;
esac
```

## 주의

- matcher는 **리터럴 파일명**만 받는다(정규식 X). `.envrc|.env`처럼 OR 나열로만 가능.
- 디렉토리 패턴 watch 불가.
- 파일은 이미 변경된 상태에서 발화 — 차단으로 변경을 되돌릴 수 없다.
