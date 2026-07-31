# Handoff: `doctor` pregunta al daemon por el backend

## Current state

- SDD status: `closing`. Gates `spec`, `plan`, `quality` y `conformance` aprobados.
- Revision: rama `fix/doctor-backend-via-daemon` sobre `main` en `1182a92`.
- Suite: **562 passed, 1 skipped**.

## What changed

Nace `daemon.query_backend`, y `checks._default_backend_models` la usa antes de probar el backend
por su cuenta. Con eso desaparece el `[ -- ] … 401` que salía en cualquier consola sin la clave.

Cinco ficheros: `daemon.py`, `checks.py`, `tests/test_daemon.py`, `tests/test_doctor.py`,
`CHANGELOG.md`.

## Decisions

- **La clave NO se mueve.** Se descartó explícitamente ponerla en el entorno de usuario: dejaría el
  secreto en texto plano en el registro de Windows, que es justo lo que el cifrado DPAPI evita. El
  arreglo pregunta por el **resultado** a quien ya la tiene.
- **`doctor.backend_probe` no se toca.** Significa «prueba el backend directamente» y la usa también
  `_backend_up`; meterle el daemon dentro cambiaría su semántica para todos.
- **`available: false` del daemon es diagnóstico, no duda** (aviso, no `unknown`): él sí tiene
  credencial. Es lo que distingue este caso del 401.
- **Una respuesta sin `available` es «no se pudo preguntar»**, nunca «caído».

## Next action

Merge del PR. Después, lo que queda de la sesión es backlog viejo; nada urgente.

Aviso para quien siga: **`main` lleva tres changes sin publicar** desde la 0.18.0 (`client.observed`
salió en ella, pero el fix del daemon y este no). La próxima release sería una **0.18.1**.

## Memory

- Canonical note: `projects/local-delegate/jornada-2026-07-31-la-0-18-0.md`.
- Indexes updated: pendiente al cerrar.
