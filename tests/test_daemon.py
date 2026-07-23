"""Tests del daemon singleton MCP HTTP + dashboard."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from filelock import FileLock

from local_delegate import cli, config, daemon


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
