# Implementation plan: Resumen de salidas de tests: totales y versión por programa, y aviso de negación sin falsos positivos

## Approach

Todo por programa en `runner_totals.py` (funciones puras): la lectura de la línea de totales ya
existe; se amplía para guardar las partes `N outcome` de cada línea y la línea que cuenta cada
categoría, se añade la categoría `errors`, la coma y las cifras en letras como cortes de la
negación, y una lectura acotada de la cabecera de pytest. `server.py` solo cablea: el
`_test_totals_notice` de `local_summarize` y el postproceso de `local_lint_summary` añaden la
línea fija y el aviso de versión.

## Ordered tasks

<!-- One checklist item per task: "- [ ] T<n> — title (REQ-NNN, ...)". Close it with [x]; drop it with
"- [-] T<n> ... dropped: <reason>". Every requirement needs at least one task that is not dropped. -->

- [x] T1 — Tests rojos con datos que distinguen (REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006)
  - Files or modules: tests/test_test_summary_figures.py
  - Verification: fallan contra `main` por la razón que dicen
  - Depends on: none
- [x] T2 — runner_totals: coma, cifras en letras, categoría errors, línea por categoría, partes y cabecera (REQ-001, REQ-002, REQ-003, REQ-004, REQ-007)
  - Files or modules: src/local_delegate/runner_totals.py
  - Verification: tests de T1 y tests/test_summarize_runner_totals.py
  - Depends on: T1
- [x] T3 — Cableado en local_summarize y local_lint_summary, catálogos es/en (REQ-005, REQ-006)
  - Files or modules: src/local_delegate/server.py, src/local_delegate/resources/i18n/es/mcp.json, src/local_delegate/resources/i18n/en/mcp.json
  - Verification: tests de T1 con backend falso
  - Depends on: T2
- [ ] T4 — Suite completa, CHANGELOG «Sin publicar», wiki, prueba en vivo en test-window (REQ-007)
  - Files or modules: CHANGELOG.md, docs/wiki/Tools.md
  - Verification: pesado.sh pytest -n 2; tabla antes/después
  - Depends on: T3

## Test strategy

- Unit: funciones puras de `runner_totals` con los casos del review y del día.
- Integration: `local_summarize` y `local_lint_summary` con backend falso (`backend_mock`).
- End-to-end or manual: prueba en vivo en proceso desde el worktree, dentro de `test-window`.
- Security and secret scanning: sin entradas nuevas de red ni secretos; regex acotadas.

## Migration and compatibility

- Solo se añade texto al final de la respuesta; el resumen no cambia. Sin migración.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
