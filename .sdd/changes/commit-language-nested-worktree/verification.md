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
| `pytest -q -n 2 --dist loadgroup` (full suite, via `pesado.sh`) | yes, before review fixes | 6389 passed, 4 failed (2 fixed: lexicon/catalogue; 2 from editing during the run, pass alone) | local run, 2026-11-04 |
| `pytest` on the 3 commit-language files + name detector (after review fixes) | yes | 80 passed | local, without the lock (it was held by a hung run) |
| CI of PR #562 (ubuntu, macos, windows, lang-es, lint, CodeQL…) | yes | see `gh pr checks 562` | first run: 2 failures on ubuntu, fixed (see deviations) |

## Positive control

| Test | Mutant | Assert that fires |
| --- | --- | --- |
| nested worktree (loose, packed) and 5 more reading tests | «reflog only» | `("es","mixed_repo") == ("en","repo")` / `[] == ENGLISH` |
| deltas (ofs, ref) | «delta copies from 0» | subjects garbled |
| object cap, zip bomb | «no size check» | subjects come back / `pytest.raises` gets `ValueError` |
| odd HEAD | «any ref» | subjects come back |
| packed ref | «loose refs only» | `[]` and `mixed_repo` |
| corrupt store | «errors escape» | `_Unreadable` raised |
| merges | «use the merge subject» | `any(startswith("Merge pull request"))` |
| short history filled from the reflog | «history replaces the reflog when not empty» | `("es","short_history") == ("en","repo")` |
| delta depth cap | «no depth check» (both) | all six subjects come back |
| huge packed-refs | «no size check» (both) | subjects come back |

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
- First CI run on ubuntu: `test_a_short_history_is_filled_from_the_reflog` assumed the newest
  commit is stored whole after `git repack`; the runner's git stored it as a delta, so a depth cap
  of 0 read nothing. The reader was fine (the packed, delta and nested-worktree tests passed on
  ubuntu); the test now cuts the walk with a damaged older loose object. Also `regular` went to
  the lexicon.
- After the review fixes the full suite could not run locally (the machine-wide lock was held
  by a hung run of this agent); CI covers it.
- First full run had 2 failures (`test_density`, `test_dashboard_cost`) caused by editing
  `server.py` comments while the run was going (`inspect.getsource` read shifted lines); both pass
  alone and in the rerun.
