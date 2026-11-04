# Handoff: Haiku 5.5 price and price check that survives unpriced models (#563)

## Current state

- SDD status: verifying (conformance approved; `memory` left to the main session)
- Last completed gate: conformance
- Current revision: branch `fix/prices-claude-5-and-unpriced-models`

## What changed

- `prices.json`: `claude-haiku-5-5` and the top-level `long_prompt` tier map; `consulted` 2026-11-04.
- `pricing`: `long_prompt`, band spanning both tiers, `priced_verdict`.
- `transcripts.request_cost`: per-request tier.
- `recompute._check`: `judged` = priced rows, `unpriced_rows`, `outside_by_model`; summary sentences.
- `checks._probe_cost`: OK with the unpriced note.

## Decisions

- The tier lives in a separate top-level map so every model entry keeps its exact key set (the
  price watcher and the inventory test rely on it).
- Sonnet 5.5 cache read left at $0.20: Claude Code's own `costUSD` uses it (local evidence).
- The Mac's 70 outside rows are priced-model rows; `outside_by_model` will name the model.

## Next action

- Merge after CI; then #564 (watcher) in its own PR.

## Memory

- Canonical note: TBD (main session)
- Indexes updated: TBD (main session)
