"""Tests del daemon singleton MCP HTTP + dashboard."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from filelock import FileLock

from local_delegate import cli, config, daemon, server


class _RespuestaFalsa:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _doblar_get(monkeypatch, payload):
    """Dobla el GET de httpx2 para que `query_backend` reciba `payload`."""

    class _ClienteFalso:
        def __init__(self, *_a, **_kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def get(self, _url):
            return _RespuestaFalsa(payload)

    monkeypatch.setattr(daemon.httpx2, "Client", _ClienteFalso)


def test_query_backend_devuelve_lo_que_ve_el_daemon(monkeypatch):
    _doblar_get(monkeypatch, {"available": True, "models": []})
    assert daemon.query_backend("127.0.0.1", 9393) == {"available": True, "models": []}


def test_query_backend_sin_el_campo_available_es_none(monkeypatch):
    """Sin el campo que responde la pregunta, «no se pudo preguntar» es más honesto que inventar.

    Si se devolviera el dict igualmente, `available` saldría ausente y quien llama lo leería como
    un backend caído — un diagnóstico falso a partir de una respuesta que no dice nada.
    """
    _doblar_get(monkeypatch, {"models": []})
    assert daemon.query_backend("127.0.0.1", 9393) is None


def test_query_backend_con_respuesta_que_no_es_un_objeto_es_none(monkeypatch):
    _doblar_get(monkeypatch, [1, 2, 3])
    assert daemon.query_backend("127.0.0.1", 9393) is None


def test_combined_app_serves_daemon_status_dashboard_and_mcp_route():
    app = daemon.build_app("127.0.0.1", 19393)

    with TestClient(app) as client:
        status = client.get(daemon.DAEMON_STATUS_PATH)
        assert status.status_code == 200
        assert status.json()["service"] == "local-delegate"
        assert status.json()["mcp_url"] == "http://127.0.0.1:19393/mcp"

        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert "<!doctype html>" in dashboard.text.lower()

        # Sin un payload MCP válido debe fallar como protocolo, no como ruta ausente.
        mcp = client.post("/mcp")
        assert mcp.status_code != 404


def _handshake(client: TestClient, host: str):
    """Manda un `initialize` al MCP con un header Host concreto."""
    return client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        headers={
            "Host": host,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
    )


def test_mcp_en_loopback_acepta_localhost_y_rechaza_hosts_ajenos():
    """Con host de loopback el SDK activa solo la protección contra DNS rebinding."""
    app = daemon.build_app("127.0.0.1", 19393)

    with TestClient(app) as client:
        for host in ("127.0.0.1:19393", "localhost:19393"):
            assert _handshake(client, host).status_code == 200, host

        # Un Host que no es loopback es justo el vector del ataque: 421, no 200.
        assert _handshake(client, "atacante.example:19393").status_code == 421


def test_mcp_publicado_en_la_lan_no_rechaza_por_host():
    """`LOCAL_DELEGATE_WEB_HOST=0.0.0.0` publica en la red local, y el proyecto lo permite.

    La protección del SDK solo se auto-activa con loopback; si se activara aquí, el daemon
    respondería 421 a todo cliente que llegara por la IP de la LAN.
    """
    app = daemon.build_app("0.0.0.0", 19393)

    with TestClient(app) as client:
        assert _handshake(client, "192.168.1.50:19393").status_code == 200


def test_handshake_declara_la_version_del_paquete():
    """`serverInfo.version` reportaba la del SDK, que no dice qué local-delegate corre."""
    app = daemon.build_app("127.0.0.1", 19393)

    with TestClient(app) as client:
        respuesta = _handshake(client, "127.0.0.1:19393")

    carga = next(
        json.loads(linea[6:]) for linea in respuesta.text.splitlines() if linea.startswith("data: ")
    )
    info = carga["result"]["serverInfo"]
    assert info["name"] == "local-delegate"
    assert info["version"] == server._get_version()


def test_serve_writes_state_holds_singleton_and_cleans_up(tmp_path, monkeypatch):
    observed = {}

    class FakeUvicornServer:
        def __init__(self, uvicorn_config):
            self.config = uvicorn_config
            self.started = False

        def run(self):
            observed["state"] = json.loads((tmp_path / "daemon.json").read_text(encoding="utf-8"))
            observed["lock_exists"] = (tmp_path / "daemon.lock").exists()
            self.started = True

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "AUTOSTART", False)
    monkeypatch.setattr(daemon, "_port_available", lambda _host, _port: True)
    monkeypatch.setattr(daemon.uvicorn, "Server", FakeUvicornServer)

    assert daemon.serve("127.0.0.1", 19393) == 0
    assert observed["state"]["pid"] > 0
    assert observed["state"]["mcp_url"] == "http://127.0.0.1:19393/mcp"
    assert observed["lock_exists"] is True
    assert not (tmp_path / "daemon.json").exists()


def test_serve_is_idempotent_when_daemon_lock_is_held(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    current = {
        "service": "local-delegate",
        "mode": "daemon",
        "pid": 4321,
        "mcp_url": "http://127.0.0.1:19393/mcp",
    }
    monkeypatch.setattr(daemon, "query_daemon", lambda _host, _port: current)

    lock = FileLock(str(tmp_path / "daemon.lock"))
    with lock.acquire(timeout=0):
        assert daemon.serve("127.0.0.1", 19393) == 0

    output = capsys.readouterr().out
    assert "ya está activo" in output
    assert "pid=4321" in output


def test_serve_treats_ctrl_c_as_clean_shutdown(tmp_path, monkeypatch):
    class InterruptingServer:
        started = True

        def __init__(self, _uvicorn_config):
            pass

        def run(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "AUTOSTART", False)
    monkeypatch.setattr(daemon, "_port_available", lambda _host, _port: True)
    monkeypatch.setattr(daemon.uvicorn, "Server", InterruptingServer)

    assert daemon.serve("127.0.0.1", 19393) == 0
    assert not (tmp_path / "daemon.json").exists()


def test_serve_without_stdout_supports_pythonw(tmp_path, monkeypatch):
    class FakeUvicornServer:
        started = True

        def __init__(self, _uvicorn_config):
            pass

        def run(self):
            pass

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "AUTOSTART", False)
    monkeypatch.setattr(daemon, "_port_available", lambda _host, _port: True)
    monkeypatch.setattr(daemon.uvicorn, "Server", FakeUvicornServer)
    monkeypatch.setattr(daemon.sys, "stdout", None)

    assert daemon.serve("127.0.0.1", 19393) == 0
    assert not (tmp_path / "daemon.json").exists()


def test_cli_serve_dispatches_daemon(monkeypatch):
    calls = []
    monkeypatch.setattr(
        daemon,
        "serve",
        lambda **kwargs: calls.append(kwargs) or 7,
    )

    result = cli.run(["serve", "--host", "127.0.0.1", "--port", "19393", "--log-level", "info"])

    assert result == 7
    assert calls == [{"host": "127.0.0.1", "port": 19393, "log_level": "info"}]
