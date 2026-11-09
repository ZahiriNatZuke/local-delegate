# Implementation plan: local_summarize: tope de salida que crece con la entrada grande

## Approach

`_summary_max_tokens(words, chars=0)` adds `max(0, chars - SUMMARY_FLAT_CHARS) // SUMMARY_CHARS_PER_EXTRA_TOKEN`
(16 000 and 20) to `3w + 64`. Only the single call of `local_summarize` passes `len(content)`; the
map/reduce keeps calling it with the words only (unchanged, and out of #610's way). The trim to the
last sentence (`trim_cut`, #581) stays as the fallback.

## Ordered tasks

- [x] T1 — Tests first with a fake backend: cap by input size, `length` trimmed with notice (REQ-001, REQ-002)
  - Files or modules: tests/test_summarize_big_input_cap.py
  - Verification: the cap test fails on origin/main by its `max_tokens` assert
  - Depends on: none
- [x] T2 — Cap that grows with a big input in the single call (REQ-001, REQ-003)
  - Files or modules: src/local_delegate/server.py, CHANGELOG.md
  - Verification: new and existing summarize tests; full suite
  - Depends on: T1
- [x] T4 — Ceiling and the structured single call, after the review of #615 (REQ-005, REQ-006)
  - Files or modules: src/local_delegate/server.py (`_big_input_extra`, `_single_call_cap`), tests
  - Verification: the 4 new tests fail on 04341ab7 (2114, 9714, 884, no helper); area tests green
  - Depends on: T2
- [x] T3 — Live rerun recipe (REQ-004)
  - Files or modules: scratchpad/live/rerun_580.md (outside the repo)
  - Verification: review
  - Depends on: T2

## Test strategy

- Unit: `_summary_max_tokens` values at the boundary.
- Integration: `local_summarize` through its real path with the backend mocked (`stop` and `length`).
- End-to-end or manual: live rerun in the release joint test (recipe).
- Security and secret scanning: pre-commit hooks.

## Migration and compatibility

- Request bodies change only for inputs over 16 000 characters (frozen fixtures are short).

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
