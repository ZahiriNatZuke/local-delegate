"""Puente MCP stdio → daemon HTTP para el chat de Claude Desktop (SDD claude-plugin-and-mods, REQ-012).

Se prueba contra la app **real** del daemon (`daemon.build_app`) servida por uvicorn en un hilo de
este proceso: HTTP de verdad, `Mcp-Session-Id`, respuestas SSE y el 401 del token. Un daemon falso
diría si el puente habla con lo que el puente cree, no con lo que hay.
"""

from __future__ import annotations

import io
import json
import logging
import socket
import threading
import time
from contextlib import contextmanager

import anyio
import httpx2
import uvicorn

from local_delegate import config, daemon, desktop_bridge, token_source

TOKEN = "bridge-test-port-token-1234567890"
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "claude-ai", "version": "0.1.0"},
    },
}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
PING = {"jsonrpc": "2.0", "id": 3, "method": "ping"}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def real_daemon(monkeypatch, token: str):
    """La app de `daemon.py` con `token`, servida en un puerto libre; devuelve la URL de `/mcp`."""
    monkeypatch.setattr(config, "WEB_TOKEN", token)
    port = _free_port()
    app = daemon.build_app("127.0.0.1", port)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        assert thread.is_alive(), "uvicorn murió al arrancar"
        assert time.monotonic() < deadline, "uvicorn no arrancó"
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}{daemon.MCP_PATH}"
    finally:
        server.should_exit = True
        thread.join(15)


async def _run_session(bridge: desktop_bridge.Bridge, messages, out: list) -> None:
    async def lines():
        for message in messages:
            if callable(message):
                await message()
                continue
            yield (json.dumps(message) + "\n").encode("utf-8")

    async def write(data: bytes) -> None:
        out.append(json.loads(data))

    await bridge.run(lines(), write)


def run_session(
    url: str, token: str, messages, logs: list | None = None
) -> tuple[list, desktop_bridge.Bridge]:
    out: list = []
    bridge = desktop_bridge.Bridge(
        url,
        token_provider=lambda: token,
        log=(logs.append if logs is not None else lambda _m: None),
    )
    anyio.run(_run_session, bridge, messages, out)
    return out, bridge


def _by_id(out: list) -> dict:
    return {message.get("id"): message for message in out}


def test_bridge_against_real_daemon_app(monkeypatch):
    with real_daemon(monkeypatch, TOKEN) as url:
        out, bridge = run_session(url, TOKEN, [INIT, INITIALIZED, LIST, PING])

    responses = _by_id(out)
    assert set(responses) == {1, 2, 3}
    assert responses[1]["result"]["serverInfo"]["name"]
    names = {tool["name"] for tool in responses[2]["result"]["tools"]}
    assert "local_summarize" in names
    assert responses[3]["result"] == {}
    assert bridge.session_id  # el daemon dio sesión y el puente la usó en las siguientes


def test_two_instances_in_parallel(monkeypatch):
    """Desktop lanza cada servidor dos veces (chat y Cowork/Code): dos puentes a la vez."""
    with real_daemon(monkeypatch, TOKEN) as url:
        results: list = [None, None]

        async def both():
            async def one(slot: int):
                out: list = []
                bridge = desktop_bridge.Bridge(
                    url, token_provider=lambda: TOKEN, log=lambda _m: None
                )
                await _run_session(bridge, [INIT, INITIALIZED, LIST, PING], out)
                results[slot] = (out, bridge.session_id)

            async with anyio.create_task_group() as group:
                group.start_soon(one, 0)
                group.start_soon(one, 1)

        anyio.run(both)

    for out, session in results:
        assert set(_by_id(out)) == {1, 2, 3}
        assert [m for m in out if "error" in m] == []
        assert session
    assert results[0][1] != results[1][1]


def test_wrong_token_surfaces_401_as_mcp_error(monkeypatch):
    with real_daemon(monkeypatch, TOKEN) as url:
        out, _ = run_session(url, "not-the-token", [INIT])

    (response,) = out
    assert response["id"] == 1
    assert response["error"]["code"] == desktop_bridge.ERROR_TOKEN_REJECTED
    assert "401" in response["error"]["message"]
    assert token_source.TOKEN_VARIABLE in response["error"]["message"]
    assert "not-the-token" not in json.dumps(response)


def test_rotated_token_is_reread_once_after_401(monkeypatch):
    """El puente lee el token al arrancar; si lo rotaron después, un 401 lo hace releer una vez."""
    reads = iter(["old-token"])

    def provider():
        return next(reads, TOKEN)

    with real_daemon(monkeypatch, TOKEN) as url:
        out: list = []
        bridge = desktop_bridge.Bridge(url, token_provider=provider, log=lambda _m: None)
        anyio.run(_run_session, bridge, [INIT, INITIALIZED, PING], out)

    assert set(_by_id(out)) == {1, 3}
    assert [m for m in out if "error" in m] == []


def test_daemon_down_returns_mcp_error():
    url = f"http://127.0.0.1:{_free_port()}{daemon.MCP_PATH}"
    logs: list = []

    out, _ = run_session(url, TOKEN, [INIT, INITIALIZED, PING], logs)

    responses = _by_id(out)
    assert set(responses) == {1, 3}  # a la notificación no se le responde
    for response in responses.values():
        assert response["error"]["code"] == desktop_bridge.ERROR_DAEMON_DOWN
        assert url in response["error"]["message"]
    assert any(url in line for line in logs)  # el fallo de la notificación queda en stderr


def test_lost_session_is_restored_and_retried(monkeypatch):
    """Si el daemon olvida la sesión (reinicio), el puente la rehace y repite la petición."""
    with real_daemon(monkeypatch, TOKEN) as url:
        holder: dict = {}

        async def kill_session():
            async with httpx2.AsyncClient() as client:
                response = await client.delete(
                    url,
                    headers={
                        "Authorization": f"Bearer {TOKEN}",
                        "Mcp-Session-Id": holder["bridge"].session_id,
                    },
                )
            assert response.status_code < 300
            holder["first"] = holder["bridge"].session_id

        out: list = []
        bridge = desktop_bridge.Bridge(url, token_provider=lambda: TOKEN, log=lambda _m: None)
        holder["bridge"] = bridge
        anyio.run(_run_session, bridge, [INIT, INITIALIZED, kill_session, LIST], out)

    responses = _by_id(out)
    assert set(responses) == {1, 2}
    assert "tools" in responses[2]["result"]
    assert bridge.session_id and bridge.session_id != holder["first"]


def test_invalid_json_line_gets_parse_error(monkeypatch):
    out: list = []

    async def main():
        async def lines():
            yield b"{not json\n"
            yield b"\n"  # las líneas vacías se ignoran

        async def write(data: bytes) -> None:
            out.append(json.loads(data))

        bridge = desktop_bridge.Bridge(
            "http://127.0.0.1:1/mcp", token_provider=lambda: "", log=lambda _m: None
        )
        await bridge.run(lines(), write)

    anyio.run(main)

    assert out == [
        {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": desktop_bridge.ERROR_PARSE, "message": out[0]["error"]["message"]},
        }
    ]


def test_main_speaks_stdio(monkeypatch):
    """`main` con flujos binarios: lo que Desktop ve es JSON-RPC por línea en stdout y nada más."""
    monkeypatch.setattr(token_source, "web_token", lambda: TOKEN)
    with real_daemon(monkeypatch, TOKEN) as url:
        stdin = io.BytesIO(
            b"".join((json.dumps(m) + "\n").encode() for m in (INIT, INITIALIZED, PING))
        )
        stdout = io.BytesIO()
        stderr = io.StringIO()

        code = desktop_bridge.main(["--url", url], stdin=stdin, stdout=stdout, stderr=stderr)

    assert code == 0
    lines = stdout.getvalue().split(b"\n")
    assert lines[-1] == b""
    messages = [json.loads(line) for line in lines[:-1]]
    assert {m["id"] for m in messages} == {1, 3}
    assert [m for m in messages if "error" in m] == []
    assert url in stderr.getvalue()


def test_mcp_path_matches_the_daemon():
    assert desktop_bridge.MCP_PATH == daemon.MCP_PATH


def test_default_url_comes_from_daemon_state(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "WEB_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "WEB_PORT", 9393)
    assert desktop_bridge.daemon_url() == "http://127.0.0.1:9393/mcp"

    (tmp_path / "daemon.json").write_text(
        json.dumps({"host": "0.0.0.0", "port": 9555}), encoding="utf-8"
    )
    assert desktop_bridge.daemon_url() == "http://127.0.0.1:9555/mcp"


def test_never_logs_token(monkeypatch, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    logs: list = []
    outputs: list = []
    with real_daemon(monkeypatch, TOKEN) as url:
        out, _ = run_session(url, TOKEN, [INIT, INITIALIZED, LIST, PING], logs)
        outputs += out
        out, _ = run_session(url, TOKEN + "-wrong", [INIT, INITIALIZED, PING], logs)
        outputs += out
    out, _ = run_session(url, TOKEN, [INIT, INITIALIZED, PING], logs)  # daemon ya parado
    outputs += out

    monkeypatch.setattr(token_source, "web_token", lambda: TOKEN)
    stderr = io.StringIO()
    desktop_bridge.main(["--url", url], stdin=io.BytesIO(b""), stdout=io.BytesIO(), stderr=stderr)

    captured = capsys.readouterr()
    everything = "\n".join(
        [json.dumps(outputs), *logs, stderr.getvalue(), captured.out, captured.err, caplog.text]
    )
    assert logs, "la prueba no llegó a registrar nada"
    assert TOKEN not in everything
