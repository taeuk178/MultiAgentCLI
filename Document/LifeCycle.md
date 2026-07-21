# LifeCycle — Hook 생애주기 메모

이 문서는 초기 Claude Code hook 조사 메모를 축약한 보관 문서입니다. 현재 imprint 구현 기준의 상세 흐름은 `flow.md` 를 우선합니다.

## imprint 가 실제로 쓰는 hook

| hook | 현재 역할 |
|---|---|
| `SessionStart` | 스키마 적용, 프로젝트 등록, `.imprint/Guardrail.md` prepend, background rollup spawn |
| `UserPromptSubmit` | prompt 저장, working surface 저장, working → pinned → 관련 unpinned 순의 context section prefill, opt-in lazy-fetch worker spawn |
| `Stop` | assistant 응답을 `events` 에 archive |

`SessionStart` 의 rollup 정책은 host 별로 다릅니다. Claude Code 는 current session 을 제외한 stale session 만 background rollup 합니다. Codex App 은 하나의 thread 를 오래 재사용하므로 `compact` 때 current session 이 idle 조건을 만족하면 1 batch guarded rollup 을 추가합니다.

## 구현 원칙

- hook 은 사용자 세션을 끊지 않습니다. 실패는 silent skip + `plugin.log` 로 처리합니다.
- stdout 은 모델 컨텍스트로 들어갈 수 있으므로 디버그 출력은 stderr 또는 로그 파일로 보냅니다.
- 동기 hook 은 가볍게 유지하고, LLM 호출과 외부 fetch 는 background 로 분리합니다.
- 새 hook 을 추가할 때는 실제 stdin payload 를 임시로 캡처해 필드를 확인한 뒤 캡처 코드를 제거합니다.

## 참고

- 공식 hooks reference: <https://code.claude.com/docs/en/hooks>
- Plugin reference: <https://code.claude.com/docs/en/plugins-reference>
- 등록 hook: `hooks/hooks.json`
- hook script: `scripts/imprint/{session-start,user-prompt-submit,stop}.sh`
