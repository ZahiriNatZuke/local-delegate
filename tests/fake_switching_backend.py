"""A llama-swap stand-in in pure Python, for the two-machine test (concurrency PC+Mac, lot 4).

An HTTP server in a thread of the test, on a free loopback port, that behaves like llama-swap on
the one point that matters here: two models that clash cannot be served at once. A request for a
model that is not the loaded one waits until every request of the loaded model has finished, then
swaps (`load_s`) and is served. Each model answers after its own delay.

Endpoints: `POST /v1/chat/completions` (OpenAI shape), `GET /running` (llama-swap's shape) and
`GET /v1/models`. It records what it served, in order (`served`), and every swap (`swaps`).
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass(frozen=True)
class Served:
    model: str
    start: float
    end: float


class FakeSwitchingBackend:
    def __init__(self, delays: dict[str, float], *, load_s: float = 0.05) -> None:
        self.delays = dict(delays)
        self.load_s = load_s
        self.loaded: str | None = None
        self.active = 0
        self.served: list[Served] = []
        self.swaps: list[tuple[str | None, str]] = []
        self._cond = threading.Condition()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # --- the llama-swap part ------------------------------------------------------------------

    def _serve(self, model: str) -> None:
        with self._cond:
            while self.loaded != model and self.active > 0:
                self._cond.wait(timeout=0.5)
            if self.loaded != model:
                self.swaps.append((self.loaded, model))
                self.loaded = model
                time.sleep(self.load_s)  # under the lock: nobody is served while it loads
            self.active += 1
        start = time.monotonic()
        try:
            time.sleep(self.delays.get(model, 0.05))
        finally:
            with self._cond:
                self.active -= 1
                self.served.append(Served(model, start, time.monotonic()))
                self._cond.notify_all()

    def order(self) -> list[str]:
        """The models in the order they were served, consecutive repeats collapsed."""
        with self._cond:
            ordered = sorted(self.served, key=lambda s: s.start)
        out: list[str] = []
        for s in ordered:
            if not out or out[-1] != s.model:
                out.append(s.model)
        return out

    def running(self) -> dict:
        with self._cond:
            if self.loaded is None:
                return {"running": None}
            return {"running": [{"model": self.loaded, "state": "ready"}]}

    # --- HTTP ----------------------------------------------------------------------------------

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        backend = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:  # quiet
                return

            def _send(self, code: int, body: dict) -> None:
                data = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                if self.path == "/running":
                    self._send(200, backend.running())
                elif self.path == "/v1/models":
                    self._send(200, {"data": [{"id": m} for m in backend.delays]})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    self._send(400, {"error": "bad json"})
                    return
                if self.path != "/v1/chat/completions" or not isinstance(body, dict):
                    self._send(404, {"error": "not found"})
                    return
                model = str(body.get("model") or "")
                if model not in backend.delays:
                    self._send(400, {"error": f"unknown model {model}"})
                    return
                backend._serve(model)
                self._send(
                    200,
                    {
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": "a"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 1},
                    },
                )

        return Handler

    def start(self) -> int:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="fake-switching-backend", daemon=True
        )
        self._thread.start()
        return self._server.server_address[1]

    def stop(self) -> None:
        """Stop serving and join the thread (bounded)."""
        server, thread = self._server, self._thread
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=10)
            assert not thread.is_alive(), "the fake backend's thread did not stop"
