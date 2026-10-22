"""Puntos de parada de una llamada cancelada (SDD claude-plugin-and-mods, abandoned-calls).

Los escenarios de punta a punta están en `test_desktop_bridge.py`; aquí, las dos piezas que esos
escenarios no ejercitan por separado: salir de la cola del turno y abandonar un envío en curso.
"""

from __future__ import annotations

import json
import socket
import threading
import time

import anyio
import pytest

from local_delegate import cancellation, server, turn


def _always_clash(_a: str, _b: str) -> bool:
    return True


def test_cancelled_wait_leaves_turn_queue_without_waiting_the_tick():
    # Tic de 30 s: si la espera solo mirara la parada en cada tic, el test lo vería.
    state = turn.Turn(_always_clash, tick=30.0)
    state.request(turn.PendingRequest("holder", frozenset({"big"}), "big"))
    token = cancellation.Token("local_classify")
    outcome: dict[str, object] = {}

    def waiter() -> None:
        try:
            state.request(
                turn.PendingRequest("waiter", frozenset({"small"}), "small"),
                should_stop=token.is_cancelled,
            )
            outcome["result"] = "granted"
        except turn.AbandonedWait:
            outcome["result"] = "abandoned"
        outcome["at"] = time.monotonic()

    thread = threading.Thread(target=waiter, daemon=True)
    thread.start()
    deadline = time.monotonic() + 2
    while not state.snapshot().queue:
        assert time.monotonic() < deadline, "la espera no llegó a la cola"
        time.sleep(0.01)

    token.on_cancel(state.wake)
    cancelled_at = time.monotonic()
    token.cancel(cancellation.REASON_NOTIFICATION)
    thread.join(2)

    assert not thread.is_alive(), "la espera cancelada sigue en la cola"
    assert outcome["result"] == "abandoned"
    assert float(outcome["at"]) - cancelled_at < 1.0
    assert state.snapshot().queue == ()


def test_run_abandonable_returns_as_soon_as_cancelled():
    token = cancellation.Token("local_summarize")
    finished = threading.Event()

    def slow_post() -> str:
        time.sleep(1.5)
        finished.set()
        return "late"

    def run() -> None:
        cancellation._CURRENT.set(token)
        cancellation.run_abandonable(slow_post)

    errors: list[BaseException] = []

    def target() -> None:
        try:
            run()
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    time.sleep(0.1)
    started = time.monotonic()
    token.cancel(cancellation.REASON_DISCONNECT)
    thread.join(1.0)

    assert not thread.is_alive(), "quien espera el envío no se enteró de la cancelación"
    assert time.monotonic() - started < 1.0
    assert len(errors) == 1 and isinstance(errors[0], cancellation.CallCancelled)
    assert errors[0].reason == cancellation.REASON_DISCONNECT
    assert token.observed
    assert not finished.is_set()  # guarda: se volvió antes de que el envío acabara
    assert finished.wait(3)  # y el envío abandonado terminó solo


def test_abandonable_send_can_still_reach_the_event_loop():
    """`questions.ask` corre dentro del envío y salta al bucle con `anyio.from_thread.run`."""

    async def answer() -> str:
        return "yes"

    def tool_thread() -> str:
        cancellation._CURRENT.set(cancellation.Token("local_summarize"))
        return cancellation.run_abandonable(lambda: anyio.from_thread.run(answer))

    async def main() -> str:
        return await anyio.to_thread.run_sync(tool_thread)

    assert anyio.run(main) == "yes"


def test_without_token_everything_runs_inline():
    assert cancellation.current() is None
    cancellation.checkpoint()  # no lanza
    caller = threading.get_ident()
    assert cancellation.run_abandonable(threading.get_ident) == caller


def test_run_abandonable_propagates_backend_errors():
    token = cancellation.Token("local_classify")

    def broken() -> str:
        raise ValueError("boom")

    def run() -> None:
        cancellation._CURRENT.set(token)
        cancellation.run_abandonable(broken)

    errors: list[BaseException] = []
    thread = threading.Thread(target=lambda: _capture(run, errors), daemon=True)
    thread.start()
    thread.join(2)
    assert len(errors) == 1 and isinstance(errors[0], ValueError)
    assert not token.observed


def _capture(function, errors: list[BaseException]) -> None:
    try:
        function()
    except Exception as exc:
        errors.append(exc)


@pytest.mark.parametrize("reason", ["first", "second"])
def test_first_reason_wins(reason):
    token = cancellation.Token()
    token.cancel(reason)
    token.cancel("other")
    assert token.reason == reason
    with pytest.raises(cancellation.CallCancelled):
        token.check()


class _HangingBackend:
    """Un `/chat/completions` de verdad (socket) que tarda `hold` s y anota si el cliente cerró antes.

    Es lo que mira llama.cpp para dejar de generar: que el cliente cierre la conexión. Las demás
    peticiones (la sonda de carga, `/running`) reciben un 404 y se cierran.
    """

    def __init__(self, hold: float) -> None:
        self.hold = hold
        self.closed_early = threading.Event()
        self.got_request = threading.Event()
        self.answered = threading.Event()
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self._sock.settimeout(0.2)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._threads = [threading.Thread(target=self._accept, daemon=True)]
        self._threads[0].start()

    def _accept(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                continue
            worker = threading.Thread(target=self._serve, args=(conn,), daemon=True)
            self._threads.append(worker)
            worker.start()

    def _serve(self, conn: socket.socket) -> None:
        with conn:
            conn.settimeout(5)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                data += chunk
            head, _, body = data.partition(b"\r\n\r\n")
            length = 0
            for line in head.split(b"\r\n")[1:]:
                name, _, value = line.partition(b":")
                if name.strip().lower() == b"content-length":
                    length = int(value.strip())
            while len(body) < length:
                body += conn.recv(65536)
            if b"/chat/completions" not in head.split(b"\r\n")[0]:
                conn.sendall(
                    b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
                return
            self.got_request.set()
            end = time.monotonic() + self.hold
            conn.settimeout(0.05)
            while time.monotonic() < end and not self._stop.is_set():
                try:
                    if conn.recv(1) == b"":
                        self.closed_early.set()  # el cliente cerró: llama.cpp pararía aquí
                        return
                except TimeoutError:
                    continue
                except OSError:
                    self.closed_early.set()
                    return
            payload = json.dumps(
                {"choices": [{"message": {"content": "a"}, "finish_reason": "stop"}]}
            ).encode()
            try:
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    + f"Content-Length: {len(payload)}\r\n\r\n".encode()
                    + payload
                )
                self.answered.set()
            except OSError:
                self.closed_early.set()

    def close(self) -> None:
        self._stop.set()
        self._sock.close()
        for thread in self._threads:
            thread.join(2)


def test_cancelled_send_closes_the_backend_connection(monkeypatch):
    """Al cancelar, el envío en curso CORTA su conexión: el backend lo ve y deja de generar."""
    backend = _HangingBackend(hold=6.0)
    monkeypatch.setattr(server.config, "BASE_URL", f"http://127.0.0.1:{backend.port}/v1")
    token = cancellation.Token("local_summarize")
    errors: list[Exception] = []

    def tool_thread() -> None:
        cancellation._CURRENT.set(token)
        try:
            server._send("gemma4-26b-a4b", {"messages": [], "max_tokens": 8})
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=tool_thread, daemon=True)
    try:
        thread.start()
        assert backend.got_request.wait(5), "el envío no llegó al backend"
        cancelled_at = time.monotonic()
        token.cancel(cancellation.REASON_DISCONNECT)
        thread.join(2)
        assert not thread.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], cancellation.CallCancelled)
        assert backend.closed_early.wait(2), (
            "el backend no vio cerrarse la conexión: seguiría generando el trozo abandonado"
        )
        assert time.monotonic() - cancelled_at < 2
        assert not backend.answered.is_set()
    finally:
        backend.close()


def test_other_sends_keep_the_shared_client(monkeypatch):
    """Sin token (CLI, benchmark) se sigue usando el cliente compartido con keep-alive."""
    backend = _HangingBackend(hold=0.0)
    monkeypatch.setattr(server.config, "BASE_URL", f"http://127.0.0.1:{backend.port}/v1")
    try:
        result = server._send("gemma3-4b", {"messages": [], "max_tokens": 8})
        assert result.ok and result.text == "a"
        assert server._client is not None
    finally:
        backend.close()
