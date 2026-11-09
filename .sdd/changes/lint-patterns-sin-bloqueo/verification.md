# Verification: lint_patterns: buscar ficheros en tiempo lineal sobre logs con tramos largos sin espacios

## Environment

- Revision: branch `fix/lint-patterns-sin-bloqueo` on `origin/main` `ac33807a`
- Relevant runtime and tool versions: Python 3.11.15 (`.venv` of the main checkout, `PYTHONPATH=src`), Windows 11

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_a_long_run_without_spaces_is_searched_in_linear_time` (7 shapes, 20 000 chars, cap 1 s) | pass | branch: all 7 pass; 20 000 dots in 0.009 s |
| REQ-002 | `test_file_spans_are_the_spans_of_the_regex` (30 000 random texts, >5 000 with files) and `test_known_shapes_give_what_the_regex_gives`; existing lint tests unchanged (136 passed) | pass | equal spans; no counterexample by either judge |
| REQ-003 | `test_the_finding_counter_check_is_the_regex` (fuzz incl. `\n`, `\r`, `ſ`, `ı`) and `test_a_long_json_key_is_checked_in_linear_time` (240 000-char key) | pass | `is_finding_counter` equal to `_FINDING_COUNT.fullmatch` |
| REQ-004 | `test_a_chunked_unittest_log_returns_in_seconds` (real `local_lint_summary`, `_run_chat` faked, chunked, inventory names `tests/test_x.py`) | pass | 0.08 s on the branch |
| REQ-005 | Positive control: the time-capped tests run against `origin/main` sources (`git archive`) | pass | main: `files_by_frequency took 36.94 s on dots`, `clean_verdict took 26.62 s`, `local_lint_summary took 154.73 s` — 3 failed, each by its time assert |

Before/after (`files_by_frequency` on a log with a line of n dots; this PC):

| n | origin/main | branch |
| --- | --- | --- |
| 2 000 | 0.35 s | 0.001 s |
| 4 000 | 1.43 s | 0.002 s |
| 8 000 | 6.05 s | 0.003 s |
| 20 000 | 36.9 s | 0.009 s |
| 200 000 | (not run: ~1 h) | 0.074 s |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest -q -n 2 tests` (via `pesado.sh`) | yes | pass after lexicon update | first run: 1 failed (`test_detect_spanish_names`: new English words unclassified), 6714 passed, 29 skipped; words added to `scripts/data/spanish_lexicon.json` `en` and the test rerun green |
| `ruff check` / `ruff format --check` on changed files | yes | pass | All checks passed |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- `scripts/score_lint_fidelity.py` (offline measurement script) still calls `FILE.findall`: out of scope.
- Memory of the scanner: 8 bytes per character of a path run that holds an extension (`array('q')`);
  the input size of `local_lint_summary` itself is not capped (pre-existing).

## Final result

- Merged in `main` as `7d972fc8` (PR #607, 2026-11-09T12:25:36Z).
- `main` CI on `7d972fc8`: all check runs green.
- `main` at `c25e608f`: CI (run 42678307325 Wiki, 42678307752 CI), CodeQL and Vendor audit green on `c25e608f`.
- Closed on 2026-11-09 in the 0.50.0 release PR (`release/0.50.0`).
