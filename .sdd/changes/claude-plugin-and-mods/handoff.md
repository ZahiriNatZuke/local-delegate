# Handoff: local-delegate como plugin de Claude Code y Claude Desktop, con mods

## Current state

- SDD status: closed (2026-11-23)
- Last completed gate: memory
- Current revision: `0253b630`

## What changed

- F1: el plugin `local-delegate` en el paquete, con hooks por subcomando, entrega por plugin con fallback a `settings.json`, migración desde la 0.39, estado de instalación, `doctor`, `update`, `uninstall` y el puente `desktop-bridge` para el chat de Claude Desktop (0.40.0).
- F2 y F3: el mod con tools fijas, comandos sin turno del modelo, delegaciones del mod separables en el panel y barra de estado (0.40.0).
- F4: clasificador único de lectura, mod de lectura con elección, guarda que no deja escribir sobre un resumen y hooks de lectura que se apartan cuando el mod actúa (0.41.0 y 0.41.1).
- REQ-024: medición de adopción hecha el 2026-11-23, no concluyente.

## Decisions

- El MCP se queda fuera del plugin; `install` en esta PC va con los cuatro flags y `--desktop`.
- El mod de lectura sale encendido por defecto desde la 0.41.0, tras pasar los controles en vivo.
- REQ-024 se cierra con el dato honesto: no concluyente no cuenta como éxito.
- `pinned_tools` no se toca en este SDD: cambiar su valor por defecto es una decisión de producto (tarjeta del Project 3).

## Next action

- Ninguna en este SDD. Lo que sigue (decidir `pinned_tools` y medir sin el sesgo del propio repo) vive en el Project 3.

## Memory

- Canonical note: memoria `mods-y-sdd-claude-plugin-and-mods.md`; vault `projects/local-delegate/auditoria-sesgo-medicion-2026-11-08.md`
- Indexes updated: tarjetas del Project 3 «Medir la adopción del plugin» y «Cerrar el SDD de plugin y mods» (Hecho)
