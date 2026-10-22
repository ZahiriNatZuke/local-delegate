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
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

import anyio
import httpx2
import pytest
import uvicorn

from local_delegate import config, daemon, desktop_bridge, server, token_source

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


# --- Llamadas abandonadas (SDD claude-plugin-and-mods, abandoned-calls) --------------------------
#
# Medido el 2026-10-22 contra el daemon 0.40.0: una `tools/call` cuyo cliente desaparece (puente
# matado, stdin cerrado, `notifications/cancelled`) seguía hasta el final y retenía el turno del
# backend. Aquí, con la app real del daemon y un backend falso lento: un `local_summarize` troceado
# en ~20 llamadas de 0,4 s (unos 8 s en total) y, para el turno, la topología de hoy, donde el
# modelo largo y el mecánico chocan. Cada test mide algo que sin cancelación sale distinto: el
# puente tardaría los ~8 s en salir, la segunda llamada esperaría el turno ~8 s y la entrada de
# `inflight.json` seguiría ahí ~8 s.

TODAY_TOPOLOGY = Path(__file__).parent / "fixtures" / "topology" / "today.yaml"
LONG_MODEL = "gemma4-26b-a4b"
BACKEND_DELAY_S = 0.4
SUMMARIZE = {
    "jsonrpc": "2.0",
    "id": 10,
    "method": "tools/call",
    "params": {
        "name": "local_summarize",
        "arguments": {
            "text": "\n\n".join(f"p{i} " + ("palabra " * 75).strip() for i in range(1, 21))
        },
    },
}
CLASSIFY = {
    "jsonrpc": "2.0",
    "id": 11,
    "method": "tools/call",
    "params": {"name": "local_classify", "arguments": {"text": "hola", "labels": ["a", "b"]}},
}
_HTTP_TIMEOUT = httpx2.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0)


class SlowBackend:
    """`server._post_chat` falso: cada llamada tarda `delay` s y responde «a»."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.calls: list[str] = []
        self.active = 0
        self._lock = threading.Lock()

    def __call__(self, model: str, _payload: dict) -> server.ChatResult:
        with self._lock:
            self.calls.append(model)
            self.active += 1
        try:
            time.sleep(self.delay)
            return server.ChatResult(text="a", ok=True, finish_reason="stop")
        finally:
            with self._lock:
                self.active -= 1

    def count(self, model: str) -> int:
        with self._lock:
            return sum(1 for m in self.calls if m == model)


def _settle(condition: Callable[[], object], cap: float) -> object:
    end = time.monotonic() + cap
    while time.monotonic() < end:
        value = condition()
        if value:
            return value
        time.sleep(0.02)
    return condition()


async def _until(condition: Callable[[], object], cap: float) -> None:
    end = time.monotonic() + cap
    while not condition():
        assert time.monotonic() < end, "el guion no llegó a su punto de partida"
        await anyio.sleep(0.02)


@pytest.fixture
def slow_backend(tmp_path, monkeypatch):
    """Topología de hoy en una copia, backend en loopback, plazas 2 y un resumen en ~20 trozos."""
    copy = tmp_path / "llamaswap.yaml"
    copy.write_bytes(TODAY_TOPOLOGY.read_bytes())
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(copy))
    monkeypatch.setattr(config, "BASE_URL", "http://127.0.0.1:9292/v1")
    monkeypatch.setattr(server, "_chat_slots", threading.BoundedSemaphore(2))
    monkeypatch.setattr(config, "LONG_INPUT_CHARS", 1000)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 1000)
    backend = SlowBackend(BACKEND_DELAY_S)
    monkeypatch.setattr(server, "_post_chat", backend)
    yield backend
    # Lo que quede en el backend falso termina antes de que el siguiente test toque `server`.
    _settle(lambda: backend.active == 0, cap=15)


def _events(tmp_path: Path) -> list[dict]:
    lines: list[str] = []
    for file in sorted(tmp_path.glob("usage*.jsonl")):  # el registro rota por mes
        lines += file.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _summarize_in_flight() -> bool:
    return any(e.get("tool") == "local_summarize" for e in server.inflight_snapshot())


class _RawSession:
    """Un cliente MCP mínimo sobre HTTP, para mirar el daemon sin el puente por medio."""

    def __init__(self, client: httpx2.AsyncClient, url: str) -> None:
        self.client = client
        self.url = url
        self.session_id: str | None = None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN}",
            "Mcp-Protocol-Version": INIT["params"]["protocolVersion"],
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    async def open(self) -> None:
        response = await self.client.post(self.url, json=INIT, headers=self._headers())
        assert response.status_code == 200, response.text
        self.session_id = response.headers["mcp-session-id"]
        await self.notify(INITIALIZED)

    async def notify(self, message: dict) -> None:
        response = await self.client.post(self.url, json=message, headers=self._headers())
        assert response.status_code < 300, response.text

    async def call(self, message: dict) -> dict | None:
        async with self.client.stream(
            "POST", self.url, json=message, headers=self._headers()
        ) as response:
            body = (await response.aread()).decode("utf-8")
        for line in body.splitlines():
            if line.startswith("data:"):
                data = json.loads(line[5:].strip())
                if data.get("id") == message["id"]:
                    return data
        if body.strip().startswith("{"):
            return json.loads(body)
        return None

    async def delete(self) -> None:
        await self.client.delete(self.url, headers=self._headers())


def _assert_summarize_stopped(backend: SlowBackend, at_cancel: int, tmp_path: Path, reason):
    """Lo que tiene que pasar al cancelar: fuera de `inflight.json`, sin más trozos y apuntada."""
    assert _settle(lambda: not _summarize_in_flight(), cap=2.0), (
        "la llamada cancelada sigue en inflight.json 2 s después"
    )
    time.sleep(3 * BACKEND_DELAY_S)
    assert backend.count(LONG_MODEL) <= at_cancel + 1, (
        f"siguieron saliendo trozos al backend: {at_cancel} al cancelar, "
        f"{backend.count(LONG_MODEL)} después"
    )
    events = [e for e in _events(tmp_path) if e.get("tool") == "local_summarize"]
    assert events, "la llamada cancelada no quedó en el registro de uso"
    assert events[-1]["ok"] is False and events[-1].get("error") == "cancelled", events[-1]
    if reason is not None:
        assert events[-1].get("cancel_reason") == reason, events[-1]


def test_cancelled_notification_releases_backend_turn(monkeypatch, slow_backend, tmp_path):
    """`notifications/cancelled` para la llamada larga: la segunda (otro modelo, choca) no la espera."""
    with real_daemon(monkeypatch, TOKEN) as url:

        async def scenario() -> tuple[int, float, dict | None]:
            async with httpx2.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                session = _RawSession(client, url)
                await session.open()
                async with anyio.create_task_group() as group:
                    group.start_soon(session.call, SUMMARIZE)
                    await _until(lambda: slow_backend.count(LONG_MODEL) >= 1, cap=10)
                    at_cancel = slow_backend.count(LONG_MODEL)
                    await session.notify(
                        {
                            "jsonrpc": "2.0",
                            "method": "notifications/cancelled",
                            "params": {"requestId": SUMMARIZE["id"], "reason": "test"},
                        }
                    )
                    started = time.monotonic()
                    answer = await session.call(CLASSIFY)
                    elapsed = time.monotonic() - started
                    group.cancel_scope.cancel()
                return at_cancel, elapsed, answer

        at_cancel, elapsed, answer = anyio.run(scenario)
        assert answer is not None and "result" in answer, answer
        assert elapsed < 2.5, f"la segunda llamada esperó {elapsed:.1f} s a la cancelada"
        _assert_summarize_stopped(slow_backend, at_cancel, tmp_path, "notification")


def test_session_delete_cancels_inflight(monkeypatch, slow_backend, tmp_path):
    """El `DELETE` de la sesión cancela lo que esa sesión tenga en curso."""
    with real_daemon(monkeypatch, TOKEN) as url:

        async def scenario() -> int:
            async with httpx2.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                session = _RawSession(client, url)
                await session.open()
                async with anyio.create_task_group() as group:
                    group.start_soon(session.call, SUMMARIZE)
                    await _until(lambda: slow_backend.count(LONG_MODEL) >= 1, cap=10)
                    at_cancel = slow_backend.count(LONG_MODEL)
                    await session.delete()
                    with anyio.move_on_after(3):
                        while _summarize_in_flight():
                            await anyio.sleep(0.02)
                    group.cancel_scope.cancel()
                return at_cancel

        at_cancel = anyio.run(scenario)
        _assert_summarize_stopped(slow_backend, at_cancel, tmp_path, None)


def test_client_disconnect_cancels_inflight(monkeypatch, slow_backend, tmp_path):
    """Si el cliente cierra la conexión de la petición, la llamada se cancela."""
    with real_daemon(monkeypatch, TOKEN) as url:

        async def scenario() -> int:
            async with httpx2.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                session = _RawSession(client, url)
                await session.open()
                async with anyio.create_task_group() as group:
                    group.start_soon(session.call, SUMMARIZE)
                    await _until(lambda: slow_backend.count(LONG_MODEL) >= 1, cap=10)
                    at_cancel = slow_backend.count(LONG_MODEL)
                    group.cancel_scope.cancel()  # corta la conexión con la respuesta a medias
                return at_cancel

        at_cancel = anyio.run(scenario)
        _assert_summarize_stopped(slow_backend, at_cancel, tmp_path, "disconnect")


def test_stdin_eof_cancels_inflight_and_exits_fast(monkeypatch, slow_backend, tmp_path):
    """stdin cerrado con una llamada en curso: el puente la cancela, cierra la sesión y sale ya."""
    with real_daemon(monkeypatch, TOKEN) as url:
        marks: dict[str, float] = {}

        async def backend_started() -> None:
            await _until(lambda: slow_backend.count(LONG_MODEL) >= 1, cap=10)
            marks["at_cancel"] = slow_backend.count(LONG_MODEL)
            marks["eof"] = time.monotonic()

        _out, bridge = run_session(url, TOKEN, [INIT, INITIALIZED, SUMMARIZE, backend_started])
        exit_s = time.monotonic() - marks["eof"]

        assert exit_s <= 3.0, f"el puente tardó {exit_s:.1f} s en salir tras cerrarse stdin"
        assert bridge.session_id
        _assert_summarize_stopped(slow_backend, int(marks["at_cancel"]), tmp_path, "notification")
