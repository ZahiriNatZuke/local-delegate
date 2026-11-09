# Specification: recompute-cost no pierde el relleno ni los agregados si la lectura previa falla

## Summary

`recompute-cost` never replaces the month backfill or `cost-aggregates.json` with less than what
they had because a read failed for a moment.

## Requirements

- **REQ-001** — A transient read failure (`OSError` other than "not found") of the existing month
  backfill is retried; when a retry succeeds, the written file keeps every previous entry.
  - Request: "abortar la escritura de ese fichero o reintentar"
  - Verify: test `test_backfill_survives_a_transient_read_failure`
- **REQ-002** — If the existing backfill (new or legacy name) still cannot be read after the
  retries, `write_backfill` raises an `OSError` subclass and the file on disk is byte-identical.
  - Request: "separar «no existe» de «no se pudo leer o está roto». En el segundo caso, abortar la escritura de ese fichero"
  - Verify: test `test_backfill_is_not_written_over_an_unreadable_file`
- **REQ-003** — The same for `cost-aggregates.json` in `recompute.run`: transient failure retried;
  persistent failure aborts the run before writing any file, and `cost-aggregates.json` keeps its bytes.
  - Request: "Pasa lo mismo con cost-aggregates.json"
  - Verify: test `test_run_survives_a_transient_aggregates_read_failure`, `test_run_writes_nothing_if_the_aggregates_cannot_be_read`
- **REQ-004** — `local-delegate recompute-cost` exits 1 with a message that says it could not READ
  an existing file (by name, without directory) and that nothing was overwritten.
  - Request: derived: today the CLI would print "could not write", which misleads.
  - Verify: test `test_the_cli_says_it_could_not_read`
- **REQ-005** — A damaged existing file (not JSON, not UTF-8 or wrong shape) is copied byte for byte
  to `<name>.damaged-<UTC stamp>` before being replaced; the run summary counts it in `set_aside`
  and the terminal summary says so. Otherwise the damaged file keeps being treated as empty, as today.
  - Request: "o está roto"
  - Verify: test `test_a_damaged_backfill_is_set_aside_before_being_replaced`, `test_a_damaged_aggregates_file_is_set_aside`
- **REQ-006** — Two `recompute.run` on the same log dir do not overlap: a `FileLock`
  (`recompute-cost.lock`) is held for the whole run; if it cannot be taken within its timeout the
  run raises without writing and the CLI exits 1 saying another `recompute-cost` is running.
  - Request: "tomar un cerrojo de fichero durante el recálculo"
  - Verify: test `test_a_second_run_waits_for_the_lock`
- **REQ-007** — The tolerant readers (`read_backfill`, `read_aggregates`) and every existing test
  keep their behavior.
  - Request: derived: no-regression rule; the panel reads these files on every poll.
  - Verify: cmd `pytest` (full suite, existing tests unchanged)

## Acceptance scenarios

### Scenario: the antivirus holds the month file for an instant

- **Given** `attribution-202610.json` with 50 entries whose first read raises `PermissionError`
- **When** `recompute-cost` writes one new entry for that month
- **Then** the file has 51 entries

### Scenario: the file stays locked

- **Given** the read keeps failing
- **When** `recompute-cost` runs
- **Then** it exits 1 saying it could not read `attribution-202610.json`, and the file is unchanged

## Edge cases and failure behavior

- Not found is not a failure: the legacy seed path and first runs stay as today.
- Retries: a few attempts with a short growing delay (about 1.5 s total), then abort.
- A damaged copy name ends in `.damaged-<stamp>`, never `.json`, so no reader picks it up.
- Months written before the abort stay written: each month file is merge-only and atomic.

## Non-functional requirements

- Windows and POSIX (`filelock`). No new dependency. No paths in summary or messages.

## Non-goals

- Making the panel readers strict; rotating or pruning damaged copies.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
