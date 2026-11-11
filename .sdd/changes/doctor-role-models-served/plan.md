# Implementation plan: doctor: cada rol tiene su modelo servido

## Approach

`failures.BackendView` gets an optional `models: tuple[str, ...] | None = None` (NamedTuple default,
so every positional construction keeps working). `_default_backend_models` fills it from the
daemon's `models`, and `probes.backend_probe` from `data[].id`. `Context` memoizes the view
(`_backend_view(ctx)`), used by `service.backend` and the new `service.role_models`, which walks
`backend_params.ROLES` with a map role to (config attribute, variable).

## Ordered tasks

- [x] T1 — Tests first with a simulated `/models` (REQ-001, REQ-002, REQ-003, REQ-004)
  - Files or modules: tests/test_checks_role_models.py
  - Verification: they fail without the check
  - Depends on: none
- [x] T2 — `BackendView.models`, memo, check, catalogs (REQ-001, REQ-002, REQ-003, REQ-004)
  - Files or modules: src/local_delegate/failures.py, checks.py, probes.py, resources/i18n/*/doctor.json
  - Verification: area tests
  - Depends on: T1
- [x] T3 — Counts, wiki row, CHANGELOG (REQ-005)
  - Files or modules: checks.py docstrings, doctor.py, docs/wiki/Integration-install.md, tests counting checks, CHANGELOG.md
  - Verification: full suite
  - Depends on: T2

## Test strategy

- Unit: fake `backend_models` and a fake daemon `query_backend`; a fake `httpx2.Client` for the direct probe.
- Integration: full suite with `-n 2`.
- End-to-end or manual: none (no backend call needed; the check reads the same `/models`).
- Security and secret scanning: no new input but backend ids, shown as text.

## Migration and compatibility

- New daemon field read only if present; old daemons give `unknown`.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
