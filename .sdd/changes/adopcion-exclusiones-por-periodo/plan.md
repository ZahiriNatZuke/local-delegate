# Implementation plan: La medicion de adopcion del plugin acota las exclusiones a su periodo

## Approach

Keep the id search open-ended and compute the exclusion counter with a second call
`model_decided_ids(rows, windows, since, until)` whose ids are discarded. The rows are already in
memory, so it costs one extra pass, and the function keeps its contract.

## Ordered tasks

- [x] T1 — Regression test first, verify it fails on `main` by the `excluded_rows` assert (REQ-001, REQ-002)
  - Files or modules: tests/test_measure_plugin_adoption.py
  - Verification: pytest on the new test, before and after the fix
  - Depends on: none
- [x] T2 — Bound `excluded_rows` to `[since, until)` in `measure()` (REQ-001, REQ-002)
  - Files or modules: scripts/measure_plugin_adoption.py
  - Verification: new test green
  - Depends on: T1
- [x] T3 — Run the script's tests and the full suite; CHANGELOG line with #597 (REQ-003)
  - Files or modules: CHANGELOG.md
  - Verification: pytest
  - Depends on: T2

## Test strategy

- Unit: new test through `measure()` (the script's public entry used by `main`), with a mod row after
  `until` and a late model delegation for a session in the period.
- Integration: existing `test_main_prints_the_criterion`.
- End-to-end or manual: none (the real log must not be used).
- Security and secret scanning: no secrets involved; diff review.

## Migration and compatibility

- Output keys unchanged; the values of `excluded_rows` shrink to the period. No consumer of the JSON
  other than humans reading it (grep: only the script and its test).

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
