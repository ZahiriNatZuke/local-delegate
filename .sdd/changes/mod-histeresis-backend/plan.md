# Implementation plan: El mod usa la histéresis del panel para el estado del backend

## Approach

`common.js` exporta `initialView`/`visibleState` (texto identico al del panel) entre marcas
`backend-view:start/end`; `metrics.py` sustituye `__BACKEND_VIEW__` en `HTML` al importar con ese
bloque sin `export`. `status.js` guarda `view.backendView`, lo actualiza en cada `statusRead` con un
cuerpo que tenga `available` booleano y pasa a `statusSnapshot` el cuerpo visible (`ref` si
conectado, `last` si caido, `null` si comprobando). El ritmo rapido incluye `failures > 0`.

## Ordered tasks

<!-- One checklist item per task: "- [x] T<n> — title (REQ-NNN, ...)". Close it with [x]; drop it with
"- [-] T<n> ... dropped: <reason>". Every requirement needs at least one task that is not dropped. -->

- [x] T1 — Fuente unica de la histeresis (REQ-003)
  - Files or modules: mod/common.js, web/metrics.py, tests/test_backend_view_shared.py
  - Verification: pytest del test nuevo y tests/test_dashboard_states.py
  - Depends on: none
- [x] T2 — Banda del mod con estado visible y ritmo (REQ-001, REQ-002, REQ-004)
  - Files or modules: mod/status.js, mod/status.test.ts
  - Verification: build_mod + claude plugin test
  - Depends on: T1
- [x] T3 — CHANGELOG y suite (REQ-001, REQ-002, REQ-003, REQ-004)
  - Files or modules: CHANGELOG.md
  - Verification: suite completa
  - Depends on: T2

## Test strategy

- Unit: mod (plugin test) y panel (node) con controles positivos.
- Integration: el test que ata ejecuta las dos copias servidas (common.js y metrics.HTML).

## Rollback

- Revertir el PR.
