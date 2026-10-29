"""Cancelar una llamada a una tool cuando su cliente ya no la espera (SDD claude-plugin-and-mods).

Dónde se perdía (medido el 2026-10-22): el SDK de MCP **sí** cancela el ámbito del handler al
llegar `notifications/cancelled` (`mcp/shared/jsonrpc_dispatcher.py`, `in_flight.scope.cancel()`)
o al cerrar la sesión, pero las tools del daemon son síncronas y el SDK las corre con
`anyio.to_thread.run_sync(...)` sin `abandon_on_cancel` (`mcp/server/mcpserver/utilities/
func_metadata.py`, `call_fn`). Esa espera no se puede interrumpir: la cancelación queda retenida
hasta que el hilo acaba, y el hilo no se enteraba de nada. Seguía mandando trozos al backend,
esperando turno y ocupando plaza hasta el final (un resumen de 21 trozos: cancelado a los 0,09 s,
devuelto a los 8,56 s).

El arreglo tiene dos mitades:

- **Señal** (`middleware`): por cada `tools/call` se crea un `Token` y se deja en una
  `ContextVar`, que el hilo de la tool hereda. Un vigilante en el mismo ámbito del handler lo
  cancela cuando ese ámbito se cancela (aviso de cancelación, `DELETE` de la sesión, transporte
  moderno que corta la petición) o cuando el cliente HTTP cierra la conexión de la petición
  (`DisconnectWatcher`, que en el transporte con sesión el SDK no convierte en cancelación).
- **Puntos de parada** en el hilo (`checkpoint`, `run_abandonable` y las esperas de `server`):
  antes de cada plaza, durante la espera de turno y de plaza, y durante el envío al backend. Al
  cancelarse lanzan `CallCancelled`, y los `finally` de siempre sueltan el turno, la plaza y la
  entrada de `inflight.json`.
"""

from __future__ import annotations

import contextvars
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

import anyio
from mcp.server.mcpserver.exceptions import ToolError

try:  # el token del bucle de un hilo de anyio; ver `run_abandonable`
    from anyio._core._eventloop import threadlocals as _anyio_threadlocals
except ImportError:  # pragma: no cover - otra versión de anyio: se pierde solo la pregunta
    _anyio_threadlocals = None

T = TypeVar("T")

#: Cada cuánto mira una espera bloqueante si la llamada se canceló, cuando no puede despertarla
#: la propia cancelación (el semáforo de plazas).
POLL_S = 0.1

#: Clave del `scope` ASGI donde `watch_disconnect` deja el evento de desconexión de la petición.
DISCONNECT_KEY = "local_delegate.disconnected"

REASON_NOTIFICATION = "notification"
REASON_DISCONNECT = "disconnect"
REASON_ABORTED = "aborted"
#: The daemon's own budget for the call (`config.CALL_MAX_S`) ran out (issue #476).
REASON_DEADLINE = "deadline"


class CallCancelled(ToolError):
    """La llamada se canceló: quien la pidió ya no espera la respuesta.

    Es un `ToolError` para que el SDK la trate como un fallo previsto de la tool (una línea INFO)
    y no como un fallo inesperado con traza en el log del daemon.
    """

    def __init__(self, reason: str, message: str | None = None) -> None:
        super().__init__(message or reason)
        self.reason = reason


class Token:
    """La cancelación de UNA llamada: se activa desde el bucle de eventos, se mira desde hilos."""

    def __init__(self, tool: str | None = None) -> None:
        self.tool = tool
        self.started = time.monotonic()
        self.reason: str | None = None
        #: Un punto de parada llegó a lanzar `CallCancelled`: la llamada no se completó.
        self.observed = False
        #: La primera operación que abrió la llamada (`tool`, `model`, `source`, `chars_in`), para
        #: apuntarla en el registro de uso aunque no llegue a escribir su evento.
        self.entry: dict[str, Any] | None = None
        #: Issue #476: what the call measured until it stopped, so an aborted call is logged with
        #: its waits and its real backend calls, not only with its duration. Written from the
        #: tool's thread (`server`), read when the call ends.
        self.turn_wait_ms = 0
        self.slot_wait_ms = 0
        self.attempts: list[Any] = []
        #: Concurrency PC+Mac, step 0: the operation's `concurrency.Trace`, so a stopped call's event
        #: carries its phases too (set by `server._OperationTurn`).
        self.concurrency_trace: Any = None
        #: The exception that stopped an operation that had started (`server._note_failure`): the
        #: operation never got to write its event, so `middleware` writes it with `on_failed`.
        self.failure: BaseException | None = None
        #: The daemon's budget for this call in seconds (`0`: none), for the deadline's message.
        self.deadline_s = 0.0
        #: Issue #479: where the call is now, for the progress heartbeat's message. Written from
        #: the tool's thread (`server._inflight_*`), read by `middleware` on the event loop:
        #: `wait` ("turn" or "slot"), `position`, `in_use`, `chunk`, `chunks`, `phase`.
        self.status: dict[str, Any] = {}
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[], None]] = []

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self, reason: str) -> None:
        """Activa la cancelación (la primera razón es la que queda) y despierta a quien espera."""
        with self._lock:
            if self._event.is_set():
                return
            self.reason = reason
            self._event.set()
            callbacks, self._callbacks = self._callbacks, []
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass  # despertar es una ayuda: quien espera también mira cada POLL_S

    def on_cancel(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Llama a `callback` al cancelarse (ya, si ya lo estaba). Devuelve cómo quitarlo."""
        with self._lock:
            if not self._event.is_set():
                self._callbacks.append(callback)

                def remove() -> None:
                    with self._lock:
                        if callback in self._callbacks:
                            self._callbacks.remove(callback)

                return remove
        callback()
        return lambda: None

    def check(self) -> None:
        """Punto de parada: lanza `CallCancelled` si la llamada se canceló."""
        if self._event.is_set():
            self.observed = True
            reason = self.reason or REASON_ABORTED
            raise CallCancelled(reason, self._message(reason))

    def _message(self, reason: str) -> str | None:
        """What the caller reads: the deadline says why and what to do (issue #476)."""
        if reason != REASON_DEADLINE:
            return None
        from . import i18n

        return i18n.t("mcp.error.call_deadline", seconds=round(self.deadline_s))

    def progress_message(self) -> str:
        """The heartbeat's text (issue #479): the phase when known, and the time so far."""
        from . import i18n

        status = dict(self.status)  # a copy: the tool's thread may write meanwhile
        wait = status.get("wait")
        if wait == "turn":
            phase = i18n.t(
                "mcp.progress.turn",
                position=status.get("position") or 1,
                models=", ".join(status.get("in_use") or ()) or "-",
            )
        elif wait == "slot":
            phase = i18n.t("mcp.progress.slot")
        elif status.get("phase") in ("reduce", "retry"):
            phase = i18n.t(f"mcp.progress.{status['phase']}")
        elif status.get("chunks"):
            phase = i18n.t(
                "mcp.progress.chunk", chunk=status.get("chunk") or 1, chunks=status["chunks"]
            )
        else:
            phase = i18n.t("mcp.progress.running")
        elapsed = round(time.monotonic() - self.started)
        return i18n.t("mcp.progress.message", phase=phase, elapsed=elapsed)


_CURRENT: contextvars.ContextVar[Token | None] = contextvars.ContextVar(
    "local_delegate_cancel_token", default=None
)


def current() -> Token | None:
    """El token de la llamada en curso; `None` fuera de una `tools/call` (CLI, tests, benchmark)."""
    return _CURRENT.get()


def checkpoint() -> None:
    token = _CURRENT.get()
    if token is not None:
        token.check()


def run_abandonable(fn: Callable[[], T]) -> T:
    """Corre `fn` (un envío al backend) y la abandona si la llamada se cancela mientras tanto.

    Un POST síncrono no se puede interrumpir desde fuera. Por eso, con un token activo, va en un
    hilo propio y quien llama espera a lo primero que pase: la respuesta o la cancelación. Si es la
    cancelación, lanza `CallCancelled` en el acto: el turno y la plaza se sueltan ya, y el envío
    abandonado termina solo (su respuesta se descarta). Sin token, `fn()` tal cual.
    """
    token = _CURRENT.get()
    if token is None:
        return fn()
    token.check()
    box: dict[str, Any] = {}
    wake = threading.Event()
    context = contextvars.copy_context()
    # `questions.ask` (la pregunta de arrancar el backend, dentro del envío) salta al bucle de
    # eventos con `anyio.from_thread.run`, que solo funciona en un hilo de anyio: lee el token del
    # bucle de un `threading.local`. El hilo nuevo hereda el del hilo de la tool.
    loop_token = getattr(_anyio_threadlocals, "current_token", None)

    def run() -> None:
        if loop_token is not None:
            _anyio_threadlocals.current_token = loop_token
        try:
            box["value"] = context.run(fn)
        except Exception as exc:  # se relanza en el hilo que espera
            box["error"] = exc
        finally:
            box["done"] = True
            wake.set()

    remove = token.on_cancel(wake.set)
    try:
        threading.Thread(target=run, name="local-delegate-backend-call", daemon=True).start()
        wake.wait()
    finally:
        remove()
    # Cancelada, aunque el envío ya haya vuelto: si fue el corte de la conexión lo que lo hizo
    # volver, su resultado es un error de transporte que no hay que tomar por respuesta.
    token.check()
    if "error" in box:
        raise box["error"]
    if "value" not in box:
        # El envío murió con algo que no es `Exception` (`SystemExit`…): no hay resultado.
        raise RuntimeError
    return box["value"]


def _cancel_requested(ctx: Any) -> bool:
    """¿Llegó `notifications/cancelled` para esta petición? Solo para el motivo del registro.

    El SDK no lo expone en el contexto del middleware; lo lleva el canal de la petición. Si un SDK
    futuro lo mueve, la cancelación sigue funcionando y el motivo queda en `aborted`.
    """
    try:
        outbound = getattr(ctx.session, "_request_outbound", None)
        event = getattr(outbound, "cancel_requested", None)
        return bool(event is not None and event.is_set())
    except Exception:
        return False


def _disconnect_event(ctx: Any) -> anyio.Event | None:
    request = getattr(ctx, "request", None)
    scope = getattr(request, "scope", None)
    if isinstance(scope, Mapping):
        event = scope.get(DISCONNECT_KEY)
        if isinstance(event, anyio.Event):
            return event
    return None


async def _report_progress(ctx: Any, progress: float, message: str) -> None:
    """One `notifications/progress` for this request (issue #479); a no-op without a token.

    The SDK keeps the request's `progressToken` in the session's per-request channel and drops
    the notification when the caller did not ask for progress. It never raises here: a heartbeat
    that fails must not stop the call.
    """
    session = getattr(ctx, "session", None)
    report = getattr(session, "report_progress", None)
    if report is None:
        return
    try:
        await report(progress, None, message)
    except Exception:
        pass


def middleware(
    on_cancelled: Callable[[Token], None],
    on_failed: Callable[[Token], None] | None = None,
    deadline_s: Callable[[], float] | None = None,
    progress_interval_s: Callable[[], float] | None = None,
) -> Callable[..., Any]:
    """El middleware del SDK que da a cada `tools/call` su token y lo cancela cuando toca.

    `on_cancelled(token)` se llama al final si la llamada llegó a pararse en un punto de parada:
    es quien la apunta en el registro de uso como cancelada.

    Issue #476: `on_failed(token)` is called instead when an operation that had started ended with
    an exception before writing its event (`token.failure`): a saturated queue or an unexpected
    error. And `deadline_s()`, read per call, is the daemon's own budget: past it the call is
    cancelled with `REASON_DEADLINE`, because a client that gives up does not always say so.

    Issue #479: every `progress_interval_s()` seconds (`0`: never) a live call sends
    `notifications/progress` with its phase (`Token.progress_message`). The tool runs in a thread,
    so the heartbeat is a task here, on the event loop, for as long as the call lives. It is what
    keeps a queued or long call from being cut by the client's idle timeout (Claude Code: 300 s).
    """

    async def cancel_abandoned_calls(ctx: Any, call_next: Any) -> Any:
        if getattr(ctx, "method", None) != "tools/call":
            return await call_next(ctx)
        params = ctx.params if isinstance(ctx.params, Mapping) else {}
        name = params.get("name")
        token = Token(name if isinstance(name, str) else None)
        token.deadline_s = max(0.0, float(deadline_s())) if deadline_s is not None else 0.0
        _CURRENT.set(token)
        finished = False
        disconnected = _disconnect_event(ctx)

        async def watch() -> None:
            try:
                if disconnected is None:
                    await anyio.sleep_forever()
                await disconnected.wait()
                if not finished:
                    token.cancel(REASON_DISCONNECT)
            except anyio.get_cancelled_exc_class():
                # Este vigilante vive en el ámbito del handler: si alguien lo cancela desde fuera
                # (aviso de cancelación, sesión cerrada), la llamada se acabó para el cliente.
                if not finished:
                    reason = REASON_NOTIFICATION if _cancel_requested(ctx) else REASON_ABORTED
                    token.cancel(reason)
                raise

        async def expire() -> None:
            await anyio.sleep(token.deadline_s)
            if not finished:
                token.cancel(REASON_DEADLINE)

        interval = 0.0
        if progress_interval_s is not None:
            try:
                interval = max(0.0, float(progress_interval_s()))
            except Exception:
                interval = 0.0

        async def beat() -> None:
            sent = 0
            while True:
                await anyio.sleep(interval)
                if finished or token.cancelled:
                    return
                sent += 1
                await _report_progress(ctx, sent, token.progress_message())

        result: Any = None
        try:
            async with anyio.create_task_group() as group:
                group.start_soon(watch)
                if token.deadline_s > 0:
                    group.start_soon(expire)
                if interval > 0:
                    group.start_soon(beat)
                try:
                    result = await call_next(ctx)
                finally:
                    finished = True
                    group.cancel_scope.cancel()
        finally:
            try:
                if token.observed:
                    on_cancelled(token)
                elif token.failure is not None and on_failed is not None:
                    on_failed(token)
            except Exception:
                pass  # apuntar es best-effort; nunca cambia lo que vuelve al cliente
        return result

    return cancel_abandoned_calls


class DisconnectWatcher:
    """Middleware ASGI: deja en el `scope` un evento que se activa si el cliente corta la petición.

    En el transporte con sesión el SDK no cancela el handler cuando se cae la conexión de la
    respuesta (el cliente debería mandar `notifications/cancelled`); un puente matado no manda
    nada. El evento lo mira el middleware de `middleware`.
    """

    def __init__(self, app: Callable[..., Any]) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        event = anyio.Event()
        scope[DISCONNECT_KEY] = event

        async def receive_watching() -> Any:
            message = await receive()
            if message.get("type") == "http.disconnect":
                event.set()
            return message

        await self.app(scope, receive_watching, send)
