# Specification: El JS del panel se prueba ejecutandolo

## Summary

La suite ejecuta con node las funciones del panel donde un fallo cambia lo que el usuario ve, en
vez de comprobar que el fichero parsea y que cierto texto está presente.

## Requirements

- **REQ-001:** Los seis presets de `computeRange` se comprueban por su resultado.
- **REQ-002:** «Hoy» arranca en la medianoche **local**, no en la de UTC.
- **REQ-003:** Los presets de 7 y 30 días **incluyen hoy**.
- **REQ-004:** El rango personalizado cubre el **último día entero**.
- **REQ-005:** Un preset desconocido no inventa rango.
- **REQ-006:** `localDayKey` devuelve la clave del día **local**.
- **REQ-007:** `byDay` agrupa por día local, ordena cronológicamente e ignora fechas ilegibles.
- **REQ-008:** `agg` suma por clave, descarta los ceros y ordena de mayor a menor.
- **REQ-009:** `fmtHace` cambia de unidad en las fronteras exactas.
- **REQ-010:** Los tests fijan la zona horaria a una con offset, no usan la del que ejecuta.

## Acceptance scenarios

### Scenario: alguien rompe la agrupación por día

- **Given** `localDayKey` reescrito con `toISOString()`
- **When** corre la suite
- **Then** fallan los tests de día local y de `byDay`

### Scenario: la suite corre donde no hay node

- **Given** un entorno sin `node` en el PATH
- **When** corren estos tests
- **Then** se saltan, no fallan

## Edge cases and failure behavior

- **`ts` ilegible en `byDay`:** se ignora esa fila; el gráfico no puede quedarse en blanco por una
  línea corrupta.
- **Empates en `agg`:** conservan el orden de aparición. Es consecuencia de que `sort` es estable
  y `Map` conserva la inserción, no una decisión; se fija en el test para que se vea.

## Non-functional requirements

- **Determinismo por zona horaria:** con `TZ=UTC` varios de estos fallos pasarían inadvertidos, así
  que los tests fijan `America/Havana` (UTC-5/-4).
- **Portabilidad:** el entorno del subproceso se hereda entero; recortarlo mata a node en Windows.

## Non-goals

- Playwright en el CI.
- Probar Chart.js.
- Interacción real (clics, foco, paginación en el DOM).

## Traceability

| Requisito | Evidencia |
| --- | --- |
| REQ-001 a REQ-005 | los cinco tests de `computeRange` + 4 mutantes |
| REQ-006 | `test_la_clave_del_dia_es_la_local_*` + mutante `toISOString` |
| REQ-007 | dos tests de `byDay` + 2 mutantes (orden y `ts` ilegible) |
| REQ-008 | dos tests de `agg` + 2 mutantes (ceros y sentido del orden) |
| REQ-009 | `test_fmtHace_*` con las diez fronteras + mutante |
| REQ-010 | `TZ_PRUEBA` en el ayudante; sin ella, el mutante de UTC no caería |
