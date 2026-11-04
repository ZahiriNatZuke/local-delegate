# Handoff: Price watcher reads the two Haiku 5.5 price tiers (#564)

## Current state

- SDD status: verifying (conformance approved; `memory` left to the main session)
- Last completed gate: conformance
- Current revision: branch `fix/price-watcher-tiered-prices`, stacked on #565

## What changed

- `scripts/price_watcher.py`: two-row tiered models, `long_prompt` in extract/compare/update/PR body, «USD» in the web search sentence, «verification required» ignored.

## Decisions

- A tiered model is recognized only by `rowSpan="2"` plus the exact tier caption; anything else stops the job.

## Next action

- Merge #565 first, then this PR; then dispatch the watcher workflow.

## Memory

- Canonical note: TBD (main session)
- Indexes updated: TBD (main session)
