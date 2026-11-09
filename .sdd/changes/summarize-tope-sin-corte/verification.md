# Verification: local_summarize: tope de salida que crece con la entrada grande

## Environment

- Revision: branch `fix/summarize-tope-sin-corte` on `origin/main` `2fd7ab43`
- Relevant runtime and tool versions: Python 3.11.15 (`.venv` of the main checkout, `PYTHONPATH=src`), Windows 11

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_the_cap_grows_with_a_big_input_only`, `test_the_single_call_of_a_big_input_asks_the_wider_cap`, `test_a_small_input_keeps_the_cap`, `test_the_cap_counts_characters_not_bytes_of_a_file` | pass | on origin/main the tool-path test fails by `assert [514] == [884]` and the unit one by `TypeError` (no `chars`) |
| REQ-002 | `test_a_big_input_still_cut_ends_at_a_sentence_with_a_notice` (fake backend answers `length`) | pass | guard: passes on main too (trim from #581); keeps it on big inputs |
| REQ-003 | `test_summarize_word_budget.py`, `test_request_body_compat.py`, `test_structured_summary.py`, focus tests unchanged | pass | 185 passed; map/reduce calls `max_tokens_for(words)` without characters |
| REQ-005 | `test_the_widening_stops_at_the_chunk_cap`, `test_a_raised_long_limit_does_not_ask_more_than_the_chunk_cap`, `test_the_context_left_after_the_prompt_bounds_the_widening` | pass | on 04341ab7: `assert [2114] == [2048]`, `assert [9714] == [2048]`, `assert 884 < 884` |
| REQ-006 | `test_the_structured_single_call_gets_the_same_room` (switch on, guard on the structured prompt) | pass | on 04341ab7 fails (no `_big_input_extra`; the structured call asked its base cap) |
| REQ-004 | `scratchpad/live/rerun_580.md` | pass | call, file (`docs/wiki/Architecture.md`, 22 719 chars), expected cap 849, criterion |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest -q -n 2 tests` (via `pesado.sh`) | yes | pass after lexicon update | 6727 passed, 29 skipped, 1 failed (`test_detect_spanish_names`: `grows` unclassified) -> added to the lexicon, rerun green |
| `ruff check` / `ruff format --check` on changed files | yes | pass | All checks passed |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- `LOCAL_DELEGATE_STRUCTURED_SUMMARY`: off by default (`config.py:325`); not defined in this PC's user or machine environment nor in `~/.claude/settings.json`.
- `_widened_cap` of #610 is not in `main` yet: the ceiling is written here; unify when #610 lands.
- Not measured live yet: the release joint test runs the recipe.
- Just above 16 000 characters the extra is small (564 at 17 000); cuts there still end at a
  sentence with the notice. A runaway answer is now bounded by `CHUNK_MAX_TOKENS` (2 048, 4x before).
- The map/reduce pieces keep 3w+64 (out of #610's way).

## Final result

- Merged in `main` as `f0dea77a` (PR #615, 2026-11-09T17:04:44Z).
- `main` CI on `f0dea77a`: all check runs green.
- `main` at `c25e608f`: CI (run 42678307325 Wiki, 42678307752 CI), CodeQL and Vendor audit green on `c25e608f`.
- Closed on 2026-11-09 in the 0.50.0 release PR (`release/0.50.0`).
