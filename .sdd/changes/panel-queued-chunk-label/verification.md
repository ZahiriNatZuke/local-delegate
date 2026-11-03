# Verification: Panel: queued chunked rows say which chunk waits and for how long

## Environment

- Revision: branch `fix/panel-queued-chunk-label` on top of `6eea8660`
- Relevant runtime and tool versions: Python 3.11 (main checkout `.venv`, `PYTHONPATH=src`), Playwright Chromium

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | test tests/test_inflight_state.py::test_panel_queued_chunk_says_it_waits | pass | mutant `queuedChunk = false` fails it («Trozo 2/3» under «En cola») |
| REQ-002 | test tests/test_inflight_state.py::test_panel_queued_row_title_says_why | pass | mutant without `queuedTitle` fails the first assert |
| REQ-003 | test tests/test_inflight_state.py::test_inflight_reports_how_long_it_waits | pass | mutant without `local_wait_since` fails with KeyError 'wait_s' |
| REQ-004 | test tests/test_inflight_state.py::test_panel_queued_row_shows_the_wait | pass | mutant without `waitText` in the chip fails «Espera trozo 1/4 · 1 min 53 s» |
| REQ-005 | test tests/test_dashboard_ui.py::test_inflight_rows_keep_time_and_chars_on_one_line | pass | mutants: `.ifchips{flex-wrap:wrap}` and `.ifchips{flex:1 1 auto}` trip the equal-height assert; no `.ifmeta{flex-basis:100%}` trips the narrow-card assert; screenshots light/dark es/en |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| pytest -n 2 (full suite) | yes | pass | 6243 passed, 29 skipped, 1 failed (Spanish-name detector on two new test words, renamed; rerun of that test and the touched files: 63 passed) |
| ruff check src tests | yes | pass | All checks passed |
| ruff format --check (touched files) | yes | pass | 4 files already formatted |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [ ] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- The mod band (`status.js`) is not changed: it already says `2/3 · en cola · <total>`.
- One line at 1366 px needs room: the tool shows without `local_` and the model badge gives way with an ellipsis (full names in titles).
- The existing assert `">#3<" in html` in tests/test_inflight_state.py was changed to look for the position in the title: the coordinator asked to drop the «#n» chip.
- Light theme: chip text contrast is about 2.1–2.3:1 (main's palette) and 1.4–1.8:1 with main's `.ifrow.queued{opacity:.72}`; not changed here.
