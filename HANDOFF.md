# Handoff — 다음 세션 픽업

**문서 책임**
- 본 문서는 **단기**: 즉시 다음에 손댈 검토 안건, deferred TODO, 측정 후 캘리브레이션 항목, 다음 세션 시작 시 픽업 지점만 담는다.
- **큰 그림**(비전·아키텍처·남은 단계·위험 요소)은 `LoadMap.md` 참조.
- **결정 사유 로그**(왜 그렇게 바꿨는지·폐기한 대안)는 `HISTORY.md` 참조.
- 구현된 동작·설치·전체 플로우 다이어그램은 `README.md` 참조.

최종 업데이트: 2026-05-16.

## RAG 기본 동작 안정화 우선순위

목표는 기능 확장보다 먼저 **실제 프로젝트에서 기억이 저장되고, 다시 검색되며, 사용자가 답변 근거로 참고할 수 있는지**를 확인하는 것. 2026-05-16 에 redaction coverage, 자동 memory loop smoke test, 기본 읽기 경로 안내, 검색 fixture 는 1차 적용 완료. 다음 PR 은 아래 순서로 진행.

1. **외부 source 갱신/누락 가시화**
   Slack/Notion URL cap 초과, stale `fetched_at`, fetch 실패를 사용자가 볼 수 있게 `plugin.log` 또는 `/memory show/list` 에 표시. 자동 refresh 보다 “지금 참조한 기억이 낡았는지 알기”가 먼저.

2. **읽기 경로 수렴**
   단기 안내는 적용 완료: 기본 사용자 RAG는 자동 prefill + `/memory search/inject`, `/retrieve` 는 `chunks_v2` 문서 retrieval. 남은 결정은 `memory_chunks → chunks_v2` bridge 또는 `/retrieve` 의 legacy `memory_chunks` fallback 중 하나.

3. **노이즈 turn soft filter**
   `events.noise=1` 플래그부터 도입. 삭제가 아니라 표식만 붙여 RAG 후보 품질과 DB 증가량을 관찰한다.

4. **측정 후 캘리브레이션**
   `IMPRINT_PROFILE=1` 로 한 주 데이터 수집 후 latency budget, contradiction 임계, daemon 분리, summary 생성 품질을 판단한다.

5. **후순위 기능 확장**
   Workflow skill(`/commit-message`, `/pr-draft`, `/recap`, `/handoff`), registry, entity merge/split UI 는 RAG 기본 저장/검색 루프가 안정된 뒤 진행.

## 보안 — Redaction coverage 갭 (2026-05-11 관찰)

**현상**. 사용자가 GitHub token 관련 대화를 한 turn 에서 token 문자열이 events 테이블에 raw 로 저장된 사례가 관찰됨. 토큰 형식(`gh[pousr]_...`)이 `redact-rules.default.json` 의 default 룰에 일치함에도 불구하고 redaction 이 적용되지 않음.

**원인**. `redact_text` (`lib/common.sh:96`) 가 호출되는 곳은 `/memory remember --redact` 옵트인 경로 한 군데뿐 (`memory.sh:85`). raw 저장하는 두 INSERT path 는 redaction 을 거치지 않음.

- `user-prompt-submit.sh:47-50` — `events.kind='user_message'` INSERT (사용자 prompt 원문)
- `stop.sh:120-123` — `events.kind='llm_response'` INSERT (assistant 응답 원문)
- `stop.sh:131` 뒤의 chunk extraction path 도 raw 텍스트를 stdin 으로 넘김 — `lib/ingestion.py extract` 가 자체 redaction 을 하지 않으면 chunk 단계까지 누출 전파.

`sql_escape` 는 SQL injection 방지(작은 따옴표 escaping)이지 redaction 이 아님.

**우선순위**. 실제 token 누출이 관찰된 회귀이므로 기능 확장 진입과 무관하게 별도 패치로 처리. TODO 3 의 "보안·운영 인터뷰" 라운드 안건이지만, 인터뷰 없이 결정 가능한 단순 갭 (호출 지점 추가 + 패턴 보강) 부분만 먼저 진입 가능.

**대응 후보**.

1. **자동 redaction 진입점 통합** *(가장 단순)*

   `user-prompt-submit.sh` 와 `stop.sh` 에서 `db_exec` INSERT 직전에 `text=$(redact_text "$text")` 한 줄 추가. ingestion.py extract 진입 직전(`stop.sh:128-129` 의 `TMP_BG` 작성) 에도 같은 줄 추가. 호출 비용은 python3 spawn 1 회 / turn — 동기 hook 안에서 이미 다른 python3 spawn (transcript 재파싱) 이 일어나므로 추가 영향은 ms 단위.

   - **왜 이 안인가**: 코드 변경 ~3 줄, 회귀 위험 0 (모든 raw 경로가 같은 룰셋을 통과). simplicity first.
   - **트레이드오프**: 정규식 false positive 로 정상 문자열이 마스킹될 수 있음 — 룰셋이 보수적인 패턴(접두사 + 길이) 만 잡고 있어 실 사용에서 false positive 는 드묾.

2. **default 룰셋 보강** *(병행)*

   현재 default 룰셋(`lib/redact-rules.default.json`) 에 누락:
   - **GitHub fine-grained PAT**: `github_pat_[A-Za-z0-9_]{80,}` — 현 `gh[pousr]_` 룰이 못 잡음.
   - **비밀번호 키워드 컨텍스트**: `(password|pw|비밀번호|passwd)\s*[:=]\s*\S+` — 자유 텍스트 안의 비밀번호 노출.
   - **신용카드 16자리 + Luhn 검증**: 네 묶음 4자리 (`\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}`) + Python re.sub callback 에서 Luhn 체크로 false positive 억제.
   - **한국 주민등록번호**: `\d{6}-\d{7}`.
   - **bearer / authorization 헤더**: `(?i)bearer\s+[A-Za-z0-9._-]{20,}` · `(?i)authorization:\s*\S+`.

   사용자 정의 추가 경로(`~/.claude/imprint/redact-rules.json` 우선) 는 이미 있어 룰 파일만 갱신.

3. **schema-side trigger** *(보류, 측정 후)*

   SQLite trigger 로 `events` / `memory_chunks` INSERT 시 redaction 강제. 호출 경로 누락에 대한 영구 방어지만, SQLite 안에서 정규식 호출은 추가 확장(`sqlite3_create_function`) 이 필요해 의존성 증가. 1+2 로 충분히 흡수되면 영구 보류.

**다음 액션**.

- 기본 저장 진입점 redaction 과 default 룰셋 보강은 2026-05-16 에 적용 완료.
- 남은 운영 액션: 기존 사용자 DB의 `events` / `memory_chunks` 에 이미 들어간 token-shaped 문자열은 사용자 승인 하에 별도 청소.
- 필요 시 다음 개선: card-like 패턴을 Luhn callback 기반 redaction helper 로 고도화해 false positive 를 줄임.

## events 노이즈 누적 갭 (2026-05-11 관찰)

**현상**. `events` 테이블이 모든 turn 의 사용자 prompt 와 assistant 응답을 raw 로 저장. `user-prompt-submit.sh:36` 의 필터는 공백만 있는 빈 문자열 한 가지만 거름. "응", "맞아", "커밋해줘" 같은 짧은 confirm/backchannel turn 도 무필터로 INSERT 되어, 시간이 지나면 events 상당 부분이 의미 없는 noise turn 으로 채워질 수 있음.

**파급**.

- 노이즈 turn 자체는 `memory_chunks` 가 LLM 필터링을 거치므로 retrieval 품질에는 직접 영향 없음.
- 다만 (a) 디스크 사용량 단조 증가, (b) 짧은 confirm prompt 에도 사용자가 무심코 token / 비밀번호를 붙여 넣을 수 있어, 위 "보안 — Redaction coverage 갭" 과 결합 시 누출 표면이 확대.

**학계 표준 — raw 보존 + soft filter**. 노이즈 turn 을 "삭제" 하기보다 "감쇠/플래그" 로 다루는 게 주류 (Sources 참조).

- **MemGPT** (Packer et al., arXiv 2310.08560) — virtual context management, archival vs recall tier 분리. raw 는 cold storage 보존.
- **MemoryBank** (Zhong et al., AAAI 2024, arXiv 2305.10250) — Ebbinghaus forgetting curve `R = exp(-t/S)`. 재호출되면 strength 증가, 안 쓰이면 자연 감쇠.
- **Generative Agents** (Park et al., 2023) — LLM 이 1~10 점 importance scoring. 검색 점수 = `α·recency + β·relevance + γ·importance`. "응" 같은 turn 은 자연히 1~2 점.
- **Backchannel/continuer 언어학** (Yngve 1970, Schegloff 1982) — non-lexical("uh-huh") / phrasal("yeah", "ok") / substantive(repeat) 3분류. 길이 + 정규식만으로 정확도 매우 높음.
- **LongMemEval / LoCoMo** (arXiv 2410.10813, 2402.17753) — 두 벤치마크 모두 distractor session 의도적 혼입. "노이즈 제거" 가 아닌 "노이즈가 있어도 정답 찾기" 로 평가.

공통 결론은 imprint 의 `memory_chunks` (LLM 필터) + `events` (raw) 2-tier 가 이미 표준과 동일 구조라는 점. 추가할 것은 events tier 에 soft filter 한 겹.

**대응 후보 — 3 단계 점진 도입**.

1. **Stage 1 — Backchannel rule filter** *(즉시, 무비용)*

   `user-prompt-submit.sh:36-50` INSERT 직전에 (a) backchannel 정규식 매칭, (b) `len(prompt) < 20`, (c) 직후 Stop hook chunk 추출 결과 0 개 의 세 조건 동시 만족 시 `events.noise=1` 플래그 (삭제 아님, 표식). 정규식 예: `^(응|네|ㅇㅇ|좋아|그래|맞아|커밋해줘|ok|yes|yeah)\W*$`.
   - **왜 이 안인가**: 코드 변경 ~10 줄, schema 마이그레이션 1 컬럼. Yngve/Schegloff 전통의 phrasal continuer 와 정확히 부합 — false positive 거의 없음.
   - **트레이드오프**: "응" + 긴 follow-up 한 줄짜리 prompt 는 정상 통과. 짧은 confirm 만 표식.

2. **Stage 2 — Forgetting curve soft delete** *(가벼움)*

   `events` 에 `score REAL DEFAULT 1.0`, `last_accessed TEXT` 컬럼 추가. retrieval hit 시 reinforce (`score *= 1.2`, `last_accessed = now`), 미접근 시 자연 감쇠 (cron 으로 `score *= exp(-age_days / S)`). `score < threshold AND age > 30d AND noise=1` 인 행만 hard delete — 의미 있는 raw 는 score 가 자연 유지되어 영구 보존.
   - **왜 이 안인가**: MemoryBank 식. raw 보존 철학을 깨지 않으면서 "오래 안 쓰인 노이즈" 만 정리. cron 1 회 / 주.
   - **트레이드오프**: 새 컬럼 + cron job 추가. retrieval 경로에 reinforce 호출 한 줄 필요.

3. **Stage 3 — Importance scoring** *(선택, 보류 우세)*

   Stop hook 의 chunk 추출 LLM 호출에 piggyback 으로 1~10 점 importance 를 요청. Generative Agents 식. 다만 `memory_chunks` 가 이미 의미 단위 추출을 하고 있어 ROI 낮음 — chunk 추출 결과가 0 개면 사실상 "중요도 1점" 으로 간주해도 무방. Stage 1+2 효과가 부족한 시점에만 진입.

**보류 — 결이 안 맞는 접근**.

- **LLMLingua / recursive summarization** — turn 단위 보존 철학과 결이 다르고 (information lossy, debug 가독성 손해), backchannel 압축은 0bit → ROI 0.
- **A-MEM dynamic linking** — 단일 사용자·단일 프로젝트 로컬 메모리 규모에서는 과잉 (Zettelkasten 식 동적 link 가 가져올 가치보다 복잡도가 큼).

**도메인 분리 가정**. 현재 schema 는 `project_id` 한 축으로만 분리 — 한 project 안의 모든 events 가 단일 풀이고 명시적 `domain` 컬럼은 없음. Stage 1·2 의 noise 플래그·forgetting curve 도 project 단위 단일 정책으로 설계. 도메인별 차등 정책 (예: "인프라" 주제는 오래 보존, "잡담" 은 빨리 잊기) 이 명확히 필요해지는 시점에는 두 가지 길:

- **간접 path (권장)** — `chunk_entities` / `summaries.target_key` (Phase 7b feature 단위) 와 join 해서 retrieval reinforcement 가 feature-summary 를 거치게 만듦. 새 컬럼 없이도 events.score 가 자연스레 도메인 가중을 반영.
- **직접 path (보류)** — `events.domain TEXT NULL` 컬럼 추가. 다만 도메인 자동 분류 자체가 별도 LLM/룰 작업을 요구하고, summaries 의 feature-level 이 이미 동일 역할을 하므로 중복. 명확한 사용 사례가 나오기 전엔 보류.

**다음 액션**.

- Stage 1 (rule filter + `noise` 컬럼) 을 별도 PR — 코드 ~10 줄, schema 마이그레이션 1 컬럼.
- Stage 1 머지 후 1~2 주 데이터 (`SELECT count(*) FROM events WHERE noise=1` 비율) 보고 Stage 2 진입 여부 결정.
- Stage 3 는 Stage 2 효과가 부족한 시점에만 검토 — 영구 보류 가능.

**Sources**.

- [MemGPT (arXiv 2310.08560)](https://arxiv.org/abs/2310.08560)
- [MemoryBank (arXiv 2305.10250)](https://arxiv.org/abs/2305.10250)
- [Generative Agents (Park et al. 2023)](https://3dvar.com/Park2023Generative.pdf)
- [LongMemEval (arXiv 2410.10813)](https://arxiv.org/pdf/2410.10813)
- [LoCoMo (arXiv 2402.17753)](https://arxiv.org/abs/2402.17753)
- [Backchannel — Wikipedia (Yngve 1970)](https://en.wikipedia.org/wiki/Backchannel_(linguistics))
- [Cathcart et al., EACL 2003 — Shallow Model of Backchannel Continuers](https://aclanthology.org/E03-1069.pdf)

## 동기 경로 latency budget 위반 대응

표 자체는 `README.md` 의 동일 표. 위반 감지·대응:

- `IMPRINT_PROFILE=1` 시 모든 `(sync)` / `(sync/daemon-ready)` 노드가 진입/탈출 wall clock 을 `~/.claude/imprint/profile.jsonl` 에 기록.
- 같은 budget 위반이 5분 윈도에 3회 이상 → 가장 무거운 노드부터 daemon 분리 (`QEMB` / `HYB*` / `RR`). inline-first + daemon-ready abstraction 이 이미 박혀 있어 호출 측 코드 변경 없이 swap.
- `QEMB` 콜드 로드는 `J3` warm cache 가 1차 방어, daemon 분리가 2차.

## 성능 병목 진단 — 3축 (2026-05-09)

README의 mermaid가 그리는 hook/ingestion 파이프라인에서 **현재는 괜찮으나 설계상 미래에 터질 수 있는** 3축을 사전 진단한 결과입니다. LoadMap.md "설계상 병목 후보·대응 플랜" 섹션은 큰 그림 요약이고, 이 섹션은 "왜 문제인가 / 왜 이 대안인가"의 추론 과정을 풀어 둔 자료입니다.

**계측 hook은 박혔지만 아직 활성화는 사용자 액션이 필요합니다.** (probe lifecycle = `env_gated`)

```bash
# Claude Code 를 띄운 셸에서:
export IMPRINT_PROFILE=1
# 그 후 Claude Code 세션을 새로 시작 — 매 turn 마다 stage 별 측정값이
# ~/.claude/imprint/profile.jsonl 에 JSONL 한 줄씩 누적됩니다.
```

비활성화 시 hook 추가 비용은 env 검사 한 번뿐이라 평소에는 켜둘 필요가 없습니다. 임계 근접 의심이 들거나 설계 변경 전후 비교가 필요할 때만 켜는 것을 권장합니다.

A축은 격리 환경에서 동일 파싱 로직을 인라인 Python 으로 5회씩 측정한 값(스크립트 자체의 `IMPRINT_PROFILE=1` 경로를 거치지 않은, 동일 코드의 직접 실측)이라 코드 수정 없이도 신뢰할 수 있습니다. B·C 축은 운영 환경 OAuth + MCP 의존이라 hook 활성화 후 자연스러운 사용 안에서만 데이터가 모입니다.

---

### A축 — Stop hook 의 transcript JSONL 재파싱

**stage**: `stop.transcript_reparse`

#### 무엇이 일어나는가

매 turn 종료 직후 `stop.sh` 가 Claude Code 가 넘겨준 `transcript_path`(JSONL) 의 **첫 줄부터 끝까지** 읽으면서 `type == "assistant"` 인 줄의 본문을 갱신해 마지막 assistant 응답 텍스트를 추출합니다. 추출 결과를 `events.llm_response` 로 저장하고, 백그라운드 chunk extraction 으로 넘깁니다.

#### 왜 문제가 될 수 있는가

세션 길이에 대해 O(n) 입니다. 매 turn 마다 같은 파일을 처음부터 다시 훑기 때문에, 세션이 길어질수록 동기 hook 경로가 단조 증가합니다. README mermaid 의 "동기 ≈1초 보장" 약속이 깨지면 사용자 입력 직후 한 박자 멈추는 체감이 생깁니다.

실측 (5회 median, 같은 머신):

| 파일 크기 | 줄 수 | assistant 줄 | 추출 last bytes | median ms | max ms |
|---:|---:|---:|---:|---:|---:|
| 36.6 KB | 11 | 4 | 3,665 | 0.2 | 1.2 |
| 553.7 KB | 217 | 106 | 109 | 2.7 | 3.1 |
| 3,603.3 KB | 1,199 | 498 | 1,933 | 12.1 | 14.2 |

선형 모델 ≈ `0.2 + 0.0101 × lines` ms (≈ `3.4 ms / MB`).

#### 무엇 때문에 그렇게 동작하는가

`stop.sh` 는 Claude Code 가 hook 입력 JSON 으로 `transcript_path` 만 주기 때문에, "마지막 assistant 응답"을 알려면 직접 파일을 열어 읽어야 합니다. 가장 단순한 안전 구현은 "처음부터 끝까지 훑으면서 마지막 assistant 줄만 갱신하기" 입니다 (40-74행에 그렇게 짜여 있습니다). 작성 시점엔 세션 길이가 길어질 거라는 가정이 약했고, 작은 세션에서는 1 ms 미만이라 문제가 안 보였습니다.

#### 임계점 후보

- 동기 hook 추가 지연 100 ms → ~10,000 lines / ~30 MB / ~4,000 assistants
- 동기 hook 추가 지연 500 ms → ~50,000 lines / ~150 MB / ~20,000 assistants

3.6 MB / 1,199 lines 에서 12.1 ms 라는 실측이 있고, 위 임계점은 같은 선형 모델의 외삽치입니다. 일상 세션이 5 MB 를 넘는 경우는 드물어 당장은 안전 영역이지만, "하루 종일 이어가는 세션" 패턴에서 한 번씩 임계 근접이 생길 수 있습니다.

#### 대응 후보

1. **tail-only seek** *(가장 단순)*

   파일 끝에서 ~64 KB 만 `f.seek(max(0, file_bytes - 64*1024))` 로 잡고, 첫 incomplete line 한 줄만 버린 뒤 그 뒤를 line 단위로 읽으면서 마지막 assistant 줄을 추출합니다. assistant 응답 한 건은 보통 1~30 KB 라 64 KB 윈도면 거의 항상 충분하고, 특이하게 큰 응답이면 윈도를 두 배씩 키우며 retry 해도 됩니다.
   - **왜 이 안인가**: 코드 변경 ~10 줄, 추가 자료구조 0 개, 기존 동작과 동일 결과(마지막 assistant 텍스트 한 건). simplicity first 원칙에 정확히 맞습니다.
   - **트레이드오프**: 64 KB 안에 어떤 assistant 줄도 없는 극단 케이스(매우 긴 단일 응답이 64 KB 를 넘어가는 경우)에서는 retry 한 번이 추가됩니다 — 흔한 패턴은 아닙니다.

2. **incremental offset 저장** *(정확하지만 상태 추가)*

   `~/.claude/imprint/transcript-offsets/<session_id>.txt` 에 마지막으로 읽었던 byte offset 을 기록하고, 다음 turn 은 그 위치부터만 read 합니다.
   - **왜 후순위인가**: 정확하지만 새 디렉토리 + 세션 ID 별 상태 파일 + 정합성(파일 truncate / 세션 재개) 처리가 추가됩니다. 1번이 임계 한참 아래까지 흡수해 주므로 1번이 부족한 시점에야 진입할 가치가 생깁니다.

#### 다음 액션

- IMPRINT_PROFILE=1 활성화 후 `stop.transcript_reparse.dur_ms` 가 80 ms 를 한두 번 넘기 시작하면 1번(tail-only) 진입.
- 그때까지는 measurement 만 모으고 코드는 손대지 않습니다(CLAUDE.md Surgical Changes).

---

### B축 — 외부 fetch payload 폭주 (Notion / Slack)

**stages**: `fetch_slack_url`, `fetch_notion_url`, `fetch_slack_keywords`, `fetch_notion_keywords`, `cmd_lazy_fetch.enter|exit`, `call_claude`

#### 무엇이 일어나는가

UserPromptSubmit hook 의 백그라운드 spawn 이 `cmd_lazy_fetch` 를 호출하면 (1) 사용자 prompt 안의 Slack permalink / Notion URL 을 정규식으로 뽑고, (2) 처음 3개 URL 까지만 `claude -p haiku` + read-only MCP 로 fetch + sectioning 하며, (3) `<project>/.imprint/sources.json` 에 등록된 채널·페이지에 대해 키워드 검색을 한 번씩 더 돌립니다. 결과는 `memory_chunks` 에 INSERT 되고 dedup 키는 `metadata_json.url` 입니다.

#### 왜 문제가 될 수 있는가

여러 가지 silent failure mode 가 누적될 수 있습니다.

1. **큰 Notion 페이지의 sectioning 부하**
   `fetch_notion_url` 은 H1/H2/H3 heading 을 각각 별도 chunk 로 보존합니다(README "처리 규칙" 참조). 페이지가 클수록 `claude -p haiku` 가 모든 heading 을 JSON 으로 뱉어야 하므로 응답 토큰이 늘고 wall clock 이 늘어 `CLAUDE_TIMEOUT_FETCH = 45 s` (env override 가능) 임박합니다. 타임아웃이 발생하면 `call_claude` 가 None 을 반환하고 그 turn 의 chunk 는 통째로 비노출(silent skip + plugin.log warn).

2. **prompt 내 URL 4개 이상에서 silent skip**
   `lazy_fetch:812` `for url in list(dict.fromkeys(SLACK_PERMALINK_RE.findall(prompt)))[:3]` 처럼 처음 3개만 처리합니다. Notion 도 같은 패턴입니다. 사용자가 5개를 붙여넣으면 4·5번째 URL 은 fetch 없이 사라지지만 plugin.log 에 별도 경고가 없어 사용자가 모르고 지나갑니다.

3. **dedup TTL 무한**
   `chunk_url_exists` 는 같은 URL 의 chunk 가 하나라도 있으면 fetch 자체를 skip 합니다(README dedup 규칙). Notion 페이지가 갱신되거나 Slack thread 에 새 reply 가 달려도 강제 `/memory refresh` 전엔 옛날 chunk 만 prepend 됩니다 — 즉 시간이 갈수록 stale 비율이 올라갑니다.

4. **dedup 미스 — 같은 페이지의 chunk N개 vs 단일 URL 매칭**
   `fetch_notion_url` 은 한 페이지를 H1/H2/H3 별 chunk N 개로 쪼개고 각 chunk 의 `metadata_json.url` 에 같은 page URL 을 박습니다. 처음 fetch 후에는 페이지 URL 단일 매칭으로 skip 됩니다 — 이건 의도된 동작입니다. 다만 이 구조 때문에 (3) 의 stale 누적이 chunk 수만큼 더 크게 보입니다.

#### 무엇 때문에 그렇게 동작하는가

`[:3]` 상한과 `claude -p haiku` 단일 호출은 **한 turn 의 백그라운드 비용을 묶기 위한 의도된 결정**입니다. 사용자가 URL 을 무한히 넣어도 fetch 가 turn 당 최대 6 회 (Slack 3 + Notion 3) + keyword 검색 2 회로 묶입니다. URL > 3 silent skip 은 이 의도의 부산물이고, dedup TTL 무한은 사용자가 명시 갱신하기 전까지 외부 system 트래픽을 0 으로 만들기 위한 결정입니다 (README "갱신" 항목).

당시엔 "사용자가 모르는 silent skip" 보다 "사용자가 모르게 큰 fetch 가 반복되는" 시나리오를 더 위험하다고 본 trade 라 보면 자연스럽습니다.

#### 임계점 후보 (코드 분석, IMPRINT_PROFILE=1 데이터로 갱신 예정)

- 단일 fetch payload(`fetch_*_url.payload.payload_bytes`) > 50 KB → `claude -p haiku` 단일 응답으로 모든 heading 을 JSON 직렬화하기 어려움.
- 단일 `fetch_*_url.dur_ms` > 30,000 → 45 s 타임아웃의 67%, 다음 turn 에 chunk 비노출 위험.
- prompt 내 동일 source URL > 3 → 4번째부터 silent skip (현 상태).
- chunk `fetched_at` age > 14 d → stale 위험 — 분류·정책 도입 후보.

#### 대응 후보

1. **URL 개수 cap 을 silent 에서 visible 로 승격** *(가장 단순)*

   `lazy_fetch` 의 `[:3]` 분기에서 잘려나간 URL 수를 세서 `plugin.log` 에 `WARN: lazy_fetch dropped {n} URLs (cap=3) — first 3 fetched` 한 줄 emit. 코드 변경 ~3 줄.
   - **왜 이 안인가**: 사용자가 자기 prompt 의 어떤 URL 이 무시됐는지 추적 가능해지고, 동작은 그대로 두므로 회귀 위험 0. simplicity first.
   - **다음 단계**: 빈도가 높으면 cap 자체를 5·7로 올리는 검토.

2. **`fetched_at` TTL → stale flag** *(중간 복잡도)*

   `metadata_json.fetched_at` 이 N일(예: 14d) 지난 url-dedup chunk 는 `/memory list` / `/memory show` 가 `[stale]` 태그로 표시. 자동 refresh 는 하지 않고, 사용자가 보고 `/memory refresh <url>` 을 칠 수 있게 신호만 줍니다.
   - **왜 이 안인가**: TTL 무한 정책 자체는 외부 트래픽 보호로 유지하면서, "stale 인지 알기"의 사각지대만 좁힙니다. 자동 refresh 는 Notion 페이지가 사일런트로 새로 fetch 되는 부작용이 있어 의도적으로 피합니다.
   - **트레이드오프**: 14d 임계는 임의값 — 측정 데이터가 모이면 source 별로 다르게 잡을 수 있습니다.

3. **Notion chunking 단순화 (H1 only)** *(상대적으로 큰 변경, 보류)*

   현재 H1/H2/H3 모두 별도 chunk 인데, 큰 페이지는 chunk 수십 개로 쪼개져 검색 후보가 분산됩니다. H1 단위로만 chunk 하고 H2·H3 는 본문에 inline 시키면 chunk 수가 줄고 sectioning 응답도 짧아집니다.
   - **왜 후순위인가**: 검색 정밀도 trade — H3 단위로 검색되던 사용자 흐름이 깨질 수 있어 측정 데이터를 본 뒤 결정합니다.

#### 다음 액션

- IMPRINT_PROFILE=1 활성화 후 stage 들의 dur_ms / payload_bytes 분포가 모이면 임계점 수치를 재조정.
- "URL > 3 cap 잘림" 빈도가 한 번이라도 나오면 1번(visible cap)부터 진입 — 코드 ~3 줄, 회귀 위험 0.

---

### C축 — 동시 백그라운드 부하 (UPS lazy-fetch + Stop extract 겹침)

**stages**: `ups.spawn`, `cmd_lazy_fetch.enter|exit`, `stop.spawn`, `cmd_extract.enter|exit`, `call_claude`

#### 무엇이 일어나는가

매 turn 마다 두 hook 이 백그라운드 프로세스를 spawn 합니다.
- `UserPromptSubmit` → `cmd_lazy_fetch` (외부 fetch + chunk INSERT)
- `Stop` → `cmd_extract` (응답에서 chunk 추출 + INSERT)

각 프로세스는 `claude -p haiku` 를 호출하고 같은 `~/.claude/imprint/app.sqlite` 에 INSERT 합니다.

#### 왜 문제가 될 수 있는가

turn 사이클이 빠를수록 두 프로세스가 겹쳐 동시 실행됩니다.

1. **claude CLI 동시 실행 2개**
   turn N 의 `cmd_extract` 가 30 s 안에 끝나지 않은 상태에서 turn N+1 의 prompt 가 제출되면 `cmd_lazy_fetch` 가 새로 뜹니다. 두 프로세스는 각각 `claude -p haiku` 서브프로세스를 spawn 하므로 OAuth refresh 가 두 번 일어나고 API 트래픽이 곱해집니다.

2. **SQLite write 경합**
   둘 다 `memory_chunks` 에 INSERT 합니다. 이미 schema.sql 에 `PRAGMA journal_mode = WAL` + `PRAGMA busy_timeout = 5000` 가 켜져 있어 일반 동시 INSERT 는 흡수됩니다 — 즉 즉각적 위험은 낮습니다. 다만 5 s busy_timeout 안에 못 끝나는 long write 가 있으면 그 turn 의 INSERT 는 silent fail 하고 다음 turn 부터 그 chunk 가 검색 대상에서 빠집니다. **참고**: Phase 7a 의 single-writer ingest queue (`PACK* → ENQ → DEDUPE → VRES → CONF → W1`) 가 이 축의 영구 대응으로 자연 흡수되어, 새 retrieval ingestion 경로는 직렬 commit. 다만 기존 `memory_chunks` 직접 INSERT path 는 여전히 두 hook 이 별도로 쓰는 구조라 이 진단은 유효.

3. **좀비 spawn 누적**
   노트북 슬립/재개, 네트워크 단절, claude CLI 가 응답 없이 멈추는 등의 상황에서 `cmd_lazy_fetch` / `cmd_extract` 가 enter 만 찍고 exit 가 안 떨어질 수 있습니다. 사용자에겐 보이지 않는 백그라운드 프로세스가 누적되어 시스템 리소스를 점유합니다.

#### 무엇 때문에 그렇게 동작하는가

"hook 은 사용자 turn 을 차단하지 않는다" 는 CLAUDE.md 규약을 지키기 위해 무거운 작업을 모두 백그라운드로 분리한 결과입니다 (`( ... ) & + disown`). 동시성 제어를 명시적으로 두지 않은 이유는 (1) WAL + busy_timeout 으로 SQLite 는 보호되고, (2) `IMPRINT_BYPASS_HOOKS=1` 가드로 hook 무한 재귀는 차단되며, (3) 일반 사용 패턴에서 turn 간격이 30 s 이상이라 겹침이 거의 없을 거라는 가정이 있었기 때문입니다.

`/loop`, `ooo auto`, 또는 사용자가 빠르게 prompt 를 던지는 패턴은 이 가정을 벗어납니다.

#### 이미 있는 보호

- `schema.sql` 의 `PRAGMA journal_mode = WAL` (concurrent read + single write)
- `schema.sql` 의 `PRAGMA busy_timeout = 5000` (lock 5 s 까지 자동 retry)
- `IMPRINT_BYPASS_HOOKS = 1` 재귀 가드 — `ingestion.py` 가 spawn 하는 `claude` 서브프로세스가 다시 hook 을 타며 무한 재귀하지 않게.
- `IMPRINT_DISABLE_EXTRACT = 1` escape hatch — 사용자가 chunk 추출만 끄고 싶을 때.
- Phase 7a single-writer ingest queue — retrieval ingestion path 는 직렬 commit (기존 memory_chunks 직접 INSERT 와 별개).

#### 임계점 후보 (활성화 후 수치로 갱신)

- 5분 윈도에서 enter 만 있고 exit 없는 spawn 이 2건 이상 → CPU·OAuth 부하 알림.
- `call_claude.dur_ms` 동시 실행 > 2 → API 큐잉 대기 발생.
- profile.jsonl 의 enter ↔ exit 짝이 30 s 초과 미매칭 → 좀비 후보.

#### 대응 후보

1. **lazy-fetch lockfile** *(가장 단순)*

   `~/.claude/imprint/locks/lazy-fetch.lock` 에 PID + 시작시각을 적고, `cmd_lazy_fetch` 진입 시 lock 파일이 존재하고 PID 가 살아 있으면 silent skip + plugin.log info. lock 파일이 stale (PID 죽음) 이면 덮어쓰기.
   - **왜 이 안인가**: turn N+1 의 lazy-fetch 는 어차피 turn N+2 prefill 에서나 노출됩니다. 한 turn 빠지더라도 손실이 미미하고, 코드 변경은 작은 함수 한 개로 끝나고 외부 라이브러리 추가 0.
   - **트레이드오프**: 사용자가 빠른 turn 을 연속으로 치면 일부 turn 의 fetch 가 빠집니다 — 다음 turn 에 자연스럽게 다시 잡히므로 누적 손실은 0 에 가깝습니다.

2. **좀비 detection** *(분석 도구 차원)*

   `/memory stats` 가 profile.jsonl 을 읽어 enter ↔ exit 짝을 맞추고, 30 s 초과 unmatched enter 수를 "stale spawn" 으로 표시. 자동 kill 은 하지 않고 사용자에게 보고만 합니다.
   - **왜 이 안인가**: 자동 kill 은 정상 fetch 를 중단시킬 위험(특히 큰 Notion 페이지). 사용자가 보고 결정하게 두는 게 안전합니다.

3. **단일 writer 큐 — 기존 memory_chunks path 도** *(보류, 측정 후)*

   retrieval ingestion 은 이미 single-writer 큐를 거치지만, 기존 `memory_chunks` 직접 INSERT path (Phase 1~3) 는 여전히 두 hook 이 별도 write. WAL + busy_timeout 만으로 부족하다고 판단되는 경우에만 같은 큐로 통합 검토.

#### 다음 액션

- IMPRINT_PROFILE=1 활성화 후 enter ↔ exit 짝짓기 데이터로 (a) 동시 실행 빈도, (b) 좀비 빈도, (c) BUSY 빈도를 한 주씩 모음.
- 동시 실행이 5분 윈도에 2건 이상 관찰되면 1번(lockfile) 진입.
- 좀비가 한 번이라도 관찰되면 2번(`/memory stats` 표시) 진입.
- BUSY 가 한 번도 안 나면 3번(memory_chunks 직접 INSERT path 통합) 는 영구 보류.

---

### 측정 → 의사결정 흐름

```
IMPRINT_PROFILE=1 활성화
  → ~/.claude/imprint/profile.jsonl 누적
  → stage 별 분포 (dur_ms / payload_bytes / chunks / rc / err)
  → 임계점 후보 수치 갱신 (이 문서 + LoadMap.md)
  → 임계 도달 시 해당 축의 1번(simplicity first) 대응 진입
  → fix 직후 측정 비교 (계측 hook 그대로 유지)
  → 안정 확인 후 다음 축으로 이동
```

계측 hook 자체는 영구 코드(env_gated)로 남기고, 영구 fix 진입은 별도 사이클로 분리해 진행합니다.

## Chunk 분류 2단계 (대기)

`metadata.source` / `page_id`를 generated column으로 승격하고 인덱스를 추가한다. 검색 체감이 느려진 시점에 점진 도입.

```sql
ALTER TABLE memory_chunks ADD COLUMN
  meta_source TEXT GENERATED ALWAYS AS (json_extract(metadata_json,'$.source')) VIRTUAL;
ALTER TABLE memory_chunks ADD COLUMN
  meta_page_id TEXT GENERATED ALWAYS AS (json_extract(metadata_json,'$.page_id')) VIRTUAL;
CREATE INDEX idx_chunks_source ON memory_chunks(project_id, meta_source);
CREATE INDEX idx_chunks_page ON memory_chunks(project_id, meta_page_id);
```

진입 조건: `chunk_url_exists` / `cmd_refresh` / prefill 검색에서 row-level `json_extract` 비용이 체감될 때. 현재 28건 규모에서는 측정 가능한 차이가 없어 보류. 1단계(외부 source `chunk_type` 분리)의 사유와 두 단계로 끊은 이유는 `HISTORY.md` 2026-05-09 참조.

## TODO — 다음 세션에서 이어서

### TODO 1. RAG 저장/검색 루프 검증

다뤄야 할 미해결:
- **자동 hook loop**: `SessionStart`, `UserPromptSubmit`, `Stop` 을 샘플 JSON 으로 직접 호출해 event 저장, chunk 추출, 다음 turn prefill 이 이어지는지 확인.
- **읽기 경로 정합성**: 자동 저장된 `memory_chunks` 가 `/memory search` 와 prefill 에서 안정적으로 노출되는지, `/retrieve` 와 분리된 사실이 사용자에게 충분히 명확한지 확인.
- **fixture 기반 검색 품질**: 한국어 부분일치, pinned 우선순위, source/type 필터, `/memory inject` 출력 검증.

진입 명령: 수동 smoke test PR 로 시작. 인터뷰보다 실제 fixture 와 hook 직접 호출 검증을 우선.

### TODO 2. Chunk lifecycle 인터뷰 라운드 (deferred)

다뤄야 할 미해결:
- **dedup 정책**: 같은 의미 chunk가 여러 turn에서 누적될 때 — 자동 dedup 룰? 사용자 명령? 무시 후 검색 단계 dedup?
- **자동 pin 룰**: high-confidence decision은 자동 pin? confidence 임계치? 사용자 명시 pin만?
- **prefill 검색 ranking 가중치**: `pinned DESC, created_at DESC, BM25` 외에 source별·chunk_type별 가중? D17의 keywords union 점수 합산 방식?

진입 명령: `/ouroboros:interview chunk lifecycle (dedup·자동 pin·검색 ranking 가중치)`

### TODO 3. 보안·운영 인터뷰 라운드 (deferred)

다뤄야 할 미해결:
- **redaction 정규식**: 어떤 패턴(`sk-`, `xoxb-`, JWT, IP, email...)을 어디 단계에서(chunk insert 전 / FTS 인덱싱 시)? 사용자 정의 추가 가능?
- **redaction 호출 경로 갭 (2026-05-11 관찰)**: 단순 결정 가능 부분은 "보안 — Redaction coverage 갭" 섹션으로 분리. 인터뷰가 필요한 잔여 질문 — (a) FTS 인덱싱 전후 어디에서 redact 해야 검색이 깨지지 않는지, (b) 이미 raw 로 저장된 과거 events 행을 일괄 redact / 삭제 / 방치 중 어느 정책으로 갈지, (c) IP·email·전화번호 같은 PII 는 default 룰에 넣을지 사용자 opt-in 으로 갈지.
- **plugin.log 회전**: 크기·날짜 기반 회전 정책. 압축? 며칠 보관?
- **반복 실패 사용자 알림**: silent fail이 누적될 때 statusline·session-start prepend로 보고할지. 임계치?
- **conversation_id 관리**: 한 SessionStart마다 새 conversation? idle 시간 기준 분리?

진입 명령: `/ouroboros:interview 보안·운영 (redaction·log 회전·에러 알림·conversation_id)`

### TODO 4. 사용자 환경 검증

1. iOS 팀 멤버 1명이 브랜치 checkout 후 자기 사내 프로젝트에서 1주 정성 검증 (AC5)
2. `IMPRINT_ALLOWED_TOOLS_FETCH` 가 사용자 등록 Slack/Notion MCP 이름과 일치하는지 확인 (각자 다를 수 있음)
3. plugin.log에서 `WARN: claude -p` 빈도 모니터링 — 일정 임계 초과 시 timeout 조정

### TODO 5. retrieval 측정 → 캘리브레이션 (deferred, 1주 데이터 후)

- contradiction 임계 (`HIGH=0.8`, `MID=0.4`) — 첫 100~200 쌍 측정 후 캘리브레이션
- summary LLM (claude haiku) vs deterministic concat 정확도 비교
- chunk_entities 자동 link 가 안정화되면 contradiction 후보 그룹화가 entity 기준으로 정확해짐
- entity merge / split UI — `entities` CLI 가 confirm/reject 만 지원, canonical 합치기는 별도 명령 필요
- daemon 분리 시점 — `(sync/daemon-ready)` 노드의 budget 위반 누적 시 inline → daemon backend 전환

## 단기 Watch List

- Stop hook의 `transcript_path` 포맷은 Claude Code 내부 구조에 의존 — Claude Code 버전 업그레이드 시 깨질 수 있어 plugin.log에서 `stop logged` 로그 누락 여부를 정기 확인.
- `IMPRINT_BYPASS_HOOKS` 가드가 빠진 새 hook 추가 시 ingestion 무한 재귀 재발 위험 — hook 추가 시 가드 한 줄 누락 점검.
- ML 의존성(transformers / sentence-transformers / sqlite-vec) 의 모델 캐시가 `~/.cache/huggingface` 에 누적 — 디스크 사용량 모니터링. `IMPRINT_MODEL_CACHE_DIR` 로 위치 변경 가능.
- `claude -p haiku` RTT 가 11~28 s 라 LLM judge / NER 의 inline 호출은 BG side 전제. 동기 경로에 끌고 가면 budget 위반.

## 다음 세션 시작 시 추천 픽업 지점

1. **외부 source stale/누락 가시화** — URL cap, stale fetched_at, fetch 실패를 사용자 관찰 가능하게 만들기.
2. **읽기 경로 수렴 결정** — `memory_chunks → chunks_v2` bridge 와 `/retrieve` legacy fallback 중 어떤 경로가 더 단순한지 비교.
3. **events noise soft filter** — `events.noise=1` 컬럼 + backchannel rule filter 를 별도 PR 로 적용.
4. **retrieval 측정** — `IMPRINT_PROFILE=1` 데이터 수집으로 임계 캘리브레이션 / daemon 분리 결정.
5. **후순위** — Workflow skill, registry, entity merge/split UI, Chunk 분류 2단계는 RAG 기본 동작 안정 후 진입.
