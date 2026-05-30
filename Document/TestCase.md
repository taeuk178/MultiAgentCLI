# TestCase — imprint 회귀 테스트 기준

자동화된 회귀 테스트는 `scripts/imprint/tests/run_tests.py` 가 기준입니다. 이 문서는 오래된 수동 케이스 설명을 반복하지 않고, 현재 테스트 운영 방식만 남깁니다.

## 실행

```bash
python3 scripts/imprint/tests/run_tests.py
```

테스트는 임시 `IMPRINT_HOME` 에서 실행되므로 사용자 `~/.imprint/app.sqlite` 를 수정하지 않습니다.

현재 기준선:

```text
TOTAL  36 PASS / 0 FAIL
```

## 현재 커버리지

- 문서 ingest, chunking, supersede
- local/feature/global `/search`
- entity alias, contradiction judge/fallback
- hook memory loop, redaction, first-turn working overlay
- `/memory` search/list/show/inject/status/profile
- `/search`, `/remember`, `setup vector` dispatcher
- `/remember --stdin` 문서형 split/group 저장, search group cap, `forget --group`
- retrieval text override, decision-rich extract
- Stop archive-only session metadata, delta/rollup cursor, stale session 보완
- rollup write-lock 안전성, transaction 밖 자동 embedding, `/search` rollup detail 출력
- Codex compact current-session guarded rollup 과 Claude Code current-session 제외 정책
- lazy fetch opt-in
- source status, noise flag, profile, dedup/provenance trace

## 테스트 추가 원칙

- 새 사용자-facing 동작은 `TC-XX` 로 고정합니다.
- 외부 네트워크와 사용자 홈에 의존하지 않습니다.
- optional ML 은 기본적으로 비활성화하고, 필요한 경우 별도 fixture 로 제한합니다.
- 실패 메시지는 어떤 사용자 시나리오가 깨졌는지 바로 알 수 있게 남깁니다.
