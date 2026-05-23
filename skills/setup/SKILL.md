---
name: setup
description: Set up imprint runtime features such as optional vector search. Use when the user asks to install dependencies, enable semantic/vector RAG, warm up embedding models, backfill memory embeddings, or check imprint setup status.
level: 2
---

# Imprint Setup

Use this skill when the user wants imprint setup or vector/RAG readiness handled for them.

## Dispatcher

All setup actions go through:

```bash
DISPATCHER="${IMPRINT_PLUGIN_ROOT:-${PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}}}/scripts/imprint/setup.sh"
```

In this repo, the direct path is:

```bash
bash scripts/imprint/setup.sh vector --status
```

## Vector Setup Workflow

1. Check status first:

```bash
bash "$DISPATCHER" vector --status
```

Status is intentionally lightweight: it checks importable packages and does not load BGE-M3.

2. If dependencies are missing and the user asked you to install/enable vector search, run:

```bash
bash "$DISPATCHER" vector --install --warmup --backfill
```

This installs `requirements-optional.txt` with user pip, loads BGE-M3 once, and backfills existing memory for the current project with embeddings.

## Notes

- `--install` may need network access and writes to the user Python site-packages.
- `--warmup` may download the BGE-M3 model into the HuggingFace cache.
- `--backfill` only touches the current project id unless `--project-id <id>` is passed.
- Backfill embeds current `search_entries` rows. Run `imprint migrate search-entries` separately when converting a legacy DB; default plugin behavior stays lightweight.
- The dispatcher prints `[imprint setup]` progress lines for each step and writes the same setup events to `~/.imprint/plugin.log`.
- On failure, report the failed step, exit code, and hint shown by the dispatcher. Ask the user to inspect `~/.imprint/plugin.log` when the Python traceback or pip output is needed.
