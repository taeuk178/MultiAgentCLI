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

3. If the user wants future memory to embed automatically, tell them the persistent shell line:

```bash
bash "$DISPATCHER" vector --print-env
```

Only edit `~/.zshrc` or another shell rc file when the user explicitly asks. Otherwise, show the line and let them decide.

## Notes

- `--install` may need network access and writes to the user Python site-packages.
- `--warmup` may download the BGE-M3 model into the HuggingFace cache.
- `--backfill` only touches the current project id unless `--project-id <id>` is passed.
- The script uses `IMPRINT_MEMORY_BRIDGE_EMBEDDING=1` only when the user chooses to persist it; default plugin behavior stays lightweight.
