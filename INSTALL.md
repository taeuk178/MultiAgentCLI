# Imprint — Claude Code Plugin 설치

이 저장소는 Claude Code 플러그인입니다. 설치 후 Claude Code 세션에서 `memory` 스킬과 자동 hook이 동작합니다.

## 사전 조건

- Claude Code (구독 OAuth로 인증됨)
- `sqlite3` (macOS 기본 포함)
- `python3` (macOS 기본 포함)
- 선택: Slack / Notion MCP (외부 source lazy fetch에서 사용)

## 설치 방법

### 1. 로컬 마켓플레이스로 등록

이 저장소를 Claude Code 마켓플레이스로 추가합니다.

```bash
# Claude Code 세션 안에서 (이 repo의 절대 경로를 사용)
/plugin marketplace add <ABSOLUTE_PATH_TO_THIS_REPO>
/plugin install imprint@imprint
```

### 2. 직접 심볼릭 링크 (개발 모드)

```bash
mkdir -p ~/.claude/plugins/cache/local
ln -s <ABSOLUTE_PATH_TO_THIS_REPO> ~/.claude/plugins/cache/local/imprint
```

이후 Claude Code를 재시작하면 플러그인이 로드됩니다.

## 설치 후 확인

새 Claude Code 세션을 열고 다음 질문을 보내면 `[Project memory context]` 블록이 자동 주입됩니다.

```
이 프로젝트의 최근 결정 사항을 알려줘
```

Hook이 동작하면 `~/.claude/imprint/app.sqlite`가 생성되고, `~/.claude/imprint/plugin.log`에 기록이 남습니다.

## 사용

### Memory

```
/memory remember <text> [--type decision|fix|todo|...] [--pin] [--redact]
/memory search <query>
/memory list [--recent|--pinned|--type <t>|--source <slack|notion|internal>]
             [--since <date>] [--limit <n>] [--project <path|id-prefix>]
/memory show <chunk-id> [--json]
/memory stats [--all] [--json]
/memory inject <chunk-id>
/memory pin <chunk-id>
/memory forget <chunk-id>
/memory refresh <url|source slack|source notion|project>
```

## 데이터 위치

```
~/.claude/imprint/
  app.sqlite        # 이벤트 로그 + memory chunks (FTS5 포함)
  plugin.log        # hook/skill 디버그 로그
```

## 제거

```bash
/plugin remove imprint
rm -rf ~/.claude/imprint  # memory 까지 같이 지우려면
```

## 동작 원리

- **SessionStart hook**: SQLite 스키마 적용, 현재 프로젝트 row upsert
- **UserPromptSubmit hook**: 유저 입력을 events에 저장하고, pinned + recent 청크를 `[Project memory context]` 블록으로 stdout 출력 → Claude Code가 prompt에 자동 추가
- **Stop hook**: turn 종료 시 마지막 assistant 응답을 `transcript_path`에서 읽어 events에 저장

모든 LLM 호출은 Claude Code 본체 또는 hook이 백그라운드에서 호출하는 `claude -p`(prefill 분석·Slack/Notion lazy fetch·Stop chunk 추출)를 통해 **OAuth 구독으로** 처리됩니다. API key는 사용하지 않습니다.
