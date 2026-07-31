# Brief: `doctor` pregunta al daemon por el backend en vez de salir sin credencial

## Problem

Reportado por el usuario el 2026-07-31 («me incomoda mucho»), corriendo `local-delegate doctor`
desde su consola:

```
[ -- ] backend: http://127.0.0.1:9292/v1/models responde 401: está arriba pero rechaza la
       credencial (¿falta LOCAL_DELEGATE_API_KEY en este entorno?)
```

**Causa, verificada por ejecución.** `config.API_KEY` se lee **del entorno del proceso**
(`config.py:52`), y ahí está la asimetría: el daemon la recibe de su lanzador —en Windows,
descifrada con DPAPI— pero una consola interactiva no la tiene. `service.backend` prueba el backend
**directamente** (`doctor.backend_probe`), manda `auth_headers()` vacío y cobra un 401.

**Y el dato existía todo el tiempo.** Medido contra el daemon vivo:

```
GET http://127.0.0.1:9393/api/backend
{"available":true,"models":[{"id":"gemma3-4b","status":"unloaded"}, …5 modelos…],"origin":"local"}
```

Es el **mismo servicio** que `service.daemon` ya consulta, a un HTTP de distancia y autenticado.
`doctor` prefería salir por su cuenta sin credencial y fallar: dos caminos para el mismo dato, y el
que se usaba era el que no podía saberlo.

## Desired outcome

`doctor` dice si el backend está sano **también** cuando se ejecuta desde un entorno sin la clave, y
deja de mostrar el 401 en una máquina cuyo backend está perfectamente.

## In scope

- `daemon.query_backend(host, port)`: preguntar al daemon por el backend, con la misma forma que
  `query_daemon` (dict o `None`).
- `checks._default_backend_models`: preguntar al daemon primero; probar directo si no hay daemon.
- Tests de los tres caminos y del contrato de `query_backend`.

## Out of scope

- **Poner `LOCAL_DELEGATE_API_KEY` en el entorno de usuario**: dejaría la clave en texto plano en el
  registro de Windows, que es justo lo que el cifrado DPAPI evita. Descartado por seguridad.
- Cambiar `doctor.backend_probe`, cuya semántica —«prueba el backend directamente»— sigue siendo
  correcta y la usa también `_backend_up`.
- Autenticar el dashboard o el endpoint `/api/backend` (loopback, ya tratado en `SECURITY.md`).

## Constraints and risks

- **La clave no debe salir del proceso que la tiene.** El arreglo no la mueve, no la copia y no la
  escribe: solo pregunta por el **resultado** a quien ya la usa.
- El peor caso hace **dos** llamadas HTTP (daemon 1 s, backend 2 s). Aceptable para un diagnóstico.
- **Riesgo de test dependiente del entorno**: si el colaborador nuevo no se dobla, la suite sale a
  la red de verdad y da verde en CI (sin daemon) y otra cosa en la máquina de desarrollo. Ya pasó
  hoy con `clients.jsonl`; hay que doblarlo en `_stub_environment`.
- Una respuesta del daemon **sin** `available` no debe leerse como «backend caído»: sería inventar
  un fallo a partir de una respuesta que no dice nada.

## Open questions

Ninguna. La causa está verificada por ejecución y la fuente alternativa, medida en vivo.
