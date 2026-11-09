# Specification: El mod usa la histéresis del panel para el estado del backend

## Summary

Un sondeo lento suelto ya no pinta CAIDO en la banda del mod; el mod y el panel deciden el estado
del backend con la misma funcion, y estando caido el mod vuelve en cuanto el backend responde.

## Requirements

<!-- One block per requirement. Request quotes the literal fragment of the request, or says
"derived: <reason>". Verify starts with one method: test, cmd, manual or review. -->

- **REQ-001** — Tras un sondeo bueno, un solo `available: false` deja la banda como estaba (lista,
  delegando u ocupada); el segundo fallo seguido la pasa a caido. Sin ningun sondeo bueno, el primer
  fallo no pinta caido (equivale a «comprobando» del panel: sin estado de backend).
  - Request: "El mod marca CAÍDO por un solo sondeo lento"
  - Verify: test mod/status.test.ts
- **REQ-002** — Con un fallo pendiente de confirmar (`failures === 1`), el temporizador del mod va a
  `STATUS_HOT_MS`; con la caida ya confirmada, o al volver un sondeo bueno sin nada en curso, vuelve
  a `STATUS_COLD_MS` (revision del orquestador: 1 s durante toda una caida eran ~20 sondeos por
  minuto y sesion contra el backend).
  - Request: "y se queda así hasta 30 s"
  - Verify: test mod/status.test.ts
- **REQ-003** — `initialView` y `visibleState` tienen una sola fuente (`mod/common.js`) y el panel
  sirve ese mismo texto; ante la misma secuencia de sondeos, el estado que pinta el mod y el del panel
  coinciden.
  - Request: "Reutiliza la lógica de histéresis del panel ... haz un test que lo ate"
  - Verify: test tests/test_backend_view_shared.py
- **REQ-004** — `/api/backend` sin respuesta (cuerpo nulo) no cuenta como sondeo: ni suma un fallo
  ni pone la cuenta a cero, como en el panel. Ese latido la banda sigue diciendo «sin datos», como
  hasta ahora (diferencia deliberada con el panel, que repinta lo anterior: la banda no tiene otra
  forma de decir que el daemon no contesto esa ruta).
  - Request: derived: misma regla que `pollBackend` del panel
  - Verify: test mod/status.test.ts

## Acceptance scenarios

### Scenario: sondeo lento suelto

- **Given** la banda en LISTO
- **When** un sondeo de `/api/backend` llega con `available: false`
- **Then** sigue en LISTO y el siguiente latido es a 1 s; si el siguiente tambien falla, CAIDO

### Scenario: vuelta

- **Given** la banda en CAIDO
- **When** un sondeo vuelve con `available: true`
- **Then** LISTO en el mismo latido y ritmo de 30 s sin nada en curso

## Edge cases and failure behavior

- Daemon caido (`/api/stats` sin respuesta): `SIN SERVICIO` como hoy.

## Non-functional requirements

- Sin coste extra fuera del estado caido o pendiente.

## Non-goals

- Cambiar el daemon o el panel en su comportamiento.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
