# Plan: El hook de prompt se dispara con eventos del sistema

Modo ligero. **Desviación declarada:** el usuario pidió corregirlo en esta misma pasada; el plan se
escribió después de implementar y se revisó contra la spec antes de las compuertas de calidad.

## Tarea 1 — filtro de eventos del sistema
- Files or modules: `src/local_delegate/resources/hooks/suggest_delegate_prompt.py`
  (`_EVENTO_SISTEMA`, `es_evento_sistema`, retorno temprano en `main`).
- Requirements covered: REQ-001, REQ-002, REQ-003.
- Verification: tests con payloads reales + dos mutantes + suite + prueba instalada.
- Rollback or recovery: revertir el commit; `local-delegate update` repone el hook anterior.

## Tarea 2 — tests
- Files or modules: `tests/test_hook_recipes.py`.
- Requirements covered: REQ-001…003, con control positivo.

## Plan review
- Sin cambio en telemetría histórica, panel ni otros hooks. El hook de prompt no escribe
  `version`, así que el cambio no abre un tramo nuevo en la medición de adopción del bloqueo de
  lectura (que mide por la versión de `suggest_delegate_read.py`).
