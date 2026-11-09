# Implementation plan: local_extract: el prompt pide null y prohíbe rellenar con otra clave o fila

## Approach

Una constante `_EXTRACT_NO_FILL_CLAUSE` que se suma al `system` de `local_extract` antes de que
lo usen la llamada única, el map y el reduce; frontera `0.50.0` en `PROMPT_BOUNDARIES`; el cambio
declarado en los dos tests que congelan prompts (autorizado por el orquestador); y
`_decode_empty_lists` junto a los marcadores de #591.

## Ordered tasks

- [x] T1 — cláusula en el `system` de `local_extract` (REQ-001)
  - Files or modules: src/local_delegate/server.py
  - Verification: tests/test_extract_no_fill.py
  - Depends on: none
- [x] T2 — frontera y cambio declarado en los tests congelados (REQ-002, REQ-003)
  - Files or modules: scripts/build_corpus.py, tests/test_corpus.py, tests/test_request_body_compat.py, tests/data/uncatalogued_exceptions.json
  - Verification: tests/test_corpus.py, tests/test_request_body_compat.py
  - Depends on: T1
- [x] T3 — `"[]"` a `[]` con `decoded_keys` (REQ-004)
  - Files or modules: src/local_delegate/server.py
  - Verification: tests/test_extract_no_fill.py
  - Depends on: none

## Test strategy

- Unit: la regla en la llamada única, con numeración, en el map y en el reduce; `"[]"` y los textos que no se tocan.
- Integration: corpus congelados y cuerpos de petición con el cambio declarado.
- End-to-end or manual: prueba conjunta contra el backend real, fuera de esta rama.
- Security and secret scanning: sin dependencias; la clave del backend no se toca.

## Migration and compatibility

- Clave nueva opcional `decoded_keys`; el resto del contrato igual.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
