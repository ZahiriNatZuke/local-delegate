"""Daemon HTTP singleton de local-delegate.

Sirve el transporte MCP Streamable HTTP y el dashboard de métricas en un único
proceso persistente. Los clientes MCP se conectan a ``/mcp`` y el navegador usa
``/``. Un ``FileLock`` por usuario evita que dos clientes o tareas programadas
levanten daemons competidores.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import logging.handlers
import os
import signal
import socket
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx2
import uvicorn
from filelock import FileLock, Timeout
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from . import autostart, cancellation, config, i18n, server, token_source, turn_leases
from .web import auth, host_guard, metrics, turn_api

MCP_PATH = "/mcp"
DAEMON_STATUS_PATH = "/api/daemon"
BACKEND_STATUS_PATH = "/api/backend"
_DEVNULL_STREAMS: list[object] = []

# Issue #576: the daemon's own trace. Under `pythonw` there is no console, so without a file the
# reason a daemon stopped serving is lost; bounded so a looping error cannot fill the disk.
ERROR_LOG_NAME = "daemon-errors.log"
_ERROR_LOG_BYTES = 256 * 1024
#: Exit code of a daemon whose listening socket died under it (#576). Not 0, so whoever launched it
#: (the scheduled task, a client) can tell it apart from a clean stop and start a new one. 75 is
#: `EX_TEMPFAIL` («try again later»); 3 would read as an `abort()` on Windows.
EXIT_LISTENER_DIED = 75
#: How often uvicorn calls the listener watch (`timeout_notify`); uvicorn checks it every second.
_LISTENER_CHECK_SECONDS = 1
#: Bound on the graceful shutdown. Without it uvicorn closes the listener first and then waits
#: forever for open connections — and a client's MCP stream never closes on its own (#576).
_GRACEFUL_SHUTDOWN_SECONDS = 10
#: A registered daemon younger than this may still be binding its port: never relieved.
_RELIEF_GRACE_SECONDS = 60
_RELIEF_LOCK_WAIT_SECONDS = 15.0
_log = logging.getLogger("local_delegate.daemon")


def _ensure_standard_streams() -> None:
    """Da streams válidos a librerías de consola cuando se ejecuta con ``pythonw``."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            stream = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 - vive con el daemon
            _DEVNULL_STREAMS.append(stream)
            setattr(sys, name, stream)


def _console_print(message: str) -> None:
    """Escribe solo cuando existe consola (``pythonw.exe`` no define stdout)."""
    if sys.stdout is not None:
        print(message)


def _lock_path() -> Path:
    return config.LOG_DIR / "daemon.lock"


def _state_path() -> Path:
    return config.LOG_DIR / "daemon.json"


def _daemon_payload(host: str, port: int) -> dict:
    base = f"http://{host}:{port}"
    return {
        "service": "local-delegate",
        "mode": "daemon",
        "version": server._get_version(),
        "pid": os.getpid(),
        "host": host,
        "port": port,
        "mcp_url": f"{base}{MCP_PATH}",
        "dashboard_url": f"{base}/",
        # Concurrency PC+Mac, lot 3: this run of the daemon; a remote client tells a restart by it.
        "daemon_id": turn_leases.DAEMON_ID,
    }


def _write_state(payload: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _remove_own_state() -> None:
    path = _state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("pid") == os.getpid():
            path.unlink(missing_ok=True)
    except (OSError, ValueError, TypeError):
        # Limpieza de apagado: si el archivo de estado no existe, está corrupto o lo escribió otra
        # cosa, no hay nada nuestro que borrar. Fallar aquí solo ensuciaría la salida del daemon.
        pass


def _error_log_path() -> Path:
    return config.LOG_DIR / ERROR_LOG_NAME


#: Loggers whose errors go to the daemon's file: ours, asyncio (where the event loop reports an
#: `accept` that failed and took the listener with it) and uvicorn's.
_TRACED_LOGGERS = ("local_delegate.daemon", "asyncio", "uvicorn.error")


@contextlib.contextmanager
def _error_log() -> Iterator[logging.Handler | None]:
    """Send warnings and errors of the daemon to a size-bounded file while it runs (#576).

    The handler is removed and closed on the way out: `serve` runs more than once in a test process,
    and a handler left behind would keep a file open in a temporary folder. A file that cannot be
    opened is not a reason not to serve, so it yields ``None`` instead of failing.
    """
    try:
        path = _error_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=_ERROR_LOG_BYTES, backupCount=1, encoding="utf-8", delay=True
        )
    except OSError:
        yield None
        return
    handler.setLevel(logging.WARNING)
    handler.addFilter(_not_a_tolerated_reset)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s pid=%(process)d: %(message)s")
    )
    try:
        _attach_error_log(handler)
        yield handler
    finally:
        for name in _TRACED_LOGGERS:
            logging.getLogger(name).removeHandler(handler)
        handler.close()


def _not_a_tolerated_reset(record: logging.LogRecord) -> bool:
    """Drop the record asyncio writes for each client reset that the tolerant accept absorbed.

    The stdlib leaves one «Task exception was never retrieved» per failed `accept` behind; under a
    burst of resets they would rotate every useful line out of the bounded file.
    """
    exc = record.exc_info[1] if record.exc_info else None
    return not (
        record.name == "asyncio"
        and isinstance(exc, OSError)
        and getattr(exc, "winerror", None) in _ACCEPT_RESET_WINERRORS
        and "never retrieved" in record.getMessage()
    )


def _attach_error_log(handler: logging.Handler | None) -> None:
    """Idempotent: uvicorn's `Config` replaces the handlers of its loggers, so it is re-attached."""
    if handler is None:
        return
    for name in _TRACED_LOGGERS:
        logger = logging.getLogger(name)
        if handler not in logger.handlers:
            logger.addHandler(handler)


def _listener_closed(uvicorn_server: object) -> bool:
    """True if a listening socket of the server is closed while the server still runs.

    Why it can happen (#576): in the Windows `ProactorEventLoop` any `OSError` from `accept`
    —`WinError 64` when a client resets its connection while it waits in the backlog— makes asyncio
    close the listening socket for good and only report it to the loop's exception handler. The
    loop keeps running, so uvicorn never learns that nobody can connect any more.
    """
    for listener in getattr(uvicorn_server, "servers", None) or ():
        for sock in getattr(listener, "sockets", None) or ():
            if sock.fileno() == -1:
                return True
    return False


#: Windows errors of an `accept` whose client went away before the loop took it (#576):
#: `ERROR_NETNAME_DELETED`, `ERROR_CONNECTION_ABORTED`, `WSAECONNABORTED`, `WSAECONNRESET`.
_ACCEPT_RESET_WINERRORS = frozenset({64, 1236, 10053, 10054})
#: Failed accepts in a row, other than client resets, before the listener is taken for broken.
_ACCEPT_RETRIES = 50
#: Wait before retrying such an error: it doubles from the first value up to the second, so the
#: 50 retries take about 45 s instead of spinning through them in microseconds.
_ACCEPT_BACKOFF_S = (0.01, 1.0)


def _tolerate_accept_resets(loop: asyncio.AbstractEventLoop) -> bool:
    """Make the `accept` of a Windows proactor loop retry when the client already reset (#576).

    The root of #576: in the `ProactorEventLoop` any `OSError` from `accept` closes the listening
    socket for good. A client that resets its connection before it is accepted is enough, and
    remote-turn clients that give up over the network do exactly that: forty of them took a test
    daemon's listener down in one second. That error concerns the client that left, not the
    listener, so the accept is posted again and the listener keeps serving everybody else. Any
    `OSError` is retried while the listener is open (the reset codes vary with the Windows and
    Python versions); errors other than a client reset, up to `_ACCEPT_RETRIES` in a row.

    Only the proactor (Windows) has `_proactor`; on any other loop this does nothing. Idempotent.
    """
    proactor = getattr(loop, "_proactor", None)
    original = getattr(proactor, "accept", None)
    if original is None or getattr(original, "_ld_tolerant", False):
        return False

    def accept(listener: socket.socket) -> asyncio.Future:
        outer = loop.create_future()
        current: list[asyncio.Future] = []
        failures = [0]

        def attempt() -> None:
            if outer.done():
                return
            try:
                # `AcceptEx` can also fail right here, synchronously; unhandled, that exception
                # would end in this callback and leave `outer` pending: no accept ever again.
                inner = original(listener)
            except OSError as exc:
                failed(exc)
                return
            current[:] = [inner]
            inner.add_done_callback(settle)

        def failed(exc: OSError) -> None:
            # A client reset is always retried: each one takes a real client, so it cannot spin.
            # Any other error counts towards the cap.
            reset = getattr(exc, "winerror", None) in _ACCEPT_RESET_WINERRORS
            if not reset:
                failures[0] += 1
            if listener.fileno() != -1 and failures[0] <= _ACCEPT_RETRIES:
                if reset:
                    loop.call_soon(attempt)
                else:
                    first, top = _ACCEPT_BACKOFF_S
                    loop.call_later(min(top, first * 2 ** (failures[0] - 1)), attempt)
            else:
                # A listener that fails this many times in a row is broken for real: let asyncio
                # close it, and the listener watch stop the daemon.
                outer.set_exception(exc)

        def settle(inner: asyncio.Future) -> None:
            if outer.done():
                return
            if inner.cancelled():
                outer.cancel()
                return
            exc = inner.exception()
            if isinstance(exc, OSError):
                failed(exc)
            elif exc is not None:
                outer.set_exception(exc)
            else:
                outer.set_result(inner.result())

        def cancel_inner(done: asyncio.Future) -> None:
            # The loop stops serving by cancelling the future it was given: pass it on.
            if done.cancelled() and current:
                current[0].cancel()

        outer.add_done_callback(cancel_inner)
        attempt()
        return outer

    accept._ld_tolerant = True  # type: ignore[attr-defined]
    proactor.accept = accept  # type: ignore[union-attr]
    return True


class _AcceptResetGuard:
    """ASGI wrapper that installs :func:`_tolerate_accept_resets` on the loop that serves.

    It goes in at the lifespan, which uvicorn runs **before** it opens the listening socket, so the
    first `accept` is already the tolerant one. Through the app and not through a uvicorn loop
    factory, whose contract changed between the uvicorn versions the project accepts.
    """

    def __init__(self, app: object) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") == "lifespan":
            _tolerate_accept_resets(asyncio.get_running_loop())
        await self.app(scope, receive, send)  # type: ignore[operator]


class _ListenerWatch:
    """Uvicorn's `callback_notify`: stops the server when its listener is gone (#576).

    It goes through `uvicorn.Config` and not through a subclass of `uvicorn.Server` so the server
    stays the one `uvicorn.Server` builds — the one the tests replace.
    """

    def __init__(self) -> None:
        self.server: object | None = None
        self.tripped = False

    async def __call__(self) -> None:
        server = self.server
        if self.tripped or server is None or not _listener_closed(server):
            return
        self.tripped = True
        _log.error(
            "listening socket closed under a running daemon; stopping with exit code %d",
            EXIT_LISTENER_DIED,
        )
        server.should_exit = True  # type: ignore[attr-defined]


def _probe_host(host: str) -> str:
    """Where to connect to reach a daemon listening on ``host`` (a wildcard is not an address)."""
    return {"0.0.0.0": "127.0.0.1", "::": "::1", "": "127.0.0.1"}.get(host, host)


def _refuses_connections(host: str, port: int, attempts: int = 3, pause: float = 0.5) -> bool:
    """True only if every attempt to connect is **refused**: nobody listens on that port.

    A refusal is the one answer that cannot come from a daemon that is merely slow: the kernel
    accepts the TCP connection into the backlog even if the process never gets to it. A timeout or
    any other error means «cannot tell», and «cannot tell» never relieves anybody. Windows retries
    a refused SYN for about two seconds, hence the timeout.

    Known limit: on Windows a **full** `listen` backlog also answers with a refusal. A daemon alive
    but with its event loop blocked for the whole probe (three attempts, several seconds) and its
    backlog full could be taken for dead and relieved. It needs a loop blocked for that long, which
    is itself a daemon that does not serve; the other conditions (age, creation time, stable
    `daemon.json`) still apply.
    """
    for attempt in range(attempts):
        try:
            with socket.create_connection((_probe_host(host), port), timeout=4.0):
                return False
        except ConnectionRefusedError:
            pass
        except OSError:
            return False
        if attempt + 1 < attempts:
            time.sleep(pause)
    return True


def _read_registration() -> dict | None:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
        return {
            "pid": int(data["pid"]),
            "host": str(data["host"]),
            "port": int(data["port"]),
            "started_at": int(data.get("started_at") or 0),
        }
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _process_started_at(pid: int) -> float | None:
    """When the process ``pid`` was created (epoch seconds), or ``None`` if it cannot be told.

    Only Windows (where #576 happens) and Linux answer; anywhere else ``None`` means «do not
    relieve», which is the safe side.
    """
    try:
        if sys.platform == "win32":
            import ctypes
            import ctypes.wintypes

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return None
            try:
                times = [ctypes.wintypes.FILETIME() for _ in range(4)]
                if not k32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                    return None
            finally:
                k32.CloseHandle(handle)
            ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            return ticks / 10_000_000 - 11_644_473_600  # FILETIME epoch is 1601-01-01
        if sys.platform.startswith("linux"):
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            boot = next(
                float(line.split()[1])
                for line in Path("/proc/stat").read_text().splitlines()
                if line.startswith("btime ")
            )
            return boot + int(fields[19]) / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration, AttributeError):
        return None
    return None


def _is_the_registered_process(data: dict) -> bool:
    """True if the pid of ``data`` is still the process that registered, not one that reused it.

    A daemon stopped without its `finally` (`schtasks /End`, `TerminateProcess`, a shutdown) leaves
    `daemon.json` behind, and Windows hands its pid out again. The daemon was created before it
    wrote `started_at`; a process that reused the pid, only after. Unknown (macOS) is «no».
    """
    created = _process_started_at(data["pid"])
    return created is not None and created <= data["started_at"] + 1


def registered_process() -> dict | None:
    """The registration in ``daemon.json`` if its process is still alive, without asking its port.

    For `doctor`: when nothing listens on the daemon's port, an alive registered process is the
    state of #576 (a daemon that lost its listener) and not «no daemon at all». Only if that pid is
    still the daemon (see :func:`_is_the_registered_process`): otherwise `doctor` would blame some
    other process that got the pid.
    """
    data = _read_registration()
    if data is None or not server._pid_alive(data["pid"]):
        return None
    if not _is_the_registered_process(data):
        return None
    return data


def stale_registration(now: float | None = None) -> dict | None:
    """The registered daemon if it is alive but its listener is dead (#576); ``None`` otherwise.

    Every condition is there to never relieve a daemon that works: the process is alive and is not
    this one, it started long enough ago to have bound its port, its port refuses connections
    (see :func:`_refuses_connections`) and ``daemon.json`` still says the same after the probes —
    a daemon that started meanwhile rewrites it.
    """
    first = _read_registration()
    if first is None or first["pid"] == os.getpid() or not server._pid_alive(first["pid"]):
        return None
    if (now if now is not None else time.time()) - first["started_at"] < _RELIEF_GRACE_SECONDS:
        return None
    # The pid must still be the daemon that wrote the file, not a process that reused the pid after
    # it died: the daemon was created before it wrote `started_at`, a reused pid only after.
    if not _is_the_registered_process(first):
        return None
    if not _refuses_connections(first["host"], first["port"]):
        return None
    if _read_registration() != first:
        return None
    return first


def _relieve(stale: dict, lock: FileLock) -> bool:
    """Stop a daemon whose listener is dead and take its lock. True if the lock is now ours."""
    pid = stale["pid"]
    _log.error(
        "relieving daemon pid=%d: alive but nothing listens on %s:%d",
        pid,
        stale["host"],
        stale["port"],
    )
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        _log.error("could not stop daemon pid=%d: %s", pid, exc)
        return False
    try:
        lock.acquire(timeout=_RELIEF_LOCK_WAIT_SECONDS)
        return True
    except Timeout:
        pass
    # SIGTERM is a request outside Windows (there `os.kill` is `TerminateProcess`), and an older
    # daemon could wait without a bound for its connections to close: the request becomes an order.
    sigkill = getattr(signal, "SIGKILL", None)
    # Fifteen seconds later the pid may belong to someone else: kill it only if it is still
    # the process that registered.
    if sigkill is not None and _is_the_registered_process(stale):
        with contextlib.suppress(OSError):
            os.kill(pid, sigkill)
        try:
            lock.acquire(timeout=5.0)
            return True
        except Timeout:
            pass
    _log.error("daemon pid=%d still holds the lock after being stopped", pid)
    return False


def _port_available(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            return sock.connect_ex((host, port)) != 0
    except OSError:
        return False


def query_daemon(host: str, port: int, timeout: float = 1.0) -> dict | None:
    """Devuelve el estado del daemon si el puerto pertenece a local-delegate."""
    try:
        with httpx2.Client(timeout=timeout) as client:
            response = client.get(
                f"http://{host}:{port}{DAEMON_STATUS_PATH}", headers=config.web_auth_headers()
            )
            response.raise_for_status()
            data = response.json()
        if data.get("service") == "local-delegate" and data.get("mode") == "daemon":
            return data
    except (httpx2.HTTPError, ValueError, TypeError):
        # La pregunta que responde esta función es «¿este puerto es un daemon nuestro?», y
        # cualquier fallo significa que no lo es: nadie escucha, responde otra cosa, no habla
        # HTTP o devuelve algo que no es JSON. Todas esas respuestas son el mismo `None`, y
        # distinguirlas no cambiaría lo que hace quien llama.
        pass
    return None


def daemon_requires_token(host: str, port: int, timeout: float = 1.0) -> bool | None:
    """¿Ese puerto lo sirve un daemon nuestro que exige token? ``None`` si no se pudo saber.

    Función aparte de :func:`query_daemon`, y no un flag suyo, por lo mismo que el probe del
    backend separa «¿está sano?» de «¿exige credencial?»: son dos preguntas cuya respuesta
    depende de **quién** las hace, y un booleano cuyo significado cambiara con el entorno de quien
    pregunta sería justo el dato que engaña. Esta pregunta se hace **sin** cabecera de
    autorización, que es la única forma de ver lo que encuentra quien no lleva el token.

    El ``realm`` es lo que evita el falso positivo: un 401 a secas podría venir de cualquier cosa
    escuchando en ese puerto, y decir «es tu daemon, te falta el token» sobre un servicio ajeno
    sería exactamente el diagnóstico inventado que esta comprobación existe para no dar.
    """
    try:
        with httpx2.Client(timeout=timeout) as client:
            response = client.get(f"http://{host}:{port}{DAEMON_STATUS_PATH}")
    except httpx2.HTTPError:
        return None
    if response.status_code != 401:
        return False
    return "local-delegate" in response.headers.get("www-authenticate", "")


def daemon_accepts_token(host: str, port: int, token: str, timeout: float = 1.0) -> bool | None:
    """¿Entra ESTE token al puerto del daemon? ``None`` si la respuesta no permite decirlo.

    Hermana de :func:`daemon_requires_token`, y aparte por lo mismo: aquella pregunta sin cabecera
    y esta con un token que no sale del entorno de quien pregunta, sino de la configuración de un
    cliente. Existe para Claude Desktop, que lleva el token escrito literal y no se reescribe al
    rotarlo: saber que el puerto exige token no dice si el que lleva ese fichero sigue valiendo.
    """
    try:
        with httpx2.Client(timeout=timeout) as client:
            response = client.get(
                f"http://{host}:{port}{DAEMON_STATUS_PATH}",
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx2.HTTPError:
        return None
    if response.status_code == 401:
        return False
    return True if 200 <= response.status_code < 300 else None


def query_backend(host: str, port: int, timeout: float = 1.0) -> dict | None:
    """Lo que el daemon ve del backend de inferencia, o ``None`` si no se le pudo preguntar.

    Existe porque el diagnóstico y el daemon **no tienen las mismas credenciales**: la clave del
    backend se lee del entorno del proceso, y el daemon la recibe de su lanzador mientras que un
    `local-delegate doctor` escrito en una consola cualquiera no la tiene. Probando el backend por
    su cuenta, el diagnóstico se llevaba un 401 y no podía decir si estaba sano — sobre una
    máquina en la que el daemon lo estaba viendo perfectamente.

    Misma forma que :func:`query_daemon` —dict o ``None``— y por el mismo motivo: cualquier fallo
    significa «no se pudo preguntar», y quien llama hace lo mismo en todos esos casos (probar por
    su cuenta).
    """
    try:
        with httpx2.Client(timeout=timeout) as client:
            response = client.get(
                f"http://{host}:{port}{BACKEND_STATUS_PATH}", headers=config.web_auth_headers()
            )
            response.raise_for_status()
            data = response.json()
    except (httpx2.HTTPError, ValueError, TypeError):
        return None
    # `available` es el campo que responde la pregunta; sin él, la respuesta no sirve y es más
    # honesto decir «no se pudo preguntar» que interpretar su ausencia como una caída.
    return data if isinstance(data, dict) and "available" in data else None


def build_app(
    host: str | None = None, port: int | None = None
) -> Starlette | auth.PortToken | host_guard.HostGuard:
    """Construye el ASGI combinado preservando el lifespan del server MCP.

    Devuelve la app envuelta por la guarda del `Host` (salvo escucha en todas las interfaces) y por
    el token cuando hay uno configurado. El tipo de retorno lo dice en vez de
    esconderlo tras un alias: quien lo lea tiene que saber que el objeto servido no siempre es la
    Starlette del SDK.
    """
    host = host or config.WEB_HOST
    port = port or config.WEB_PORT

    # La ruta va como argumento: el SDK 2.x sacó los campos de transporte de `Settings`, así que
    # `settings.streamable_http_path` ya no existe.
    #
    # `host` no es decorativo: con un host de loopback el SDK activa **solo** la protección contra
    # DNS rebinding y rechaza con 421 cualquier petición cuyo header `Host` no sea
    # `127.0.0.1`/`localhost`/`[::1]`. Pasarle el host configurado es lo que hace lo correcto en los
    # dos casos: en el normal (loopback) la protección queda puesta gratis, y con
    # `LOCAL_DELEGATE_WEB_HOST=0.0.0.0` —publicar en la red local, que el proyecto permite— no se
    # activa y el daemon sigue respondiendo a quien llegue por la IP de la LAN. Sin esto, ese
    # segundo escenario se rompía en silencio al migrar.
    #
    # Desde `panel-host-check` los ajustes salen de `host_guard`, la misma lista que protege el
    # resto del puerto: así `LOCAL_DELEGATE_WEB_ALLOWED_HOSTS` abre `/mcp` y el panel a la vez, y
    # una interfaz concreta en `WEB_HOST` queda protegida también en `/mcp` (antes solo loopback).
    mcp_app = server.mcp.streamable_http_app(
        streamable_http_path=MCP_PATH,
        host=host,
        transport_security=host_guard.transport_security(host),
    )

    async def daemon_status(_request: Request) -> JSONResponse:
        return JSONResponse(_daemon_payload(host, port))

    # Las rutas exactas deben quedar antes del mount raíz del dashboard.
    mcp_app.routes.insert(0, Route(DAEMON_STATUS_PATH, daemon_status, methods=["GET"]))
    mcp_app.routes.append(Mount("/", app=metrics.app))
    # Una petición cuyo cliente corta la conexión cancela su llamada (llamadas abandonadas): el
    # middleware de `cancellation` necesita saber de la desconexión, y el SDK no se la cuenta.
    mcp_app.add_middleware(cancellation.DisconnectWatcher)

    # El token se exige envolviendo la raíz, o sea DESPUÉS de montar el dashboard: así una ruta
    # nueva queda protegida por existir, no por acordarse de protegerla. Sin token configurado
    # `protect` devuelve la misma app y aquí no cambia nada.
    #
    # La guarda del `Host` va por FUERA del token: un `Host` ajeno es un navegador engañado por DNS
    # rebinding, no un cliente sin credencial, y recibe 421 antes de llegar a pedirle nada. Cubre
    # también `/daemon/status` y el panel montado en `/`, que la protección del SDK no alcanza.
    port_token = token_source.daemon_token()
    # Concurrency PC+Mac, lot 3: only the daemon serves `/api/turn/*`, with the same port token as
    # its `PortToken` (a stdio process that wins the port answers 404 there).
    turn_api.enable(port_token)
    return host_guard.protect(auth.protect(mcp_app, port_token, config.WEB_SESSION_SECONDS), host)


def registered_daemon() -> dict | None:
    """El daemon que dejó escrito su estado, mirado **donde él dijo estar**.

    Existe por el ámbito del lock: es uno por usuario (`LOG_DIR/daemon.lock`), no uno por puerto.
    Así que cuando el lock está tomado y el puerto que se pidió no contesta, la pregunta correcta
    no es «¿hay un daemon en el puerto que pedí?» —esa ya se respondió que no— sino «¿dónde está
    el que tiene el lock?». `daemon.json` lo dice, y hasta ahora nadie lo leía en esa rama.

    Se le pregunta igualmente por HTTP en vez de fiarse del fichero: un `daemon.json` puede quedar
    huérfano si el proceso murió de mala manera, y anunciar un daemon muerto sería sustituir un
    diagnóstico incompleto por uno falso.
    """
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
        registered_host, registered_port = data["host"], int(data["port"])
    except (OSError, ValueError, TypeError, KeyError):
        return None
    return query_daemon(registered_host, registered_port)


def serve(host: str | None = None, port: int | None = None, log_level: str = "warning") -> int:
    """Sirve MCP+dashboard en primer plano; es idempotente **por usuario**.

    Por usuario y no por puerto, que es lo que decía antes esta línea: el lock es
    `LOG_DIR/daemon.lock`, uno solo, así que un segundo `serve` en otro puerto no arranca aunque
    ese puerto esté libre. Es la intención (un daemon por persona), pero el mensaje que se daba
    hablaba del puerto pedido y mandaba a buscar el daemon donde no estaba.
    """
    _ensure_standard_streams()
    host = host or config.WEB_HOST
    port = port or config.WEB_PORT
    with _error_log() as error_log:
        return _serve(host, port, log_level, error_log)


def _serve(host: str, port: int, log_level: str, error_log: logging.Handler | None) -> int:
    lock = FileLock(str(_lock_path()))

    try:
        lock.acquire(timeout=0)
    except Timeout:
        current = query_daemon(host, port)
        if current:
            _console_print(i18n.t("cli.daemon.already_running", pid=current["pid"]))
            _console_print(current["mcp_url"])
            return 0
        other = registered_daemon()
        if other:
            _console_print(
                i18n.t(
                    "cli.daemon.other_daemon",
                    host=other["host"],
                    port=other["port"],
                    pid=other["pid"],
                    wanted=port,
                )
            )
            _console_print(other["mcp_url"])
            return 1
        # #576: the lock holder is alive but its listener is dead, so it will never answer and
        # never let go of the lock. Relieving it is what lets the standard restart recover.
        stale = stale_registration()
        if stale is None or not _relieve(stale, lock):
            _console_print(
                i18n.t("cli.daemon.lock_busy", host=host, port=port, state=_state_path())
            )
            return 1
        _console_print(
            i18n.t("cli.daemon.relieved", pid=stale["pid"], host=stale["host"], port=stale["port"])
        )

    try:
        if not _port_available(host, port):
            current = query_daemon(host, port)
            if current:
                _console_print(i18n.t("cli.daemon.already_running", pid=current["pid"]))
                return 0
            _console_print(i18n.t("cli.daemon.port_busy", host=host, port=port))
            return 1

        if config.AUTOSTART:
            autostart.ensure_backend(wait=0)

        payload = _daemon_payload(host, port)
        payload["started_at"] = int(time.time())
        _write_state(payload)
        _console_print(f"local-delegate daemon -> {payload['mcp_url']}")
        _console_print(f"dashboard -> {payload['dashboard_url']}")

        # #576: a client that resets before being accepted must not take the listener down.
        app = _AcceptResetGuard(build_app(host, port))
        watch = _ListenerWatch()
        uvicorn_config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level=log_level,
            access_log=False,
            callback_notify=watch,
            timeout_notify=_LISTENER_CHECK_SECONDS,
            timeout_graceful_shutdown=_GRACEFUL_SHUTDOWN_SECONDS,
        )
        # The `Config` above reconfigured uvicorn's loggers and dropped the handler from them.
        _attach_error_log(error_log)
        uvicorn_server = uvicorn.Server(uvicorn_config)
        watch.server = uvicorn_server
        # Ctrl+Break entra por `SIGBREAK`, que uvicorn también captura y también vuelve a lanzar
        # sobre el handler original — solo que ahí el original era `SIG_DFL` y mataba el proceso
        # con código 3 a mitad del apagado. Igualarlo a Ctrl+C hace que caiga en el `except` de
        # abajo, que es el camino ya probado. El porqué completo, en `server.prepare_ctrl_break`.
        server.prepare_ctrl_break()
        try:
            uvicorn_server.run()
        except KeyboardInterrupt:
            # Algunos runners (incluido uvicorn sobre asyncio en Windows) vuelven a
            # propagar Ctrl+C después de cerrar limpiamente el lifespan. Y con Ctrl+Break es
            # exactamente lo mismo: `capture_signals` re-emite la señal capturada al salir.
            return 0
        except Exception:
            # Under `pythonw` the traceback would go nowhere: it goes to the file, then up as before.
            _log.exception("the HTTP server stopped with an exception")
            raise
        if watch.tripped:
            return EXIT_LISTENER_DIED
        return 0 if uvicorn_server.started else 1
    finally:
        _remove_own_state()
        lock.release()
