# Brief: recompute-cost no pierde el relleno ni los agregados si la lectura previa falla

## Problem

`recompute-cost` fuses its results into files that hold data which can no longer be rebuilt
(entries of transcripts Claude Code already deleted, manual `resets`, expired quota points,
`n_by_month` of closed months). Before fusing it reads them, and a failed read is taken as "empty":

- `attribution.py:_load_entries` returns `{}` on `OSError` or broken JSON; `write_backfill`
  (`attribution.py:370`) fuses against that `{}` and replaces the month file.
- `recompute.py:_load`/`read_aggregates` return `None` on `OSError`; `run` does
  `previous = read_aggregates(log_dir) or {}` and `write_aggregates` rewrites everything.

A transient lock (antivirus, indexer, the panel reading the same file) at that moment wipes the
history silently. Nothing stops two `recompute-cost` from running at once either.

## Desired outcome

A writer never replaces a file whose previous content it could not read. A transient failure is
retried; a persistent one aborts that run with a clear message and leaves the file intact. A
damaged file (not JSON or wrong shape) keeps a byte copy before being replaced. Only one
`recompute-cost` runs at a time.

## In scope

- `json_state.py` (shared "read before merge" helper), `attribution.write_backfill`,
  `recompute.run`, `cli.cmd_recompute_cost`, i18n keys (es, en), tests, CHANGELOG.

## Out of scope

- The tolerant readers used by the panel (`read_backfill`, `read_aggregates`) keep their contract.
- Telemetry append files (other SDD: `telemetria-escritura-concurrente`).

## Constraints and risks

- Existing tests must pass unchanged, notably `test_a_damaged_new_file_does_not_seed_again`
  (a damaged new aggregates file does not re-seed from the legacy one) and the idempotency test,
  which globs `*.json` in the log dir: the lock and the damaged copies must not end in `.json`.
- Windows and POSIX: `filelock` (already a dependency, used by `test_windows`, `backend_params`).
- Summary and messages carry counts and file names, never full paths (privacy test).

## Open questions

- none.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-09 Original request, verbatim:

  > Tarjeta: recompute-cost borra el relleno de atribución y los agregados si la lectura previa falla un instante. attribution.py _load_entries: OSError o JSON roto -> {}; write_backfill funde contra ese {} y reemplaza el fichero; recompute.py read_aggregates -> None con OSError y previous = ... or {} y luego write_aggregates reescribe todo. Arreglo sugerido: separar «no existe» de «no se pudo leer o está roto»; en el segundo caso abortar la escritura de ese fichero o reintentar, y tomar un cerrojo de fichero durante el recálculo.
- L2 2026-11-09 Implementado, revisado por jueces y verificado; falta mezclar el PR y cerrar.
