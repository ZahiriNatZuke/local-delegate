"""Issue #628: `/api/backend` still asks llama-swap's `/running` when the probe of `/v1/models`
failed but the backend's port did take the connection (no answer in time, an HTTP error, a body
that is not the list). The band of the mod reads a model in `starting` there and says «loading»
instead of «down».

What must not change: with a backend that is not there (refused, no route, connect timeout, DNS,
any other network failure) `/running` is not asked, so «down» costs one deadline and not two
(REQ-013); and `available` keeps meaning «`/v1/models` answered with its list».
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Self

import backend_mock
import httpx2
import pytest
from fastapi.testclient import TestClient

from local_delegate import config
from local_delegate.web import metrics

MODELS = "http://test-backend/v1/models"
RUNNING = "http://test-backend/running"
STARTING = {"running": [{"model": "gemma4-26b-a4b", "state": "starting"}]}


class _SlowModelsBackend:
    """A llama-swap double on loopback: `/v1/models` holds its answer, `/running` answers at once."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.paths: list[str] = []
        double = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                double.paths.append(self.path)
                if self.path == "/v1/models":
                    double.release.wait(10)  # far beyond the probe's read deadline of the test
                    body = {"data": [{"id": "gemma4-26b-a4b"}]}
                elif self.path == "/running":
                    body = STARTING
                else:
                    self.send_error(404)
                    return
                payload = json.dumps(body).encode()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except OSError:
                    pass  # the probe gave up and closed: that is the case under test

            def log_message(self, *args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def __enter__(self) -> Self:
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


def test_a_slow_models_probe_still_reports_the_model_that_is_starting(monkeypatch):
    """The repro of the issue with a slow double: `/v1/models` does not answer within the probe's
    read deadline while `/running` shows a model in `starting`."""
    monkeypatch.setattr(config, "PROBE_READ_TIMEOUT", 0.3)
    with _SlowModelsBackend() as double:
        monkeypatch.setattr(config, "BASE_URL", double.base_url)
        started = time.monotonic()

        j = TestClient(metrics.app).get("/api/backend").json()

        elapsed = time.monotonic() - started
        # Guard: the probe did fail the way the issue describes (connected, no answer in time).
        assert j["available"] is False
        assert j["cause"] == "no_response"
        assert double.paths[0] == "/v1/models"
        assert j["running"] == STARTING["running"]
        assert j["running_ok"] is True
        # One read deadline for `/v1/models` plus a `/running` that answers at once.
        assert elapsed < 3.0


@backend_mock.mock
@pytest.mark.parametrize(
    "models_answer",
    [
        {"side_effect": httpx2.ReadTimeout("timed out")},
        {"return_value": httpx2.Response(503)},
        {"return_value": httpx2.Response(200, json={"object": "list"})},
    ],
    ids=["no_response", "http_error", "invalid_response"],
)
def test_running_is_asked_when_the_backend_accepted_the_connection(
    monkeypatch, models_answer, request
):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get(MODELS).mock(**models_answer)
    running_route = backend_mock.get(RUNNING).mock(return_value=httpx2.Response(200, json=STARTING))

    j = TestClient(metrics.app).get("/api/backend").json()

    assert j["available"] is False
    assert j["cause"] == request.node.callspec.id
    assert running_route.call_count == 1
    assert j["running"] == STARTING["running"]
    assert j["running_ok"] is True


def _refused() -> httpx2.ConnectError:
    error = httpx2.ConnectError("refused")
    error.__cause__ = ConnectionRefusedError(111, "Connection refused")
    return error


@backend_mock.mock
@pytest.mark.parametrize(
    ("models_answer", "cause"),
    [
        ({"side_effect": _refused()}, "refused"),
        ({"side_effect": httpx2.ConnectTimeout("timed out")}, "connect_timeout"),
        ({"side_effect": httpx2.ConnectError("down")}, "transport"),
        ({"return_value": httpx2.Response(401)}, "credential"),
    ],
    ids=["refused", "connect_timeout", "transport", "credential"],
)
def test_running_is_not_asked_when_the_backend_is_not_there(monkeypatch, models_answer, cause):
    """REQ-013 holds: a backend that is off is «down» after ONE deadline. And a rejected credential
    would be rejected by `/running` too."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get(MODELS).mock(**models_answer)
    running_route = backend_mock.get(RUNNING).mock(return_value=httpx2.Response(200, json=STARTING))

    j = TestClient(metrics.app).get("/api/backend").json()

    assert j["available"] is False
    assert j["cause"] == cause
    assert running_route.call_count == 0
    assert j["running"] == []
    assert j["running_ok"] is False


@backend_mock.mock
def test_a_failed_probe_with_a_running_that_fails_too_reports_nothing(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get(MODELS).mock(side_effect=httpx2.ReadTimeout("timed out"))
    backend_mock.get(RUNNING).mock(side_effect=httpx2.ReadTimeout("timed out"))

    j = TestClient(metrics.app).get("/api/backend").json()

    assert j["available"] is False
    assert j["running"] == []
    assert j["running_ok"] is False
