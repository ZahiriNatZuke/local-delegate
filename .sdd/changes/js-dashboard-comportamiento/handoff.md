# Handoff: El JS del panel se prueba ejecutandolo

## Current state

- Estado SDD: `verifying` → cierra con el CI del PR.
- Último gate aprobado: `quality`.
- Base `e59c554`; rama `test/js-dashboard-comportamiento`.

## What changed

- `tests/test_dashboard_js.py` (nuevo): 12 tests que **ejecutan** con node `computeRange`,
  `localDayKey`, `byDay`, `agg` y `fmtHace`.
- `CHANGELOG.md`.
- **`metrics.py` no se toca.**

## Decisions

- **Se fija `TZ=America/Havana` en los tests.** Con la zona del runner (normalmente UTC), un
  `localDayKey` escrito con `toISOString()` pasaría en verde: local y UTC coincidirían. Para que
  el test distinga, los dos no pueden ser lo mismo.
- **Se eligen las funciones por riesgo, no por cobertura.** Las que deciden qué se pide y cómo se
  agrupa; no se persiguen las 40.
- **No se toca el panel para poder probarlo.** Si hubiera que reescribir el código para hacerlo
  testeable, el test dejaría de probar lo que se sirve.
- **Playwright sigue fuera**, y con razón escrita: haría falta para interacción real (clics,
  paginación en el DOM), no para esto.
- **El entorno del subproceso se hereda entero.** Recortarlo a `PATH`+`TZ` mata a node en Windows
  con SIGABRT; está anotado en el código.

## Next action

Merge. Queda del backlog el punto 5 (atar los PNG al `favicon.svg`), y después la 0.20.0.

## Memory

- Nota canónica: `projects/local-delegate/backlog.md` (borrar el punto al cerrar).
- Índices actualizados: al cierre de la sesión.
