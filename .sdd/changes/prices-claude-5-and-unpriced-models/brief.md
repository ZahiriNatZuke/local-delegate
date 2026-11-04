# Brief: Haiku 5.5 price and price check that survives unpriced models (#563)

## Problem

Issue #563: with 0.48.0 on the Mac, `recompute-cost` reports the price check as failed (282 rows judged, 70 outside, unpriced: claude-haiku-5-5) and `doctor` keeps a permanent WARN.

## Desired outcome

Haiku 5.5 priced from the official page; an unpriced model no longer fails the whole check; the 70 outside rows explained.

## In scope

- `prices.json`, `pricing.py`, `transcripts.request_cost`, `recompute._check` and summary, `checks._probe_cost`, i18n.

## Out of scope

- Price watcher (separate issue); Sonnet 5.5 cache-read discrepancy (reported); `git_history.py` and server.py (another agent).

## Constraints and risks

- Record known technical, security, compatibility, and delivery constraints.

## Open questions

- Resolve questions that materially change the specification before implementation.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-04 Original request, verbatim:

  > Issue #563: recompute-cost price check fails because the table lacks claude-haiku-5-5. Add missing Claude 5 prices from a verifiable source; rows of an unpriced model are excluded from the check with a separate notice and doctor only warns when priced rows do not match; find out whether the 70 outside rows belong to the unpriced model; no calculation change for already priced models.
