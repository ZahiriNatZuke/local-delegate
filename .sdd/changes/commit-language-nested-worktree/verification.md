# Verification: local_commit_msg: repo language from the commit history, not the reflog (#548)

## Environment

- Revision: branch `fix/commit-language-nested-worktree` on top of 89551158 (0.48.0 + SDD close).
- Relevant runtime and tool versions: Python 3.11.15 (repo `.venv`, `PYTHONPATH=src`), git for
  Windows, Windows 11.

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_a_worktree_nested_in_the_main_checkout_follows_the_history[loose,packed]`; probe on this agent worktree | pass | Probe before: git dir and `commondir` right, common reflog 20 subjects 10 es / 7 en → `mixed_repo`; after: 20 subjects 1 es / 15 en → `("en", "repo")` from root and from `.sdd/changes/<slug>/` |
| REQ-002 | `test_commits_stored_as_deltas_are_rebuilt[ofs-delta,ref-delta]`, packed variant of REQ-001, `test_a_full_fresh_clone_reads_its_history` | pass | guard asserts the pack holds delta commits; mutant «copy from 0» fails both |
| REQ-003 | existing `tests/test_commit_grounding.py`, `tests/test_commit_language_notice.py`; `test_a_corrupt_store_falls_back_to_the_reflog` | pass | fake-reflog tests unchanged and green; one real-clone test moved to a shallow clone (see deviations) |
| REQ-004 | `test_an_object_over_the_cap_is_not_inflated`, `test_a_zip_bomb_loose_object_stops_at_the_cap`, `test_an_odd_head_is_not_followed`, `test_no_git_process_is_started` | pass | mutants «no size check», «any ref», «errors escape» each fail their test |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `ruff check src tests scripts` | yes | pass | All checks passed |
| `ruff format --check src tests scripts` | yes | pass | 353 files already formatted |
| `pytest -q -n 2 --dist loadgroup` (full suite, via `pesado.sh`) | yes | pass | see handoff for counts |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Existing test `test_a_fresh_copy_says_short_history_not_mixed` pinned the old symptom: a full
  fresh clone with six English commits answered `short_history`. With the history read from the
  objects it answers `("en", "repo")`, which is the right answer. The test now clones with
  `--depth 1` (the CI checkout shape), so it still checks that a short history is not called
  «mixed»; the full-clone case is covered by `test_a_full_fresh_clone_reads_its_history`.
- Not supported (fall back to the reflog as before): SHA-256 repos, `objects/info/alternates`,
  reftable refs. Shallow repos stop the walk at the boundary.
- First full run had 2 failures (`test_density`, `test_dashboard_cost`) caused by editing
  `server.py` comments while the run was going (`inspect.getsource` read shifted lines); both pass
  alone and in the rerun.
