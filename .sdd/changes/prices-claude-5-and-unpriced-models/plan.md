# Implementation plan: Haiku 5.5 price and price check that survives unpriced models (#563)

## Approach

Data first, then the pure functions, then the two readers. The prompt-length tier goes in a new
top-level `long_prompt` map of `prices.json` (`{id: {"above_tokens", five prices}}`) so every model
entry keeps its exact key set. `pricing` gains `long_prompt(mid, table)`; `_judge` widens the high
end of the band with the long tier when it exists; `request_cost` picks the tier per request.
`recompute._check` uses a new `pricing.priced_verdict` (the old `verdict` stays as is) and stores
`unpriced_rows` and `outside_by_model`. `checks._probe_cost` adds the unpriced note to the OK line.

## Ordered tasks

- [x] T1 — Haiku 5.5 entry and long-prompt tier in `prices.json`, `consulted` 2026-11-04, note (REQ-001)
  - Files or modules: `src/local_delegate/resources/data/prices.json`, `tests/test_pricing.py` (SPEC_IDS only), new `tests/test_unpriced_check.py`
  - Verification: test
  - Depends on: none
- [x] T2 — `pricing.long_prompt`, band in `_judge`, `priced_verdict` (REQ-002, REQ-004)
  - Files or modules: `src/local_delegate/pricing.py`
  - Verification: test
  - Depends on: T1
- [x] T3 — per-request tier in `transcripts.request_cost` (REQ-003)
  - Files or modules: `src/local_delegate/transcripts.py`
  - Verification: test
  - Depends on: T2
- [x] T4 — check fields and summary sentence in `recompute` + i18n es/en (REQ-004, REQ-005, REQ-007)
  - Files or modules: `src/local_delegate/recompute.py`, `resources/i18n/{es,en}/cli.json`
  - Verification: test
  - Depends on: T2
- [x] T5 — doctor OK note for unpriced models (REQ-006)
  - Files or modules: `src/local_delegate/checks.py`, `resources/i18n/{es,en}/doctor.json`
  - Verification: test
  - Depends on: T4
- [x] T6 — full suite, control positivo, CHANGELOG (REQ-008)
  - Files or modules: `CHANGELOG.md`
  - Verification: cmd
  - Depends on: T1-T5

## Test strategy

- Unit: new `tests/test_unpriced_check.py` and `tests/test_unpriced_check.py` with literal rows
  (one Haiku 5.5 row copied from a real `cost-state` number set, reduced to its six fields).
- Integration: `recompute._check` over a synthetic index; `checks._probe_cost` over written aggregates.
- End-to-end or manual: read-only run of the check over this PC's transcripts with a temporary log.
- Security and secret scanning: no secrets involved; `personal-security-check` before commit.

## Migration and compatibility

- New keys only; old aggregates still read. `pricing.verdict` keeps its behavior for its callers/tests.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
