# Implementation plan: Panel: desglose y filtro por proyecto con nombres locales; fuera el conmutador del propio repo

## Approach

Replace the own-repo filter in `web/metrics.py` with one project filter applied after the tests
filter, in the three endpoints, and a `by_project` aggregate computed in Python only (no JS
mirror needed: no new figure is computed in the browser). The names map lives beside the salt in
`hook_common`, reusing its cross-process lock and atomic-replace patterns, and is written from
`project_fields`, the single place the hash is born. The backfill for 0.51.0 rows runs lazily in
`/api/stats`. The panel gets a `<select>` in the existing controls bar and a table card built like
«Quién delegó».

## Ordered tasks

- [x] T1 — Names map in `hook_common`: read, record, atomic write, caps, backfill (REQ-006, REQ-007, REQ-008, REQ-015)
  - Files or modules: src/local_delegate/resources/hooks/hook_common.py
  - Verification: tests/test_project_names.py
  - Depends on: none
- [x] T2 — API: `?project=`, `by_project`, cost, removal of `include_self` and counters, lazy backfill (REQ-002, REQ-003, REQ-004, REQ-005, REQ-015)
  - Files or modules: src/local_delegate/web/metrics.py
  - Verification: tests/test_metrics_project_filter.py
  - Depends on: T1
- [x] T3 — Panel: selector, «Por proyecto» card, escaping, removal of the switch; i18n es/en (REQ-001, REQ-010, REQ-011, REQ-012)
  - Files or modules: src/local_delegate/web/metrics.py, src/local_delegate/resources/i18n/es/panel.json, src/local_delegate/resources/i18n/en/panel.json
  - Verification: tests/test_dashboard_project_filter.py (node and Playwright)
  - Depends on: T2
- [x] T4 — `local_status` without the own-repo line (REQ-013)
  - Files or modules: src/local_delegate/server.py, src/local_delegate/resources/i18n/*/mcp.json
  - Verification: tests/test_status_own_repo.py
  - Depends on: none
- [x] T5 — Privacy end to end and scripts untouched (REQ-009, REQ-014)
  - Files or modules: tests/test_project_privacy.py
  - Verification: tests/test_project_privacy.py, tests/test_measure_adoption_own_repo.py, tests/test_measure_plugin_adoption_own_repo.py
  - Depends on: T1, T2
- [x] T6 — Docs and capture mock (REQ-016)
  - Files or modules: CHANGELOG.md, README.md, docs/wiki/Savings-and-metrics.md, docs/wiki/Configuration.md, docs/wiki/Claude-plugin.md, docs/recipes/claude-code-hooks.md, scripts/dev/capture_dashboard.py
  - Verification: review; tests/test_capture.py
  - Depends on: T3
- [x] T7 — Screenshots light and dark against a test port; full suite; reviews; PR (REQ-017)
  - Files or modules: none in the repo
  - Verification: screenshots in the scratchpad; full pytest with -n 2
  - Depends on: T1, T2, T3, T4, T5, T6

## Test strategy

- Unit: map read/record/caps/backfill; API filter and breakdown with TestClient.
- Integration: threads and subprocesses writing the same map; privacy end to end through the real
  write paths (server, hook subprocess, mod line, recompute).
- End-to-end or manual: Playwright against `PanelServer` on a free port; screenshots.
- Security and secret scanning: hostile names in node and browser tests; security reviewer;
  `personal-security-check` before commit.

## Migration and compatibility

- No data migration: old rows fall in «Sin proyecto» or get their name from the lazy backfill.
- API consumers of `include_self`/`excluded_self` (only the panel and the capture mock) updated.
- Rollback: revert the PR; the map file is ignored by older versions.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
