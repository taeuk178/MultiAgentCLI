# TestCase — imprint 보편 사용 시나리오

이 문서는 imprint 플러그인의 보편 사용 케이스를 정의합니다. 각 케이스는
**입력 / 기대 결과 / 측정 항목 / pass 조건** 구조로 통일합니다. 자동화된 테스트
러너는 `scripts/imprint/tests/run_tests.py` 가 순차 실행하고 케이스당 ms / pass-fail /
counts 를 출력합니다.

테스트는 임시 `IMPRINT_HOME`(`mktemp -d` 결과) 에서 동작하므로 사용자의 실제
`~/.claude/imprint/app.sqlite` 에는 영향이 없습니다.

## 환경 변수

| 환경 변수 | 기본 (러너) | 의미 |
|---|---|---|
| `IMPRINT_DISABLE_EMBEDDING=1` | ON | sentence-transformers 미설치 환경 가정 |
| `IMPRINT_DISABLE_RERANK=1` | ON | cross-encoder 미설치 환경 가정 |
| `IMPRINT_DISABLE_NLI=1` | ON | transformers 미설치 환경 가정 |
| `IMPRINT_DISABLE_SUMMARY_LLM=1` | ON | summary 는 deterministic concat 으로 |
| `IMPRINT_DISABLE_NER_LLM=1` | ON | NER 는 LLM 호출 없이 skip (속도) |
| `IMPRINT_DISABLE_LLM_JUDGE` | OFF | contradiction LLM judge 만 활성 (실측) |

→ 즉 retrieval 의 결정적 path 는 모두 측정하고, contradiction LLM judge 만 실제
claude CLI 호출. 전체 케이스 합계 시간 < 60 s 목표.

## 케이스 목록

### TC-01. Save 짧은 텍스트 (단일 chunk)

**입력**: 한 문단 (~50자) 의 짧은 spec.
**기대 결과**:
- documents 1건 INSERT
- chunks_v2 1건 INSERT
- ingest_queue 에 J5 / J4 enqueue
**측정**: 실행 ms, chunk 수.
**pass 조건**: chunks_v2 = 1, documents = 1.

### TC-02. Save 긴 문서 (다중 chunk)

**입력**: H1 1개 + H2 3개 + 각 섹션 본문 ~200자 의 markdown PRD.
**기대 결과**:
- documents 1건
- chunks_v2 ≥ 3건 (heading 별 분리, target_tokens 600 안에서)
- 각 chunk 의 section_path 가 올바른 heading 경로
**측정**: 실행 ms, chunk 수, section 수.
**pass 조건**: chunks_v2 ≥ 3, distinct section_path ≥ 3.

### TC-03. Search 짧은 쿼리 (local scope)

**입력**: "test 버튼" (≤ 10자, entity alias).
**기대 결과**:
- scope 분류 = local (entity matched + 짧음)
- chunks_v2_fts 에서 매칭 chunk 회수
- summary 미사용
**측정**: 실행 ms, scope, chunk 수, alias resolve 수.
**pass 조건**: scope = local, candidates ≥ 1.

### TC-04. Search 긴 쿼리 (feature scope)

**입력**: "테스트 모드 진입 UX 시나리오 흐름 설명".
**기대 결과**:
- scope = feature (`UX` / `시나리오` / `흐름` 키워드)
- HYB2 가 feature summary 검색 (최대 5)
- HYB1 도 chunk 회수 (최대 8)
- summary_links 따라 GROUND drill-down 시도
**측정**: 실행 ms, scope, summary 수, chunk 수, ground_chunks 수.
**pass 조건**: scope = feature, summaries ≥ 1, chunks ≥ 1.

### TC-05. Search global 쿼리

**입력**: "이 프로젝트의 테스트 관련 정책 전체 정리해줘".
**기대 결과**:
- scope = global (`프로젝트` / `전체` / `정리` 키워드)
- HYB3 = project 1 + document 3 + feature 5 + chunk 6
**측정**: 실행 ms, scope, level 별 summary 수.
**pass 조건**: scope = global, level distinct ≥ 2 (project, document 또는 feature).

### TC-06. Entity alias 매칭

**입력**:
- 사전 등록 entity: `test_button` (canonical), aliases `test 버튼`, `디버그 토글` (둘 다 confirmed)
- 쿼리: "디버그 토글 누르면 어떻게 돼?"

**기대 결과**:
- resolved_entities 에 `test_button` 매칭
- chunks 에 BOOST_ENTITY 적용
**측정**: 실행 ms, resolved 수, matched_entities 수.
**pass 조건**: resolved entity 1+ AND matched_entities ≥ 1.

### TC-07. Document 갱신 + supersede

**입력**:
- 1단계: PRD ingest (3 chunk: A, B, C)
- 2단계: 같은 source_ref 로 변경된 PRD 재 ingest (2 chunk: A', C')
   - A 슬롯 본문 변경
   - B 슬롯 제거
   - C 슬롯 본문 변경

**기대 결과**:
- 1단계 후 chunks_v2 current=1 인 row 3건
- 2단계 후 A 슬롯과 C 슬롯은 UPDATE (is_current=1, valid_from 갱신), B 슬롯은 is_current=0 + valid_to
- 총 row 수는 그대로 3건
**측정**: 단계별 ms, current 수, valid_to 채워진 수.
**pass 조건**: 2단계 후 current=1 row 2건, current=0 row 1건.

### TC-08. Contradiction 감지 (LLM judge 실측)

**입력**:
- entity 등록 + 같은 entity_id 로 chunk_entities 링크
- 같은 section 의 decision 청크 2개:
  - "test 버튼 클릭 시 즉시 테스트 모드로 진입한다"
  - "test 버튼 클릭 시 확인 모달 후 테스트 모드로 진입한다"
- contradiction-scan 실행 (LLM judge 활성)

**기대 결과**:
- 후보 1쌍 생성
- LLM judge → contradiction (score ≥ 0.7) → status=candidate
- detector = "llm" (NLI 비활성이므로 LLM primary)
**측정**: 실행 ms (claude CLI 11~28s 예상), pairs_examined, pairs_inserted, status 분포.
**pass 조건**: contradictions 1건 INSERT, status = candidate, score ≥ 0.7.

### TC-09. 요청 중간 중단 (LLM timeout fallback)

**입력**:
- TC-08 와 같은 청크 페어
- `IMPRINT_LLM_JUDGE_TIMEOUT_MS=1` 로 LLM judge 강제 timeout
- NLI 도 비활성 → fallback chain 모두 실패

**기대 결과**:
- `_judge_pair` 가 rule weak signal + needs_retry=True 반환
- contradictions 에 status=candidate 로 저장 (다음 batch 재시도 트리거)
- detector = "rule"
**측정**: 실행 ms, status, detector.
**pass 조건**: status = candidate AND detector = rule.

### TC-10. 동시 ingest + priority 순서 drain

**입력**:
- 5개 항목 enqueue (priority 9 NER 2건 + priority 5 summary 2건 + priority 1 fetch 1건)
- drain 호출

**기대 결과**:
- drain 순서가 priority 1 → 5 → 9
- 모두 done 상태로 변경

**측정**: 실행 ms, drain 순서, done 수.
**pass 조건**: priority 1 항목이 가장 먼저 처리, priority 9 가 마지막.

## 측정 출력 형식

각 케이스 끝에 한 줄:

```
TC-XX  PASS|FAIL  XXXX ms  | <metric_summary>
```

전체 합계:

```
TOTAL  N PASS / M FAIL  XXXXX ms
```
