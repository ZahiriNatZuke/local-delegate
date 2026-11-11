# Research: Panel: desglose y filtro por proyecto con nombres locales; fuera el conmutador del propio repo

## Current behavior

- `src/local_delegate/web/metrics.py` (`_include_self`, `_without_self`, `_usage_rows`) leaves out
  rows with `caller_project_kind: self` from `/api/stats`, `/api/events` and `/api/hooks` unless
  `include_self=1`, and returns `excluded_self`, `self_in_range`, `unknown_project`. The cost of
  `/api/stats` follows that switch; `?session=` skips it.
- The panel (HTML/JS inside `metrics.py`) has a `#self` button, `#selfCount`, `#selfInfo` and the
  dialog section `#dlgSelf`; `buildQuery(range, tests, lang, includeSelf)`; `ld-self` in
  localStorage; i18n keys `panel.self.*`, `panel.info.self`, `panel.dialog.self.title`.
- `server.local_status` adds «del propio repo (local-delegate): N de esos eventos»
  (`mcp.status.log.own_repo`).
- The hash is computed in ONE place, `resources/hooks/hook_common.project_fields(name, directory)`,
  reached from `project_identity` (server at call time, hooks, the mod's line through
  `hook_entry.record_read`) and from `transcripts.py` (the `recompute-cost` backfill, with an
  explicit `directory`). `LOG_DIR` comes from the process environment (`log_dir()`), D12 of
  `usage-log-project-and-own-repo-exclusion`.
- `hook_common` already has a cross-process file lock (`_open_shared` + `_exclusive`) and an atomic
  create pattern for the salt (`tempfile.mkstemp` + `os.replace`/`os.link`).
- Hook events carry `project` (hash) and `project_kind`.
- `scripts/measure_adoption.py` and `scripts/measure_plugin_adoption.py` use
  `attribution.project_kind` / `caller_project_kind` and `self-projects.json`.
- `scripts/dev/capture_dashboard.py` mocks `/api/*` with `excluded_self` for the README capture.
- The per-event accounting has a JS mirror (`_accounting` in server.py and its copy in the panel);
  the series of the charts are computed in JS from `/api/events`.

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| `web/metrics.py` API | own-repo filter and counters | replaced by `?project=` and `by_project` | lines of `_usage_rows`, `stats`, `hooks` |
| `web/metrics.py` panel | switch, dialog, `buildQuery` | selector, card, escaping | `#self`, `renderSelfInfo` |
| `hook_common.py` | hash and kind | also writes `project-names.json`; backfill | `project_fields` |
| `server.py` | own-repo status line | line removed | `local_status` |
| i18n `panel.json`, `mcp.json` | switch texts | removed; project texts added | key grep |
| `scripts/measure_*.py` | own-repo exclusion | unchanged | tests `test_measure_*_own_repo.py` |
| docs | own-repo section | «Por proyecto» section | wiki `Savings-and-metrics.md` |
| tests | own-repo tests | rewritten for the filter | `test_metrics_own_repo.py`, `test_dashboard_own_repo.py`, `test_status_own_repo.py`, `test_project_privacy.py` |

## Existing conventions

- Code and JSON fields in English; output texts in Spanish and English from the i18n catalog.
- Untrusted text in the panel goes through `escHooks` or `textContent`; CSP forbids inline handlers.
- Mixed line endings per file (metrics.py, server.py, README.md are CRLF).

## Dependencies and integrations

- No new dependency. Only stdlib in `hook_common` (`threading` added).
- The mod's status line calls `/api/stats?session=` without new parameters.

## Risks and unknowns

- Confirmed: the JS charts take their rows from `/api/events`, so filtering that endpoint filters
  the charts; the JS accounting mirror needs no change (no new figure is computed in JS).
- Assumption validated by test: `msvcrt.locking` and `flock` conflict between two descriptors of
  the same process, so threads also need the in-process lock (added anyway).
- On Windows `os.replace` fails while a reader holds the map open: retried a few times; if it still
  fails the name waits for the next call.
