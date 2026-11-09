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

- Not measured live yet: the release joint test runs the recipe.
- Just above 16 000 characters the extra is small (564 at 17 000); cuts there still end at a
  sentence with the notice. A runaway answer at 48 K can take up to 2 114 tokens (4x before).
- The map/reduce pieces keep 3w+64 (out of #610's way).
