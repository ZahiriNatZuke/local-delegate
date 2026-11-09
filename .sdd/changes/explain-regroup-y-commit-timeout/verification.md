# Verification: Regroup cortado en explain_code y diff grande en commit_msg (#598, #596)

## Environment

- Revision: branch `fix/explain-regroup-y-commit-timeout` over `origin/main` ac33807a.
- Relevant runtime and tool versions: Python 3.11 (`.venv` of the main checkout, `PYTHONPATH=src`
  pointing to the worktree), pytest with xdist `-n 2`, ruff of the repo.

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_a_cut_regroup_that_cannot_split_is_retried_wider`, `test_a_widened_retry_that_overflows_keeps_the_cut_output`, `test_without_the_flag_the_cut_regroup_is_kept_as_before`, `test_explain_with_a_question_widens_a_cut_regroup` | pass | 182 passed (affected files); mutants M1 (`truncated_out` assert) and M5 (`any(max_tokens == 2×cap)` assert) fail as expected |
| REQ-002 | `test_a_regroup_cut_again_is_named_as_a_combining_step` | pass | mutant M2 fails on the `combine_cut` assert |
| REQ-003 | `test_a_cut_answer_that_denies_gets_the_warning`, `test_without_a_cut_the_negative_answer_is_unchanged`, `test_a_cut_answer_that_denies_nothing_gets_no_warning`, `test_denies_something[*]` | pass | mutant M3 fails on the `negative_unreliable` assert |
| REQ-004 | `test_the_issue_diff_stops_the_map_in_time_and_says_so`, `test_the_first_chunk_alone_never_stops_the_map`, `test_the_estimate_skips_the_first_chunk` | pass | mutant M4 fails on `clock - start <= 120` (148 fake seconds) |
| REQ-005 | same issue test (warning, receipt, `truncated_in`), `test_with_time_left_the_prompts_are_unchanged`, `tests/test_corpus.py`, `tests/test_map_reduce.py` | pass | corpus `techo-commit-156k` and `test_a_diff_that_does_not_fit_goes_in_whole_without_truncating` green without changes |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest -q -n 2 tests` (via `pesado.sh`) | full suite | pass | 6715 passed, 29 skipped in 368 s |
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
- Residual time risks (judge B, B-07): a chunk split by #455 or overflowing costs ~3× the
  estimate after the check (worst case ~123 s); a regroup inside the reduce is not estimated; a
  wait over 95 s before the second chunk cannot be stopped (two chunks are needed to estimate).
- No live check against the real backend (tests fake it); the behaviour on the 125 KB diff is
  modelled with the issue's measured pace.
