# Implementation plan: Un read_timeout dice si fue cola, carga o generación y en qué trozo (#572)

## Approach

La vigilancia `waiting_backend` de cada envío (`concurrency.SendWatch`) ya muestrea `/running` cada
10 s hasta ver el modelo `ready`: se le anota cuándo lo vio cargándose y cuándo listo, y
`_backend_wait_watch` la deja en un `ContextVar` para que `_post_chat` la lea al vencer el plazo. La
espera de turno y plaza sale de la traza de concurrencia (`Trace.phase_ms`). El trozo lo pone
`_map_reduce` al componer el error. Todo se añade solo cuando hay dato, así que el texto de hoy no
cambia sin él.

## Ordered tasks

- [x] T1 — Anotar carga y listo en `SendWatch`; exponerla a `_post_chat`; texto de carga y campo `read_timeout_load_ms` (REQ-002, REQ-004)
  - Files or modules: src/local_delegate/concurrency.py, src/local_delegate/server.py, i18n es/en
  - Verification: tests/test_read_timeout_explains.py, tests/test_read_timeout_cause.py
  - Depends on: none
- [x] T2 — Frase de espera de turno/plaza de 1 s o más (REQ-003)
  - Files or modules: src/local_delegate/concurrency.py, src/local_delegate/server.py, i18n es/en
  - Verification: tests/test_read_timeout_explains.py
  - Depends on: T1
- [x] T3 — Trozo X de N en el texto y en el evento de `_map_reduce` (REQ-001)
  - Files or modules: src/local_delegate/server.py, i18n es/en
  - Verification: tests/test_read_timeout_explains.py
  - Depends on: none

## Test strategy

- Unit: backend falso (`backend_mock`) con `/running` que pasa de `starting` a `ready` y POST que agota un plazo corto; espera de turno simulada en la traza; operación troceada.
- Integration: `local_summarize`/`local_commit_msg` troceados con log temporal.
- End-to-end or manual: no (sin backend real; la prueba en vivo queda para la sesión principal).
- Security and secret scanning: `personal-security-check` antes del commit.

## Migration and compatibility

- Campos nuevos y opcionales en el log; `read_timeout_cause` conserva sus valores.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
