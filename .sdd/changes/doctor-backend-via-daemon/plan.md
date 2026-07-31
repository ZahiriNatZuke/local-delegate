# Implementation plan: `doctor` pregunta al daemon por el backend

## Approach

La pregunta al daemon vive en **`daemon.py`**, junto a `query_daemon`, con su misma forma (dict o
`None`) y por el mismo motivo: cualquier fallo significa «no se pudo preguntar», y quien llama hace
lo mismo en todos esos casos. Poner la URL o el path en `checks.py` habría creado una segunda
definición de «dónde se le pregunta al daemon».

El cambio de comportamiento vive en **`_default_backend_models`**, no dentro de
`doctor.backend_probe`: esa función significa «prueba el backend directamente», la usa también
`_backend_up`, y meterle el daemon dentro cambiaría su significado para todos sus consumidores.

**No se toca el `Context`.** Todos los tests que doblan `backend_models` siguen funcionando igual,
porque lo que cambia es el *default*, no el contrato `(bool, str)`.

## Ordered tasks

1. **`daemon.query_backend`**
   - Files: `src/local_delegate/daemon.py` (+ constante `BACKEND_STATUS_PATH`)
   - Requirements: REQ-001, REQ-002
   - Verification: tres tests de contrato con el cliente HTTP doblado.
   - Rollback: quitar la función; nadie más la usa.

2. **`_default_backend_models` pregunta primero al daemon**
   - Files: `src/local_delegate/checks.py`
   - Requirements: REQ-003 a REQ-006
   - Rollback: revertir a `doctor.backend_probe()`.

3. **Aislar los tests del entorno**
   - Files: `tests/test_doctor.py` — `_stub_environment` gana `backend_via_daemon`, con `None` por
     defecto. **Sin esto la suite sale a la red de verdad.**
   - Requirements: soporte de todos.

4. **Tests de comportamiento + CHANGELOG**
   - Files: `tests/test_doctor.py`, `tests/test_daemon.py`, `CHANGELOG.md` (**CRLF**: con la
     herramienta de edición).

## Test strategy

- **Unit**: contrato de `query_backend` (dict válido, sin `available`, respuesta que no es objeto).
- **Integration**: `run_doctor` con daemon que dice `available: true` (no sale el 401), con
  `available: false` (cuenta como aviso) y sin daemon (camino de antes intacto).
- **End-to-end manual**: `local-delegate doctor` en esta máquina, con el daemon vivo y la consola
  **sin** la clave — que es exactamente el caso reportado.
- **Verificar al revés**: no preguntar al daemon, dar por bueno un `available: false`, y aceptar una
  respuesta sin `available`. Cada uno debe romper **su** test.
- **Security**: revisar el diff para confirmar que no aparece `API_KEY` ni `auth_headers` en el
  código nuevo (REQ-007).

## Migration and compatibility

- Aditivo: sin cambios de contrato, de dependencias ni de configuración.
- **Cambia lo que ve el usuario en una máquina con daemon**: el `[ -- ]` del 401 pasa a `[ OK ]`.
  Eso es el objetivo, y puede bajar el exit code de 1 a 0 en máquinas donde el único aviso era este.
- Sin daemon, todo idéntico.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback — ninguna: solo lecturas.
- [x] Dependencies and configuration changes are explicit — ninguna.
- [x] The plan does not include unrelated work — `backend_probe` y la autenticación del dashboard
      quedan fuera, declaradas como no-goals.
