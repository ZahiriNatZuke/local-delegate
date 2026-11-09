# Implementation plan: El verificador de citas acepta un alias o una constante del nombre citado (#616)

## Approach

En `check`, antes de comprobar las citas, se buscan en el fichero los alias de cada nombre
code-like de las citas: líneas `ALIAS = nombre`, `ALIAS = 'nombre'`, `ALIAS: tipo = "nombre"`
(con `const`/`let`/`var` delante o no, y el valor como toda la expresión) y `nombre as ALIAS`. Cada
alias code-like se añade a los nombres de esa cita al buscar en su ventana. Las palabras sueltas de
la respuesta no reciben alias (solo confirman). Patrones anclados al inicio de palabra y con
cuantificadores acotados, por fichero una pasada por nombre (con memo).

## Ordered tasks

- [x] T1 — Tests nuevos (fallan sin el arreglo los de REQ-001) (REQ-001, REQ-002, REQ-004)
  - Files or modules: `tests/test_explain_code_verified_lines.py`
  - Verification: pytest del fichero
  - Depends on: none
- [x] T2 — `aliases()` y su uso en `check` (REQ-001, REQ-002, REQ-003, REQ-004)
  - Files or modules: `src/local_delegate/line_check.py`
  - Verification: pytest de los ficheros de `line_check`; controles positivos con mutantes
  - Depends on: T1
- [x] T3 — CHANGELOG y suite completa (REQ-001, REQ-002, REQ-003, REQ-004)
  - Files or modules: `CHANGELOG.md`
  - Verification: suite completa por `pesado.sh`, `ruff`
  - Depends on: T2

## Test strategy

- Unit: `line_check.check` con ficheros pequeños (JS y Python).
- Integration: los tests existentes que llaman a la tool por `server` siguen igual.
- End-to-end or manual: no.
- Security and secret scanning: regex sin retroceso catastrófico (test de tiempo); hook de secretos al commit.

## Migration and compatibility

- Sin migración: solo puede quitar avisos en líneas que usan un alias real del nombre.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
