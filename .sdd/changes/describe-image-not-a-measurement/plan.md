# Implementation plan: local_describe_image no mide: aviso por programa ante alineación, píxeles o saltos de línea (#663)

## Approach

Guarda por programa, no por prompt: el aviso no depende de que el modelo obedezca y no puede
degradar las descripciones normales. `_MEASUREMENT_TERMS` (literales alternados es/en) se busca en
la pregunta y en la respuesta; el `postprocess` de `_chat` añade el aviso al final, antes del
recibo de ahorro, y solo con respuesta buena. La descripción de la tool, la skill y la wiki lo
dicen para que el agente no use la tool para medir.

## Ordered tasks

- [x] T1 — Docstring de `local_describe_image` (REQ-001)
  - Files or modules: src/local_delegate/server.py
  - Verification: test de la descripción
  - Depends on: none
- [x] T2 — Guarda `_MEASUREMENT_TERMS` + postproceso y clave i18n (REQ-002, REQ-003)
  - Files or modules: src/local_delegate/server.py, resources/i18n/{es,en}/mcp.json
  - Verification: tests/test_vision_measurement_notice.py
  - Depends on: none
- [x] T3 — Documentación (REQ-004)
  - Files or modules: docs/wiki/Tools.md, resources/skills/local-delegation/SKILL.md y SKILL.en.md, CHANGELOG.md
  - Verification: revisión y paridad i18n
  - Depends on: T2

## Test strategy

- Unit: casos del issue y del comentario, positivos y negativos parametrizados.
- Integration: `backend_mock` con imagen PNG mínima; el prompt del sistema enviado se compara con el de antes.
- End-to-end or manual: sin prueba en vivo obligatoria (el prompt no cambia); prueba opcional descrita en el PR.
- Security and secret scanning: sin secretos; expresión sin retroceso catastrófico.

## Migration and compatibility

- Las respuestas que hablan de medidas ganan una línea de aviso al final; el resto, idénticas.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
