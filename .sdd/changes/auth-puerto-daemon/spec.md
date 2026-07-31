# Specification: El puerto del daemon exige token cuando se configura uno

## Summary

Con `LOCAL_DELEGATE_WEB_TOKEN` definida en el entorno del daemon, **todo** su puerto exige ese
token: el endpoint MCP, el dashboard y `/api/*`. Sin la variable, el daemon se comporta
exactamente como hasta ahora. El secreto no se escribe en ningún fichero de configuración: los
clientes lo referencian por el nombre de la variable.

## Requirements

- **REQ-001:** Con token configurado, una petición sin credencial válida a cualquier ruta del
  puerto recibe `401`.
- **REQ-002:** El token se acepta como `Authorization: Bearer <token>` y como
  `Authorization: Basic <base64(usuario:token)>`, ignorando el usuario.
- **REQ-003:** El `401` incluye `WWW-Authenticate` con un `realm` propio, para que un navegador
  pida las credenciales por sí solo.
- **REQ-004:** Sin token configurado, el comportamiento del puerto es idéntico al anterior.
- **REQ-005:** Los mensajes que no son peticiones HTTP (`lifespan`) atraviesan la puerta sin
  tocarse.
- **REQ-006:** El CLI se autentica contra su propio daemon cuando hay token en su entorno.
- **REQ-007:** `install --mcp-mode http --web-token-env` deja a Claude Code y a Codex
  autenticándose **sin** que el secreto aparezca en sus ficheros.
- **REQ-008:** El diagnóstico distingue «hay otro proceso en el puerto» de «está nuestro daemon y
  a este entorno le falta el token», y solo lo afirma si el `401` lleva nuestro `realm`.
- **REQ-009:** Ni el diagnóstico ni las respuestas de error imprimen el valor del token.

## Acceptance scenarios

### Scenario: el puerto protegido rechaza a quien no lleva token

- **Given** un daemon arrancado con `LOCAL_DELEGATE_WEB_TOKEN`
- **When** llega una petición sin credencial a `/mcp`, `/`, `/api/status`, `/api/daemon` o
  `/api/backend`
- **Then** todas reciben `401` con `WWW-Authenticate`

### Scenario: el navegador puede abrir el panel

- **Given** el mismo daemon
- **When** el navegador recibe el `401` y el usuario pega el token como contraseña
- **Then** el panel carga

### Scenario: el diagnóstico no acusa al daemon de ser otro proceso

- **Given** un daemon protegido y un `doctor` sin el token en su entorno
- **When** se ejecuta `local-delegate doctor`
- **Then** el check del daemon dice que falta el token y ofrece la variable como arreglo, sin
  imprimir su valor

### Scenario: quien no configura token no nota nada

- **Given** un daemon sin la variable
- **When** llega cualquier petición
- **Then** responde como siempre, sin `401`

## Edge cases and failure behavior

- **`Basic` mal formado** (no es base64, o no trae `:`): credencial inválida → `401`. No es un
  error del servidor.
- **Token con `:` dentro:** válido. El separador de `Basic` es el **primer** `:`, así que la
  contraseña puede contener los suyos.
- **Un `401` de otro servicio en ese puerto:** no se atribuye al daemon. Sin mirar el `realm`, el
  diagnóstico cambiaría un mensaje falso por otro.
- **No se pudo preguntar al puerto:** `None`, y el diagnóstico mantiene el mensaje de siempre. «No
  lo sé» no es «no lo exige».
- **Esquema desconocido** (`Negotiate`, etc.): `401`.

## Non-functional requirements

- **Seguridad:** comparación en tiempo constante (`secrets.compare_digest`). La pregunta de si el
  puerto exige token se hace **sin** cabecera de autorización — mirar por el camino que sí lleva
  credencial es lo que ya tapó una avería un día entero aquí.
- **Compatibilidad:** sin la variable, cero cambios observables y cero coste por petición (la app
  vuelve sin envolver).
- **Privacidad:** el token no aparece en mensajes de error, detalles de checks ni ficheros de
  configuración.

## Non-goals

- Detectar si el puerto está publicado (descartado con el usuario: ataría el MCP a una herramienta
  externa concreta).
- Cuentas, sesiones, cookies, CSRF, OAuth o roles.
- Cifrar el tránsito: eso es del proxy que haya delante.
- Defensas basadas en `Host` o IP de origen: descartadas por medición.

## Traceability

| Requisito | Trabajo | Evidencia |
| --- | --- | --- |
| REQ-001 | Tarea 2 | `test_web_auth.py` + e2e contra daemon real |
| REQ-002 | Tarea 2 | `test_web_auth.py` (Bearer, Basic, usuario indiferente) |
| REQ-003 | Tarea 2 | `test_el_401_invita_al_navegador_a_preguntar` + e2e |
| REQ-004 | Tareas 1-3 | `test_sin_token_*`, mutante `proteger-siempre-envuelve` |
| REQ-005 | Tarea 2 | `test_el_lifespan_no_se_filtra` |
| REQ-006 | Tarea 3 | `test_el_cli_se_autentica_contra_su_propio_daemon` |
| REQ-007 | Tarea 4 | `test_el_token_del_puerto_se_referencia_y_nunca_se_escribe` |
| REQ-008 | Tarea 5 | `test_el_puerto_protegido_no_se_confunde_*` + tests del `realm` |
| REQ-009 | Tareas 4-5 | `test_el_diagnostico_del_token_no_imprime_el_secreto` |
