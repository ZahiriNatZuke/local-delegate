# Handoff: Price watcher reads the two Haiku 5.5 price tiers (#564)

## Current state

- SDD status: closed (closing PR `chore/close-sdd-2026-11-04`)
- Last completed gate: memory
- Current revision: merged in `main` as `2ef5cf44` (PR #566)

## What changed

- `scripts/price_watcher.py`: two-row tiered models, `long_prompt` in extract/compare/update/PR body, «USD» in the web search sentence, «verification required» ignored.

## Decisions

- A tiered model is recognized only by `rowSpan="2"` plus the exact tier caption; anything else stops the job.

## Next action

- Merge #565 first, then this PR; then dispatch the watcher workflow.

## Memory

- Canonical note: vault `projects/local-delegate/jornada-2026-11-04-seis-arreglos-y-el-vigilante-de-precios.md`
- Indexes updated: `projects/local-delegate` journey index (main session)
