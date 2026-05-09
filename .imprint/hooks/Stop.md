<!--
이 파일은 imprint plugin이 활용하는 Stop hook의 사용자 가이드입니다.
Claude Code가 직접 읽지 않습니다 — 사람이 보는 참고 문서입니다.

언제 발화: 모델 응답이 끝나고 다음 사용자 입력 대기로 들어가기 직전
무엇을 함: transcript에서 마지막 assistant 응답을 찾아 events 테이블에 archive
주의: 응답은 이미 사용자에게 노출됨, 본문 수정 불가, 청크 추출은 잔여 작업
-->

# Stop

## 무엇

모델 응답이 끝날 때마다 발화하는 슬롯입니다. plugin은 이 시점에 transcript JSONL을 읽어 마지막 assistant 응답을 SQLite events 테이블에 저장합니다 — 메모리 누적의 1단계.

## 어떻게 활용

기본 동작에 사용자 편집 지점은 없습니다. 응답은 자동 archive되고, `/memory search`로 이전 응답을 조회할 수 있습니다.

```bash
imprint memory search "이전 답변에서 언급한 결정"
```

## 간단한 예시

```bash
# 응답이 끝나면 plugin이 자동으로:
# 1. JSONL transcript의 마지막 assistant 메시지를 추출
# 2. SQLite events에 kind='llm_response'로 INSERT
# 3. 다음 turn에 UserPromptSubmit hook이 그 청크를 검색·주입에 활용
```

## 주의

- 응답은 이 hook이 발화할 시점에 **이미 사용자에게 보여졌습니다**. 본문을 검열·수정할 수 없습니다.
- 응답에 API key·token 등이 포함되면 그대로 events 테이블에 저장됩니다. **redact 룰셋은 미구현** — Phase 3 잔여 작업.
- 현재는 raw 텍스트 저장만 합니다. `decision/error/fix` 같은 chunk_type별 분리는 아직 — Phase 3 이후.
- transcript 포맷은 Claude Code 버전에 의존합니다. 포맷이 바뀌면 silent fail로 빠집니다 (`~/.claude/imprint/plugin.log`에 기록).
