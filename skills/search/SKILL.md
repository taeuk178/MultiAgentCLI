---
name: search
description: Search project context with imprint hybrid retrieval. Use when the user asks to /search, semantically search remembered project history, inspect retrieval evidence, or find broader implementation context beyond simple /memory keyword search.
level: 3
---

# Search - Project Context Retrieval

Use this skill when the user wants to search remembered project context, implementation history, decisions, or broader feature flow with the unified `search_entries`/summary path.

Prefer `/search` language in user-facing replies. `/memory search` remains the lightweight FTS search over `search_entries`; this skill is for the fuller project search path that can use source document entries, summaries, routing, and optional vector search.

## Dispatcher

All search actions go through:

```bash
DISPATCHER="${IMPRINT_PLUGIN_ROOT:-${PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}}}/scripts/imprint/search.sh"
```

In this repo, the direct path is:

```bash
bash scripts/imprint/search.sh "질문"
```

## Usage

Use natural-language search. It is routed by default: imprint chooses local, feature, or global scope from the query.

```bash
bash "$DISPATCHER" "로그인 feature 의 공유하기는 어떻게 구현됐었지?"
```

## Notes

- `/search` is routed by default.
- The public `/search` dispatcher intentionally accepts only a query for now.
- Optional vector search is used only when embeddings are available. Check or set it up with `imprint setup vector --status` or `imprint setup vector --install --warmup --backfill`.
- If the user asks only for exact keyword memory rows, use `/memory search` instead.
