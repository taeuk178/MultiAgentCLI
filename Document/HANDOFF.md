# Handoff — 다음 세션 픽업

**문서 책임**
- 다음 세션에서 바로 볼 실행 항목과 운영 체크만 남깁니다.
- 큰 그림은 `LoadMap.md`, 결정 사유는 `HISTORY.md`, 상세 흐름과 테이블 역할은 `flow.md` 를 봅니다.

최종 업데이트: 2026-07-21.

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

## 발견된 미해결 이슈 — prefill 저관련 memory 주입 (2026-07-21 분석)

### 증상

질문과 무관한 memory 가 `[Retrieved memory]` 섹션으로 주입됩니다. 실제 관찰 사례:

- "imprint 활용 후기를 어떻게 쓰면 좋을까?" → SQLite 경로 디버깅 decision,
  search.sh 엣지 케이스 note 등 내부 구현 memory 주입.
- "memory 의 decision 이 왜 들어갔을까?" → Transformer positional encoding
  학습 노트 주입. 질문의 "memory", "decision", "맥락" 토큰이 저장 텍스트와
  어휘 겹침을 일으킨 것으로 추정.

주제(imprint)는 같지만 의도(후기 작성 vs 내부 디버깅)가 다른 경우를 구분하지
못하고, 일반어 토큰 하나만 겹쳐도 후보가 됩니다.

### 근본 원인

prefill 경로는 `/search` 의 hybrid 파이프라인(`retrieve.py`)을 쓰지 않습니다.

- `cmd_prefill` (`ingestion.py:1614`) → `retrieval_gate()` 통과 시
  `search_memory()` (`ingestion.py:1298`) 호출.
- `search_memory` 는 FTS5 hit 에 **일괄 2.0점**, metadata.keywords hit 에
  `1.0 + 0.5×hits`, LIKE fallback 에 1.5점을 주는 경량 스코어러입니다.
  임베딩·RRF·rerank 모두 없음.
- **절대 점수 하한이 없어** 키워드 하나만 겹쳐도 상위 8개
  (`PREFILL_CONTEXT_LIMIT`) 를 채웁니다.
- **무조건 fallback**: 매칭이 하나도 없으면 최신
  decision/fix/todo/note/spec/message/thread 를 관련성 없이 recency 순으로
  score 0.1 로 반환합니다 (`ingestion.py:1411`). "빈 결과를 내지 않도록" 이
  의도된 설계였으나 자동 prefill 에서는 이 의도 자체가 오주입 원인입니다.
- `retrieval_gate()` (`ingestion.py:1129`) 는 "왜/어떻게" 류 키워드 또는
  5개 이상 토큰이면 대부분 열리므로 관련성 판정 역할을 하지 못합니다.
- `retrieve.py` 의 `_low_confidence_reasons()` (top1 < 0.13,
  working_only, entity_mismatch 진단) 는 `/search` 경로 전용이며, 그마저도
  trace/CLI 출력용일 뿐 후보 제외에는 쓰이지 않습니다.
- profile 의 `retrieved_chunks` 는 dedupe/cap 적용 전에 계산되어 실제 포함
  수와 다를 수 있습니다 (`ingestion.py:1645` 부근).

즉 문제는 "top-1 점수가 낮다" 가 아니라 **관련 후보가 부족해도 슬롯을 끝까지
채우는 정책**입니다. 저신뢰 진단 인프라는 있으나 prefill 은 그 경로를 타지
않고, 타는 경로에는 진단 자체가 없습니다.

### 확정 해결 방향 (2026-07-21 리뷰 합의)

초기 A+B안(점수 임계값 + stopword 확장)은 리뷰를 거쳐 아래 안으로 교체했습니다.

1. **unpinned 최신 memory fallback 제거**
   검색 결과가 없으면 빈 결과가 정상입니다. `search_memory` 호출처는
   `cmd_prefill` 한 곳뿐임을 확인했으므로 제거 영향은 prefill 에 한정됩니다.
   명시 검색 요구는 `/search` 가 담당합니다.

2. **pinned 별도 조회 + relevance 필터 우회**
   현재 구현은 pinned 도 FTS 후보나 fallback 에 걸려야만 보여
   SKILL.md 의 "prefill hook always includes it" 계약과 어긋납니다
   (`skills/memory/SKILL.md:116`). pinned 를 별도 쿼리로 조회해 relevance
   필터 전에 합칩니다. 단 "항상 포함" 의 범위는 **무제한이 아니라
   "relevance 필터는 우회하되 전체 prefill limit 내에서 retrieved 슬롯을
   우선 점유"** 로 정의하고, SKILL.md 문구도 이에 맞춰 수정합니다.

   **pinned 조회는 `retrieval_gate()` 결과와 무관하게 항상 수행합니다.**
   gate 는 unpinned 검색만 제어합니다. "응" 같은 gate=False 질문에서도
   pinned 는 포함되어야 계약에 맞습니다. 조립 순서는
   **working → pinned → accepted unpinned** 이며 남은 전체 prefill 슬롯을
   순서대로 사용합니다. 같은 chunk 가 pinned 조회와 unpinned 검색 양쪽에
   나타나면 **pinned lane 이 이기고 unpinned 후보에서 제거**합니다 —
   dedupe 방향을 고정해야 `retrieved_included` 계산이 결정적이 됩니다.

3. **후보별 최소 근거 필터 (섹션 단위 생략 아님)**
   각 후보가 다음 중 하나를 만족할 때만 통과시킵니다.
   - **match_count ≥ 2** — match_count 는 원본 query 의 **distinct non-weak
     token 매칭 수**입니다. weak token 은 match_count 를 증가시키지
     않습니다.
   - 또는 **강한 식별자 1개**가 정확히 매칭
   - pinned 는 예외 (2번 경로로 이미 포함)

   필터는 **넉넉한 후보 pool 에 적용**합니다. 최종 출력 limit(8) 만 조회한
   뒤 필터하면 9번째 이후의 관련 후보를 놓치므로, `PREFILL_CANDIDATE_LIMIT`
   (기본 32, `IMPRINT_PREFILL_CANDIDATE_LIMIT` 환경변수로 오버라이드) 로
   후보를 조회해 필터한 뒤 최종 조립에서 `PREFILL_CONTEXT_LIMIT`(8) 로
   자릅니다.

   **LIKE 억제 해소**: 현재 LIKE 검색은 `if keywords and not seen`
   (`ingestion.py:1371`) 이라 FTS/metadata 후보가 하나라도 있으면 실행되지
   않습니다. 새 필터 도입 후에는 weak token 이 만든 무관한 FTS 후보가
   `seen` 을 채워 LIKE 를 막고, 그 FTS 후보가 필터에서 전원 탈락하면
   2글자 토큰으로만 찾을 수 있던 관련 후보를 회수할 기회 자체가 사라집니다
   (trigram FTS 는 3글자 미만 토큰을 매칭할 수 없음). 따라서:
   - **FTS, metadata.keywords, LIKE 는 모두 최종 필터 전 후보 생성
     경로**입니다. rejected FTS 후보가 존재한다는 이유로 LIKE 경로를
     생략하지 않습니다.
   - LIKE 실행 조건: **`accepted_unpinned < PREFILL_CONTEXT_LIMIT` 이고
     원본 query 에 길이 2인 non-weak token 이 존재**할 때. 길이 2 기준은
     한국어("버튼", "결제") 만이 아니라 **모든 스크립트**("UI", "DB",
     "PR") 에 적용합니다 — trigram 이 놓치는 것은 문자 수 기준이기
     때문입니다. 조립 상태와 독립적인 조건이므로 pinned 가 슬롯을 이미
     채운 경우 LIKE 가 불필요하게 실행될 수 있으나 정확성에는 영향이
     없고 비용은 profile 로 관찰합니다.
   - **LIKE 용 토큰은 원본 query 에서 추출한 2글자 non-weak token 을
     우선 구성**합니다. `prefill_keywords()` 앞 8개를 그대로 쓰면 긴
     질의나 rewrite term 이 한도를 차지해 정작 필요한 짧은 토큰이 빠질
     수 있습니다.
   - 실행 흐름: ① FTS + metadata 후보 생성 → ② 후보별 relevance 필터 →
     ③ 조건 충족 시 LIKE 실행 → ④ 후보 ID union/dedupe → ⑤ 전체 후보를
     다시 필터·정렬 → ⑥ **profile 의 found/accepted/skipped 는 최종
     union 기준으로 한 번만 계산**.

   세부 규칙:
   - **match_count 는 사용자가 직접 입력한 원본 토큰만** 셉니다.
     `deterministic_query_surfaces()` 가 만든 rewrite term (button,
     handler, action 등) 을 독립 hit 로 세면 사용자 토큰 하나가 여러 근거로
     부풀려집니다. rewrite token 은 후보 검색 확장과 BM25 정렬에만 쓰고
     통과 근거에서는 제외합니다.
   - **weak token** (memory, decision, context, 코드, 프로젝트명 등 저장
     텍스트에 편재하는 단어) 은 **match_count 에 포함하지 않습니다.**
     stopword 로 제거하는 것이 아니라 **후보 발견과 BM25 정렬에는 계속
     사용**하되 통과 근거만 되지 않는 토큰입니다. 이 정의로 "memory
     decision" 류 질의가 왜 거부되는지가 명확해집니다. 부수 효과로
     **weak token 만으로 구성된 질의는 unpinned 통과가 0 이 되는 것이
     의도된 동작**입니다 — 이런 회상형 질의는 `/search` 가 담당합니다.
   - **강한 식별자의 결정적 정의 (precision-first)**: 파일명, 경로,
     snake_case/camelCase 심볼, 버전, 이슈 키처럼 구조가 드러나는 토큰만
     인정합니다. "SQLite" 같은 일반 기술명은 강한 식별자로 보지 않고 다른
     의미 토큰 1개를 추가로 요구합니다.
   - **강한 식별자는 raw prompt 에서 추출합니다.** `TOKEN_RE`
     (`[가-힣A-Za-z0-9_]+`, `ingestion.py:78`) 는 `.`, `/`, `-` 를 토큰
     경계로 제거하므로 `foo.py`, `src/foo.py`, `ABC-123`, `v1.2.3` 구조가
     `prefill_keywords()` 결과에서는 사라집니다. 강한 식별자는
     `prefill_keywords()` 가 아니라 **raw prompt 전용 matcher** 로 추출하고,
     후보의 text / literal files / symbols / source URI 와 정확히 비교합니다.
   - **match_count 비교 표면**: 통과 근거로 인정하는 비교 대상은 후보의
     **원본 text 와 literal files/symbols 메타데이터만**입니다. 확장된
     `retrieval_text`, rewrite term, LLM 생성 keyword 는 후보 검색과 정렬에만
     쓰고 통과 근거 표면에서는 제외합니다.

4. **BM25 는 통과 후보 정렬에만 사용**
   FTS 결과를 최근순 대신 SQLite `bm25()` 순으로 정렬하는 것은 적용하되,
   BM25 절대값은 DB 크기·질의에 따라 달라지므로 절대 임계값
   (`IMPRINT_PREFILL_MIN_SCORE` 류) 으로는 쓰지 않습니다. 통과 여부는
   match_count 와 강한 식별자가 결정하고, BM25 는 순서만 결정합니다.

   BM25 값이 없는 metadata.keywords / LIKE 경로 후보를 포함한 전체 정렬
   기준: **강한 식별자 정확 매칭 우선 → match_count DESC → bm25 ASC
   (NULL last) → recency DESC**. 강한 식별자를 통과 기준에서 match ≥ 2 와
   동급 예외로 인정한 만큼 정렬에서도 1순위로 두어야 일관적입니다 —
   `foo.py` 정확 매칭 후보가 일반 토큰 2개 겹침 후보보다 뒤로 밀리면
   precision-first 와 모순됩니다. pinned 는 이 정렬 전에 별도 lane 으로
   처리합니다.

5. **low-relevance 는 조용히 생략 + profile 기록**
   - 기존 gate skip 문구 `(retrieved-memory search skipped: ...)` 는 그대로
     유지합니다. 새 low-relevance skip 문구는 prompt 에 추가하지 않습니다.
     gate 문구 제거 여부는 별도 관측성 정리 작업으로 분리합니다.
   - profile 관측값 (모두 정수 개수). **pinned 와 unpinned 는 lane 을
     분리**합니다 — pinned 는 필터를 우회하므로 accepted 에 섞으면
     gate=False + pinned 케이스에서 `skipped = 0 − 1 = −1` 이 됩니다.
     - `pinned_found`: 별도 조회된 pinned 수
     - `retrieved_found`: unpinned 검색 후보 수 (pool 조회 기준)
     - `retrieved_accepted`: 필터를 통과한 unpinned 수
     - `retrieved_skipped_low_relevance` = `retrieved_found` −
       `retrieved_accepted` (unpinned lane 전용이라 항상 ≥ 0)
     - `retrieved_included`: pinned + accepted unpinned 중 dedupe·cap 후
       실제 prefill 포함 수
     - 후보별 `matched_term_count`
     - 기존 `retrieved_chunks` 는 호환을 위해 유지하되
       `retrieved_included` 와 같은 값으로 정정합니다.

hook 원칙은 그대로 유지합니다 — 필터 미달·검색 실패 어느 경우에도 stdout 은
정상 흐름을 출력하며, 섹션 생략은 정상 흐름의 일부입니다.

### 기각·보류된 대안

- **C안 (prefill 을 `chunk_retrieve()` hybrid 로 교체)**: 기각.
  ① `BOOST_CURRENT=0.15` 가 `LOW_CONFIDENCE_TOP1=0.13` 보다 커서 무관한
  current 후보도 하한을 넘기 쉽고 (`retrieve.py:40,64`), ② hook 은 매
  prompt 별도 Python 프로세스라 embedding/rerank 모델 캐시가 유지되지 않아
  foreground cold-load 가 반복되며, ③ hybrid 경로 자체도 무관 결과를
  반환한 사례가 있어 별도 relevance calibration 이 선행돼야 합니다.
- **precision-first 모드** (자동 prefill 은 Session memory + pinned 만,
  persistent memory 는 "전에/지난번/기억" 류 회상 의도가 있을 때만 검색):
  오주입은 거의 사라지지만 자동 회수율이 낮아지므로 기본 정책 변경은 제품
  방향 결정이 필요합니다. 보류.
- **중기 과제**: `retrieve.py` 에서 embedding/rerank 를 끈 lexical-only
  함수를 분리해 prefill 과 `/search` 가 BM25·후보 조립 로직을 공유. 이번
  최소 수정 범위를 넘으므로 후속 작업으로 둡니다.

### 검증 시나리오

테스트 fixture 최소 구성:

1. 부정: "imprint 활용 후기를 어떻게 쓰면 좋을까?" — 무관 memory 미주입.
2. 부정: "memory 의 decision 이 왜 들어갔을까?" — 어휘 겹침만으로 미통과.
3. 긍정: "SQLite 경로 어떻게 정리했었지?" — 관련 decision 회수 유지.
4. rewrite 비가산: rewrite term 으로 후보는 발견되지만 원본 근거가
   부족하면 필터됨.
5. 긍정: 원본 의미 토큰 2개가 직접 매칭되면 정상 통과.
6. 무매칭: 최신 unpinned memory 가 fallback 으로 주입되지 않음.
7. pinned: relevance 하한과 무관하게 포함되되 prefill limit 은 준수.
8. pinned + gate=False: "응" 같은 backchannel 질문에서도 pinned 는 포함됨.
9. FTS 실패: hook exit 0, 정상 stdout 유지.
10. 부분 채움 방지: 정상 후보 뒤 남은 슬롯을 무관 후보로 채우지 않음.
11. 강한 식별자 (parameterized): `foo.py`(파일명), `src/foo.py`(경로),
    `ABC-123`(이슈 키), `v1.2.3`(버전) **네 유형 각각**에 대해 raw prompt
    matcher 로 발견되고 정확 매칭 후보만 통과함 — 서로 다른 matcher 분기를
    사용하므로 "중 하나" 로는 커버리지가 성립하지 않음
    (`prefill_keywords()` 토큰화로는 유실되는 케이스).
12. profile 정합성: gate=False + pinned / unpinned 필터 탈락 / cap 발생
    각각에서 모든 count 가 음수 없이 계산식과 일치함.
13. LIKE 억제 해소: 무관한 FTS 후보가 먼저 발견됐지만 필터에서 탈락하고,
    2글자 원본 non-weak token 으로 찾은 관련 LIKE 후보는 정상 통과함.

공통: `python3 scripts/imprint/tests/run_tests.py` 기준선 유지.
배포 후 `IMPRINT_PROFILE=1` 로 며칠 운용하며 found/accepted/included/
skipped 분포로 필터 강도를 조정합니다.
