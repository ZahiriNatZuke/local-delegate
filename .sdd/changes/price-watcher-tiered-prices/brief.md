# Brief: Price watcher reads the two Haiku 5.5 price tiers (#564)

## Problem

The weekly price watcher fails since 2026-10-19 on the two Haiku 5.5 price rows (#564).

## Desired outcome

The watcher reads both tiers and runs green against the live page.

## In scope

- `scripts/price_watcher.py` and its tests.

## Out of scope

- The Sonnet 5.5 cache-read decision; running the GitHub side locally.

## Constraints and risks

- Record known technical, security, compatibility, and delivery constraints.

## Open questions

- Resolve questions that materially change the specification before implementation.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-04 Original request, verbatim:

  > Issue #564: scripts/price_watcher.py reads the two Haiku 5.5 tiers (name cell with rowSpan=2, extra text in the input cell, continuation row with one cell less) and proposes the base entry and the long_prompt tier; extract_price_table/compare/updated_table know long_prompt. Tests with a synthetic HTML of the same shape. Check locally that the script runs green against the real page. An unreadable cell must still fail with a clear message.
