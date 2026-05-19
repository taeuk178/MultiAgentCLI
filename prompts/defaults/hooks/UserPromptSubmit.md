<!--
이 파일은 imprint plugin이 활용하는 UserPromptSubmit hook의 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: 사용자가 prompt를 보낼 때마다 (매 turn)
무엇을 함:
  1) 현재 prompt를 working mini-chunk로 즉시 저장
  2) 라우팅 룰(.imprint/UserPromptSubmit.md)을 평가해 매칭된 agent 권고 prepend
  3) gate 결과에 따라 context section 별 메모리 청크를 [Project memory context] 블록으로 prepend
사용자 손길이 닿는 곳: `<project>/.imprint/UserPromptSubmit.md`
주의: 매 turn 토큰을 소모, 모델이 라우팅 권고를 거부할 수 있음
-->

# UserPromptSubmit

## 무엇

사용자가 prompt를 보낼 때마다 그 직전에 발화하는 슬롯입니다. plugin은 이 슬롯에서 세 가지 일을 합니다.

1. **working 저장** — 현재 prompt를 첫 turn 에도 보이는 경량 메모리로 저장
2. **라우팅** — prompt에서 키워드를 감지하면 적합한 agent 호출을 권고
3. **메모리 주입** — query context, session memory, retrieved memory, external source context 를 `[Project memory context]` 블록으로 prepend

## 어떻게 활용

`<project>/.imprint/UserPromptSubmit.md`의 라우팅 표를 편집해 키워드 → agent 매핑을 추가/수정하세요.

## 간단한 예시

```markdown
# .imprint/UserPromptSubmit.md 라우팅 표 (사용자 편집)

| 패턴                       | Agent        | 권고 메시지                  |
|---------------------------|--------------|------------------------------|
| `\b(PR\|pull\s*request)\b` | pr-agent     | PR 작업 — pr-agent 호출 권장 |
| `\bdeploy\b\|배포`         | deploy-guard | 배포 작업 — deploy-guard 호출 |
```

`이 PR 본문 만들어줘`라는 prompt가 들어오면, 모델이 받기 직전에 다음이 prepend됩니다.

```
[imprint routing — UserPromptSubmit]
- [pr-agent] PR 작업 — pr-agent 호출 권장

[Project memory context]
[Query context]
- [working] ...
[Retrieved memory]
- [decision] ...
```

## 주의

- **모델이 권고를 거부할 수 있습니다.** Agent 호출은 모델 자율 결정 — plugin은 강한 권고만 합니다.
- **매 turn 토큰을 소모**합니다. 룰 수와 메모리 청크 길이를 짧게 유지하세요.
- **한국어 키워드에 `\b` 사용 금지** — 한글은 word character로 인식되어 boundary가 안 잡힙니다. 영어 약어(PR, commit)에만 `\b`를 씁니다.
- 표 안에서 정규식 alternation은 `\|`로 escape — markdown 셀 구분자와 충돌하기 때문입니다.
