# Brief: La medicion de adopcion del plugin acota las exclusiones a su periodo

## Problem

`scripts/measure_plugin_adoption.py:189` calls `model_decided_ids(rows, windows, since, _END_OF_TIME)`
and returns that same exclusion `Counter` as the period's `excluded_rows` (line 220). The open end is
intended for the ids (a session of the last day may delegate after the cut), but it makes
`excluded_rows` count every row from `since` until today: `base.excluded_rows.plugin = 146` while
only 11 mod rows exist before 2026-10-22.

## Desired outcome

`excluded_rows` of each period counts only the rows whose `ts` falls in `[since, until)`; every
other figure of the measurement stays as it is.

## In scope

- `measure()` in `scripts/measure_plugin_adoption.py`.
- A regression test in `tests/test_measure_plugin_adoption.py`.

## Out of scope

- The open end of the id search (intended, documented at lines 187-188).
- The adoption percentage and the criterion (not affected, the issue says so and the code confirms).

## Constraints and risks

- Record known technical, security, compatibility, and delivery constraints.

## Open questions

- Resolve questions that materially change the specification before implementation.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-09 Original request, verbatim:

  > Issue #597: la medición de adopción del plugin cuenta las exclusiones (excluded_rows) desde el periodo base hasta hoy y no hasta el fin del periodo («plugin: 146» antes de que existiera el plugin).
- L2 2026-11-09 Implementado, revisado por jueces y verificado; falta mezclar el PR y cerrar.
