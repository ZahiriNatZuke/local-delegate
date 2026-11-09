# Handoff: La medicion de adopcion del plugin acota las exclusiones a su periodo

## Current state

- SDD status: closed (cerrado en el PR de la release 0.50.0, rama `release/0.50.0`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `12b8a577` (PR #611, 2026-11-09T13:50:06Z)

## What changed

- `scripts/measure_plugin_adoption.py` cuenta `excluded_rows` solo con las filas de `[since, until)` de cada periodo.
- El periodo «después» deja de contar las filas de pasados sus 14 días; el porcentaje no cambia.

## Decisions

- Las filas sin `ts` se siguen saltando en las dos pasadas (sin test propio).

## Next action

- Ninguna para este cambio.

## Memory

- Canonical note: Sin nota aparte: lo durable va en el CHANGELOG 0.50.0, el PR y `review.md`; la jornada del 2026-11-09 del vault la escribe la sesión principal.
- Indexes updated: ninguno desde este cambio (la sesión principal actualiza el índice de jornadas).
