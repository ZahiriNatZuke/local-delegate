# Handoff

## Current state

- SDD status: closed (cerrado en el PR de la release 0.50.0, rama `release/0.50.0`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `22e15bc7` (PR #605, 2026-11-09T16:19:33Z)

## What changed

- La telemetría de hooks, el log de fallos y las notas de bloqueo se escriben con cerrojo de fichero (`msvcrt.locking` / `flock`) y una sola escritura.
- Una línea partida anterior ya no se pega a la nueva; el panel y la medición se saltan los trozos que no son eventos.

## Decisions

- En POSIX los tests concurrentes no discriminan (O_APPEND ya era atómico): son de no regresión.

## Next action

- `mod/read.js` `readRecordLost` sigue reescribiendo `hook-failures.jsonl`: seguimiento aparte.

## Memory

- Canonical note: Sin nota aparte: lo durable va en el CHANGELOG 0.50.0, el PR y `review.md`; la jornada del 2026-11-09 del vault la escribe la sesión principal.
- Indexes updated: ninguno desde este cambio (la sesión principal actualiza el índice de jornadas).
