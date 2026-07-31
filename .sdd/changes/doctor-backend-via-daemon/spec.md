# Specification: `doctor` pregunta al daemon por el backend

## Summary

Cuando hay un daemon corriendo, `doctor` toma de él el estado del backend en vez de probarlo por su
cuenta sin credencial. Deja de salir el `[ -- ] … 401` en máquinas cuyo backend está sano.

## Requirements

- **REQ-001:** `daemon.query_backend(host, port, timeout)` devuelve lo que el daemon ve del backend,
  o `None` si no se le pudo preguntar (no hay daemon, no responde, no es JSON, no es un objeto).
- **REQ-002:** Una respuesta **sin el campo `available`** es `None` — «no se pudo preguntar», no
  «backend caído».
- **REQ-003:** `service.backend` consulta al daemon **antes** de probar directamente.
- **REQ-004:** Con el daemon reportando `available: true`, el check es `ok` y **no** menciona la
  credencial.
- **REQ-005:** Con el daemon reportando `available: false`, el check **cuenta como aviso** (no
  `unknown`), porque el daemon sí tiene credencial y su negativa es un diagnóstico.
- **REQ-006:** Sin daemon al que preguntar, el comportamiento es **el de antes**: se prueba directo,
  con su distinción entre «no responde» y «responde 401».
- **REQ-007:** La clave del backend no se lee, copia, escribe ni expone en ningún sitio nuevo.

## Acceptance scenarios

### Scenario: el caso reportado

- **Given** el daemon arriba y autenticado, y una consola **sin** `LOCAL_DELEGATE_API_KEY`
- **When** el usuario ejecuta `local-delegate doctor`
- **Then** la línea del backend sale `[ OK ]`, la cabecera dice «arriba» sin coletilla, y el exit
  code es 0

### Scenario: sin daemon

- **Given** ningún daemon escuchando
- **When** el usuario ejecuta `local-delegate doctor` con el backend caído
- **Then** el diagnóstico dice CAÍDO, igual que antes del cambio

## Edge cases and failure behavior

- Daemon que responde algo que no es JSON, o un JSON que no es objeto → `None` → prueba directa.
- Daemon lento → `timeout` de 1 s, igual que `query_daemon`; luego prueba directa.
- El peor caso encadena dos llamadas (1 s + 2 s). Aceptable en un diagnóstico.

## Non-functional requirements

- **Seguridad:** REQ-007. El arreglo pregunta por el **resultado** a quien ya tiene la clave; no la
  mueve. Se descarta explícitamente ponerla en el entorno de usuario (texto plano en el registro).
- **Tests deterministas:** el colaborador nuevo debe estar doblado en `_stub_environment`, o la
  suite sale a la red y depende de si la máquina tiene daemon.

## Non-goals

- Tocar `doctor.backend_probe`, que sigue significando «prueba el backend directamente».
- Autenticar `/api/backend` (loopback; ya tratado en `SECURITY.md`).

## Traceability

| Requisito | Verificación |
| --- | --- |
| REQ-001 | `test_query_backend_devuelve_lo_que_ve_el_daemon` |
| REQ-002 | `test_query_backend_sin_el_campo_available_es_none` |
| REQ-003, REQ-004 | `test_el_daemon_responde_por_el_backend_y_se_acabo_el_401` + ejecución real |
| REQ-005 | `test_si_el_daemon_dice_que_el_backend_esta_caido_eso_no_es_una_duda` |
| REQ-006 | `test_sin_daemon_el_backend_se_prueba_directo_como_siempre`, `test_run_doctor_keeps_the_previous_output` |
| REQ-007 | revisión del diff: no aparece `API_KEY` ni `auth_headers` en el código nuevo |
