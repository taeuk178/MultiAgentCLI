# UserPromptSubmit Routing Rules

이 파일은 `<project>/.imprint/UserPromptSubmit.md` 로 seed 되는 사용자 편집용 routing 룰입니다.

룰을 추가하면 `UserPromptSubmit` hook 이 사용자 prompt를 이 표의 정규식과 비교하고, 매칭된 권고를 현재 turn 컨텍스트 앞에 prepend합니다. 기본값은 빈 표라서 아무 agent 권고도 발생하지 않습니다.

| 패턴 | Agent | 권고 메시지 |
|---|---|---|
