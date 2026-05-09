---
name: advisor
description: Multi-provider advisor orchestration via OAuth subscription. Ask Codex or Gemini for opinions, or run CCG (Claude-Codex-Gemini) tri-model parallel advisor with Claude synthesizing the result.
level: 4
---

# Advisor - Multi-Provider Advisor Orchestration

This skill calls Codex or Gemini CLI from inside a Claude Code session to get external opinions, then optionally has Claude synthesize them. All providers use OAuth subscription authentication — no API keys required.

## When to Use

- Cross-validate an architectural decision (Codex perspective)
- Get UX/design alternatives (Gemini perspective)
- Code review from multiple angles
- When Claude Code is uncertain and external opinion would help

## Requirements

- `codex` CLI installed and authenticated (ChatGPT subscription)
- `gemini` CLI installed and authenticated (Google account)
- `claude` CLI for CCG synthesis (already present in Claude Code env)

## Subcommands

### `/advisor codex <prompt>`
Ask Codex for an opinion. Result is also saved to memory as a `provider_runs` row.

```bash
multiagent advisor codex "Review this Rust error handling pattern: ..."
```

### `/advisor gemini <prompt>`
Ask Gemini for an opinion.

```bash
multiagent advisor gemini "Suggest UX alternatives for this CLI flow"
```

### `/advisor ccg <prompt>`
Run Codex and Gemini in parallel, then have Claude synthesize.

```bash
multiagent advisor ccg "Should I use SQLite WAL mode for concurrent writes?"
```

Internal flow:
1. Decompose prompt into Codex (architecture/correctness) and Gemini (UX/alternatives) prompts
2. Run `codex exec` and `gemini -p` in parallel
3. Read results
4. Call `claude -p` with both outputs to synthesize a unified answer
5. Persist all three rounds to `provider_runs` and `events` tables

## Implementation

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/multiagent/advisor.sh" <subcommand> [args...]
```

## Provenance

Every advisor run produces:
- `run_id` - unique identifier
- `prompt_event_id` - the input
- `output_event_id` - the response
- `phase` - single | advisor_draft | advisor_review | advisor_synthesize
- `provider` - claude | codex | gemini
- `status` - succeeded | failed | canceled

This makes the orchestration auditable — you can see exactly which provider said what.

## Cost

- Claude Code itself: subscription
- `codex exec`: ChatGPT subscription
- `gemini -p`: Google account quota
- No Anthropic API key billing
