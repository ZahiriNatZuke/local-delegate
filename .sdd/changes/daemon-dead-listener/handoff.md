# Handoff: El daemon sale (y se puede relevar) cuando su listener HTTP muere

## Current state

- SDD status: closed (PR de cierre `chore/close-sdd-2026-11-04-tarde`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `d75c09cf` (PR #578, issue #576)

## What changed

- El daemon sale con código 75 (`EX_TEMPFAIL`) y deja escrito el motivo en `daemon-errors.log` cuando su socket de escucha se cierra con el bucle vivo (WinError 64 en `accept` del `ProactorEventLoop`); el apagado tiene plazo (`timeout_graceful_shutdown`).
- Los cortes de cliente en la cola de `accept` ya no tumban el listener en Windows; los demás errores de `accept` se reintentan con espera creciente.
- `serve` releva a un daemon registrado que ya no escucha (rechazo TCP repetido, pid vivo y no reutilizado, `started_at` > 60 s, `daemon.json` estable); `doctor` distingue un daemon vivo sin listener de uno ausente.

## Decisions

- En macOS no hay relevo: la hora de creación del proceso solo se lee en Windows y Linux.
- Excepción explícita a «nunca señal a un pid leído de un fichero» (en `update._terminate` y el CHANGELOG), protegida por la guarda de pid reutilizado.
- La tarea programada de Windows no relanza el daemon tras el código 75; launchd y systemd sí.

## Next action

- Ninguna. El PR se mezcló sin los jobs de macOS (cancelados); el CI de `main` ya está en verde en commits posteriores.

## Memory

- Canonical note: vault `projects/local-delegate/jornada-2026-11-04-seis-arreglos-y-el-vigilante-de-precios.md`
- Indexes updated: índice de jornadas de `projects/local-delegate` (sesión principal)

