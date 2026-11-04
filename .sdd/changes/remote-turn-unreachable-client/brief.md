# Brief: Turno remoto inalcanzable: en serie, corte y aviso (#577)

## Problem

Issue #577: desde la Mac (backend en la PC), con el turno remoto de la PC sin responder, cinco
`local_describe_image` esperaron ~55 s el turno, fueron igualmente al backend sin turno (dos a la
vez, `MAX_CONCURRENT_REQUESTS=2`) y cada una agotó sus 180 s; dos más esperaron 180 s de plaza
(~415 s). El corte por backend inalcanzable no saltó (las conexiones se abrían) y el enfriamiento
por modelo no cuenta `capacity_or_load` (un `read_timeout` con el modelo sin cargar se clasifica así).

## Desired outcome

Con el turno inalcanzable: no competir a ciegas, cortar rápido cuando hay prueba de backend ocupado
y decir en el error que no había turno.

## In scope

- Cliente del turno (`remote_turn.py`), operación (`server._OperationTurn`), corte nuevo
  (`cooldown.remote_turn_cut`), config, i18n, docs.

## Out of scope

- Servidor del turno y `/api/turn/*` (#576, otro agente).
- Clasificación de errores del turno (#512, cerrado) y del `read_timeout`.

## Constraints and risks

- #512: daemon parado con backend sano debe seguir funcionando → se sigue sin turno, en serie.
- Sin plazos nuevos más largos. Tests existentes intactos.
- Research: `remote_turn.py` (memoria de razones, `acquire`), `server.py` 2783-3150
  (`_waiting_for`, `_remote_grant`, `release_slot`), 3396-3426 (corte por backend), 3514-3600
  (`_with_fallback`), `cooldown.py` (`CooldownState`, `backend_breaker`), `failures.py` (clases);
  jornadas del vault 2026-10-29 y 2026-10-30 (resumidas con `local_summarize`).

## Open questions

- Ninguna bloqueante. La serie es por proceso; el corte, por máquina (fichero compartido).

## Log

- L1 (2026-11-04): issue #577 — «con el turno remoto inalcanzable, las delegaciones van al backend
  sin coordinar y cada una agota el plazo (hasta ~415 s)». Rama `fix/remote-turn-unreachable-client`.
