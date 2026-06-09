# Handoff — 다음 세션 픽업

**문서 책임**
- 다음 세션에서 바로 볼 실행 항목과 운영 체크만 남깁니다.
- 큰 그림은 `LoadMap.md`, 결정 사유는 `HISTORY.md`, 상세 흐름과 테이블 역할은 `flow.md` 를 봅니다.

최종 업데이트: 2026-05-30.

## 현재 동작 요약

- 자동 hook 루프: `SessionStart → UserPromptSubmit → Stop → 다음 UserPromptSubmit`.
- 수동 저장/검색: `/remember`, `/search`, `/memory search/list/show/inject/refresh/forget/stats/profile/status`.
- persistent memory 는 `search_entries` 단일 인덱스에 저장됩니다.
- Stop hook 은 assistant 응답을 `events` 에 archive 만 합니다. per-turn flat extract 는 최소 RAG 검증을 위해 제거했고, 검색용 구현 기억은 delta/rollup 이 담당합니다.
- 구현 중 여러 turn 에 걸친 decision/code_context/summary/note 는 delta/rollup 으로 `search_entries` 에 정제 저장되고, `/search` 는 `reason/files/symbols/tests/event_range` detail 을 출력합니다.
- `/search` 는 같은 주제의 `/remember` 와 rollup row 가 함께 있을 때 역할을 분리합니다. 큰 틀/정책/요약 질문은 `manual_remember` 를 `canonical_memory` 로 앞세우고, 왜/어떻게/구현/파일/테스트 질문은 rollup row 를 `rollup_evidence` 로 앞세웁니다.
- 긴 `/remember --stdin` 입력은 `chunk_group_id` 로 묶인 여러 `search_entries` row 로 분할 저장됩니다. `/search` 최종 후보는 같은 그룹을 최대 2개까지만 보여주며, `/memory forget --group <id-or-group-id>` 로 묶음 삭제가 가능합니다.
- Claude Code 는 stale session 중심으로 rollup 하고, Codex App 은 compact 때 current session 이 idle 조건을 만족하면 1 batch guarded rollup 을 추가합니다.
- vector 검색은 기존 entry 의 경우 `imprint setup vector --backfill` 로 `search_entries.embedding` 을 채운 뒤 참여합니다. 새 rollup entry 는 vector 설치 환경에서 자동 embedding 됩니다.
- 선택 ML 의존성이 없어도 FTS5/LIKE fallback 으로 동작해야 합니다.

최근 검증 기준:

```text
python3 scripts/imprint/tests/run_tests.py
TOTAL  36 PASS / 0 FAIL
```

테스트는 임시 `IMPRINT_HOME=/tmp/...` 에서 실행합니다. 사용자 홈 `~/.imprint` 직접 수정은 명시 동의 전까지 하지 않습니다.

## 다음 우선순위

1. **delta/rollup eval 세트 구성**
   실제 사용 시나리오에 가까운 multi-turn fixture 를 10~20개 고정합니다. 예: "처음 A안 → 사용자 반박 → B안 결정 → 파일 수정 → 테스트 통과" 흐름을 만들고, `/search "왜 B로 바꿨지?"` 가 `decision + reason + files/symbols + tests` 를 회수하는지 봅니다. flat extract 를 제거했으므로 eval 은 반드시 rollup 실행 후의 `search_entries` 를 기준으로 합니다.

2. **rollup freshness 운영 기준**
   현재 rollup 은 Claude Code 에서는 stale session 또는 명시 명령 중심이고, Codex 에서는 compact current-session guarded rollup 을 추가합니다. 구현 직후 바로 검색해야 하는 요구가 반복되면 `rollup.sh --latest --all` 를 UX 상 어디에 노출할지, 또는 긴 세션용 K-turn 안전밸브를 둘지 결정합니다. 단, per-turn extract 를 되살리기보다 rollup trigger/cadence 를 조정하는 방향을 우선합니다.

3. **rollup entry 품질 보강**
   결정 하나에 `reason/files/symbols/tests/alternatives/event_range` 가 함께 묶이는지 확인합니다. 부족하면 prompt 와 capped `retrieval_text` surface 를 조정하고, 파일/심볼은 환각 방지를 위해 transcript 에 literal 로 등장한 문자열만 허용하는 현재 원칙을 유지합니다.

4. **rollup origin 명칭 정리 검토**
   현재 rollup 결과는 기존 schema 호환 때문에 `origin=assistant_extract` 로 저장됩니다. 동작 문제는 없지만 flat extract 를 제거한 뒤에는 `origin=rollup_extract` 가 더 정확합니다. migration 영향이 있으므로 지금은 문서에 legacy origin 으로 명시하고, 다음 schema 변경 때 rename 또는 alias 를 검토합니다.

5. **개념 질의 eval 세트 구성**
   "로그인 feature 의 공유하기는 어떻게 구현됐었지" 같은 자연어 질문 20~30개를 고정합니다. `/remember` 로 선별 저장한 기억이 `/search` 에서 어떻게 회수되는지 보고, 내부 retrieval JSON trace 의 `embedding_used`, `vector_rank`, top1 score, fallback 이유를 같이 기록합니다.

6. **`/search` confidence 표시 기준**
   현재 confidence 는 확률이 아니라 내부 휴리스틱입니다. `/search` 는 세부 근거 detail 을 이미 출력하므로, eval 결과를 본 뒤 `evidence_strength=strong|medium|weak` 또는 calibrated numeric score 로 표현할지 결정합니다. 출력에는 숫자만 두지 말고 weak/medium 의 이유도 함께 보여줘야 합니다.

7. **운영 피드백 수집**
   vector setup, FTS fallback, profile 로그에서 반복 실패나 지연 신호가 있는지 확인합니다. 바로 기능을 늘리기보다 trace/profile 데이터로 먼저 판단합니다.

## 확인 체크리스트

- 새 세션 시작과 compact 직후 `SessionStart` 가 스키마 적용과 `Guardrail.md` prepend 를 조용히 수행하는지.
- Codex compact 에서는 current session guarded rollup 이 idle 조건에서만 실행되고, Claude Code compact 에서는 current session 이 계속 제외되는지.
- 질문 직후 `[Project memory context]` 가 query/session/retrieved/external section 으로 나뉘는지.
- Stop 이후 `events.llm_response` 에 session_id metadata 가 저장되고, 별도 flat search entry 가 생기지 않는지.
- opt-in external fetch 는 `IMPRINT_ENABLE_LAZY_FETCH=1` 또는 `/memory refresh <url>` 일 때만 후보로 보이는지.
- `/search` 가 `search_entries` 를 primary 로 읽고 `source_status` marker 를 제외하는지.
- rollup decision 후보가 `/search` 에서 `reason/files/symbols/tests/event_range` 를 함께 보여주는지.
- vector 설치 환경에서 새 rollup entry 가 자동 embedding 되고, 기존 entry 는 `setup vector --backfill` 로 채워지는지.
- 같은 주제의 `/remember` 와 rollup 후보가 공존할 때 큰 틀 질문은 `canonical_memory`, 구현 질문은 `rollup_evidence` 를 먼저 보여주는지.
- `imprint setup vector --status/--install/--warmup/--backfill` 이 한국어 진행 로그와 실패 힌트를 화면과 `plugin.log` 양쪽에 남기는지.

## 관찰 지표

`IMPRINT_PROFILE=1` 로 `~/.imprint/profile.jsonl` 을 누적한 뒤 `/memory profile --json` 과 `/memory status --json` 으로 확인합니다.

- `cmd_prefill`: working/retrieved count, retrieved-memory search skip 사유, context section count.
- `retrieve_done`: query surface 수, fallback 여부와 이유, rerank gate 사유.
- `stop.transcript_reparse`: 긴 세션에서 증가하는지.
- `call_claude`: background 모델 호출 RTT 와 timeout 빈도.
- `fetch_notion_url.payload`, `fetch_slack_url.payload`: opt-in external fetch 를 켠 경우 큰 payload 반복 여부.

DB 관찰:

```sql
SELECT noise, COUNT(*) FROM events GROUP BY noise;
SELECT raw_type, COUNT(*) FROM search_entries GROUP BY raw_type;
SELECT json_extract(metadata_json, '$.status'), COUNT(*)
FROM search_entries
WHERE raw_type = 'source_status'
GROUP BY 1;
```

## 다음 세션 시작 순서

1. `git status -sb` 로 작업 상태 확인.
2. `python3 scripts/imprint/tests/run_tests.py` 로 기준선 확인.
3. `imprint setup vector --status` 로 벡터 런타임 상태 확인.
4. 실제 프로젝트에서 개념 질의 1~2개로 `/search` 출력과 trace 의 `embedding_used` 확인.
5. `/memory status --json`, `/memory profile --json`, `plugin.log` 로 실패/지연 신호 확인.

## 발견된 미해결 이슈 — SKILL.md dispatcher 환경변수 부재 (2026-06-09 분석)

### 증상

imprint repo 가 아닌 다른 프로젝트(예: NudgeEAP-iOS)에서 `/imprint:search` 또는
`/imprint:remember` 를 실행하면 다음 에러가 납니다.

```
Bash(bash scripts/imprint/search.sh "..."): Exit 127, No such file or directory
DISPATCHER=/scripts/imprint/search.sh
ls: /scripts/imprint/search.sh: No such file or directory
not found
```

### 근본 원인

설치된 skill 의 SKILL.md 가 다음 패턴으로 dispatcher 를 구성합니다.

```bash
DISPATCHER="${IMPRINT_PLUGIN_ROOT:-${PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}}}/scripts/imprint/search.sh"
```

Claude Code 가 skill bash 호출에 넘기는 환경에는 위 네 변수 중 **어느 것도 설정되어
있지 않습니다.** 확인 시 `env | grep -iE "claude|imprint|plugin"` 결과에 `CLAUDE_PLUGIN_DATA`
는 있지만 `CLAUDE_PLUGIN_ROOT` 는 없습니다 (Claude Code 2.1.169 기준).

네 변수가 모두 빈 문자열이면 `${var:-…}` 체인은 마지막에 빈 문자열을 그대로 사용하고
결과적으로 `DISPATCHER=/scripts/imprint/search.sh` (filesystem root 의 절대경로) 가
됩니다. 이 경로는 존재하지 않으므로 `ls` 와 `bash` 모두 실패합니다.

`bash scripts/imprint/search.sh ...` 직접 호출 역시 imprint repo 가 아닌 PWD 에서는
상대경로가 깨져 동일하게 실패합니다. imprint repo 내부에서만 우연히 동작했기 때문에
지금까지 발견이 늦었습니다.

### 영향 범위

같은 dispatcher 패턴을 사용하는 모든 skill:

- `skills/search/SKILL.md`
- `skills/remember/SKILL.md`
- `skills/memory/SKILL.md`
- `skills/setup/SKILL.md`
- `skills/hud/SKILL.md`

imprint repo 외부의 모든 프로젝트에서 5 개 명령이 동일한 증상을 보입니다.

### "에러는 아니지만 헷갈리는" 부수 신호

진짜 에러는 위의 dispatcher 부재이지만 `~/.imprint/plugin.log` 에는 매 session-start
마다 다음 WARN 이 반복 기록되고 있어 사용자가 별개의 문제로 오해할 수 있습니다.

```
WARN: embedding model load failed: ModuleNotFoundError("No module named 'sentence_transformers'") — falling back to FTS-only
WARN: cross-encoder load failed: ModuleNotFoundError("No module named 'sentence_transformers'") — rerank disabled
```

이쪽은 graceful degradation 이며 `imprint setup vector --install --warmup --backfill`
로 별도 해결합니다. dispatcher 버그와는 무관합니다.

### 해결 방향 후보

| 안 | 설명 | 트레이드오프 |
|---|---|---|
| A | SKILL.md 에 glob fallback 추가: `$(ls -d "$HOME"/.claude/plugins/cache/imprint/imprint/*/scripts/imprint/<cmd>.sh \| sort -V \| tail -1)` 형태로 latest install 을 탐색 | 즉시 동작, 설치 변경 불필요. Codex 경로도 같이 탐색해야 양 host 호환. |
| B | `imprint setup` 단계에서 `~/.imprint/plugin-root` marker 에 plugin root 절대경로를 기록하고 SKILL.md 는 이 파일을 읽음 | 깔끔하지만 setup 변경과 설치 순서 의존성 추가. |
| C | `bin/` 에 `imprint-search` / `imprint-remember` 등 shim 을 두고 PATH 에 의존 (PATH 에는 이미 `imprint/0.2/bin` 이 들어가 있음) | 가장 정석적이지만 bin shim 다섯 개 신규 추가 필요. 현재 bin 디렉터리는 비어 있음. |

권장은 **A 안 즉시 적용 + B 안 또는 C 안 후속**입니다. A 안만으로도 사용자 환경에서
다음 세션부터 다섯 개 skill 이 정상 동작하게 됩니다.

### 검증 시나리오

수정 후 다음을 확인합니다.

1. imprint repo 가 아닌 임의 디렉터리(예: `~/Desktop/Develop/NudgeEAP-iOS`)에서
   `/imprint:search "테스트 쿼리"` 가 exit 0 으로 grounding chunks 를 출력하는지.
2. Codex 환경(CODEX_PLUGIN_ROOT 만 있는 경우 등)에서도 동일하게 동작하는지.
3. 환경변수가 모두 설정된 정상 케이스에서 기존 동작에 회귀가 없는지.
4. `imprint repo` 안에서 `bash scripts/imprint/search.sh "..."` 직접 호출 흐름은
   여전히 정상인지 (SKILL.md 변경이 직접 호출 경로에는 영향 없음).
