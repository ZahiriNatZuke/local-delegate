# Handoff

## Current state

- SDD status: closed (cerrado en el PR de la release 0.50.0, rama `release/0.50.0`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `bc8dc80e` (PR #604, 2026-11-09T14:46:54Z)

## What changed

- `recompute-cost` reintenta un fichero que no pudo leer y, si sigue sin poder, se para sin reescribirlo; uno dañado se guarda como `.damaged-<fecha>`.
- Dos corridas a la vez se serializan con un cerrojo.

## Decisions

- Las copias `.damaged-*` no se podan; en POSIX el `.lock` queda en disco, como los demás cerrojos.

## Next action

- Ninguna para este cambio.

## Memory

- Canonical note: Sin nota aparte: lo durable va en el CHANGELOG 0.50.0, el PR y `review.md`; la jornada del 2026-11-09 del vault la escribe la sesión principal.
- Indexes updated: ninguno desde este cambio (la sesión principal actualiza el índice de jornadas).
