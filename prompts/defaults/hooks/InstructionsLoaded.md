<!--
이 파일은 Claude Code의 InstructionsLoaded hook 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: CLAUDE.md / .claude/rules/*.md가 컨텍스트에 로드될 때
무엇을 함: 어떤 instruction이 활성됐는지 감사, 민감 rule 필터
사용자 손길이 닿는 곳: 본 plugin은 등록하지 않습니다 — 참고 문서
주의: reason="compact"가 존재 → 압축 후에도 CLAUDE.md는 자동 재첨부됨
-->

# InstructionsLoaded

> 🔵 본 plugin은 이 hook을 현재 등록하지 않습니다.

## 무엇

`CLAUDE.md` 또는 `.claude/rules/*.md`가 컨텍스트에 로드될 때마다 발화. 페이로드에 `file_path`, `reason`.

reason 값으로 어떤 경로로 로드됐는지 구분된다: `session_start | nested_traversal | path_glob_match | include | compact`.

## 어떻게 활용

- 어떤 instruction이 어느 시점에 활성됐는지 audit log
- 조직 정책 위반 rule 차단
- instruction 로드 통계

## 간단한 예시

```bash
# scripts/multiagent/instructions-loaded.sh (미구현 예시)
INPUT=$(cat)
FILE=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("file_path",""))')
WHY=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("reason",""))')
echo "$(date -u +%FT%TZ) load $WHY $FILE" >> ~/.claude/multiagent/instructions.log
```

## 주의

- 파일 내용을 수정할 수 없다 — 통째로 allow/block만.
- **`reason="compact"` 발화의 함의**: Claude Code는 압축 직후 CLAUDE.md를 자동 재로드한다. 즉 SessionStart hook stdout과 달리 CLAUDE.md 콘텐츠는 plugin이 별도 재주입을 안 등록해도 압축 내성이 있다.
