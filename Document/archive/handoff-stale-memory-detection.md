# Handoff: Stale Memory Detection (시간 + git log 시그널 조합)

## 개요

imprint plugin이 매 세션에 `[Project memory context]`로 메모리를 prepend해주는 현재 구조는 세션 간 연속성을 제공하지만, **메모리가 시간에 따라 stale(폐기됨/구현 안 됨/방향 전환됨)** 되는 문제를 안고 있다. 이 문서는 stale 메모리를 자동 감지·환기하는 기능에 대한 제안서이며, plugin 작성자에게 핸드오프하기 위한 요구사항·로직·UX 정리를 담는다.

본 문서는 사용자(@dnwndlsdlsi)와 Claude 간의 대화 끝에 합의된 방안 (2) "**시간 + git log 변경 감지 조합**"을 기준으로 작성됐다.

---

## 1. 해결하려는 문제

### 1-1. False positive — 순수 시간 기반 노티의 한계

| 케이스 | 메모리 상태 | 2주 후 노티가 적절한가? |
|---|---|---|
| 결정만 합의, 코드 미반영 | pending | YES — 잊혀진 todo 환기 |
| 결정 + 코드 반영 + 운영 중 | applied | **NO** — 이미 완료된 사실 |
| 결정 후 방향 전환 | deprecated | YES — 폐기 후보 발견 |
| `[note]` 단순 사실 기록 | factual | **NO** — 시간과 무관 |
| `[fix]` 버그 수정 기록 | factual | **NO** — 영구 가치 |

→ 순수 시간 기반 노티는 노이즈 비율이 높아 사용자가 알람 피로로 인해 결국 무시한다.

### 1-2. 실제 충돌 시나리오

- 몇 달간 미진행 → 메모리만 "결정됨"으로 남음 → 새 세션에서 모델이 "이미 한 것처럼" 추론
- 다른 방향으로 구현 → 옛 결정 메모리가 stale → 모델이 옛 결정 따라 작업 시도 → 충돌
- 일부만 적용 후 중단 → "B안 채택" 메모리가 다른 사이트도 동일하게 진행된 것처럼 추론하게 만듦
- 파일 삭제됨 → 메모리가 존재하지 않는 파일 기준으로 답변

---

## 2. 채택된 방안: 시간 + git log 변경 감지

### 2-1. 핵심 아이디어

> "이 메모리가 작성된 후, 메모리에 언급된 파일/심볼이 git history에서 한 번도 변경되지 않았다면 → 미반영 가능성 ↑"

시간만으로는 false positive가 크다. **메모리 작성 시점 이후 관련 파일이 한 번이라도 커밋되었다면, 그 메모리는 코드에 반영되었거나 검토된 것으로 간주**한다.

### 2-2. 트리거 로직 (의사코드)

```pseudo
for memory in all_memories:
    if memory.type in [note, fix]:
        continue  // 사실 기록은 만료 면제

    age = now - memory.created_at
    expiration = expiration_policy[memory.type]   // 아래 2-3 참조

    if age < expiration:
        continue  // 아직 만료 전

    related_files = extract_file_refs(memory.body)   // 자동 추출
    if not related_files:
        // 파일 참조가 없는 메모리는 시간만으로 노티
        notify(memory, reason: "age_only")
        continue

    last_touched = max(git_log_last_modified(f) for f in related_files)
    if last_touched > memory.created_at:
        // 메모리 작성 이후 파일이 변경됨 → 반영/검토되었을 가능성
        continue

    notify(memory, reason: "stale_age_and_untouched")
```

### 2-3. 메모리 타입별 만료 정책

| Type | 만료 기간 | 사유 |
|---|---|---|
| `decision` | 30일 | 의사결정은 시간 지나면 검증 필요 |
| `todo` | 14일 | 작업 미완료 환기 주기 |
| `note` | **만료 없음** | 단순 사실 기록 |
| `fix` | **만료 없음** | 버그 수정은 영구 가치 |
| `reference` | 90일 | 외부 링크 살아있는지 검증 |
| `user` | 만료 없음 | 사용자 프로필은 비교적 안정적 |
| `feedback` | 만료 없음 | 협업 규칙은 누적 가치 |

만료 기간은 사용자 설정(`~/.claude/imprint/config.toml` 등)으로 커스터마이즈 가능하게 제공.

### 2-4. 파일 참조 추출 규칙

메모리 본문에서 자동으로 추출:

- 경로 패턴: `[A-Za-z0-9_/-]+\.(swift|m|h|ts|tsx|js|py|...)` 등
- 백틱 코드: ``` `CashwalkWKWebView.swift` ```
- 클래스/심볼명도 가능하면 추출 (선택 사항, 첫 버전에서는 생략 가능)

추출 실패 시 `related_files`가 빈 배열 → 시간 만으로 노티.

### 2-5. git log 검증

```bash
# memory.created_at 이후 file이 한 번이라도 변경됐는지
git log --since="<memory.created_at>" --format="%H" -- <file> | head -1
```

빈 결과 → 미변경. 결과 있음 → 변경됨(검토/반영 추정).

대용량 repo에서는 캐시 권장. 메모리당 매 세션 시작 시 1회 검증, 결과는 24시간 캐시.

---

## 3. UX 제안

### 3-1. 노티 시점

세션 시작 시(`SessionStart` hook) `[Project memory context]` prepend 직전에 stale 후보 검사. stale 메모리가 N개 이상이면 다음 형식으로 안내:

```
[imprint] 묵은 메모리 N개가 감지되었습니다:

  1. [decision] webview-inplace-refactor (45일 경과, 관련 파일 변경 없음)
     "CashwalkWKWebView in-place 진화로 통합..."

  2. [todo] phase-2-home-search-migration (28일 경과, 관련 파일 변경 없음)
     "HomeWebType, SearchWebType 동일 마이그레이션 적용"

조치:
  /memory forget <slug>     - 해당 메모리 삭제
  /memory pin <slug>        - 만료 면제 (이 메모리는 계속 유효)
  /memory snooze <slug> 30d - 30일 뒤 다시 알림
  /memory verify            - 현재 코드 기준 일괄 검증
```

### 3-2. 자동 명령 제공

- `/memory forget <slug>` — 즉시 삭제 (이미 있음)
- `/memory pin <slug>` — **신규** — 만료 면제 플래그
- `/memory snooze <slug> <duration>` — **신규** — N일/주 뒤로 미루기
- `/memory verify` — **신규** — 모든 stale 후보를 한 번에 검토

### 3-3. 노이즈 방어

- 한 세션당 stale 노티는 1회만 표시 (사용자가 dismiss하면 같은 세션 내 재표시 X)
- 동일 stale 메모리는 7일 1회 알림으로 제한 (사용자가 forget/pin/snooze 하지 않은 경우)
- 최대 N개(예: 5개)까지만 한 화면에 표시. 그 이상은 `/memory verify`로 유도.

---

## 4. 구현 우선순위

| Priority | 항목 | 비고 |
|---|---|---|
| P0 | 타입별 만료 정책 + 시간 기반 노티 | 최소 기능 (시간만으로도 동작) |
| P0 | `/memory forget` / `/memory snooze` 노티에서 직접 호출 가능 | UX 핵심 |
| P1 | 파일 참조 자동 추출 + git log 검증 | false positive 대폭 감소 |
| P1 | `/memory pin` / `/memory verify` 신규 명령 | 사용자 운영 도구 |
| P2 | 메모리 메타데이터에 `last_verified_at` 캐시 | 성능 최적화 |
| P2 | 24시간 결과 캐시 | 성능 최적화 |
| P3 | 설정 파일 기반 만료 기간 커스터마이즈 | 고급 사용자용 |

---

## 5. Future Work

다음 단계로 다음 항목들이 자연스럽게 이어진다.

### 5-1. `status` 필드 정식 도입

메모리 프론트매터에 `status: pending | applied | deprecated` 필드 추가. `applied`는 자동 만료 면제. 사용자가 `/memory apply <slug>`로 상태 전환:

```yaml
---
name: webview-inplace-refactor
description: ...
metadata:
  type: decision
  status: applied         # 신규
  applied_at: 2026-06-15  # 신규
  related_files:          # 신규 (자동 추출 보조)
    - Trost_iOS/NewTrost/WebKit/CashwalkWKWebView.swift
    - Trost_iOS/NewTrost/WebKit/CashwalkWebType.swift
---
```

→ 본 핸드오프 v2에서 다룰 수 있는 영역.

### 5-2. 메모리 그룹화

`webview-refactor` 같은 prefix로 묶이는 메모리들을 group 단위로 함께 stale 검출. 그룹 내 1개라도 변경 시 그룹 전체 면제.

### 5-3. 자동 폐기 제안

`age > 만료_기간 * 3` 이고 git log에도 흔적 없으면 자동 폐기 후보로 강조. 사용자 confirm 후 일괄 forget.

---

## 6. 검증 시나리오 (QA 체크리스트)

구현 후 다음 시나리오로 동작 검증:

- [ ] 30일 경과한 `decision` 메모리, 관련 파일 변경 없음 → 노티 발생
- [ ] 30일 경과한 `decision` 메모리, 관련 파일이 그 사이 커밋됨 → 노티 발생 안 함
- [ ] 365일 경과한 `note`/`fix` 메모리 → 노티 발생 안 함 (타입 면제)
- [ ] `/memory snooze <slug> 7d` 후 7일 이내 노티 없음, 7일 후 재발
- [ ] `/memory pin <slug>` 후 1년 후에도 노티 없음
- [ ] `git log` 호출 비용 측정 — 100개 메모리 기준 세션 시작 < 500ms
- [ ] 파일 참조 추출 정확도 — 다양한 경로 패턴 매칭 검증

---

## 7. 본 문서가 작성된 컨텍스트 (참고용)

이 핸드오프는 TROST-App-iOS 프로젝트에서 웹뷰 구조 리팩터링 작업 중 사용자와 Claude의 대화에서 도출됐다. 핵심 통찰:

- 사용자가 "2주 단위 노티" 아이디어를 먼저 제시
- 즉시 "근데 적용된 기능도 2주가 지났다면 노티를 받겠네"라며 자기 한계 발견
- Claude가 "시간 + 코드 변경 감지 조합" 제안 (방안 2)
- 사용자가 방안 2 채택, 본 문서 작성 의뢰

핵심 가치: **"메모리는 결정의 스냅샷이지, 코드의 현재 상태가 아니다."** stale 메모리는 plugin이 능동적으로 감지·환기해야 하며, 사용자가 수동으로 청소하는 부담을 줄여야 한다.

---

## 8. 연락처 / 후속 논의

- 본 문서 작성: 2026-05-12
- 작성 컨텍스트: imprint plugin 활성 상태의 Claude Code 세션
- 의문점 / 추가 논의: 사용자(@dnwndlsdlsi) 직접 문의
