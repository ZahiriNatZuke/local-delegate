# Verification: Panel: desglose y filtro por proyecto con nombres locales; fuera el conmutador del propio repo

## Environment

- Revision: branch feat/dashboard-project-filter on top of main 2a6b097b
- Relevant runtime and tool versions: Python 3.11 (repo .venv), pytest 9.2 with xdist -n 2, node (nvm4w), Playwright Chromium, Windows 11

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | test_every_project_is_shown_by_default_and_include_self_is_ignored, test_the_page_has_no_own_repo_switch_and_has_the_project_filter, browser test_the_project_selector_filters_the_whole_panel | pass | tests/test_metrics_project_filter.py, tests/test_dashboard_project_filter.py |
| REQ-002 | include_self with 1, 0 and absent gives the same set; old counters absent in the three endpoints | pass | tests/test_metrics_project_filter.py |
| REQ-003 | project hash, none and invalid values in stats, events and hooks | pass | tests/test_metrics_project_filter.py |
| REQ-004 | cost with and without the filter; session keeps its figures | pass | tests/test_metrics_project_filter.py |
| REQ-005 | by_project order, names, sums, independence from the filter, tests switch | pass | tests/test_metrics_project_filter.py |
| REQ-006 | project_fields writes the map in the process LOG_DIR or the given one; no salt no name; mod request LOG_DIR untouched | pass | tests/test_project_names.py, tests/test_project_privacy.py |
| REQ-007 | six threads and four processes writing; reported writes never lost; busy lock retried | pass | tests/test_project_names.py |
| REQ-008 | missing, corrupt, too big, bad entries, cap, invalid names | pass | tests/test_project_names.py, tests/test_metrics_project_filter.py |
| REQ-009 | markers searched in every surface; only by_project name and the map carry them | pass | tests/test_project_privacy.py |
| REQ-010 | fallback labels es and en from the catalog | pass | tests/test_dashboard_project_filter.py |
| REQ-011 | hostile name escaped in the card, raw text in the option, no img in the browser, no script run | pass | tests/test_dashboard_project_filter.py |
| REQ-012 | three requests carry project; activity rows filtered; chosen project stays an option; reload resets | pass | tests/test_dashboard_project_filter.py |
| REQ-013 | local_status has no own-repo line in es and en; figures unchanged | pass | tests/test_status_own_repo.py |
| REQ-014 | the measurement scripts tests pass untouched | pass | tests/test_measure_adoption_own_repo.py, tests/test_measure_plugin_adoption_own_repo.py |
| REQ-015 | backfill names only log hashes, no salt does nothing, keeps existing names, budget and cap, never raises; dashboard calls it | pass | tests/test_project_names.py, tests/test_metrics_project_filter.py |
| REQ-016 | review of CHANGELOG, README and wiki; grep of the old anchors and names; result judge checked the new anchors | pass | grep of el-propio-repo and include_self only finds the measurement section, cli.json and the historical CHANGELOG |
| REQ-017 | metrics app on a free port with test data (scratchpad LOG_DIR and HOME), Playwright, light and dark, whole panel, bar, card and filtered | pass | session scratchpad, outside the repo (8 PNG) |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| pytest zone (project names, filter, status, privacy, dashboard node) | yes | pass | scratchpad t1.log, t2.log |
| pytest browser test of the selector (Playwright, alone) | yes | pass | scratchpad t3.log |
| pytest full suite -n 2 | yes | pass after fixes | first run 4 failed (recompute map file, typography, lexicon); fixed; zone rerun 160 passed; final full run 7696 passed, 30 skipped, 1 failed (an uncatalogued Unicode category name, given its exception); test_no_uncatalogued_text rerun 44 passed |
| ruff check and ruff format on changed files | yes | pass | clean after format |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Implementation went ahead of the written spec and plan in the same session (brief.md L2).
- Positive controls (mutant applied, target test run, file restored): writer without the file
  lock, lenient read under the lock, hashes settled before a complete pass, card without
  escHooks, own repo left out by default again, status line reading the map, project_fields
  not writing the map: all 7 caught.
- Not verified live against the installed daemon (the coordinator does it): the lazy backfill
  over the real projects root and the map written by the real hooks.
