# 제안: delta/rollup extract 설계

> **상태: 구현 전 설계 초안.** 이 문서는 구현 예정 구조를 정의한다. 현재 동작은 `flow.md` 기준이며, 구현이 끝나면 이 문서의 결론을 `flow.md` 현재-동작 서술과 `HISTORY.md` 결정 로그로 옮긴다.
>
> 관련 문서: 저장 스키마는 `flow.md`의 "제안: search_entries 통합 스키마 초안", 결정 사유 로그는 `HISTORY.md`.

## 1. 문제

`/search`가 안정적으로 찾는 것은 `search_entries`에 올라온 정제 기억뿐이다. 그런데 "왜 이 코드가 이렇게 됐는지"의 구현 결정은 보통 **여러 turn에 걸쳐** 드러난다 (처음 A안 → 사용자 반박 → B안으로 수정 → 테스트). 현재 Stop extract는 **마지막 assistant 응답 1개만**(`stop.sh`가 `last`만, `extract_chunks_from_response(response[:8000])`) 보므로 이 arc를 입력으로 못 본다.

순진한 해법인 "Stop마다 최근 N turn window를 통째로 추출"은 실패한다:

```
같은 결정이 매 turn 조금씩 다른 문장으로 재추출
 → text_hash dedup(표시 text 기준)을 빠져나감
 → search_entries에 near-duplicate 누적
```

즉 필요한 것은 window 확장이 아니라 **cursor + cadence + 중복 정책**이다.

## 2. 핵심 결정 — A 대체 + 타입 분리

| 결정 | 내용 |
|---|---|
| 추출 방식 | **A 대체.** per-turn Stop은 저비용 flat 사실 이벤트만, decision-rich 합성은 delta/rollup만 담당 |
| 트리거 | **명시 명령 + SessionStart 보완.** native session-end hook이 없으므로 우회 |
| 중복 방지 | per-turn↔rollup은 **타입 분리로 구조적 차단**, rollup 재실행은 **atomic cursor**로 차단 (text_hash dedup에 의존하지 않음) |

**왜 A + 타입 분리가 깨끗한가 (핵심 근거):** per-turn은 `decision`을 절대 emit하지 않고 rollup은 `fix/command` 등을 emit하지 않는다. 두 경로가 **서로소(disjoint)인 타입 집합**을 다루므로 per-turn과 rollup 사이엔 애초에 같은 항목이 두 번 생길 수 없다. 남는 중복 위험은 "rollup이 같은 turn 범위를 재처리할 때"뿐이고, 이건 cursor 전진을 insert와 한 트랜잭션으로 묶어 막는다.

대안 B(per-turn decision 즉시 저장 + rollup이 supersede)는 신선도는 좋지만 supersede/validity 관리가 커진다. 제품 핵심이 "중복 없이 나중에 다시 찾는 구현 히스토리"이므로 단순한 A를 기본으로 하고, 신선도 요구가 생기면 B로 승격한다.

## 3. 선행 조건 — Stop event에 session_id 저장

현재 `stop.sh`는 stdin에서 session_id를 **파싱조차 안 하고**, llm_response INSERT에 `metadata_json`도 없다(`id, project_id, source, kind, text_clean, created_at`만). session 단위 rollup을 하려면 assistant event를 session으로 묶을 수 있어야 한다.

- stdin에서 `session_id → conversation_id → thread_id` 순서로 파싱 (UserPromptSubmit과 동일 fallback)
- INSERT에 `metadata_json` 추가, `{"session_id": "..."}` 형태로 저장
- **UPS user event와 동일 shape** — 기존 `json_extract(metadata_json, '$.session_id')` 쿼리(working overlay 등)가 user/assistant event를 균일하게 처리

## 4. cursor — `extract_state`

```sql
CREATE TABLE IF NOT EXISTS extract_state (
  project_id      TEXT NOT NULL REFERENCES projects(id),
  session_id      TEXT NOT NULL,
  last_created_at TEXT,            -- 마지막으로 처리한 event의 created_at
  last_event_id   TEXT,            -- 동일 created_at 충돌 방지용 tie-breaker
  last_rolled_at  TEXT,            -- 마지막 rollup 실행 시각 (관측용)
  PRIMARY KEY (project_id, session_id)
);
```

cursor는 `(last_created_at, last_event_id)` keyset이다. rowid는 VACUUM 시 재배정될 수 있어 cursor로 쓰지 않는다. 미처리 event 선택:

```sql
SELECT e.* FROM events e
WHERE e.project_id = :pid
  AND json_extract(e.metadata_json, '$.session_id') = :sid
  AND e.noise = 0
  AND ( e.created_at > :last_created_at
        OR (e.created_at = :last_created_at AND e.id > :last_event_id) )
ORDER BY e.created_at, e.id
LIMIT :batch
```

## 5. rollup 알고리즘 — bounded batch + atomic cursor

```
rollup(project_id, session_id):
  BEGIN
    cursor = extract_state[(pid, sid)]            # 없으면 (NULL, NULL) = 처음부터
    rows   = 미처리 event 선택 (위 쿼리, LIMIT N events, 누적 M chars 상한)
    if rows 비었으면: COMMIT; return
    window = rows로 user+assistant transcript 구성 (N events / M chars로 bounded)
    chunks = rich_extract(window)                  # decision/code_context/summary/note
    for c in chunks:
        insert_search_entry(
          origin=assistant_extract,
          raw_type=c.type,
          text=c.text, retrieval_text=surface(c),  # decision은 capped surface
          source_event_id = window의 마지막 assistant event id,
          metadata += {event_range:[first_id,last_id], rolled=true},
          redact 모두 통과)
    extract_state[(pid, sid)] = (이번 batch 마지막 row의 created_at, id), last_rolled_at=now
  COMMIT
  # backlog가 남았으면 다음 호출에서 이어서 처리 (cursor가 batch 끝까지 전진했으므로)
```

**불변식**
- insert + cursor 전진은 **한 트랜잭션**. 중간 실패 시 둘 다 롤백 → 다음 실행에서 같은 범위 재시도. idempotency는 dedup이 아니라 atomic cursor로 보장.
- 입력은 항상 bounded(N events 또는 M chars). 긴 세션은 batch당 cursor를 끝까지 전진시키고 backlog는 다음 실행에서 이어 처리한다. **K-turn 자동 처리는 이번 범위 밖**(긴 세션이 명시 rollup 없이 방치되면 backlog가 쌓일 수 있다는 점은 운영 한계로 수용).
- `source_event_id`는 batch의 마지막 assistant event를 가리켜 "원문 대화로 점프"의 앵커로 둔다. 전체 범위는 `metadata_json.event_range`에 보존.

## 6. 트리거

| 트리거 | 동작 |
|---|---|
| 명시 명령 (`scripts/imprint/rollup.sh --session-id <id>` / `python3 -m retrieval.cli rollup-session ...`) | 주어진(또는 현재) session의 backlog를 bounded batch로 처리. 필요 시 cursor가 따라잡을 때까지 반복. |
| SessionStart 보완 | **현재/재개 중인 session_id는 절대 처리 안 함.** 현재가 아닌 session 중 마지막 event가 **30분 이상** 지난 것만 stale로 보고 rollup. startup/resume/compact 모두 동일. |

**SessionStart 안전 규칙**
- `resume`/`compact`는 **같은 session_id**로 발화하므로, 보완 대상에서 현재 session_id를 반드시 제외한다 (재개 중인 세션을 도중에 rollup하지 않기 위함).
- SessionStart rollup은 rich extract(background model)를 호출하므로 **세션을 막으면 안 된다** → Stop extract처럼 **background로 spawn**하고 bounded로 둔다. 모델/의존성 부재 시 silent skip(hook 원칙).

stale 임계 30분은 상수로 두되 추후 env(`IMPRINT_ROLLUP_STALE_MINUTES` 등)로 노출 가능.

## 7. 타입 분리

| 경로 | cadence | 타입 | 프롬프트 |
|---|---|---|---|
| Stop per-turn (flat) | 매 turn | `fix` / `todo` / `command` / `error` / `test_result` | 기존 flat 프롬프트에서 rich 타입 제거 |
| Rollup (rich) | 명시 / SessionStart 보완 | `decision` / `code_context` / `summary` / `note` | cross-turn arc + decision-rich(reason/files/symbols/alternatives/tests) |

- **파서는 공유**(`extract_chunks_from_response`의 검증/literal-only/redaction 로직 재사용), **프롬프트와 cadence만 분리**.
- 두 타입 집합이 서로소이므로 per-turn↔rollup 중복이 구조적으로 불가능(§2 근거).
- decision-rich 필드·capped surface·literal-only files/symbols·redaction은 이미 구현된 경로(`build_retrieval_surface`, `insert_extracted_chunk`, `_safe_optional_list`)를 그대로 사용.

## 8. 이번 과제에서 제외 (별도 트랙)

- feature/file **boost** (retrieval 점수 조정)
- search **output grouping** (기획/결정/검증 묶음 출력)
- `feature_key` **자동 채움** (NER/entity 난제)
- `/search --events` (raw event 명시 조회)

이들은 retrieval/output 개선이라 추출 cadence와 직교한다. 지금 풀 문제는 "중복 없이 여러 turn의 구현 결정 arc를 정제해 `search_entries`에 올리기"다.

## 9. 구현 순서

1. **멀티턴 eval fixture baseline** — 여러 turn 구현 흐름 + "왜 B로 바꿨지" 질문 세트. per-turn 단독으로 baseline 측정 (fixture 작성은 의존 없음 → 먼저 시작 가능).
2. **이 설계 문서 박제** (현재 단계).
3. **Stop session_id metadata 저장** (§3).
4. **`extract_state` + bounded batch rollup 명령** (§4, §5, §6 명시 트리거).
5. **SessionStart stale session 보완** (§6, background·현재세션 제외·30분).
6. **Stop flat / rollup rich 프롬프트 분리** (§7).
7. **full A/B eval** — 같은 멀티턴 fixture에 per-turn vs rollup, decision/파일/테스트가 함께 회수되는지.

A/B 실행은 rollup(4)이 있어야 하므로, 1에서 baseline, 7에서 full 비교.

## 10. 후속/미결

- **B 승격 경로**: 신선도(결정 즉시 검색)가 필요해지면 per-turn decision 즉시 저장 + rollup supersede(validity)로 확장.
- **K-turn 자동 cadence**: 긴 세션 backlog 자동 처리가 필요해지면 도입.
- `feature_key`/`plan_key` 자동 채움, file/symbol `entry_entities` 정규화, boost/grouping, `/search --events`.
