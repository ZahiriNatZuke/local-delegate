# Implementation plan: Regroup cortado en explain_code y diff grande en commit_msg (#598, #596)

## Approach

#598: inside `_regroup` of `_chat_map_reduce`, after the split guard fails, one widened retry
(cap × 2) guarded by the shrink rule of #497 and by `_retry_fits(1)`; a new counter
`widened_calls` and `combine_cut`. Plan review finding (fixed in the plan): a widened retry that
overflows the context must not fail the whole operation, so on a context overflow the failure is
cleared and the cut output is kept, as today. The counters (cut steps left of kind regroup/reduce) feed the notice. The
negative-claim warning lives in `local_explain_code`'s `_postprocess` and uses a new
`line_check.denies_something` built on the existing `_denies`/`_SENTENCE_END`.

#598 is gated by `widen_cut_regroup` (explain passes `bool(question)`): the hash test of #504
freezes the prompts and answer of explain without a question, and the other tools have their own
frozen tests; the issue's case had a question.

#596 (revised after the first full run): `_chat_map_reduce(time_budget_s=…, time_report=…)`. Before
each map chunk, `_map_time_left(budget, piece_seconds, call_started)`; the clock is `_monotonic()`
(one name for tests) and the start is the cancellation token's `started`. The first design (reduce
the diff to 4 chunks) was dropped: it changed the prompts of every large diff, which broke the
versioned corpus (`techo-commit-156k`) and `test_map_reduce::test_a_diff_that_does_not_fit_goes_in_whole_without_truncating`,
tests that the brief forbids changing. The time budget leaves the prompts untouched whenever there
is time, which is every test and corpus capture (fake backend, no elapsed time).

## Ordered tasks

- [x] T1 — Widened retry of a cut regroup and notice counters (REQ-001, REQ-002)
  - Files or modules: `src/local_delegate/server.py`, `resources/i18n/{es,en}/mcp.json`
  - Verification: `tests/test_explain_regroup_cut.py`, existing regroup tests
  - Depends on: none
- [x] T2 — The combining tail says a «does not happen» may come from the cut (REQ-003); the denial
  detector of the first round was removed after the independent review
  - Files or modules: `server.py`, i18n
  - Verification: `tests/test_explain_regroup_cut.py`
  - Depends on: T1
- [x] T3 — Time budget of the chunked commit_msg and its notice (REQ-004, REQ-005)
  - Files or modules: `server.py`, i18n
  - Verification: `tests/test_commit_large_diff_budget.py`, existing commit tests
  - Depends on: none
- [x] T4 — CHANGELOG `[Unreleased]`, full suite, PR (REQ-001, REQ-002, REQ-003, REQ-004, REQ-005)
  - Files or modules: `CHANGELOG.md`
  - Verification: full pytest `-n 2`, ruff
  - Depends on: T1, T2, T3

## Test strategy

- Unit: `_map_time_left`, `_widened_cap`.
- Worst case with a fake clock: a chunk split twice near the end and a regroup in the reduce.
- Integration: the tools by their real path with `_run_chat` faked (no network, log in tmp).
- End-to-end or manual: none (tests fake the backend).
- Security and secret scanning: no secrets touched; `personal-security-check` before commit.

## Migration and compatibility

- No new option or env var. New i18n keys only; existing texts unchanged. Four English words added
  to `scripts/data/spanish_lexicon.json` (combine, unreliable, widen, widened) for REQ-044.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
