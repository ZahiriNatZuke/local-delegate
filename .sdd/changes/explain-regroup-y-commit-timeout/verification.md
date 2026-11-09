# Verification: Regroup cortado en explain_code y diff grande en commit_msg (#598, #596)

## Environment

- Revision: branch `fix/explain-regroup-y-commit-timeout` over `origin/main` ac33807a.
- Relevant runtime and tool versions: Python 3.11 (`.venv` of the main checkout, `PYTHONPATH=src`
  pointing to the worktree), pytest with xdist `-n 2`, ruff of the repo.

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_a_cut_regroup_that_cannot_split_is_retried_wider`, `test_a_widened_retry_that_overflows_keeps_the_cut_output`, `test_without_the_flag_the_cut_regroup_is_kept_as_before`, `test_explain_with_a_question_widens_a_cut_regroup` | pass | 182 passed (affected files); mutants M1 (`truncated_out` assert) and M5 (`any(max_tokens == 2×cap)` assert) fail as expected; M10 (cap not bounded) fails `test_no_widened_retry_when_the_backend_would_not_take_a_wider_cap` |
| REQ-002 | `test_a_regroup_cut_again_is_named_as_a_combining_step` | pass | mutant M2 fails on the `combine_cut` assert |
| REQ-003 | `test_a_regroup_cut_again_is_named_as_a_combining_step` (the tail, with the «does NOT happen» sentence, right after the main one) | pass | mutant M2 fails on that assert; the denial detector of round 1 was removed with its tests |
| REQ-004 | `test_the_issue_diff_stops_the_map_in_time_and_says_so`, `test_the_worst_case_stays_well_under_the_client_limit`, `test_without_a_budget_the_worst_case_does_retry`, `test_outside_a_tool_call_every_chunk_is_read`, `_map_time_left` units | pass | mutants M4 (`<= 120`), M8 (split retry without the clock) and M9 (regroup without the clock) fail on `elapsed <= 110` |
| REQ-005 | same issue test (warning, receipt, `truncated_in`), `test_with_time_left_the_prompts_are_unchanged`, `tests/test_corpus.py`, `tests/test_map_reduce.py` | pass | corpus `techo-commit-156k` and `test_a_diff_that_does_not_fit_goes_in_whole_without_truncating` green without changes |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest -q -n 2 tests` (via `pesado.sh`) | full suite, round 2 | pass | 6738 passed, 29 skipped; the one failure (an unclassified name in a new test) fixed and rechecked |
| `ruff check src tests` and `ruff format --check` | changed files | pass | All checks passed |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes (grep of the diff for tokens, keys and private paths: none).
- [x] No unrelated changes are present.

## Deviations and residual risk

- First design for #596 (reduce the diff to 4 chunks) dropped: it broke the versioned corpus and
  `test_map_reduce`, which the brief forbids changing. The time budget never changes a prompt
  while there is time; its risk is the estimate (slowest chunk after the first): a chunk much
  slower than the ones before can still pass 120 s.
- #598 is gated to explain with a question; the other chunked tools keep today's regroup.
- The issue's count complaint («1 de 17» with 2 cut regroups) was already covered by #487: the
  split retry is named apart («aparte, 1 llamadas cortadas se repitieron…»).
- Round 2 (independent review): split retries, regroup levels and the widened retry check the
  clock too; worst case modelled under 110 s. Still open: a wait over 95 s before the second
  backend call cannot be stopped (two calls are needed to estimate), and a context-overflow split
  is not checked (without it the operation fails anyway).
- No live check against the real backend (tests fake it); the behaviour on the 125 KB diff is
  modelled with the issue's measured pace.

## Final result

- Merged in `main` as `0bfef1d2` (PR #610, 2026-11-09T16:44:39Z).
- `main` CI on `0bfef1d2`: test (ubuntu-latest) red on its own merge commit: `tests/test_completion_powershell.py` (`pwsh exit=-6`), unrelated and intermittent.
- `main` at `c25e608f`: CI (run 42678307325 Wiki, 42678307752 CI), CodeQL and Vendor audit green on `c25e608f`.
- Closed on 2026-11-09 in the 0.50.0 release PR (`release/0.50.0`).
