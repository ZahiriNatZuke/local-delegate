# Specification: A mod decision record is reported as written even when it is not

## Summary

When the mod asks to record a decision (`hook record-read`, by the daemon or by the process) and the
line cannot be written, the caller is told so: the daemon answers 500 and the CLI exits 1, and
`hook-failures.jsonl` names the decision. Normal hooks keep their best-effort telemetry and exit 0.

## Requirements

- **REQ-001** — On the `record-read` road, an `OSError` writing the telemetry line propagates out of `hook_entry.record_read`; a normal hook's `record` still swallows it.
  - Request: "Make the record-read path report the failure ... without changing normal hooks"
  - Verify: test tests/test_mod_record_lost.py
- **REQ-002** — `POST /api/hook/record-read` answers 500 (not 204) when the line was not written, and writes a failure line.
  - Request: "POST /api/hook/record-read answers 204 ... when the decision line was not written"
  - Verify: test tests/test_mod_record_lost.py
- **REQ-003** — `python -I -m local_delegate.hook record-read` exits 1 when the line was not written or the input is broken; `classify` exits 1 on an unexpected failure; every `hooks.json` hook still exits 0, never 2.
  - Request: "'python -m local_delegate.hook record-read' exits 0 when the decision line was not written"
  - Verify: test tests/test_mod_record_lost.py
- **REQ-004** — The `hook-failures.jsonl` line of a failed `record-read` carries the decision and the via (sanitized short names), never the path or message.
  - Request: "note the decision in hook-failures.jsonl"
  - Verify: test tests/test_mod_record_lost.py

## Acceptance scenarios

### Scenario: destination cannot be opened

- **Given** `LD_HOOK_TELEMETRY_LOG` points at a directory
- **When** the mod records a `summarized` decision by the daemon and then by the process
- **Then** the daemon answers 500, the process exits 1, and `hook-failures.jsonl` has `hook: record-read`, `decision: summarized`

### Scenario: normal hook

- **Given** the same broken destination
- **When** a `hooks.json` hook runs
- **Then** it exits 0 with its usual output

## Edge cases and failure behavior

- No destination or `LD_HOOK_ENABLED=0`: nothing is written by design; still success (204 / 0).
- A decision id already in the log: success without writing (unchanged).
- Non-dict entry: unchanged (silent success).

## Non-functional requirements

- No path, message or user content in `hook-failures.jsonl`.
- Exit code is only ever 0 or 1.

## Non-goals

- Changing `mod/read.js`; changing block notes.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
