# Specification: La medicion de adopcion del plugin acota las exclusiones a su periodo

## Summary

The adoption measurement reports, for each period, the excluded log rows of that period only.

## Requirements

- **REQ-001** — `excluded_rows` of a period counts only rows with `since <= ts < until`.
  - Request: "cuenta las exclusiones (excluded_rows) desde el periodo base hasta hoy y no hasta el fin del periodo"
  - Verify: test `test_excluded_rows_bounded_to_the_period`
- **REQ-002** — The delegation ids still come from `[since, ∞)`: a session of the period whose
  delegation is logged after `until` still counts as "with delegation".
  - Request: derived: the open end is intentional (`measure_plugin_adoption.py:187-188`) and must not regress.
  - Verify: test `test_excluded_rows_bounded_to_the_period` (guard assert on `with_delegation`)
- **REQ-003** — Existing tests of the script pass unchanged.
  - Request: derived: no-regression rule of the project.
  - Verify: cmd `pytest tests/test_measure_plugin_adoption.py`

## Acceptance scenarios

### Scenario: mod rows only after the install date

- **Given** a log with a mod row (`toolu_plugin_…`) after `until` and none inside the period
- **When** the period `[since, until)` is measured
- **Then** `excluded_rows` has no `plugin` key, and a model delegation logged after `until` for a
  session that started inside the period still counts

## Edge cases and failure behavior

- A row exactly at `until` belongs to the next period (half-open interval, same as sessions).
- Rows without a parseable `ts` keep being skipped, as today.

## Non-functional requirements

- No change in output keys or format; no extra log reads (the rows are already in memory).

## Non-goals

- Changing the id window, the percentage, or the criterion.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
