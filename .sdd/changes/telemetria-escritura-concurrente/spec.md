# Specification: Las escrituras concurrentes a la telemetria no pierden ni corrompen lineas

## Summary

Telemetry lines written at the same time by hooks, the daemon and the CLI all arrive whole, on
Windows and POSIX; block notes and mod decisions are not lost or duplicated by races; readers
survive a corrupt line that is already on disk.

## Requirements

- **REQ-001** — N processes calling `hook_common.record` at once on the same destination produce
  exactly N x lines valid JSON lines and no invalid one.
  - Request: "escrituras concurrentes a la telemetría pierden y corrompen líneas"
  - Verify: test `test_concurrent_records_keep_every_line`
- **REQ-002** — Threads of one process (the daemon) calling `record` at once also keep every line.
  - Request: "desde los hilos del daemon en /api/hook/record-read"
  - Verify: test `test_concurrent_threads_keep_every_line`
- **REQ-003** — N processes calling `record_block` at once keep every note (up to `MAX_NOTES`), and
  the file never exceeds `MAX_NOTES` lines.
  - Request: "record_block (leer-todo-y-reescribir sin cerrojo …)"
  - Verify: test `test_concurrent_blocks_keep_every_note`; existing `tests/test_correlation.py`
- **REQ-004** — `hook_entry._log_failure` appends with the same locked writer: concurrent failures
  keep every line.
  - Request: "y el log de fallos"
  - Verify: test `test_concurrent_failures_keep_every_line`
- **REQ-005** — On the mod road (`record_or_raise`), a line whose `id` is already in the tail is not
  written again, and the check and the write are one locked step: two racing writers of the same
  `id` leave exactly one line.
  - Request: "comprobar el id y luego escribir no es atómico"
  - Verify: test `test_racing_mod_roads_write_one_line`
- **REQ-006** — A new line never glues to a previous line left without `\n`: the writer adds the
  missing newline first, so the new line stays valid.
  - Request: derived: "Evalúa también qué hacen los lectores con una línea corrupta ya existente"
  - Verify: test `test_a_torn_last_line_does_not_swallow_the_next`
- **REQ-007** — The panel reader (`web/metrics._read_file_cached`) and `scripts/measure_adoption.py`
  skip a line that is valid JSON but not an object, instead of failing later.
  - Request: derived: same evaluation of readers (research table)
  - Verify: test `test_readers_skip_a_non_object_line`
- **REQ-008** — A hook never waits more than the bounded lock wait (about 1 s); past it, the line is
  still written with one `os.write`. Write errors keep their current handling (swallowed, raised
  only inside `record_or_raise`).
  - Request: derived: hooks run inside the agent's tool call and must not hang.
  - Verify: test `test_a_held_lock_does_not_hang_the_hook`; existing tests of `record_or_raise`
- **REQ-009** — Public signatures `record`, `record_block`, `already_recorded`, `record_or_raise`,
  `_log_failure` and every existing test stay as they are; Windows, Linux and macOS pass.
  - Request: "mantener la firma pública compatible"
  - Verify: cmd `pytest` locally (Windows) and CI matrix (ubuntu, windows, macos)

## Acceptance scenarios

### Scenario: parallel reads fire many hooks

- **Given** six hook processes and the daemon writing to the same telemetry file
- **When** they each write 300 lines at the same moment
- **Then** the file has 1800 lines and all parse as JSON objects

### Scenario: the mod retries a decision the daemon wrote late

- **Given** the daemon and the process road both write the decision with `id` X at once
- **When** both finish
- **Then** exactly one line has `id` X

## Edge cases and failure behavior

- Destination directory missing: created, as today.
- Lock not obtained within the wait: write anyway (one `os.write`), never drop the line.
- Unwritable destination: swallowed (strict mode raises), as today.
- Process killed with the lock held: the OS releases it.

## Non-functional requirements

- Stdlib only in hooks. No new dependency. No change of formats, names or locations.
- Typical cost per line: one open, one lock, one write (plus a 1-byte read for the newline check).

## Non-goals

- `mod/read.js` `readRecordLost` (other owner today; follow-up card).
- Repairing corrupt lines already on disk.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
