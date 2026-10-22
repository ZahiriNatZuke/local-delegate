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

## Verificación en vivo, primera vuelta (sesión principal, 2026-10-22)

Daemon instalado desde este worktree (pid 21908), ventana de prueba `w-20261022T142031Z`:

- `inflight.json` se vacía en ≤ 1 s en los tres casos (matar el puente, cerrar su stdin,
  `notifications/cancelled`); el puente sale en 2 s; el uso apunta `cancel_reason`.
- **Falla** «un `local_classify` posterior responde en < 5 s» en los casos de matar el puente y de
  cerrar stdin (29,7 s y 29,8 s); con `notifications/cancelled`, 4,9 s, justo.
- Causa: el envío abandonado a llama-swap (127.0.0.1:9292) seguía abierto y generando el trozo
  del `gemma4-26b-a4b`; llama-swap no cambia al `gemma3-4b` hasta que acaba.

## Segunda vuelta: cortar la conexión del envío cancelado

Cómo se enviaba: todos los envíos comparten un único `httpx2.Client` del módulo (`_client`, pool
con keep-alive). Cerrarlo cortaría los envíos de otras llamadas.

Cambio: en una `tools/call`, `_send` usa un cliente propio para ese envío (`_new_client`, mismos
plazos), lo pasa a `_post_chat` por la `ContextVar` `_SEND_CLIENT` y registra en el token
`_cut_client`: `shutdown(SHUT_RDWR)` del socket de cada conexión de ese cliente y `close()`. El
`shutdown` hace falta en Linux y macOS, donde cerrar un socket no despierta al hilo bloqueado en
`recv` ni manda el FIN. Sin token (CLI, benchmark, tests) se sigue usando el compartido. Un error
de transporte de un envío cortado no ofrece arrancar el backend (sale por el error genérico).
`run_abandonable` lanza `CallCancelled` aunque el envío haya vuelto (lo hizo volver el corte).

Coste: sin keep-alive entre trozos de una `tools/call` (una conexión TCP por envío).

Test: `tests/test_cancellation.py::test_cancelled_send_closes_the_backend_connection`, con un
backend falso por socket que tarda 6 s y anota si el cliente cerró antes. Antes del arreglo falla
con `el backend no vio cerrarse la conexión: seguiría generando el trozo abandonado`. Controles:

- Sin registrar `_cut_client` → falla igual.
- Con `close()` y sin `shutdown` → **pasa en Windows** (allí `closesocket` sí corta). El caso que
  lo distingue es Linux/macOS, que cubre el CI (`test (ubuntu-latest)`, `test (macos-latest)`).

Suite completa (`-n 2`): 4387 passed, 28 skipped. `ruff check` y `ruff format --check` limpios.

## Verificación en vivo de la segunda vuelta (2026-10-22, 15:03–15:08Z)

Daemon instalado desde esta rama (pid 59828), ventanas `w-20261022T150348Z` y `w-20261022T150629Z`.
Mismo guion: puente propio con `local_summarize` del `CHANGELOG.md` (8 trozos, `gemma4-26b-a4b`) y
después un `local_classify` (`gemma3-4b`, obliga a cambiar de modelo).

| Corte | `inflight.json` vacío | Puente sale | `local_classify` después |
|---|---|---|---|
| kill a los 4 s (×2) | ≤ 1 s | — | 11,5 s y 10,8 s |
| stdin cerrado a los 4 s (×2) | ≤ 1 s | 1 s y 2 s | 10,1 s y 10,3 s |
| `notifications/cancelled` a los 5 s | ≤ 1 s | — | 3,4 s (medido 30 s después) |
| kill a los 20 s | — | — | 4,8 s |
| kill a los 40 s | — | — | 4,9 s |

Antes del arreglo: 192 s; tras la primera vuelta: 29,7–29,8 s.

**Lectura.** Con el corte durante la generación, la llamada siguiente tarda lo que cuesta cambiar de
modelo (~4–5 s): criterio cumplido. Con el corte en los primeros segundos de un trozo, el backend
está procesando el prompt (~8 K tokens) y llama.cpp no lo deja a medias: la siguiente espera ~10 s.
Es un límite del backend, no del daemon; el daemon ya suelta turno, plaza y conexión al instante.
