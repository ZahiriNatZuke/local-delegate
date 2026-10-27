"""Host guard of the daemon port: DNS rebinding can no longer read the panel (`panel-host-check`).

The attack from the 2026-10-23 review: with no token (the default), a page that rebinds its own name
to 127.0.0.1 read `/api/events`, `/api/system`, ... and used `POST /api/hook/classify` as an oracle
for any file's existence and size. Its requests carry `Host: evil.example:<port>`, which is what the
guard rejects. Most tests run against the REAL daemon app (`daemon.build_app`), because the question
is whether the guard is plugged into what is served, not whether the middleware works on a toy app.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from local_delegate import config, daemon
from local_delegate.web import host_guard, metrics

PORT = 19393
EVIL = f"evil.example:{PORT}"
LOCAL = f"http://127.0.0.1:{PORT}"
READ_ENDPOINTS = (
    "/api/events",
    "/api/status",
    "/api/system",
    "/api/hooks",
    "/",
    daemon.DAEMON_STATUS_PATH,
)


@pytest.fixture(autouse=True)
def _no_token(monkeypatch):
    monkeypatch.setattr(config, "WEB_TOKEN", "")
    monkeypatch.setattr(config, "WEB_ALLOWED_HOSTS", [])


def _client(bind: str = "127.0.0.1") -> TestClient:
    # `client` is loopback: the hook endpoints also check the peer address (`_require_loopback`).
    return TestClient(
        daemon.build_app(bind, PORT),
        base_url=LOCAL,
        client=("127.0.0.1", 50001),
        raise_server_exceptions=False,
    )


def _handshake(client: TestClient, host: str):
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


def _classify(client: TestClient, target, headers: dict):
    body = {"payload": {"tool_name": "Read", "tool_input": {"file_path": str(target)}}, "env": {}}
    return client.post(
        "/api/hook/classify",
        content=json.dumps(body),
        headers={"Content-Type": "text/plain;charset=UTF-8", **headers},
    )


def test_rebinding_host_reads_nothing_from_the_panel():
    """The review's repro: every read endpoint answered 200 to `Host: evil.example`."""
    with _client() as client:
        for path in READ_ENDPOINTS:
            response = client.get(path, headers={"Host": EVIL})
            assert response.status_code == 421, f"{path} answered a foreign Host"
            assert response.text.startswith("Invalid Host header")
            assert "log_dir" not in response.text and "base_url" not in response.text


def test_loopback_hosts_keep_working():
    """The browser on 127.0.0.1/localhost, the hooks, the mod and the bridge all arrive by loopback."""
    with _client() as client:
        for host in (
            f"127.0.0.1:{PORT}",
            f"localhost:{PORT}",
            f"[::1]:{PORT}",
            "LOCALHOST",
            "127.0.0.1",
        ):
            for path in READ_ENDPOINTS:
                assert client.get(path, headers={"Host": host}).status_code == 200, (host, path)
        assert _handshake(client, f"localhost:{PORT}").status_code == 200


def test_classify_is_no_file_oracle_for_a_rebinding_page(tmp_path):
    target = tmp_path / "secret.txt"
    target.write_text("x" * 5417, encoding="utf-8")
    with _client() as client:
        response = _classify(client, target, {"Host": EVIL, "Origin": "http://evil.example:19393"})
        assert response.status_code == 421
        assert "5417" not in response.text and str(target) not in response.text
        # Control: from loopback the endpoint works, so the 421 above is the guard and not a broken route.
        # `/api/hook/*` only takes JSON (a «simple» text/plain request gets 415 there), so the control sends JSON.
        control = _classify(
            client, target, {"Host": f"127.0.0.1:{PORT}", "Content-Type": "application/json"}
        )
        assert control.status_code == 200


def test_a_post_from_another_site_is_refused_by_origin(tmp_path):
    """A page on another site can POST a «simple» request straight to 127.0.0.1: the Host is valid."""
    with _client() as client:
        for origin in ("http://evil.example", "https://evil.example:443", "null"):
            response = _classify(
                client, tmp_path / "x", {"Host": f"127.0.0.1:{PORT}", "Origin": origin}
            )
            assert response.status_code == 403, origin
            assert "Invalid Origin" in response.text, "403 from another check, not the guard"
        # The panel itself (same origin) and a non-web embedder are not refused by the guard. They are
        # checked on a panel route: `/api/hook/*` refuses every `Origin` on its own, the panel never calls it.
        for origin in (LOCAL, f"http://localhost:{PORT}", "app://claude"):
            response = client.get(
                "/api/events", headers={"Host": f"127.0.0.1:{PORT}", "Origin": origin}
            )
            assert response.status_code == 200, origin


def test_the_guard_answers_before_the_token(monkeypatch):
    """With a token the foreign Host still gets 421, not a 401 that would invite a credential prompt."""
    monkeypatch.setattr(config, "WEB_TOKEN", "the-port-token")
    with _client() as client:
        assert client.get("/api/status", headers={"Host": EVIL}).status_code == 421
        assert client.get("/api/status").status_code == 401
        bearer = {"Authorization": "Bearer the-port-token"}
        assert client.get("/api/status", headers=bearer).status_code == 200


def test_extra_hosts_open_the_panel_and_mcp_together(monkeypatch):
    """`tailscale serve` forwards the tailnet name as Host; one variable admits it in both places."""
    tailnet = "own-pc.tail0000.ts.net"
    monkeypatch.setattr(config, "WEB_ALLOWED_HOSTS", [tailnet])
    with _client() as client:
        assert client.get("/api/status", headers={"Host": f"{tailnet}:{PORT}"}).status_code == 200
        assert client.get("/api/status", headers={"Host": tailnet.upper()}).status_code == 200
        assert _handshake(client, f"{tailnet}:{PORT}").status_code == 200
        assert client.get("/api/status", headers={"Host": EVIL}).status_code == 421
        assert _handshake(client, EVIL).status_code == 421


def test_without_the_extra_host_the_tailnet_name_is_refused_on_both():
    """Coherence with the old 421 on `/mcp`: the panel now refuses the same Host, not just `/mcp`."""
    with _client() as client:
        host = f"own-pc.tail0000.ts.net:{PORT}"
        assert client.get("/api/status", headers={"Host": host}).status_code == 421
        assert _handshake(client, host).status_code == 421


def test_a_concrete_interface_is_admitted_and_protected():
    """`LOCAL_DELEGATE_WEB_HOST=<ip>`: clients arrive with that IP as Host, and rebinding still fails."""
    with _client("192.168.1.50") as client:
        assert (
            client.get("/api/status", headers={"Host": f"192.168.1.50:{PORT}"}).status_code == 200
        )
        assert _handshake(client, f"192.168.1.50:{PORT}").status_code == 200
        assert client.get("/api/status", headers={"Host": EVIL}).status_code == 421
        assert _handshake(client, EVIL).status_code == 421


def test_all_interfaces_without_extras_keeps_the_lan_open():
    """Same rule as the SDK: on 0.0.0.0 there is no list of names the LAN will use."""
    with _client("0.0.0.0") as client:
        assert (
            client.get("/api/status", headers={"Host": f"192.168.1.50:{PORT}"}).status_code == 200
        )


def test_all_interfaces_with_extras_applies_the_list(monkeypatch):
    monkeypatch.setattr(config, "WEB_ALLOWED_HOSTS", ["192.168.1.50"])
    with _client("0.0.0.0") as client:
        assert (
            client.get("/api/status", headers={"Host": f"192.168.1.50:{PORT}"}).status_code == 200
        )
        assert client.get("/api/status", headers={"Host": EVIL}).status_code == 421


def test_star_disables_the_guard(monkeypatch):
    monkeypatch.setattr(config, "WEB_ALLOWED_HOSTS", ["*"])
    with _client() as client:
        assert client.get("/api/status", headers={"Host": EVIL}).status_code == 200


def test_the_variable_is_read_from_the_environment(monkeypatch):
    import importlib

    monkeypatch.setenv("LOCAL_DELEGATE_WEB_ALLOWED_HOSTS", " own-pc.ts.net , ,10.0.0.2")
    try:
        importlib.reload(config)
        assert config.WEB_ALLOWED_HOSTS == ["own-pc.ts.net", "10.0.0.2"]
        assert "LOCAL_DELEGATE_WEB_ALLOWED_HOSTS" in config.ENVIRONMENT_VARIABLES
    finally:
        monkeypatch.delenv("LOCAL_DELEGATE_WEB_ALLOWED_HOSTS")
        importlib.reload(config)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("127.0.0.1:9393", "127.0.0.1"),
        ("LocalHost", "localhost"),
        ("[::1]:9393", "::1"),
        ("[::1]", "::1"),
        ("own-pc.ts.net.:443", "own-pc.ts.net"),
        ("", ""),
        ("[broken", ""),
    ],
)
def test_host_from_header(header, expected):
    assert host_guard.host_from_header(header) == expected


def test_the_stdio_web_is_guarded_too(monkeypatch):
    """`run_in_thread` (the web of the stdio MCP) serves the same panel: it must be wrapped as well."""
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
    assert isinstance(served["app"], host_guard.HostGuard)
    with TestClient(served["app"], base_url=LOCAL) as client:
        assert client.get("/api/status", headers={"Host": EVIL}).status_code == 421
        assert client.get("/api/status").status_code == 200
