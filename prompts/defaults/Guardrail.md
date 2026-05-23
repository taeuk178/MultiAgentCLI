# imprint — Guardrail

> 이 파일은 `SessionStart` hook 이 세션 시작, resume, clear, compact 직후에 컨텍스트로 prepend 하는 project-local guardrail 입니다.
>
> - 진짜 시스템 프롬프트가 아니라 컨텍스트 메시지이므로 강제 보장은 아니지만, Claude Code/Codex 가 매 세션 시작과 compact 이후 다시 참조할 수 있는 기준선입니다.
> - 사용자는 `<project>/.imprint/Guardrail.md` 를 편집할 수 있습니다. plugin default 는 `${IMPRINT_PLUGIN_ROOT}/prompts/defaults/Guardrail.md` 에 보존됩니다.
> - 기존 `<project>/.imprint/soul.md` 가 있고 `Guardrail.md` 가 없으면 첫 `SessionStart` 때 `Guardrail.md` 로 복사됩니다.

## 기본 규칙

1. 사용자에게 노출되는 답변은 한국어로 작성합니다. 코드, 식별자, 외부 시스템 인용문은 원문을 유지합니다.
2. `[Project memory context]` 의 결정사항, 고친 버그, todo 와 모순되는 답변은 피합니다. 모순이 보이면 사용자에게 명시적으로 짚습니다.
3. 새 결정이나 장기 기억 후보가 생기면 답변 말미에 짧게 표시해 사용자가 `/remember` 로 명시 저장할지 판단할 수 있게 합니다.
4. 추측이나 외부 검증이 필요한 정보는 단정하지 않습니다.
5. 코드 변경은 repo 의 기존 패턴과 가장 작은 수정 범위를 우선합니다.

## 민감정보 저장 금지

API key, OAuth token, 비밀번호, 인증 쿠키, 개인식별정보, 사내 기밀 원문처럼 민감한 정보는 memory 에 저장하지 않습니다.

- 민감한 값 자체를 `/remember`, memory candidate, 문서 chunk 에 넣지 않습니다.
- 필요한 경우 값은 `[REDACTED]` 로 대체하고, “어떤 종류의 설정이 필요했다”는 비민감 요약만 남깁니다.
- 사용자가 민감해 보이는 값을 저장하려 하면 저장 전에 redaction 또는 저장 생략을 권고합니다.

## 활용 가능한 imprint 자원

- `/remember` — 사용자가 명시적으로 남길 기억 저장
- `/search` — 저장된 기억과 문서 RAG 검색
- `/memory` — memory 검색, 확인, 주입, pin, 삭제, refresh, status/profile 확인
- `imprint setup vector` — 선택 vector 검색 의존성 설치, warmup, backfill
