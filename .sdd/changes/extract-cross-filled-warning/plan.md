# Implementation plan: local_extract: aviso de valor cruzado entre claves (cross_filled_keys, #650)

## Approach

Módulo propio `cross_fill.py` (no engorda `server.py` y deja libre la zona del detector de tablas,
que toca otro agente). Parte del prototipo del 2026-11-10 (lectura de filas HTML/Markdown/JSON/
`etiqueta: valor`, normalización de valores) y añade: CSV/TSV, tablas GFM sin tuberías externas,
la regla de ocurrencia única (fila única y celda única en el texto), el filtro de triviales y los
plurales `ies`/`es`. Elegida con datos (`research.md`): la ocurrencia única quita el falso positivo
de ayer y detecta más cruces del `holdout` que el estricto.

## Ordered tasks

- [x] T1 — Detector `cross_fill.cross_filled` con sus reglas (REQ-001, REQ-003, REQ-004, REQ-005, REQ-006)
  - Files or modules: src/local_delegate/cross_fill.py
  - Verification: tests de reglas en tests/test_extract_cross_fill.py
  - Depends on: none
- [x] T2 — Conjunto de medición y puerta como test parametrizado (REQ-007, REQ-008, REQ-009, REQ-010)
  - Files or modules: tests/data/cross_fill/, tests/test_extract_cross_fill.py
  - Verification: test_gate_totals y los parametrizados; mutantes de control positivo
  - Depends on: T1
- [x] T3 — Llamada en `local_extract`, aviso i18n y descripción (REQ-002, REQ-011, REQ-012, REQ-013)
  - Files or modules: src/local_delegate/server.py, resources/i18n/{en,es}/mcp.json
  - Verification: tests de `local_extract` con backend falso; diff sin cambios de prompt
  - Depends on: T1
- [x] T4 — CHANGELOG y wiki (REQ-012)
  - Files or modules: CHANGELOG.md, docs/wiki/Tools.md
  - Verification: review
  - Depends on: T3
- [x] T5 — Hallazgos de la revisión: coincidencia estricta, encaje real de la otra clave, campos de ubicación fuera, robustez y recorte (REQ-014, REQ-015, REQ-016)
  - Files or modules: src/local_delegate/cross_fill.py, src/local_delegate/server.py, tests/
  - Verification: casos n26-n32 y tests de robustez; mutantes M1-M11 de nuevo
  - Depends on: T1, T2, T3

## Test strategy

- Unit: reglas del detector y normalización.
- Integration: `local_extract` con `_run_chat` doblado.
- End-to-end or manual: no hace falta prueba en vivo (no cambia el prompt ni el enrutado); la puede
  hacer la sesión principal si quiere.
- Security and secret scanning: datos inventados; sin secretos.

## Migration and compatibility

- Campo nuevo y opcional en `_local_delegate`; el texto previo de `warning` se conserva.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
