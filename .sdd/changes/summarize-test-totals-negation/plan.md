# Implementation plan: local_summarize: aviso cuando el resumen niega una categoria que el runner de tests conto

## Approach

Módulo nuevo `src/local_delegate/runner_totals.py`, hermano de `grounding.py` (funciones puras,
lineales, sin patrones con backtracking): `totals(source)` lee la línea de totales del runner y
`denied(summary, source)` devuelve las categorías negadas con recuento > 0. En `server.py`,
`_test_totals_notice` envuelve el postproceso de `local_summarize` igual que `_grounding_notice`
(#630), así cubre llamada única, map-reduce y camino por secciones. El prompt no cambia: los
cambios de prompt con tests en verde ya fallaron en vivo, y el agente no puede probarlos (401).

## Ordered tasks

- [x] T1 — Lector de totales y detector de negaciones (REQ-001, REQ-003, REQ-004)
  - Files or modules: src/local_delegate/runner_totals.py, tests/test_summarize_runner_totals.py
  - Verification: tests unitarios de los cuatro runners, prosa, negaciones es/en, casos fieles y entrada hostil
  - Depends on: none
- [x] T2 — Cableado en `local_summarize` y aviso es/en (REQ-002)
  - Files or modules: src/local_delegate/server.py, src/local_delegate/resources/i18n/es/mcp.json, src/local_delegate/resources/i18n/en/mcp.json
  - Verification: tests con backend falso, con `path` y con `text`; control positivo con el `server.py` de `main`
  - Depends on: T1
- [x] T3 — Guardianes, CHANGELOG y wiki (REQ-005)
  - Files or modules: CHANGELOG.md, docs/wiki/Tools.md, tests/data/uncatalogued_exceptions.json, scripts/data/spanish_lexicon.json
  - Verification: pytest de la zona con pesado.sh; ruff
  - Depends on: T2

## Test strategy

- Unit: `runner_totals.totals` y `runner_totals.denied`.
- Integration: `local_summarize` con backend falso: aviso y resumen intacto, silencio con el fiel.
- End-to-end or manual: prueba en vivo en la sesión principal con el caso del issue.
- Control positivo: con el `server.py` de `main`, los dos tests de la tool fallan por `0 == 1`
  avisos (la razón del issue).
- Security and secret scanning: sin secretos ni datos personales; entrada sintética.

## Migration and compatibility

- Solo añade un aviso al final; ningún aviso existente cambia.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
