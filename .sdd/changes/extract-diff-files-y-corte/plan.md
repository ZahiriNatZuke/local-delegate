# Implementation plan: local_extract: ficheros de un diff por programa y respuesta de líneas cortada (#665, #666)

## Approach

Reutilizar lo que ya existe para `local_explain_code` (#582): `sections.is_unified_diff`,
`line_check.diff_file_ranges` y `_DIFF_LINES_CLAUSE`. Un predicado nuevo por nombre de campo
(`line_check.asks_for_diff_files`) decide qué campos se responden por programa. Para el corte, la
llamada a `_chat_map_reduce` de `local_extract` pasa a una función local que acepta el presupuesto
por trozo; la llamada única cortada con campos de líneas la reutiliza con la mitad de la entrada.

## Ordered tasks

- [x] T1 — Predicado `asks_for_diff_files` en `line_check` (REQ-001, REQ-003)
  - Files or modules: src/local_delegate/line_check.py
  - Verification: tests parametrizados de nombres que sí y que no
  - Depends on: none
- [x] T2 — Valor por programa, `diff_files` y cláusula de diff en el prompt (REQ-001, REQ-002, REQ-003, REQ-004)
  - Files or modules: src/local_delegate/server.py, i18n es/en
  - Verification: tests de diff troceado, llamada única, no JSON, otro campo, no diff, text=
  - Depends on: T1
- [x] T3 — Rehacer troceada la llamada única cortada; error con max_tokens; líneas de lo cortado (REQ-005, REQ-006, REQ-007, REQ-008)
  - Files or modules: src/local_delegate/server.py, i18n es/en
  - Verification: tests de corte recuperado, todo cortado, trozo cortado, entrada mínima, sin campos de líneas
  - Depends on: none
- [x] T4 — CHANGELOG (Unreleased), docs/wiki/Tools.md, docstring de la tool (REQ-001, REQ-005)
  - Files or modules: CHANGELOG.md, docs/wiki/Tools.md, src/local_delegate/server.py
  - Verification: review
  - Depends on: T2, T3

- [x] T5 — Hallazgos de la revisión: una fila de uso por llamada rehecha, `model_error`, JSON que no es objeto, plural, sin rehacer si el programa da el campo (REQ-002, REQ-007, REQ-009)
  - Files or modules: src/local_delegate/server.py (`_fold_retried_row`), src/local_delegate/line_check.py, i18n es/en
  - Verification: tests de fila única, error del backend junto a los ficheros, no objeto, no rehacer
  - Depends on: T2, T3

## Test strategy

- Unit: `asks_for_diff_files`.
- Integration: `local_extract` con `_run_chat` doblado (modelo que nombra solo el primer fichero;
  modelo que se corta pasado un número de elementos tras inventar una línea).
- End-to-end or manual: no posible contra el backend real desde un agente (401).
- Security and secret scanning: revisión del diff; sin datos de usuario en los tests.

## Migration and compatibility

- Ningún test existente cambia: la llamada rehecha se pliega en la fila de su rehecho (T5), así
  que `test_a_truncated_answer_that_is_not_json_writes_a_failed_row` sigue viendo una sola fila.
- `tests/test_detect_spanish_names.py`: cinco nombres de campo en español a propósito (dos
  literales de los issues) van a `scripts/data/name_exceptions.json` con su motivo.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
