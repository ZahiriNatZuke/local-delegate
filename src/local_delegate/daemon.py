"""Daemon HTTP singleton de local-delegate.

Sirve el transporte MCP Streamable HTTP y el dashboard de métricas en un único
proceso persistente. Los clientes MCP se conectan a ``/mcp`` y el navegador usa
``/``. Un ``FileLock`` por usuario evita que dos clientes o tareas programadas
levanten daemons competidores.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path

import httpx2
import uvicorn
from filelock import FileLock, Timeout
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from . import autostart, config, server
from .web import auth, metrics

MCP_PATH = "/mcp"
DAEMON_STATUS_PATH = "/api/daemon"
BACKEND_STATUS_PATH = "/api/backend"
_DEVNULL_STREAMS: list[object] = []


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


def build_app(host: str | None = None, port: int | None = None) -> Starlette | auth.TokenPuerto:
    """Construye el ASGI combinado preservando el lifespan del server MCP.

    Devuelve la app envuelta cuando hay token configurado. El tipo de retorno lo dice en vez de
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
    mcp_app = server.mcp.streamable_http_app(streamable_http_path=MCP_PATH, host=host)

    async def daemon_status(_request: Request) -> JSONResponse:
        return JSONResponse(_daemon_payload(host, port))

    # Las rutas exactas deben quedar antes del mount raíz del dashboard.
    mcp_app.routes.insert(0, Route(DAEMON_STATUS_PATH, daemon_status, methods=["GET"]))
    mcp_app.routes.append(Mount("/", app=metrics.app))

    # El token se exige envolviendo la raíz, o sea DESPUÉS de montar el dashboard: así una ruta
    # nueva queda protegida por existir, no por acordarse de protegerla. Sin token configurado
    # `proteger` devuelve la misma app y aquí no cambia nada.
    return auth.proteger(mcp_app, config.WEB_TOKEN, config.WEB_SESSION_SECONDS)


def daemon_registrado() -> dict | None:
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
        datos = json.loads(_state_path().read_text(encoding="utf-8"))
        registrado_host, registrado_port = datos["host"], int(datos["port"])
    except (OSError, ValueError, TypeError, KeyError):
        return None
    return query_daemon(registrado_host, registrado_port)


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
    lock = FileLock(str(_lock_path()))

    try:
        lock.acquire(timeout=0)
    except Timeout:
        current = query_daemon(host, port)
        if current:
            _console_print(f"local-delegate daemon ya está activo (pid={current['pid']})")
            _console_print(current["mcp_url"])
            return 0
        otro = daemon_registrado()
        if otro:
            _console_print(
                f"local-delegate: ya hay un daemon de este usuario en "
                f"{otro['host']}:{otro['port']} (pid={otro['pid']}), y el lock es uno por usuario. "
                f"No se puede levantar otro en el puerto {port}."
            )
            _console_print(otro["mcp_url"])
            return 1
        _console_print(
            f"local-delegate: lock ocupado y no responde ningún daemon nuestro "
            f"(ni en {host}:{port} ni donde dice {_state_path()})"
        )
        return 1

    try:
        if not _port_available(host, port):
            current = query_daemon(host, port)
            if current:
                _console_print(f"local-delegate daemon ya está activo (pid={current['pid']})")
                return 0
            _console_print(f"local-delegate: {host}:{port} está ocupado por otro proceso")
            return 1

        if config.AUTOSTART:
            autostart.ensure_backend(wait=0)

        payload = _daemon_payload(host, port)
        payload["started_at"] = int(time.time())
        _write_state(payload)
        _console_print(f"local-delegate daemon -> {payload['mcp_url']}")
        _console_print(f"dashboard -> {payload['dashboard_url']}")

        app = build_app(host, port)
        uvicorn_config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level=log_level,
            access_log=False,
        )
        uvicorn_server = uvicorn.Server(uvicorn_config)
        # Ctrl+Break entra por `SIGBREAK`, que uvicorn también captura y también vuelve a lanzar
        # sobre el handler original — solo que ahí el original era `SIG_DFL` y mataba el proceso
        # con código 3 a mitad del apagado. Igualarlo a Ctrl+C hace que caiga en el `except` de
        # abajo, que es el camino ya probado. El porqué completo, en `server.preparar_ctrl_break`.
        server.preparar_ctrl_break()
        try:
            uvicorn_server.run()
        except KeyboardInterrupt:
            # Algunos runners (incluido uvicorn sobre asyncio en Windows) vuelven a
            # propagar Ctrl+C después de cerrar limpiamente el lifespan. Y con Ctrl+Break es
            # exactamente lo mismo: `capture_signals` re-emite la señal capturada al salir.
            return 0
        return 0 if uvicorn_server.started else 1
    finally:
        _remove_own_state()
        lock.release()
