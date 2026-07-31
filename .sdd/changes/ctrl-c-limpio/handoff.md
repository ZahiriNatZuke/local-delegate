# Handoff: Ctrl+C sobre el MCP stdio sale limpio en vez de con traceback

## Current state

- Estado SDD: `verifying` → cierra con el CI del PR.
- Último gate aprobado: `quality`.
- Base `87b5d93`; rama `fix/ctrl-c-limpio`.

## What changed

- `src/local_delegate/server.py`: `mcp.run()` pasa a estar dentro de un `try/except
  KeyboardInterrupt` que retorna en silencio.
- `tests/test_ctrl_c.py` (nuevo): tres tests, el tercero comprueba los **dos** caminos juntos.
- `CHANGELOG.md`.

## Decisions

- **La captura se acota a `mcp.run()`**, no a toda `main()`. Envolver la inicialización
  escondería un fallo de arranque detrás de un cierre aparentemente normal.
- **Se sale en silencio y por 0.** Quien pulsó `Ctrl+C` ya sabe que paró el proceso, y un gestor
  de servicios no debe apuntarse una caída.
- **El test mira los dos caminos en la misma corrida.** El defecto no fue no saber qué hacer —
  `daemon.serve` ya lo hacía— sino arreglar uno y dar el problema por cerrado. Un test que mirara
  solo el camino nuevo repetiría exactamente ese error.
- **El `rc 3` ante `CTRL_BREAK` no se arregla**: es otro camino y no está diagnosticado. Al
  backlog con sus números medidos, sin causa inventada.

## Next action

Merge, y que el usuario confirme el `Ctrl+C` en su terminal. Después: la 0.20.0.

## Memory

- Nota canónica: `projects/local-delegate/backlog.md` — se borra el punto del `Ctrl+C` y se añade
  el del `rc 3`.
- Índices actualizados: al cierre de la sesión.
