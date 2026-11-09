# Brief: El mod usa la histéresis del panel para el estado del backend

## Problem

#612: `mod/status.js` (`statusSnapshot`) pone `down` con el primer `available: false` de
`/api/backend`, y `statusApply` vuelve al ritmo lento (30 s) estando caido. Un sondeo lento suelto
pinta CAIDO durante hasta 30 s. El panel ya tiene la regla buena (`visibleState`, REQ-028, en
`web/metrics.py`): un fallo tras un sondeo bueno conserva lo que se pintaba y solo el segundo fallo
seguido es caido.

## Desired outcome

El mod y el panel aplican la MISMA funcion a la misma secuencia de sondeos, y el mod sondea a ritmo
rapido mientras tiene un fallo pendiente de confirmar o esta caido.

## In scope

- Mover `initialView` y `visibleState` a `mod/common.js` entre marcas; `web/metrics.py` incrusta ese
  bloque en `HTML` al importar (una sola fuente).
- `mod/status.js`: pasar cada respuesta de `/api/backend` por `visibleState` y pintar desde el
  estado visible; ritmo rapido con fallos pendientes.
- Tests: uno que ate mod y panel (mismo texto y mismas salidas), los del mod nuevos.

## Out of scope

- Histeresis en el daemon (`/api/backend`), el timeout de `probe_backend`.
- `mod/read.js` (lo toca otro PR hoy).

## Constraints and risks

- Varios tests del mod (`status.test.ts`) esperan CAIDO tras UN solo sondeo fallido: son
  justamente el comportamiento que el issue declara malo. No pueden quedar intactos si el mod ha de
  decir lo mismo que el panel; se cambian lo minimo (dos sondeos fallidos donde esperan caido) y se
  explica en la entrega.
- `metrics.py` es CRLF; `common.js` LF. Los tests del panel extraen `visibleState` de
  `metrics.HTML`: la incrustacion va a nivel de modulo para que sigan viendolo.
- Los nombres de `common.js` pasan al nivel superior de `register.js`: `build_mod` falla si chocan.

## Open questions

- Ninguna.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-09 Original request, verbatim:

  > Issue #612: el mod marca CAÍDO por un solo sondeo lento y se queda así hasta 30 s; reutilizar la histéresis del panel (visibleState), test que ate mod y panel, sondeo rápido mientras está caído.
