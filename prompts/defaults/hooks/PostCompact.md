<!--
이 파일은 Claude Code의 PostCompact hook 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: 컨텍스트 압축이 끝난 직후
무엇을 함: 핵심 컨텍스트 재주입, 압축 통계 로깅
사용자 손길이 닿는 곳: 본 plugin은 등록하지 않습니다 — 참고 문서
주의: SessionStart matcher=compact와 발화 시점이 겹침 — 둘 중 하나만 등록
-->

# PostCompact

> 🔵 본 plugin은 이 hook을 현재 등록하지 않습니다.

## 무엇

압축이 끝나고 모델이 다시 동작 가능한 상태가 된 직후 발화. 페이로드에 `reason`(`manual` / `auto`)과 `tokens_freed` 포함.

## 어떻게 활용

- pinned memory와 핵심 결정사항을 `additionalContext`로 컨텍스트에 재주입
- 압축이 얼마나 자주 일어나는지 통계 누적

## 간단한 예시

```bash
# scripts/multiagent/post-compact.sh (미구현 예시)
INPUT=$(cat)
FREED=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tokens_freed",0))')
echo "$(date -u +%FT%TZ) compact freed=$FREED" >> ~/.claude/multiagent/compaction.log
# pinned 청크 재주입
sqlite3 ~/.claude/multiagent/app.sqlite "SELECT text FROM memory_chunks WHERE pinned=1 LIMIT 5"
```

## 주의

- `SessionStart` matcher가 `compact`를 포함하면 같은 시점에 두 번 hook이 발화한다 — **둘 중 하나만 등록**해서 중복 prepend를 피하라.
- 본 plugin은 `SessionStart matcher: "startup|resume|clear|compact"`로 통합 운영 중. 별도 PostCompact를 추가하면 충돌.
