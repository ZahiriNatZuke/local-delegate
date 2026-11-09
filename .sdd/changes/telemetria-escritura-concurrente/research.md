# Research: Las escrituras concurrentes a la telemetria no pierden ni corrompen lineas

## Current behavior

- `hook_common.record` (`src/local_delegate/resources/hooks/hook_common.py:181-212`) opens
  `LD_HOOK_TELEMETRY_LOG` with `path.open("a")` and `stream.write(json + "\n")` through a buffered
  text stream, without a lock. Writers: every hook process, the daemon threads behind
  `POST /api/hook/record-read` (`web/metrics.py:1236-1256`, `run_in_threadpool`), and the
  `record-read` CLI (`hook_entry.record_read`).
- Reproduced on this PC (Windows 11, Python 3.11) with the real `record`: 6 processes x 300 lines of
  ~330 bytes -> `valid=1515 corrupt=1`, `valid=1593 corrupt=3`, `valid=1616 corrupt=2` of 1800
  (scratch `repro_append.py`). Same order as the card (1550 / 23).
- `record_block` (`hook_common.py:963-990`): `read_text` + `write_text` of the whole notes file
  (`%TEMP%/local-delegate-blocks.jsonl`), no lock; two blocks at once keep only one note. Bounded to
  `MAX_NOTES` lines (`tests/test_correlation.py:81-84` asserts it).
- `hook_entry._log_failure` (`hook_entry.py:240-264`): same unsafe `open("a")` on
  `LOG_DIR/hook-failures.jsonl`.
- Mod road dedupe: `suggest_delegate_read.record_decision` and `suggest_delegate_shell.record_decision`
  call `already_recorded(record_id)` (`hook_common.py:266-285`, reads the last 64 KiB) and later
  `record(...)`: two roads racing (daemon late + process fallback) both pass the check.
- `mod/read.js:586-615` `readRecordLost` rewrites `hook-failures.jsonl` with `$.fs.read` +
  `$.fs.write`; the mod API exposes no append (`$.fs.read|write|stat` only in the mod).

## Readers with an already corrupt line

| Reader | Behavior on an invalid line | Behavior on a valid-JSON non-object fragment |
| --- | --- | --- |
| `web/metrics.py:_read_file_cached` (usage and hooks telemetry) | skipped (`JSONDecodeError`) | kept as-is; later `row.get(...)` (`metrics.py:753`, `:213`) raises `AttributeError` -> the endpoint fails |
| `scripts/measure_adoption.py:_events` (`:70-82`) | skipped | `event.get` raises `AttributeError` -> the measurement crashes |
| `checks.py:376-387` | skipped | filtered (`isinstance(item, dict)`) |
| `checks.py:2296-2310` (tail reader) | skipped | `event["ts"]` -> `TypeError`, caught |
| `server.py:1141-1160` block notes | skipped | `note["ts"]` -> `TypeError`, caught |

A torn line can glue to the next append when a file ends without `\n` (a previous crash or tear):
the next whole line is lost too, because both become one invalid line.

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| `hook_common.record` | append one telemetry line | locked single-write append; atomic dedupe on the mod road | `hook_common.py:181-212` |
| `hook_common.record_block` | keep last `MAX_NOTES` block notes | locked read-modify-write | `hook_common.py:963-990` |
| `hook_entry._log_failure` | append failure line | same locked append | `hook_entry.py:240-264` |
| `web/metrics.py:_read_file_cached` | parse JSONL for the panel | drop non-object rows | `metrics.py:123-150` |
| `scripts/measure_adoption.py` | measurement | drop non-object rows | `measure_adoption.py:70-82` |

## Existing conventions

- Hooks are stdlib-only; `hook_common` is also copied to the settings delivery.
- Telemetry is best effort: an `OSError` is swallowed except inside `record_or_raise`.
- Atomic replace (`tempfile` + `os.replace`) for whole-file state (`record_call`, `json_state`).
- Cross-process locks elsewhere use `filelock` (not available to hooks).

## Dependencies and integrations

- `msvcrt.locking` (Windows) and `fcntl.flock` (POSIX), both stdlib. Verified on this PC: a lock on
  one byte at offset 2**62 refuses a second handle (errno 13), does not block reading or appending
  at EOF, and unlocks.
- CI runs the suite on ubuntu, windows and macos (`.github/workflows/ci.yml:140`).

## Risks and unknowns

- Windows byte-range locks are mandatory: the locked byte must be outside any data (offset 2**62).
- A hook must not hang on a lock: bounded wait, then write anyway (current behavior, minus loss).
- A process killed while holding the lock: the OS releases it with the handle (both platforms).
- The mod's `readRecordLost` stays a non-atomic rewriter (residual, documented, other owner).
