# Implementation plan: El daemon sale (y se puede relevar) cuando su listener HTTP muere

## Approach

Todo en `daemon.serve` sin subclasear `uvicorn.Server` (los tests existentes lo doblan por
`daemon.uvicorn.Server`): el vigilante entra por `uvicorn.Config(callback_notify=…, timeout_notify=…)`,
que uvicorn llama desde su `main_loop`. En cada tick revisa los sockets de `server.servers`; si alguno
tiene `fileno() == -1` marca el motivo y pone `should_exit`. Además instala en el loop un manejador
de excepciones que registra el contexto en el log de errores y delega en el de siempre. El apagado
lleva `timeout_graceful_shutdown` finito. `serve` devuelve 3 si el vigilante disparó.

Relevo: en la rama `Timeout` del lock, si ni el puerto pedido ni el registrado responden, se evalúa
el `daemon.json`: pid vivo y distinto, `started_at` con más de 60 s, conexión TCP **rechazada** tres
veces seguidas (timeout = no se sabe = no se toca) y el mismo pid/`started_at` releído al final.
Entonces se termina el pid, se espera el lock con plazo y se sigue el arranque normal.

## Ordered tasks

<!-- One checklist item per task: "- [ ] T<n> — title (REQ-NNN, ...)". Close it with [x]; drop it with
"- [-] T<n> ... dropped: <reason>". Every requirement needs at least one task that is not dropped. -->

- [x] T1 — Vigilante del listener, salida ≠ 0 y apagado con plazo (REQ-001, REQ-002)
  - Files or modules: `src/local_delegate/daemon.py`
  - Verification: test con daemon de prueba real en subproceso, puerto y `LOG_DIR` temporales
  - Depends on: none
- [x] T2 — Log de errores acotado a fichero (REQ-004)
  - Files or modules: `src/local_delegate/daemon.py`
  - Verification: test que lee `daemon-errors.log` tras el fallo
  - Depends on: T1
- [x] T3 — Relevo del daemon registrado con el puerto muerto (REQ-003)
  - Files or modules: `src/local_delegate/daemon.py`, i18n `cli.json` es/en
  - Verification: tests unitarios de la decisión + test con un proceso zombi de prueba
  - Depends on: T2
- [x] T4 — Aviso de `doctor` (REQ-005)
  - Files or modules: `src/local_delegate/checks.py`, i18n `doctor.json` es/en
  - Verification: test del probe con el colaborador doblado
  - Depends on: none
- [x] T5 — CHANGELOG `[Unreleased]` (REQ-001, REQ-003, REQ-004, REQ-005)
  - Files or modules: `CHANGELOG.md`
  - Verification: review
  - Depends on: T1–T4

- [x] T6 — `accept` tolerante del proactor instalado en el lifespan (REQ-006)
  - Files or modules: `src/local_delegate/daemon.py`
  - Verification: test Windows con ráfagas de resets; prueba de carga con 40 clientes de turno
  - Depends on: T1

## Test strategy

- Unit: decisión de relevo (casos positivos y negativos), probe de `doctor`, config de uvicorn.
- Integration: daemon de prueba real (`python -m local_delegate serve`) en subproceso con
  `LOCAL_DELEGATE_LOG_DIR`, `LOCAL_DELEGATE_LOG` y puerto temporales; se le provoca el `accept`
  fallido con conexiones reseteadas mientras el loop está bloqueado (gancho de prueba por entorno)
  o cerrando el socket desde dentro.
- End-to-end or manual: repro en scratchpad contra el código instalado de la rama.
- Security and secret scanning: `personal-security-check` antes del commit.

## Migration and compatibility

- Sin cambios de formato en `daemon.json`. Un daemon 0.48 zombi lo releva el `serve` nuevo.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
