# Handoff: local_summarize: tope de salida que crece con la entrada grande

## Current state

- SDD status: closed (cerrado en el PR de la release 0.50.0, rama `release/0.50.0`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `f0dea77a` (PR #615, 2026-11-09T17:04:44Z)

## What changed

- El tope de salida de la llamada única de `local_summarize` crece con la entrada por encima de 16 000 caracteres, sin pasar de `LOCAL_DELEGATE_CHUNK_MAX_TOKENS` ni del contexto libre; también en el resumen por secciones.

## Decisions

- Las piezas del map/reduce siguen con 3·w+64.
- Sin medición en vivo en esta rama.

## Next action

- Unificar el techo con `_widened_cap` del #610 si conviene (ya está en `main`).

## Memory

- Canonical note: Sin nota aparte: lo durable va en el CHANGELOG 0.50.0, el PR y `review.md`; la jornada del 2026-11-09 del vault la escribe la sesión principal.
- Indexes updated: ninguno desde este cambio (la sesión principal actualiza el índice de jornadas).
