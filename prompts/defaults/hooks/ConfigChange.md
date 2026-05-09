<!--
이 파일은 Claude Code의 ConfigChange hook 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: settings/skills/rules 파일이 외부에서 변경됐을 때 (file watcher)
무엇을 함: 변경 감사, 무단 수정 차단, syntax pre-validation
사용자 손길이 닿는 곳: 본 plugin은 등록하지 않습니다 — 참고 문서
주의: 파일은 이미 디스크에 쓰여 있음 — 차단해도 reload만 막음
-->

# ConfigChange

> 🔵 본 plugin은 이 hook을 현재 등록하지 않습니다.

## 무엇

`settings.json`, `skills/`, `.claude/rules/`가 외부에서 변경되면 발화. 페이로드에 `config_type`, `file_path`, `change_type`.

## 어떻게 활용

- 조직 정책 위반 변경을 차단(`decision: "block"`)
- syntax 깨진 settings.json reload 막기
- 변경 history를 외부 audit log에 기록

## 간단한 예시

```bash
# scripts/imprint/config-change.sh (미구현 예시)
INPUT=$(cat)
PATH_=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("file_path",""))')
echo "$(date -u +%FT%TZ) config $PATH_" >> ~/.claude/imprint/config-changes.log
```

## 주의

- 파일이 디스크에 이미 쓰여진 후 발화 — 차단해도 디스크 변경은 남고 reload만 안 일어난다.
- 조직 관리형 settings를 무단 변경하는 케이스 차단에 유용하지만, 결정적 보안에는 OS 권한이 더 안전.
