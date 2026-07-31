# Handoff: El dashboard lee la telemetria de los hooks

## Current state

- Estado SDD: `verifying` → cierra con el CI del PR.
- Último gate aprobado: `quality`.
- Base `5f1a0fc`; rama `feat/telemetria-hooks-dashboard`.

## What changed

- `config.py`: `HOOK_TELEMETRY_LOG`.
- `web/metrics.py`: `_aggregate_hooks`, `GET /api/hooks`, la tarjeta, `renderHooks` y `escHooks`.
- `tests/test_hooks_telemetry_api.py`: 14 tests, **dos de ellos ejecutando JS con node**.
- `docs/wiki/Savings-and-metrics.md`, `CHANGELOG.md`.

## Decisions

- **Cuenta sugerencias, no delegaciones, y lo dice.** No hay identificador que una una sugerencia
  con la delegación posterior; correlacionarlas por cercanía temporal sería fabricar un dato. Hay
  un test que falla si ese aviso desaparece de la tarjeta.
- **La tarjeta se esconde en vez de enseñar ceros.** Un panel a cero leído de un fichero
  inexistente afirma algo falso («los hooks no sugieren nada»). Por lo mismo, el endpoint
  distingue `enabled: false` de «activada y sin eventos».
- **Se escapa la categoría** porque es el único texto de la página que no controla el daemon. El
  resto del panel interpola directo y está bien: sus datos son propios.
- **El desglose por categoría es el dato, no el porcentaje global.** Medido: 17 % global, pero
  `bash` 1396 eventos con cero sugerencias y `lint` 283 de 283.

## Next action

Merge. Después quedan del backlog: el punto 5 (atar los PNG al SVG), el punto 6 (tests de
comportamiento del JS, del que este change ya deja dos ejemplos con node) y el `Ctrl+C` del
`serve`. Luego la 0.20.0.

## Memory

- Nota canónica: `projects/local-delegate/backlog.md` (borrar el punto al cerrar).
- Índices actualizados: al cierre de la sesión.
