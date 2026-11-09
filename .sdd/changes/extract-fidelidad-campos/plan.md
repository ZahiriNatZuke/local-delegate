# Implementation plan: local_extract: aviso de valores sin respaldo y campos de línea por título

## Approach

Todo es post-proceso en `local_extract` (`src/local_delegate/server.py`), en el bloque de líneas
de #568, más una regla en `line_check.check_values`. La comprobación de palabras sin respaldo
(antigua T1) se retiró tras la revisión independiente. No cambia ninguna petición al backend, así que las fixtures de
cuerpos de petición y los corpus congelados siguen iguales. Los avisos se AÑADEN al final de
`warning`, como #497/#586, para no cambiar el texto de un aviso anterior (contrato #455).

## Ordered tasks

- [x] T2 — `line_check.outline_copy` + recorte del esquema copiado en `local_extract` (REQ-003, REQ-004; regla de duda tras la revisión independiente del #609)
  - Files or modules: src/local_delegate/line_check.py, src/local_delegate/server.py, i18n
  - Verification: tests/test_extract_field_fidelity.py
  - Depends on: none
- [x] T3 — palabras genéricas de título en `check_values` (REQ-005)
  - Files or modules: src/local_delegate/line_check.py
  - Verification: tests/test_extract_field_fidelity.py
  - Depends on: none
- [x] T4 — docstring, wiki, CHANGELOG (REQ-006)
  - Files or modules: server.py, docs/wiki/Tools.md, CHANGELOG.md
  - Verification: review del diff
  - Depends on: T2, T3

## Test strategy

- Unit: recorte sin duda, aviso con duda (5 nombres de la revisión), campos de varios sitios y regla de títulos.
- Integration: `local_extract` por su camino real (`path`, backend falso en `_run_chat`) con un
  Markdown en `tmp_path`.
- End-to-end or manual: el MCP instalado (0.49.0) reprodujo #594 en vivo antes del cambio.
- Security and secret scanning: sin dependencias nuevas; regex lineales.
- Regresión: suite de extract (`-k extract`) y suite completa sin modificar tests existentes.

## Migration and compatibility

- Claves nuevas opcionales en `_local_delegate`; nada desaparece. Una extracción con todos los
  valores respaldados devuelve exactamente lo mismo que antes.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
