# Specification: El dashboard lee la telemetria de los hooks

## Summary

`GET /api/hooks` expone lo que los hooks consultivos han **sugerido** en un rango, y el panel lo
enseña en una tarjeta. El requisito que gobierna el resto: **el panel no puede afirmar más de lo
que el dato sostiene**, y aquí el dato son sugerencias, no delegaciones.

## Requirements

- **REQ-001:** `/api/hooks` devuelve `total`, `suggested`, `rate` y el desglose por evento,
  categoría y día, filtrado por el mismo rango que el resto de endpoints.
- **REQ-002:** Un evento sin el campo `suggested` cuenta como **no sugirió**.
- **REQ-003:** Sin `LD_HOOK_TELEMETRY_LOG`, la respuesta trae `enabled: false` con el motivo, en
  vez de un cero indistinguible.
- **REQ-004:** Con el rango vacío, la tasa es `0.0` y el endpoint no revienta.
- **REQ-005:** Una línea corrupta no tumba el endpoint.
- **REQ-006:** La respuesta no incluye comandos, prompts ni ningún campo de contenido del evento.
- **REQ-007:** La tarjeta se esconde cuando no hay telemetría o no hay eventos.
- **REQ-008:** La tarjeta declara que cuenta sugerencias y no delegaciones.
- **REQ-009:** La categoría, que sale de un fichero ajeno al daemon, se escapa antes de pintarse.
- **REQ-010:** Los días salen en orden cronológico; las categorías y eventos, por volumen.

## Acceptance scenarios

### Scenario: el panel enseña lo que los hooks sugirieron

- **Given** telemetría activada con eventos en el rango
- **When** se carga el panel
- **Then** la tarjeta muestra sugeridas sobre total, el porcentaje, y el desglose por categoría

### Scenario: nadie activó la telemetría

- **Given** `LD_HOOK_TELEMETRY_LOG` sin definir
- **When** se carga el panel
- **Then** la tarjeta no aparece — y no aparece un cero que se leería como «no sugieren nada»

### Scenario: una categoría con HTML dentro

- **Given** un evento cuya categoría contiene `<img src=x onerror=…>`
- **When** se pinta la tarjeta
- **Then** el HTML sale escapado

## Edge cases and failure behavior

- **Evento sin categoría:** se agrupa en `sin categoría`. Descartarlo haría que la suma por
  categorías no cuadrara con el total.
- **Evento sin `ts` legible:** no entra en el desglose por día, pero **sí** en los totales.
- **Fichero ausente con la variable puesta:** `enabled: true`, `exists: false`, cero eventos.

## Non-functional requirements

- **Privacidad:** el contrato del hook —«nunca prompts, comandos ni paths»— no puede romperse desde
  el dashboard. El endpoint devuelve agregados, nunca el evento crudo.
- **Rendimiento:** se reutiliza el lector cacheado por `(mtime, size)`; un log de miles de líneas
  se lee una vez.
- **Coherencia:** mismo rango que el resto de la página.

## Non-goals

- Correlacionar sugerencias con delegaciones. **No hay identificador común**, y hacerlo por
  cercanía temporal sería fabricar un dato.
- Cambiar lo que los hooks registran.
- Activar el brazo B del piloto A/B.

## Traceability

| Requisito | Trabajo | Evidencia |
| --- | --- | --- |
| REQ-001 | `_aggregate_hooks`, `/api/hooks` | tests de agregado y de rango + e2e real |
| REQ-002 | `_aggregate_hooks` | `test_un_evento_viejo_sin_el_campo_suggested_*` + mutante |
| REQ-003 | `/api/hooks` | `test_sin_la_variable_*` + mutante |
| REQ-004 | `_aggregate_hooks` | `test_sin_eventos_la_tasa_es_cero_*` |
| REQ-005 | `_read_file_cached` | `test_una_linea_corrupta_*` |
| REQ-006 | `/api/hooks` | `test_el_endpoint_no_devuelve_ni_comandos_ni_prompts` |
| REQ-007 | `renderHooks` | test con node, 4 casos + mutante |
| REQ-008 | `renderHooks` | test con node + mutante que borra el aviso |
| REQ-009 | `escHooks` | test con node + mutante que quita la llamada |
| REQ-010 | `_aggregate_hooks` | `test_agrupa_por_*`, `test_las_listas_salen_ordenadas_*` + mutante |
