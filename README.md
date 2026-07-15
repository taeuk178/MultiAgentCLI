# imprint — Claude/Codex memory plugin

imprint 는 Claude Code 와 Codex 세션에 **로컬 작업 기억**을 붙이는 plugin 입니다.

## 문제

AI 코딩 세션은 끝나는 순간 맥락이 사라집니다.

- **작업 재개 비용** — 며칠 뒤 프로젝트를 다시 열면 진행 상황, 실패한 접근, 남은 TODO 를 처음부터 다시 파악해야 합니다.
- **반복 설명** — 폴더 구조, 검증 명령, 최근 결정 사항을 매 세션 다시 설명하게 됩니다.
- **사라지는 구현 의도** — 코드에는 결과만 남습니다. "이 부분 왜 이렇게 구현했었지", "폐기한 대안이 뭐였지" 같은 질문에 답할 근거가 남지 않습니다.
- **근거 없는 기억** — 모델이 이전 맥락을 "느낌상" 말할 때 사용자가 그 근거를 확인할 방법이 없습니다.

## 해결 방법

세션의 대화를 로컬 SQLite 에 archive 하고, 거기서 **구현 결정과 맥락을 추출해 검색 가능한 기억**으로 만듭니다.

- **Archive**: 모든 prompt/응답을 `events` 에 남깁니다. 원본이 있어야 나중에 추출할 수 있습니다.
- **Rollup**: 세션이 끝나면 background 에서 events 를 훑어 결정·사유·수정 파일 같은 구현 기억을 `search_entries` 로 정리합니다.
- **Prefill**: 다음 세션에서 매 prompt 앞에 관련 기억을 `[Project memory context]` 로 자동 주입합니다.
- **명시 검색**: `/search` 는 FTS5 + 벡터 hybrid 검색으로 "로그인 공유하기 어떻게 구현했었지" 같은 자연어 질문에 답하고, `/memory show` 로 근거 chunk 를 직접 확인할 수 있습니다.
- **로컬 우선**: API key 없이 host CLI 의 OAuth 구독을 그대로 쓰고, 데이터는 `~/.imprint/app.sqlite` 를 벗어나지 않습니다. 선택 ML 의존성이 없어도 FTS-only 로 동작합니다.

## 동작 과정

```text
사용자 prompt
  -> UserPromptSubmit hook: prompt archive + 관련 기억 prefill
  -> host 모델 응답
  -> Stop hook: 응답 archive
  -> stale session 또는 명시 rollup: 구현 결정을 search_entries 로 정리
  -> 다음 turn 부터 prefill / `/search` 후보가 됨
```

`/search` 는 사용자가 명시적으로 호출했을 때만 풀 검색 경로를 탑니다. 방금 끝난 구현 기억은 rollup 전까지 `/search` 에 보이지 않을 수 있습니다. 전체 다이어그램은 [`Document/flow.md`](Document/flow.md) 를 봅니다.

Slack/Notion 외부 소스는 기본 RAG 루프가 아니라 opt-in cache 입니다. `IMPRINT_ENABLE_LAZY_FETCH=1` 과 `<project>/.imprint/sources.json` 설정 시에만 동작합니다.

## 설치

```bash
claude plugin marketplace add <this-repo>
claude plugin install imprint@imprint
```

설치 후 새 세션을 열면 `SessionStart` hook 이 `~/.imprint/app.sqlite` 를 만들고 현재 프로젝트를 등록합니다. Codex 설정을 포함한 자세한 절차는 [`Document/INSTALL.md`](Document/INSTALL.md) 를 봅니다.

**요구 사항**: `bash`, `python3`, `sqlite3`, `uuidgen`, 그리고 `claude` 또는 `codex` CLI.

벡터 검색을 켜려면 선택 의존성을 설치합니다. 없어도 FTS-only fallback 으로 동작합니다.

```bash
pip install -r requirements-optional.txt
imprint setup vector --install --warmup --backfill
```

## 자주 쓰는 명령

| 하고 싶은 일 | 명령 |
|---|---|
| 기억 저장 | `/remember <text>` |
| 의미 검색 | `/search "<question>"` |
| memory 검색 / 목록 | `/memory search <query>`, `/memory list --recent` |
| chunk 주입 / pin | `/memory inject <id>`, `/memory pin <id>` |
| 상태 진단 | `/memory status --json` |

전체 하위 명령은 `/memory` skill 문서를 봅니다.

## 안전과 한계

- secret-shaped text 는 저장 전에 redaction 합니다. 그래도 민감정보를 일부러 memory 에 넣는 사용은 피하세요.
- hook 은 실패해도 사용자 세션을 끊지 않고 `plugin.log` 에만 남깁니다.
- 테스트할 때는 `IMPRINT_HOME=/tmp/...` 로 실제 DB 와 격리하세요.

## License

[MIT](LICENSE)
