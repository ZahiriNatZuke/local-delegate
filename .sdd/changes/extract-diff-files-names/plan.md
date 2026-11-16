# Implementation plan: local_extract: nombres de campo de ficheros y hunks de un diff por programa, sin null silencioso (#665)

## Approach

Extender lo del #676: `line_check` gana `asks_for_diff_hunks` y `diff_file_hunks` (el mismo
recorrido de `diff_file_ranges`, que pasa a usarlo, guardando dónde empieza cada hunk);
`is_location_field` deja de leer como recuento una palabra de `_COUNT_WORDS` que va justo delante
de un plural de ficheros. En `local_extract`, la detección de diff acepta el sufijo `.patch`/`.diff`,
los campos de hunks se responden por programa y dos avisos nuevos cubren lo que no.

## Ordered tasks

- [x] T1 — Predicados de nombre y rangos de hunks en `line_check` (REQ-001, REQ-002)
  - Files or modules: src/local_delegate/line_check.py
  - Verification: tests de nombres que sí y que no; recuentos intactos
  - Depends on: none
- [x] T2 — `local_extract`: sufijo de diff, valor de hunks por programa, avisos (REQ-001, REQ-003, REQ-004, REQ-005)
  - Files or modules: src/local_delegate/server.py, i18n es/en
  - Verification: tests de los informes (forma), preámbulo, `.patch` roto, aviso de null
  - Depends on: T1
- [x] T3 — CHANGELOG (Unreleased → Corregido), docs/wiki/Tools.md, docstring (REQ-001)
  - Files or modules: CHANGELOG.md, docs/wiki/Tools.md, src/local_delegate/server.py
  - Verification: review
  - Depends on: T2

## Test strategy

- Unit: `asks_for_diff_hunks`, `is_location_field`.
- Integration: `local_extract` con `_run_chat` doblado (modelo que no da nada).
- End-to-end or manual: la prueba en vivo la hace la sesión principal (los agentes no llegan al backend).
- Security and secret scanning: revisión del diff; entradas sintéticas, sin datos de usuario.

## Migration and compatibility

- Ningún test existente cambia; `diff_file_ranges` mantiene su firma.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
