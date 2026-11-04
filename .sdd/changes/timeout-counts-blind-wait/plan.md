# Implementation plan: La espera ciega sin turno cuenta en la explicación del plazo agotado (#575 + #579)

## Approach

`Trace` ya guarda fases por nombre y `phase_ms` suma cualquier nombre; `log_fields` solo publica las
de `PHASES` (`turn`, `slot`, `backend`). Se añaden dos fases internas que no salen en el log:
`turn_unusable` (el intento de turno remoto que termina en `remote_turn.Unusable`, que hoy
`_remote_wait` no registra a propósito) y `blind` (la espera de la plaza ciega de `_go_blind`). Una
constante `QUEUE_PHASES` en `concurrency` agrupa las cuatro esperas antes del envío y
`_read_timeout_explained` la usa en lugar de `("turn", "slot")`. Así el log de uso, los textos y los
contadores no cambian.

## Ordered tasks

- [x] T1 — Fases internas `turn_unusable` y `blind`, `QUEUE_PHASES`, y su uso en `_read_timeout_explained` (REQ-001, REQ-002)
  - Files or modules: src/local_delegate/concurrency.py, src/local_delegate/server.py
  - Verification: tests/test_read_timeout_counts_blind_wait.py
  - Depends on: none
- [x] T2 — Test de la combinación por el `_post_chat` real (dos `local_classify`, daemon que rechaza, backend con `backend_mock`) y tests unitarios de las fases; control positivo con mutantes (REQ-001, REQ-002)
  - Files or modules: tests/test_read_timeout_counts_blind_wait.py (nuevo)
  - Verification: pytest del fichero; suite completa con `pesado.sh -n 2`; ruff
  - Depends on: T1

## Test strategy

- Unit: `_remote_wait` con `Unusable` deja `turn_unusable` y no `turn`; `log_fields` no publica las fases internas.
- Integration: dos `local_classify` a la vez contra un daemon que rechaza; `_post_chat` real con `backend_mock`; la segunda espera >1 s la plaza ciega y agota el plazo; su texto lleva la nota y su evento no tiene fase `turn`.
- End-to-end or manual: no (sin backend real).
- Security and secret scanning: `personal-security-check` antes del commit.

## Migration and compatibility

- Ninguna: sin campos nuevos en el log ni textos nuevos.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
