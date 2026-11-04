# Specification: El daemon sale (y se puede relevar) cuando su listener HTTP muere

## Summary

Un daemon cuyo socket de escucha muere termina solo, con código ≠ 0 y rastro en fichero; un `serve`
nuevo releva a un daemon registrado que no atiende su puerto, y `doctor` distingue ese estado.

## Requirements

- **REQ-001** — Si el socket de escucha del daemon se cierra con el proceso vivo, el daemon sale en
  pocos segundos con código ≠ 0, borra su `daemon.json` y suelta `daemon.lock`.
  - Request: "salir con codigo distinto de 0 si el listener muere"
  - Verify: test daemon de prueba real con el listener cerrado por un `accept` fallido

- **REQ-002** — El apagado del daemon tiene plazo: conexiones abiertas (streams MCP) no lo retienen
  indefinidamente.
  - Request: derived: la vía de la señal cierra el listener y espera sin plazo, mismo síntoma
  - Verify: test `uvicorn.Config` del daemon lleva `timeout_graceful_shutdown` finito

- **REQ-003** — Con el lock ocupado, si el daemon registrado tiene el pid vivo, arrancó hace más de
  60 s y su puerto **rechaza** conexiones de forma repetida (con el mismo `daemon.json` antes y
  después), `serve` lo termina, toma el lock y arranca; en cualquier otro caso (puerto que acepta,
  timeout, arranque reciente, fichero cambiado) no toca nada.
  - Request: "relevar un daemon registrado cuyo puerto rechaza conexiones"
  - Verify: test con un proceso zombi de prueba y casos negativos

- **REQ-004** — El daemon deja en `LOG_DIR/daemon-errors.log` (acotado por tamaño, con rotación) los
  errores del loop (`Accept failed on a socket`), las excepciones de uvicorn y el motivo de salida o
  de relevo.
  - Request: "log de errores acotado a fichero"
  - Verify: test el fichero recoge el motivo tras el fallo del listener

- **REQ-005** — `doctor` avisa (WARN, no MISSING) cuando nadie escucha en el puerto pero el daemon
  registrado para ese puerto sigue vivo, y dice cómo recuperarlo.
  - Request: "aviso en doctor"
  - Verify: test probe del daemon con el colaborador doblado

- **REQ-006** — En Windows, un cliente que resetea su conexión antes de ser aceptado (`WinError 64`
  y afines) no cierra el socket de escucha: el daemon sigue atendiendo, y esos resets no llenan el
  log de errores.
  - Request: derived: pista del coordinador (#577) — clientes del turno remoto concurrentes que se cortan
  - Verify: test daemon real con ráfagas de resets en la cola de `accept`

## Acceptance scenarios

### Scenario: el listener muere

- **Given** un daemon de prueba sirviendo en un puerto temporal
- **When** un `accept` falla y asyncio cierra el socket de escucha
- **Then** el proceso sale con código ≠ 0, sin `daemon.json` y con el motivo en `daemon-errors.log`

### Scenario: relevo de un zombi viejo

- **Given** un proceso vivo que retiene `daemon.lock` y un `daemon.json` que apunta a un puerto cerrado
- **When** se lanza `serve`
- **Then** el zombi se termina y el nuevo daemon atiende el puerto

## Edge cases and failure behavior

- Daemon sano pero lento: su puerto acepta TCP aunque no conteste HTTP → no se toca.
- Arranque en curso (lock tomado, aún sin bind): `started_at` reciente → no se toca.
- Dos `serve` a la vez: ambos pueden intentar terminar el zombi; solo uno toma el lock, el otro sigue
  la rama de siempre.
- Fallo al terminar (permisos): se registra y se cae en el mensaje `lock_busy` de siempre.

## Non-functional requirements

- Sin dependencias nuevas. Log acotado (≤ 2 × 256 KB). Sin secretos en el log.

## Non-goals

- Configurar la política de reinicio de la tarea programada.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
