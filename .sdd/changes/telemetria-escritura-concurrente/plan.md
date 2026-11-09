# Implementation plan: Las escrituras concurrentes a la telemetria no pierden ni corrompen lineas

## Approach

One stdlib helper in `hook_common`, `append_line(path, text, *, unless=None) -> bool`:
`os.open(O_RDWR | O_APPEND | O_CREAT | O_BINARY)`, take an exclusive lock with a bounded wait
(`msvcrt.locking` on one byte at offset 2**62 on Windows, `fcntl.flock` on POSIX), check the last
byte and prepend `\n` if it is missing, optionally skip when `unless` (bytes) is in the last
`RECORD_ID_TAIL_BYTES`, then a single `os.write` of the whole line; unlock and close. `record` uses
it (with `unless` = the `id` needle on the mod road only); `record_block` uses the same lock for a
read-modify-write that appends while below `MAX_NOTES` and trims to half when full;
`hook_entry._log_failure` uses `append_line`. Readers drop non-object rows.

## Ordered tasks

- [x] T1 — Discriminating tests first: multi-process appends, threads, blocks, failures, racing mod roads, torn line, readers, held lock; run on `main` and record which assert fails (REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008)
  - Files or modules: tests/test_telemetry_concurrent_writes.py
  - Verification: pytest on the new file before the fix, three runs
  - Depends on: none
- [x] T2 — `append_line` and the lock primitives in `hook_common` (REQ-001, REQ-002, REQ-006, REQ-008)
  - Files or modules: src/local_delegate/resources/hooks/hook_common.py
  - Verification: new tests
  - Depends on: T1
- [x] T3 — `record` through `append_line`, atomic dedupe on the mod road (REQ-001, REQ-005, REQ-009)
  - Files or modules: hook_common.py
  - Verification: new tests + tests/test_hook_common.py, tests/test_hook_record_read_endpoint.py, tests/test_mod_record_lost.py
  - Depends on: T2
- [x] T4 — `record_block` under the lock (REQ-003)
  - Files or modules: hook_common.py
  - Verification: new test + tests/test_correlation.py
  - Depends on: T2
- [x] T5 — `hook_entry._log_failure` through `append_line` (REQ-004)
  - Files or modules: src/local_delegate/hook_entry.py
  - Verification: new test + tests/test_hook_entry.py
  - Depends on: T2
- [x] T6 — Readers skip non-object rows (REQ-007)
  - Files or modules: src/local_delegate/web/metrics.py, scripts/measure_adoption.py
  - Verification: new test + metrics tests
  - Depends on: none
- [x] T7 — Repro script again (6x300) with the fix; full suite; ruff; CHANGELOG without issue number (REQ-009)
  - Files or modules: CHANGELOG.md
  - Verification: pytest -n 2, ruff, CI matrix
  - Depends on: T3, T4, T5, T6

## Test strategy

- Unit and integration: `multiprocessing` with a start barrier, 6 processes x 400 lines of ~330
  bytes (the repro gave 10-16 % loss at 6x300: a pass by luck is out of reach); threads 8 x 200.
  Dedupe race: two processes writing the same `id` 50 times each in strict mode, behind a barrier.
- Held lock: the test takes the lock from another process and measures that `record` returns within
  the bound and the line is there.
- End-to-end: the scratch repro with the real `record`, before and after.
- Security and secret scanning: no secrets; no content in the lines changes.

## Migration and compatibility

- Formats, names and locations unchanged. Public signatures unchanged; `append_line` is new.
- Older hook copies (settings delivery) keep the old unlocked append until reinstalled: their lines
  can still tear against new ones, which `\n`-repair keeps from spreading.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
