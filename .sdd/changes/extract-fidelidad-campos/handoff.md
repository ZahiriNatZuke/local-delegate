# Handoff: local_extract: aviso de valores sin respaldo y campos de línea por título

## Current state

- SDD status: closed (cerrado en el PR de la release 0.50.0, rama `release/0.50.0`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `c6a8cc4d` (PR #609, 2026-11-09T16:30:01Z)

## What changed

- El esquema de encabezados copiado en el campo de un título se recorta solo sin duda (nombre en singular y un único encabezado); los dos casos van en `_local_delegate.outline_copies` con aviso.
- «Título: línea 1» sobre un encabezado ya no se marca como línea dudosa.

## Decisions

- El aviso `ungrounded_keys` se retiró tras la revisión independiente por falsos positivos; el #586 quedó para el cambio de prompt, que luego se revirtió (#624).

## Next action

- El #586 sigue abierto: control determinista en el servidor que avise cuando el valor de una clave está en la fila de otra (último comentario del issue).

## Memory

- Canonical note: Sin nota aparte: lo durable va en el CHANGELOG 0.50.0, el PR y `review.md`; la jornada del 2026-11-09 del vault la escribe la sesión principal.
- Indexes updated: ninguno desde este cambio (la sesión principal actualiza el índice de jornadas).
