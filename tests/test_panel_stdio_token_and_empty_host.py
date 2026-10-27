"""SDD panel-stdio-token-and-empty-host.

Dos defectos vecinos de la revisión de seguridad del 2026-10-23:

- La web que levanta el MCP stdio (`metrics.run_in_thread`) servía todo el panel y `/api/*` sin
  token aunque `LOCAL_DELEGATE_WEB_TOKEN` estuviera puesta; ahora la envuelve el mismo
  `auth.protect` que el daemon.
- Una variable vacía no usaba el valor por defecto: `LOCAL_DELEGATE_WEB_HOST=""` dejaba el panel y
  el MCP escuchando en todas las interfaces y sin la guarda del `Host`.
"""

from __future__ import annotations

import base64
import importlib
import socket
import time

import httpx2
import pytest
from fastapi.testclient import TestClient

from local_delegate import config, daemon, install
from local_delegate.web import auth, host_guard, metrics

TOKEN = "stdio-port-token"
LOCAL = "http://127.0.0.1:19393"
EVIL = "evil.example:19393"
# Las rutas que la revisión encontró abiertas con el token puesto (`repro.py embedded`).
OPEN_BEFORE = (
    "/",
    "/api/events",
    "/api/stats",
    "/api/status",
    "/api/system",
    "/api/inflight",
    "/api/hooks",
)


@pytest.fixture
def _token(monkeypatch):
    monkeypatch.setattr(config, "WEB_TOKEN", TOKEN)
    monkeypatch.setattr(config, "WEB_ALLOWED_HOSTS", [])


def _stdio_app(monkeypatch):
    """La app ASGI que `run_in_thread` le pasa a uvicorn, sin abrir un puerto."""
    served = {}

    class _Config:
        def __init__(self, app, **kwargs):
            served["app"] = app

    class _Server:
        def __init__(self, cfg):
            self.install_signal_handlers = None

        def run(self):
            return None

    monkeypatch.setattr(metrics.uvicorn, "Config", _Config)
    monkeypatch.setattr(metrics.uvicorn, "Server", _Server)
    thread = metrics.run_in_thread(host="127.0.0.1", port=1)
    assert thread is not None
    thread.join(timeout=5)
    return served["app"]


# --- La web stdio exige el token ---------------------------------------------------------------


@pytest.mark.usefixtures("_token")
@pytest.mark.parametrize("path", OPEN_BEFORE)
def test_stdio_web_refuses_every_route_without_the_token(monkeypatch, path):
    with TestClient(_stdio_app(monkeypatch), base_url=LOCAL) as client:
        response = client.get(path)
    assert response.status_code == 401
    # El mismo `realm` que el daemon: es lo que deja a `doctor` decir «te falta el token».
    assert "local-delegate" in response.headers.get("www-authenticate", "")


@pytest.mark.usefixtures("_token")
def test_stdio_web_accepts_the_three_forms_of_the_token(monkeypatch):
    app = _stdio_app(monkeypatch)
    # Un cliente nuevo por forma: el `TestClient` guarda la cookie de sesión entre peticiones.
    with TestClient(app, base_url=LOCAL) as client:
        bearer = client.get("/api/status", headers={"Authorization": f"Bearer {TOKEN}"})
        assert bearer.status_code == 200
        wrong = client.get("/api/status", headers={"Authorization": f"Bearer {TOKEN}x"})
        assert wrong.status_code == 401
    with TestClient(app, base_url=LOCAL) as client:
        basic = base64.b64encode(f"anyone:{TOKEN}".encode()).decode()
        page = client.get("/", headers={"Authorization": f"Basic {basic}"})
        assert page.status_code == 200
        assert auth.COOKIE in page.headers.get("set-cookie", "")
    with TestClient(app, base_url=LOCAL) as client:
        client.cookies.set(auth.COOKIE, auth.create_session(TOKEN, 3600))
        assert client.get("/api/stats").status_code == 200


@pytest.mark.usefixtures("_token")
def test_stdio_web_keeps_the_host_guard_outside_the_token(monkeypatch):
    app = _stdio_app(monkeypatch)
    assert isinstance(app, host_guard.HostGuard)
    with TestClient(app, base_url=LOCAL) as client:
        headers = {"Host": EVIL, "Authorization": f"Bearer {TOKEN}"}
        assert client.get("/api/status", headers=headers).status_code == 421


def test_stdio_web_without_a_token_stays_open_as_before(monkeypatch):
    monkeypatch.setattr(config, "WEB_TOKEN", "")
    monkeypatch.setattr(config, "WEB_ALLOWED_HOSTS", [])
    with TestClient(_stdio_app(monkeypatch), base_url=LOCAL) as client:
        assert client.get("/api/status").status_code == 200


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.usefixtures("_token")
def test_real_stdio_web_lets_its_clients_in_with_the_token(monkeypatch):
    """El uso, no la pieza: un puerto de verdad y los clientes con las cabeceras que ya mandan."""
    servers = []
    real_server = metrics.uvicorn.Server

    class _Recorded(real_server):
        def __init__(self, cfg):
            super().__init__(cfg)
            servers.append(self)

    monkeypatch.setattr(metrics.uvicorn, "Server", _Recorded)
    port = _free_port()
    thread = metrics.run_in_thread(host="127.0.0.1", port=port)
    assert thread is not None
    try:
        deadline = time.monotonic() + 10
        while not servers[0].started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert servers[0].started
        base = f"http://127.0.0.1:{port}"
        # El CLI, `doctor` y el singleton del daemon: `config.web_auth_headers()`.
        with httpx2.Client(timeout=5) as client:
            assert client.get(f"{base}/api/status").status_code == 401
            internal = client.get(f"{base}/api/status", headers=config.web_auth_headers())
            assert internal.status_code == 200
            # El mod: `Authorization: Bearer <LOCAL_DELEGATE_WEB_TOKEN>` (`mod/common.js`).
            mod = client.get(f"{base}/api/hooks", headers={"Authorization": f"Bearer {TOKEN}"})
            assert mod.status_code == 200
        # `doctor` reconoce el puerto como nuestro y protegido, igual que con el daemon.
        assert daemon.daemon_requires_token("127.0.0.1", port) is True
    finally:
        servers[0].should_exit = True
        thread.join(timeout=10)
    assert not thread.is_alive()


# --- Variable vacía = variable no puesta --------------------------------------------------------


@pytest.fixture
def _reload_config(monkeypatch):
    names = []

    def _set(name: str, value: str) -> None:
        names.append(name)
        monkeypatch.setenv(name, value)
        importlib.reload(config)

    yield _set
    for name in names:
        monkeypatch.delenv(name, raising=False)
    importlib.reload(config)


@pytest.mark.parametrize("blank", ["", "   "])
@pytest.mark.parametrize(
    ("variable", "attribute", "default"),
    [
        ("LOCAL_DELEGATE_WEB_HOST", "WEB_HOST", "127.0.0.1"),
        ("LOCAL_DELEGATE_BASE_URL", "BASE_URL", "http://127.0.0.1:9292/v1"),
        ("LOCAL_DELEGATE_MODEL_MECHANICAL", "MODEL_MECHANICAL", "gemma3-4b"),
        ("LOCAL_DELEGATE_MODEL_LONG", "MODEL_LONG", "gemma4-26b-a4b"),
        ("LOCAL_DELEGATE_MODEL_CODE", "MODEL_CODE", "qwen36-35b-a3b"),
        ("LOCAL_DELEGATE_MODEL_VISION", "MODEL_VISION", "gemma4-12b"),
        ("LOCAL_DELEGATE_BACKEND_ORIGIN", "BACKEND_ORIGIN_OVERRIDE", "auto"),
    ],
)
def test_a_blank_variable_takes_the_default(_reload_config, variable, attribute, default, blank):
    _reload_config(variable, blank)
    assert getattr(config, attribute) == default


def test_a_blank_llamaswap_listen_takes_the_loopback_default(_reload_config):
    _reload_config("LLAMASWAP_LISTEN", "")
    assert config.llamaswap_listen() == "127.0.0.1:9292"


def test_a_blank_token_is_still_no_token(_reload_config):
    _reload_config("LOCAL_DELEGATE_WEB_TOKEN", "   ")
    assert config.WEB_TOKEN == ""


def test_a_real_value_is_kept(_reload_config):
    _reload_config("LOCAL_DELEGATE_WEB_HOST", "100.64.0.7")
    assert config.WEB_HOST == "100.64.0.7"


def test_a_blank_web_host_keeps_the_daemon_on_loopback_and_guarded(_reload_config, monkeypatch):
    """El uso: con la variable vacía, el daemon se monta en loopback y con la guarda del `Host`."""
    _reload_config("LOCAL_DELEGATE_WEB_HOST", "")
    monkeypatch.setattr(config, "WEB_TOKEN", "")
    app = daemon.build_app(None, 19393)
    assert isinstance(app, host_guard.HostGuard)
    with TestClient(app, base_url=LOCAL) as client:
        assert client.get("/api/status", headers={"Host": EVIL}).status_code == 421
        assert client.get("/api/status").status_code == 200


@pytest.mark.parametrize("blank", ["", "  "])
def test_install_writes_a_loopback_url_for_blank_variables(monkeypatch, blank):
    monkeypatch.setenv("LOCAL_DELEGATE_WEB_HOST", blank)
    monkeypatch.setenv("LOCAL_DELEGATE_WEB_PORT", blank)
    assert install.daemon_mcp_url() == "http://127.0.0.1:9393/mcp"
