# Implementation plan: local_explain_code sobre un diff troceado: índice completo y líneas del patch (#582)

## Approach

La numeración por trozo ya es absoluta (comprobado), así que no se toca `_numbered_code_pieces`.
Lo puro (rangos de ficheros de un diff) va a `line_check.py`, al lado de `markdown_outline` (#573).
En `local_explain_code`, solo cuando `numbered` y `sections.is_unified_diff(content)`: cláusula de
líneas del patch + `_DIFF_NOTE` en el system; en el troceado, pista por trozo, índice en el reduce,
formato de map por fichero, e índice al final por programa. El aviso de troceado se añade en el
postprocess de la rama troceada (corre solo en éxito).

## Ordered tasks

- [x] T1 — `diff_file_ranges` en `line_check.py` (REQ-001)
  - Files or modules: src/local_delegate/line_check.py
  - Verification: tests unitarios
  - Depends on: none
- [x] T2 — Prompts de diff en `local_explain_code`: system, map, pista por trozo, reduce (REQ-002, REQ-003)
  - Files or modules: src/local_delegate/server.py
  - Verification: backend falso que captura prompts
  - Depends on: T1
- [x] T3 — Índice al final y aviso de troceado (REQ-004, REQ-005); textos es/en
  - Files or modules: src/local_delegate/server.py, resources/i18n/{es,en}/mcp.json
  - Verification: backend falso
  - Depends on: T2
- [x] T4 — Sin regresiones y CHANGELOG (REQ-006)
  - Files or modules: CHANGELOG.md
  - Verification: tests de explain y suite completa
  - Depends on: T3

## Test strategy

- Unit: `tests/test_explain_code_diff_index.py`, diff sintético de 32 ficheros, `_run_chat` doblado.
- Integration: suite completa con `pesado.sh` si la RAM lo permite.
- End-to-end or manual: prueba en vivo opcional con `test-window`.
- Security and secret scanning: GitGuardian en el PR.

## Migration and compatibility

- La salida troceada de `local_explain_code` gana una línea de aviso; sin diff, prompts iguales.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
