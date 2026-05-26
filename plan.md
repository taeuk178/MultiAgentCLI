# `/remember` 문서형 분할 저장 v2 계획

## Summary

`/remember`가 큰 문서를 `search_entries` 1행에 저장하던 문제를 해결하기 위해, 명시 저장 입력을 청크 단위로 분할 저장하되 `/search`에서는 같은 저장 묶음을 문서처럼 읽히게 만든다.

## Key Changes

- `/remember` 저장 경로를 Bash 직접 `INSERT`에서 Python 경로로 위임한다.
- 기존 `chunking.py`를 재사용하고 remember 전용 preset을 추가한다.
- 그룹 메타데이터는 스키마 변경 없이 `metadata_json`에 저장한다.
- embedding은 write transaction 밖에서 batch 처리한다.
- retrieve 최종 후보는 같은 `chunk_group_id`에서 최대 2개까지만 노출한다.
- `forget --group <id-or-group-id>`를 v1에 포함한다.
- `+/-1 chunk_index` 인접 확장은 v1.1로 분리한다.

## Public Interface

- `/remember <text> [--require|--high|--middle|--low] [--type <t>] [--pin] [--redact]`
- `/remember --stdin [--title <s>] [--split auto|always|never]`
- `/remember --no-split`
- `/memory forget <id>`
- `/memory forget --group <id-or-group-id>`

## Defaults

- chunk preset: `target=400`, `max=800`, `min=60`, `overlap=0`
- split default: `--split auto`
- auto split trigger: `1200자 이상`, `20줄 이상`, `heading 2개 이상`
- title auto extract: 첫 markdown heading -> 첫 줄 60자 -> 생략
- v1 dedup policy: `/remember` 명시 저장 의도에 맞춰 중복 허용

## Test Plan

- 짧은 입력은 1개 row로 저장된다.
- 긴 markdown 입력은 여러 row로 저장되고 그룹 메타데이터가 채워진다.
- `--stdin` 입력은 줄바꿈과 heading을 보존한다.
- fenced code block은 분할 중 깨지지 않는다.
- embedding은 transaction 밖에서 batch 호출된다.
- embedding 비활성 환경에서는 `embedding=NULL`로 저장된다.
- `/search` 결과는 같은 그룹 후보를 최대 2개까지만 노출한다.
- assembly 출력은 같은 그룹 후보를 문서 블록처럼 보여준다.
- `forget --group`은 id 또는 group id 기준으로 그룹 전체를 삭제한다.
- `--split never`와 `--no-split`은 긴 입력도 1개 row로 저장한다.

## Assumptions

- 스키마 변경은 하지 않는다.
- `source_documents`를 만들지 않고 `search_entries(origin=manual_remember)`만 사용한다.
- remember chunk overlap은 0으로 고정한다.
- retrieve 인접 chunk 확장은 v1.1 작업으로 남긴다.
