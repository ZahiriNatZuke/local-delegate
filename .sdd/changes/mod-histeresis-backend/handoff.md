# Handoff: El mod usa la histéresis del panel para el estado del backend

## Current state

- SDD status: closed (cerrado en el PR de la release 0.50.0, rama `release/0.50.0`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `c05cc744` (PR #613, 2026-11-09T16:56:21Z)

## What changed

- La banda del mod usa la histéresis del panel con el mismo código (`mod/common.js`): solo el segundo fallo seguido es CAÍDO, y tras un fallo el siguiente sondeo llega al segundo.

## Decisions

- Se tocaron 5 tests existentes del mod (dar el segundo sondeo): esperaban CAÍDO tras un solo fallo, que es lo que el issue declara malo.
- Si el daemon no contesta `/api/backend`, la banda dice «sin datos» ese latido; el panel repinta lo anterior.

## Next action

- Ninguna para este cambio.

## Memory

- Canonical note: Sin nota aparte: lo durable va en el CHANGELOG 0.50.0, el PR y `review.md`; la jornada del 2026-11-09 del vault la escribe la sesión principal.
- Indexes updated: ninguno desde este cambio (la sesión principal actualiza el índice de jornadas).
