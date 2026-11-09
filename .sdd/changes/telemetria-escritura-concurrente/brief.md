# Brief: Las escrituras concurrentes a la telemetria no pierden ni corrompen lineas

## Problem

Several processes append to the same telemetry files at once: every hook process, the daemon's
`/api/hook/record-read` threads, and the `record-read` CLI. `hook_common.record` opens with mode
`"a"` and writes through a buffered text stream; on Windows the CRT append is "seek to end + write",
not atomic across processes, so lines overwrite each other and others come out split (invalid
JSON that every reader drops). Reproduced on this PC: 6 processes x 300 lines -> 1515-1616 valid of
1800, 1-3 corrupt (scratch `repro_append.py`, three runs). `record_block` reads the whole notes file
and rewrites it without a lock: two simultaneous blocks lose one note. `hook_entry._log_failure`
appends to `hook-failures.jsonl` the same unsafe way. The mod's record-read path checks the `id`
in the tail (`already_recorded`) and then writes: check and write are not atomic.

## Desired outcome

Concurrent appends from any number of processes and threads, on Windows and POSIX, keep every line
whole and none is lost. Block notes are not lost by concurrent blocks. A mod decision with the same
`id` is written once even when two roads race. Readers keep working with a corrupt line that is
already in a file, and a new line is never glued to a previous truncated one.

## In scope

- `resources/hooks/hook_common.py`: a stdlib-only locked append helper; `record`, `record_block`,
  atomic dedupe on the mod road.
- `hook_entry._log_failure` (Python writer of `hook-failures.jsonl`).
- Readers' evaluation (`web/metrics.py`, `scripts/measure_adoption.py`, `checks.py`,
  `server.py` block-note reader) and a fix where one can crash on a valid-JSON non-object line.
- Tests (multi-process, discriminating) and CHANGELOG.

## Out of scope

- `mod/read.js` `readRecordLost` (rewrites `hook-failures.jsonl` through `$.fs.read` + `$.fs.write`;
  the mod API has no append). Another agent owns hooks/mod today; the race only hits when BOTH the
  daemon and the process roads already failed. Reported as residual risk and follow-up.
- Changing file formats or locations.

## Constraints and risks

- Hooks are stdlib only (`hook_common` is copied to the settings delivery): no `filelock`.
- A byte-range lock on Windows is mandatory, not advisory: locking byte 0 would make readers fail.
  The lock byte sits at offset 2**62, far beyond any end of file (checked on this PC: lock, second
  lock refused with errno 13, write lands at EOF, unlock).
- A hook must not hang: the lock wait is bounded (about 1 s); past it the line is written anyway
  with one `os.write` (best effort, as today) instead of being dropped.
- Public signatures (`record`, `record_block`, `already_recorded`, `record_or_raise`) stay.

## Open questions

- none.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-09 Original request, verbatim:

  > Tarjeta: escrituras concurrentes a la telemetría pierden y corrompen líneas. hook_common.record (open a + write sin cerrojo, desde cada hook y desde los hilos del daemon en /api/hook/record-read); record_block (leer-todo-y-reescribir sin cerrojo en local-delegate-blocks.jsonl); mod/read.js readRecordLost reescribe entero hook-failures.jsonl que Python escribe en paralelo por append; comprobar el id y luego escribir no es atómico. Arreglo sugerido: una sola os.write por línea sobre un descriptor O_APPEND y un cerrojo de fichero (msvcrt.locking/fcntl.flock) en record, record_block y el log de fallos; que el mod deje de reescribir hook-failures.jsonl. Encargo: nivel standard; Windows (sin fcntl) y POSIX; reproducir con varios procesos antes de arreglar; test que falle sin el fix; evaluar qué hacen los lectores con una línea corrupta ya existente; mantener la firma pública compatible.
- L2 2026-11-09 Implementado, revisado por jueces y verificado; falta mezclar el PR y cerrar.
