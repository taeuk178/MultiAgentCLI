<!--
이 파일은 imprint plugin이 활용하는 SessionStart hook의 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: 세션 시작·재개·`/clear`·컨텍스트 압축 직후
무엇을 함: `.imprint/` 폴더 시드 + soul.md를 stdout으로 출력 → 컨텍스트에 prepend
사용자 손길이 닿는 곳: `<project>/.imprint/soul.md`
주의: 모델이 거부할 수 있고, 압축 시 휘발 가능 (compact matcher로 자동 재주입)
-->

# SessionStart

## 무엇

세션이 시작·재개·`/clear`·컨텍스트 압축 직후마다 한 번씩 발화하는 진입점입니다. plugin은 이 슬롯을 사용해 컨텍스트 첫머리에 **persona·동작 규칙**을 깔아둡니다.

## 어떻게 활용

`<project>/.imprint/soul.md`를 편집하세요. 그 파일 내용이 매 세션 시작 시 컨텍스트에 prepend됩니다.

## 간단한 예시

```markdown
# .imprint/soul.md (사용자 편집)

당신은 한국어로 답하는 전문 코드 리뷰 어시스턴트입니다.
- PR 본문은 항상 "Summary / Changes / Risk / Test plan" 4섹션 구조로
- 외부 의존성 추가는 모두 위험으로 분류
```

다음 세션 시작에서 이 내용이 컨텍스트에 prepend되어 동작 규칙이 됩니다.

## 주의

- 진짜 시스템 프롬프트가 아니라 컨텍스트 메시지입니다 — 모델이 일부 지시를 거부할 수 있습니다.
- 컨텍스트 압축 시 일반 대화와 함께 요약/소실됩니다. plugin이 `compact` matcher로 자동 재주입하므로 압축 후엔 다시 깔립니다.
- plugin disable 시 발화하지 않습니다.
