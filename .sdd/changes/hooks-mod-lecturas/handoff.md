# Handoff: Hooks, mod y caché: lecturas sin MCP, prefiltro multilínea y fallo pasajero

## Current state

- SDD status: closed (cerrado en el PR de la release 0.50.0, rama `release/0.50.0`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `26a14cb9` (PR #603, 2026-11-09T13:42:22Z)

## What changed

- Los hooks de `Read` y de shell dejan pasar y anotan `mcp_absent` cuando el transcript dice que las tools `local_*` no están.
- El prefiltro del mod clasifica los comandos compuestos que empiezan por `cd`, `ls` o `echo`.
- Un fallo pasajero al leer `test-windows.json` o `backend-params.json` no se queda en caché.

## Decisions

- La señal sale de `deferred_tools_delta`, un formato interno de Claude Code; si cambia, el hook vuelve a avisar (nunca bloquea de más).
- Las huellas de los hooks ya estaban en `scripts/data/hook_hashes_after.json`: `bump_version.py --boundaries` no cambió nada en la release.

## Next action

- El panel no tiene etiqueta para `mcp_absent` (sale el valor crudo): pendiente menor.

## Memory

- Canonical note: Sin nota aparte: lo durable va en el CHANGELOG 0.50.0, el PR y `review.md`; la jornada del 2026-11-09 del vault la escribe la sesión principal.
- Indexes updated: ninguno desde este cambio (la sesión principal actualiza el índice de jornadas).
