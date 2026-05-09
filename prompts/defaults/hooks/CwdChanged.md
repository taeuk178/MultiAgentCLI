<!--
이 파일은 Claude Code의 CwdChanged hook 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: 모델이 cd를 실행하거나 cwd가 바뀔 때
무엇을 함: direnv·nvm·pyenv 환경 reload, 프로젝트 row 갱신
사용자 손길이 닿는 곳: 본 plugin은 등록하지 않습니다 — 참고 문서
주의: matcher 없음 — 모든 cd에 걸린다
-->

# CwdChanged

> 🔵 본 plugin은 이 hook을 현재 등록하지 않습니다.

## 무엇

cwd가 바뀔 때마다 발화. 페이로드에 `old_cwd`, `new_cwd`.

## 어떻게 활용

- direnv/nvm/pyenv 자동 reload
- 새 프로젝트 진입 시 SQLite의 `projects` row upsert
- 프로젝트별 환경 변수 자동 적용

## 간단한 예시

```bash
# scripts/imprint/cwd-changed.sh (미구현 예시)
INPUT=$(cat)
NEW=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("new_cwd",""))')
[[ -f "$NEW/.envrc" ]] && cd "$NEW" && direnv export bash >> "$CLAUDE_ENV_FILE" 2>/dev/null
```

## 주의

- matcher 없음 — 모든 디렉토리 변경에 발화. 무거운 작업 금지.
- `CLAUDE_ENV_FILE`에 export 문을 적으면 후속 Bash 호출에 환경 변수 전파됨.
- cd가 매우 잦은 워크플로(테스트 스위트 등)에선 누적 지연 위험.
