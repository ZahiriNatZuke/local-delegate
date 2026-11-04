# Specification: La espera ciega sin turno cuenta en la explicación del plazo agotado (#575 + #579)

## Summary

Cuando una operación sin turno (daemon de turno inalcanzable) espera la plaza ciega o el intento de
turno, y luego su envío agota el plazo de lectura, el texto del error dice cuánto esperó antes del
envío, igual que con una espera de turno normal.

## Requirements

- **REQ-001** — El tiempo de la espera de la plaza ciega (`_go_blind`) y el del intento de turno
  remoto que acaba en daemon inutilizable (`_remote_wait`) quedan en la traza de la operación como
  fases de espera, y `_read_timeout_explained` las suma a `turn` y `slot`: con 1 s o más en total,
  el texto lleva la nota `read_timeout_queued`.
  - Request: "que esa espera (turno remoto caído y plaza ciega) quede registrada en la traza como fase de espera, para que la explicación del plazo agotado la cuente"
  - Verify: test tests/test_read_timeout_counts_blind_wait.py
- **REQ-002** — Nada más cambia: los textos, `turn_wait_ms`, `wait_ms` y el objeto
  `concurrency.phases` del evento (sin fase `turn` con el daemon inutilizable) siguen como hoy, y los
  tests existentes pasan sin tocarlos.
  - Request: "Sin cambiar los textos ni contadores existentes salvo lo necesario; los tests existentes intactos."
  - Verify: test tests/test_read_timeout_counts_blind_wait.py y suite completa

## Acceptance scenarios

### Scenario: dos operaciones sin turno, la segunda espera la plaza ciega y agota el plazo

- **Given** un daemon de turno que rechaza la conexión y un backend cuyo primer envío tarda 1,6 s
  (contados desde que la otra operación hace cola) y el segundo agota el plazo de lectura
- **When** se lanzan dos `local_classify` a la vez
- **Then** la que esperó la plaza ciega devuelve el error de plazo agotado con la nota «esperó N s»
  y su evento no lleva fase `turn`

## Edge cases and failure behavior

- Espera de menos de 1 s: sin nota (umbral de #575).
- Si registrar la fase falla, la llamada sigue igual (observar nunca rompe la llamada).

## Non-functional requirements

- Sin textos nuevos ni campos nuevos en el log de uso.

## Non-goals

- Cambiar el umbral, el texto de la nota o el objeto `phases` del log.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
