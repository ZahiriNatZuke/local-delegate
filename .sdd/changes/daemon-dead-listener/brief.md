# Brief: El daemon sale (y se puede relevar) cuando su listener HTTP muere

## Problem

Issue #576. En Windows el daemon (0.48.0, `pythonw`, tarea `LocalDelegateDaemon`) dejó de escuchar
en `:9393` con el proceso vivo; `daemon.json` y `daemon.lock` seguían retenidos, el singleton impedía
arrancar otro y no quedó ningún log.

Causa reproducida (`scratchpad/i576/repro_accept.py`): en el `ProactorEventLoop` de CPython
(`asyncio/proactor_events.py`, `_start_serving.loop`), **cualquier `OSError` en `accept` cierra el
socket de escucha para siempre** y solo lo cuenta al manejador de excepciones del loop («Accept
failed on a socket»). Un cliente que resetea su conexión mientras espera en la cola de `accept`
(cancelaciones, `read_timeout`, carga concurrente) da `WinError 64` y basta. El loop sigue vivo,
uvicorn no se entera, `run()` no vuelve y el `finally` que suelta el lock no corre.

Segunda vía con el mismo síntoma: si uvicorn recibe una señal de salida, cierra el listener y luego
espera **sin plazo** (`timeout_graceful_shutdown=None`) a que cierren las conexiones abiertas (los
streams MCP de los clientes no cierran nunca).

## Desired outcome

El daemon no queda zombi: si su listener muere, sale con código ≠ 0 y deja un rastro; un `serve`
nuevo releva a un daemon registrado que ya no atiende su puerto; `doctor` lo dice.

## In scope

- `daemon.py`: vigilante del listener, apagado con plazo, código de salida, log de errores a fichero,
  relevo en la rama de lock ocupado.
- `checks.py`: aviso de «proceso vivo y puerto sin escuchar».
- i18n es/en de los mensajes nuevos, CHANGELOG.

## Out of scope

- La política de reinicio de la tarea programada (la crea el usuario, no el código).
- El `read_timeout` de `local_commit_msg` (#572) y `local_extract` (#568).

## Constraints and risks

- No matar un daemon sano que va lento: el relevo exige conexión **rechazada** (no timeout) varias
  veces, pid vivo, arranque con más de 60 s y el mismo `daemon.json` antes y después.
- Dos arranques simultáneos: el lock decide; el perdedor cae en la rama de siempre.
- Tests existentes intactos (doblan `daemon.uvicorn.Server`: el vigilante va por `uvicorn.Config`).

## Open questions

- Ninguna que cambie la spec.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-04 Original request, verbatim:

  > Issue #576: el daemon deja de escuchar en :9393 con el proceso vivo; el singleton bloquea el relanzamiento y no queda rastro. Arreglo: salir con codigo distinto de 0 si el listener muere, relevar un daemon registrado cuyo puerto rechaza conexiones, log de errores acotado a fichero y aviso en doctor.
