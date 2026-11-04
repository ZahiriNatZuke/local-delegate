# Implementation plan: A mod decision record is reported as written even when it is not

## Approach

A context variable in `hook_common` (`_RECORD_STRICT`, set only through `hook_common.record_or_raise`)
makes `record` re-raise its `OSError`. `hook_entry.record_read` runs `record_decision` through it, so
the endpoint (which already maps an exception to 500) and the CLI see the failure without touching
`suggest_delegate_*.py` (parallel UTF-8 work). `hook_entry.main` returns 1 for a failed
`classify`/`record-read`; `hook.run` exits with 1 only when the target returns 1, else 0.
`_log_failure` gets an optional entry and writes its sanitized `decision`/`via`.

## Ordered tasks

- [x] T1 — strict mode in `hook_common.record` and `record_or_raise` (REQ-001)
  - Files or modules: src/local_delegate/resources/hooks/hook_common.py, src/local_delegate/hook_entry.py
  - Verification: tests/test_mod_record_lost.py
  - Depends on: none
- [x] T2 — endpoint passes the entry to `_log_failure` (REQ-002, REQ-004)
  - Files or modules: src/local_delegate/web/metrics.py, src/local_delegate/hook_entry.py
  - Verification: tests/test_mod_record_lost.py
  - Depends on: T1
- [x] T3 — exit 1 for failed `classify`/`record-read` (REQ-003)
  - Files or modules: src/local_delegate/hook.py, src/local_delegate/hook_entry.py
  - Verification: tests/test_mod_record_lost.py
  - Depends on: T1
- [x] T4 — tests, positive control, CHANGELOG, installed check (REQ-001, REQ-002, REQ-003, REQ-004)
  - Files or modules: tests/test_mod_record_lost.py, CHANGELOG.md
  - Verification: pytest
  - Depends on: T1, T2, T3

## Test strategy

- Unit:
- Integration:
- End-to-end or manual:
- Security and secret scanning:

## Migration and compatibility

- Describe compatibility boundaries, data migration, and rollout considerations.

## Plan review

- [ ] Every requirement maps to at least one task and verification step.
- [ ] Risky or destructive operations have safeguards and rollback.
- [ ] Dependencies and configuration changes are explicit.
- [ ] The plan does not include unrelated work.
