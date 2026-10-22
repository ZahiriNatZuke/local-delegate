# Evidencia — Cancelar las llamadas abandonadas (abandoned-calls)

Rama `feat/plugin-abandoned-calls`, worktree `D:/Projects/ld-wt-abandoned-calls`, sobre `main` en
`97bc8c5` (0.40.0).

## Dónde se perdía la cancelación

Sonda temporal (un middleware del SDK con un vigilante en el ámbito del handler) sobre la app real
del daemon, con un backend falso de 0,4 s por llamada y un `local_summarize` de ~21 llamadas:

```
('notifications/cancelled sent', 0.09, 1)
('handler scope cancelled',      0.09, 1)
('call_next returned',           8.56, 21)
```

- El SDK **sí** cancela el ámbito del handler en cuanto llega el aviso:
  `mcp/shared/jsonrpc_dispatcher.py:645` (`in_flight.scope.cancel()`, modo `interrupt`).
- Las tools del daemon son síncronas y el SDK las corre con
  `anyio.to_thread.run_sync(functools.partial(fn, **kwargs))` **sin** `abandon_on_cancel`
  (`mcp/server/mcpserver/utilities/func_metadata.py:164`). Esa espera retiene la cancelación hasta
  que el hilo acaba, y el hilo no tenía ninguna señal: siguió mandando 20 trozos más.
- La desconexión del cliente en el transporte con sesión (2025-06-18) no cancela el handler: el
  SDK solo deja de escribir en ese flujo.
- `desktop_bridge.py`, `Bridge.run`: al agotarse stdin, el `async with` del grupo de tareas
  esperaba a las peticiones en curso; el `DELETE` iba después.

## Cambio

- `src/local_delegate/cancellation.py` (nuevo): `Token` por `tools/call` en una `ContextVar` que
  hereda el hilo de la tool; middleware del SDK con un vigilante que lo cancela cuando se cancela
  el ámbito del handler (aviso → `notification`; sesión cerrada u otra → `aborted`) o cuando el
  cliente corta la conexión (`disconnect`, vía `DisconnectWatcher`, middleware ASGI que el daemon
  monta en su app); `run_abandonable` para abandonar el envío en curso al backend;
  `CallCancelled` es un `ToolError` (línea INFO, no traza de fallo inesperado).
- `server.py`: puntos de parada en `_slot` (antes de cada trozo y durante la espera de plaza), en
  la espera de turno (`_waiting_for` → `Turn.request/wait_for_grant(should_stop=…)` + `wake`) y en
  cada envío (`_send` → `run_abandonable`). El evento de uso de la llamada cancelada sale de
  `_log_cancelled`: `ok: false`, `error: "cancelled"`, `cancel_reason`.
- `turn.py`: `should_stop` en la espera y `wake()`.
- `daemon.py`: `mcp_app.add_middleware(cancellation.DisconnectWatcher)`.
- `desktop_bridge.py`: al cerrarse stdin, margen de 0,5 s (2,5 s sin sesión, para que salgan los
  errores de conexión del propio puente), `notifications/cancelled` por cada petición pendiente
  (tope 0,5 s), cancelar el grupo y `DELETE` (tope 2 s).

## Tests primero

`tests/test_desktop_bridge.py` (app real del daemon con uvicorn, backend falso lento, topología de
hoy donde el modelo largo y el mecánico chocan). Antes del arreglo, los cuatro fallan por el
assert que dicen:

| Test | Assert que falla antes |
|---|---|
| `test_cancelled_notification_releases_backend_turn` | `la segunda llamada esperó 8.9 s a la cancelada` |
| `test_session_delete_cancels_inflight` | `la llamada cancelada sigue en inflight.json 2 s después` |
| `test_client_disconnect_cancels_inflight` | `la llamada cancelada sigue en inflight.json 2 s después` |
| `test_stdin_eof_cancels_inflight_and_exits_fast` | `el puente tardó 8.5 s en salir tras cerrarse stdin` |

Con solo el arreglo del daemon, el del puente sigue fallando igual (8,5 s): el puente no avisaba.

`tests/test_cancellation.py`: salir de la cola del turno sin esperar el tic (tic de 30 s) y
`run_abandonable`.

Controles con mutante:

- Quitar la mirada a `should_stop` en `Turn._wait` → falla
  `test_cancelled_wait_leaves_turn_queue_without_waiting_the_tick` con
  `la espera cancelada sigue en la cola`.
- Quitar `DisconnectWatcher` del daemon → falla `test_client_disconnect_cancels_inflight` con
  `la llamada cancelada sigue en inflight.json 2 s después`.

- Quitar la herencia del token del bucle de anyio en `run_abandonable` → falla
  `test_abandonable_send_can_still_reach_the_event_loop` con `NoEventLoopError`: sin ella, la
  pregunta de arrancar el backend (`questions.ask`, dentro del envío) se perdería en silencio.

Ajuste por la suite existente: las peticiones rápidas que llegan justo antes del fin de stdin
(tubería) no se cortan; de ahí el margen de 0,5 s y el de 2,5 s sin sesión
(`test_daemon_down_returns_mcp_error`: en Windows el puerto cerrado tarda ~2 s).

## Suite

`bash ~/.claude/scripts/pesado.sh uv run pytest -n 2 -q`: 4384 passed, 28 skipped, 1 failed
(`test_detect_spanish_names`: palabras nuevas sin clasificar → añadidas al léxico `en`; su test,
46 passed). `ruff check .` y `ruff format --check .` limpios.

## Verificación en vivo

Pendiente de la sesión principal (reinstalar y reiniciar el daemon): guion del plan.
