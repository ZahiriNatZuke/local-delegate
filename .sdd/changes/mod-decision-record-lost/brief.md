# Brief: A mod decision record is reported as written even when it is not

## Problem

Finding of the 2026-10-23 security review (medium). `hook_common.record` swallows `OSError`, so when `LD_HOOK_TELEMETRY_LOG` cannot be opened `hook_entry.record_read` returns normally: the daemon answers 204 and `python -I -m local_delegate.hook record-read` exits 0. The mod (`mod/read.js`) treats both as `taken`, never retries and never writes `ModRecordLost`; the decision is lost without a trace. By the process road every failure (broken JSON, broken import, exception in `record_decision`) also exits 0, and `hook-failures.jsonl` only gets the error type, not the decision.

Checked on 0.48.0: the endpoint already answers 500 when `record_read` raises, and the mod already falls back to the process and to its retry/`ModRecordLost` path on a non-204 answer or a non-zero exit. What is still broken is that nothing raises and the CLI always exits 0.

## Desired outcome

On the `record-read` road an unwritten decision line is reported as a failure (500 from the daemon, exit 1 from the CLI) so the mod's existing retry/`ModRecordLost` path runs; normal hooks of `hooks.json` keep swallowing the write error and exiting 0.

## In scope

- `hook_common.record` (strict mode only for `record-read`).
- `hook_entry.record_read`, `main`, `_log_failure` (decision and via in the failure line).
- `hook.py` exit code for `classify`/`record-read` only.
- Endpoint passes the entry to `_log_failure`.

## Out of scope

- `mod/read.js` (already handles 500 and exit != 0).
- UTF-8 hook encoding work done in parallel (`install.py`, `suggest_delegate_*.py`, start of `hook_common.py`).
- `record_block` notes.

## Constraints and risks

- Record known technical, security, compatibility, and delivery constraints.

## Open questions

- Resolve questions that materially change the specification before implementation.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-04 Original request, verbatim:

  > Fix: hook_common.record swallows OSError so POST /api/hook/record-read answers 204 and 'python -m local_delegate.hook record-read' exits 0 when the decision line was not written; the mod counts it as taken and never retries nor logs ModRecordLost. Make the record-read path report the failure (500 / exit 1) without changing normal hooks, and note the decision in hook-failures.jsonl.
