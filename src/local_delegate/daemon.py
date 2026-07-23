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
import time
from pathlib import Path

import httpx
import uvicorn
from filelock import FileLock, Timeout
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from . import autostart, config, server
from .web import metrics

MCP_PATH = "/mcp"
DAEMON_STATUS_PATH = "/api/daemon"


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
        with httpx.Client(timeout=timeout) as client:
            response = client.get(f"http://{host}:{port}{DAEMON_STATUS_PATH}")
            response.raise_for_status()
            data = response.json()
        if data.get("service") == "local-delegate" and data.get("mode") == "daemon":
            return data
    except (httpx.HTTPError, ValueError, TypeError):
        pass
    return None


def build_app(host: str | None = None, port: int | None = None) -> Starlette:
    """Construye el ASGI combinado preservando el lifespan de FastMCP."""
    host = host or config.WEB_HOST
    port = port or config.WEB_PORT

    server.mcp.settings.streamable_http_path = MCP_PATH
    mcp_app = server.mcp.streamable_http_app()

    async def daemon_status(_request: Request) -> JSONResponse:
        return JSONResponse(_daemon_payload(host, port))

    # Las rutas exactas deben quedar antes del mount raíz del dashboard.
    mcp_app.routes.insert(0, Route(DAEMON_STATUS_PATH, daemon_status, methods=["GET"]))
    mcp_app.routes.append(Mount("/", app=metrics.app))
    return mcp_app


def serve(host: str | None = None, port: int | None = None, log_level: str = "warning") -> int:
    """Sirve MCP+dashboard en primer plano; es idempotente por usuario/puerto."""
    host = host or config.WEB_HOST
    port = port or config.WEB_PORT
    lock = FileLock(str(_lock_path()))

    try:
        lock.acquire(timeout=0)
    except Timeout:
        current = query_daemon(host, port)
        if current:
            print(f"local-delegate daemon ya está activo (pid={current['pid']})")
            print(current["mcp_url"])
            return 0
        print(f"local-delegate: lock ocupado pero no responde un daemon en {host}:{port}")
        return 1

    try:
        if not _port_available(host, port):
            current = query_daemon(host, port)
            if current:
                print(f"local-delegate daemon ya está activo (pid={current['pid']})")
                return 0
            print(f"local-delegate: {host}:{port} está ocupado por otro proceso")
            return 1

        if config.AUTOSTART:
            autostart.ensure_backend(wait=0)

        payload = _daemon_payload(host, port)
        payload["started_at"] = int(time.time())
        _write_state(payload)
        print(f"local-delegate daemon -> {payload['mcp_url']}")
        print(f"dashboard -> {payload['dashboard_url']}")

        app = build_app(host, port)
        uvicorn_config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level=log_level,
            access_log=False,
        )
        uvicorn_server = uvicorn.Server(uvicorn_config)
        try:
            uvicorn_server.run()
        except KeyboardInterrupt:
            # Algunos runners (incluido uvicorn sobre asyncio en Windows) vuelven a
            # propagar Ctrl+C después de cerrar limpiamente el lifespan.
            return 0
        return 0 if uvicorn_server.started else 1
    finally:
        _remove_own_state()
        lock.release()
