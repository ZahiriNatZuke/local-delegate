# Verification: local_summarize: el aviso de foco reconoce el término en títulos con contenido

## Environment

- Revision: branch `fix/summarize-focus-aviso` on `origin/main` `ac33807a`
- Relevant runtime and tool versions: Python 3.11.15 (`.venv` of the main checkout, `PYTHONPATH=src`), Windows 11

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_the_issue_heading_with_bullets_is_a_mention`, `test_three_words_under_the_heading_are_enough` | pass | on origin/main the first fails: `assert ['local_extract'] == []` |
| REQ-002 | `test_case_backticks_and_level_do_not_matter_in_the_heading`, `test_accents_and_plural_in_the_heading` | pass | on origin/main both fail by `assert [...] == []` |
| REQ-003 | `test_a_heading_with_only_a_placeholder_or_nothing_still_warns`, `test_a_level_one_title_never_counts`, `test_a_title_over_subsections_does_not_hide_a_miss`, `test_a_copied_heading_still_warns_through_the_tool`; existing `tests/test_summarize_focus_coverage.py` unchanged | pass | guards: they pass on main and on the branch |
| REQ-004 | `test_the_issue_through_the_tool` (prose and structured, backend mocked) | pass | on origin/main fails: `assert FOCUS_WARNING not in output` |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest -q -n 2 tests` (via `pesado.sh`) | yes | pass after lexicon update | first run: 1 failed (`test_detect_spanish_names`: new English words unclassified), 6706 passed, 29 skipped; words added to `scripts/data/spanish_lexicon.json` `en` and the test rerun green |
| `ruff check` / `ruff format --check` on changed files | yes | pass | All checks passed |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Filler of 3+ words without parentheses under a copied heading counts as a mention (accepted, spec Non-goals).
