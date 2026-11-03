# Implementation plan: Panel: queued chunked rows say which chunk waits and for how long

## Approach

`_inflight_local_wait` stamps `local_wait_since` when a wait begins (kept while it continues, dropped when it ends); `inflight_snapshot` turns it into `wait_s`. `renderInflight` picks a waiting label for queued map/reduce chips, puts the reason in the row title and the chunk count in the chip title, and adds «waiting t» in the meta. The row wraps its chips in a flexible box and keeps the meta in a non-wrapping right-aligned span.

## Ordered tasks

<!-- One checklist item per task: "- [ ] T<n> — title (REQ-NNN, ...)". Close it with [x]; drop it with
"- [-] T<n> ... dropped: <reason>". Every requirement needs at least one task that is not dropped. -->

- [x] T1 — API: `wait_s` from `local_wait_since` (REQ-003)
  - Files or modules: src/local_delegate/server.py
  - Verification: tests/test_inflight_state.py
  - Depends on: none
- [x] T2 — Panel: waiting chip, row title, waited time, one-line meta (REQ-001, REQ-002, REQ-004, REQ-005)
  - Files or modules: src/local_delegate/web/metrics.py, src/local_delegate/resources/i18n/{en,es}/panel.json
  - Verification: tests/test_inflight_state.py, tests/test_dashboard_ui.py, screenshots light/dark
  - Depends on: T1
- [x] T3 — CHANGELOG `[Unreleased]` (#547) (REQ-001)
  - Files or modules: CHANGELOG.md
  - Verification: review
  - Depends on: T2

## Test strategy

- Unit: API field and panel rendering via the node DOM harness (tests/test_inflight_state.py).
- Integration: Playwright test with fake /api/inflight (tests/test_dashboard_ui.py).
- End-to-end or manual: screenshots light and dark at 1366 px.
- Security and secret scanning: escaping test of the new titles; no secrets touched.

## Migration and compatibility

- Additive optional API field; no data migration.

## Plan review

- [ ] Every requirement maps to at least one task and verification step.
- [ ] Risky or destructive operations have safeguards and rollback.
- [ ] Dependencies and configuration changes are explicit.
- [ ] The plan does not include unrelated work.
