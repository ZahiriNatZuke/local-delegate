# Brief: La espera ciega sin turno cuenta en la explicación del plazo agotado (#575 + #579)

## Problem

La revisión de integración entre #575 (el `read_timeout` explica su causa) y #579 (sin turno
remoto, de una en una) encontró un hueco: la nota «esperó N s el turno o una plaza» de #575 se
calcula con `Trace.phase_ms("turn", "slot")` (`server._read_timeout_explained`), pero la espera de
la plaza ciega de #579 (`_OperationTurn._go_blind`) solo suma a `wait_ms` y `token.turn_wait_ms`, y
`_remote_wait` no registra fase cuando el daemon no se puede usar. En el caso del #577 (~55 s entre
el turno caído y la cola ciega) el error no dice que hubo espera, aunque `turn_wait_ms` del evento
sí la cuenta.

## Desired outcome

Esa espera queda en la traza como fase de espera y la explicación del plazo agotado la cuenta.

## In scope

- Registrar en la traza el intento de turno remoto inutilizable y la espera de la plaza ciega.
- Que `_read_timeout_explained` sume esas fases.
- Un test de la combinación por el `_post_chat` real.

## Out of scope

- Cambiar textos, plazos, contadores (`turn_wait_ms`, `wait_ms`) o el objeto `concurrency.phases`
  del log de uso.

## Constraints and risks

- `_remote_wait` deja a propósito el evento sin fase `turn` cuando el daemon no se puede usar
  (REQ-026 del lote 4): las fases nuevas son internas y no salen en `log_fields`.
- Otro agente edita `tests/test_remote_turn_unreachable.py`: el test nuevo va en un fichero aparte.

## Open questions

- Ninguna.

## Log

- L1 2026-11-04 Original request, verbatim:

  > Objetivo: que esa espera (turno remoto caído y plaza ciega) quede registrada en la traza como
  > fase de espera, para que la explicación del plazo agotado la cuente; y un test de la
  > combinación que pase por el `_post_chat` real (o por `_read_timeout_explained` con la traza
  > real) y discrimine. Sin cambiar los textos ni contadores existentes salvo lo necesario; los
  > tests existentes intactos.
