# Handoff: Regroup cortado en explain_code y diff grande en commit_msg (#598, #596)

## Current state

- SDD status: closed (cerrado en el PR de la release 0.50.0, rama `release/0.50.0`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `0bfef1d2` (PR #610, 2026-11-09T16:44:39Z)

## What changed

- `local_explain_code` troceado con pregunta repite una vez, con el doble de margen, una combinación de notas cortada que no se puede partir; si sigue cortada, el aviso lo dice (#598).
- `local_commit_msg` tiene un presupuesto de 95 s: deja de leer partes cuando no cabe y redacta con lo leído y el inventario completo, con aviso (#596).

## Decisions

- Se descartó reducir el diff a 4 trozos: rompía el corpus versionado y `test_map_reduce`.
- El riesgo que queda es la estimación: un trozo mucho más lento que los anteriores aún puede pasar de 120 s.

## Next action

- Ninguna para este cambio.

## Memory

- Canonical note: Sin nota aparte: lo durable va en el CHANGELOG 0.50.0, el PR y `review.md`; la jornada del 2026-11-09 del vault la escribe la sesión principal.
- Indexes updated: ninguno desde este cambio (la sesión principal actualiza el índice de jornadas).
