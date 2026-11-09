# Handoff: local_extract: el prompt pide null y prohíbe rellenar con otra clave o fila

## Current state

- SDD status: closed como revertido (cerrado en el PR de la release 0.50.0, rama `release/0.50.0`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `1a4d720d` (PR #621, 2026-11-09T17:44:22Z); revertido por `c25e608f` (PR #624, 2026-11-09T18:54:51Z)

## What changed

- El prompt de `local_extract` pedía `null` y prohibía rellenar con otra clave o fila (PR #621).
- Revertido entero por el PR #624 (código, tests y documentación); el SDD se conserva como registro.

## Decisions

- Motivo de la reversión: la prueba en vivo con el backend real (ventana `w-20261109T184426Z`, repetida dos veces) dio dos regresiones (`custom_domain_limits` y `body_language` a `null`, `mentions_windows` a `false`) y no arregló el caso de la tabla HTML del #586.
- El cruce de claves lo produce el modelo, no el post-proceso: cambiar el prompt solo cambia el reparto.

## Next action

- #586 reabierto: control determinista en el servidor que avise cuando el valor de una clave aparece en la fila de otra clave pedida, medido antes contra falsos positivos.

## Memory

- Canonical note: Sin nota aparte: lo durable va en el CHANGELOG 0.50.0, el PR y `review.md`; la jornada del 2026-11-09 del vault la escribe la sesión principal.
- Indexes updated: ninguno desde este cambio (la sesión principal actualiza el índice de jornadas).
