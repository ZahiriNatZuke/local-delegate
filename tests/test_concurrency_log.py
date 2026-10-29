"""Concurrency PC+Mac, step 0: what the usage log says about who waited for whom.

Each entry carries the machine of origin (`host`) and, when the operation went through the backend,
`concurrency`: the UTC start and end of each phase (turn, slot, backend), the requested model, what
llama-swap had loaded before the first POST and whether the call needed a swap. Every request to
the backend carries `X-Local-Delegate-Host`, and the daemon reads that header (and only that one)
from llama-swap's `inflight` photo. Spec: `.sdd/changes/concurrencia-pc-mac/spec-step0.md`.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import backend_mock
import httpx2
import pytest
from fastapi.testclient import TestClient
from test_fallback import _text

from local_delegate import concurrency, config, llamaswap_api, server, turn
from local_delegate.web import metrics

CHAT = "http://test-backend/v1/chat/completions"
RUNNING = "http://test-backend/running"
MODEL = "gemma4-26b-a4b"  # the `long` role in the test catalog is not needed: any text model


@pytest.fixture(autouse=True)
def fresh_running_cache(monkeypatch):
    """Empty `/running` cache, and the sample taken at once (the delayed path has its own tests)."""
    concurrency.reset_cache()
    monkeypatch.setattr(concurrency, "BACKEND_SAMPLE_DELAY_S", 0)
    yield
    concurrency.reset_cache()


def _events(tmp_path: Path) -> list[dict]:
    lines: list[str] = []
    for file in sorted(tmp_path.glob("usage*.jsonl")):
        lines += file.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _ok_answer(seen: list[httpx2.Request] | None = None):
    def respond(request: httpx2.Request) -> httpx2.Response:
        if seen is not None:
            seen.append(request)
        return backend_mock.chat_response("resumen", tokens_in=10, tokens_out=5)

    backend_mock.post(CHAT).mock(side_effect=respond)


# --- the machine name ------------------------------------------------------------------------


def test_machine_name_override_is_cleaned(monkeypatch):
    monkeypatch.setattr(config, "MACHINE_NAME_OVERRIDE", " other host\r\nX: y ")
    assert config.machine_name() == "otherhostXy"


def test_machine_name_defaults_to_the_short_host_name(monkeypatch):
    import socket

    monkeypatch.setattr(config, "MACHINE_NAME_OVERRIDE", "")
    monkeypatch.setattr(socket, "gethostname", lambda: "other-host.local")
    assert config.machine_name() == "other-host"


def test_machine_name_never_empty(monkeypatch):
    import socket

    monkeypatch.setattr(config, "MACHINE_NAME_OVERRIDE", "")
    monkeypatch.setattr(socket, "gethostname", lambda: "...")
    assert config.machine_name() == "unknown"


def test_backend_headers_add_the_origin_and_keep_the_credential(monkeypatch):
    monkeypatch.setattr(config, "MACHINE_NAME_OVERRIDE", "pc")
    monkeypatch.setattr(config, "API_KEY", "secret-value")
    assert config.backend_headers() == {
        "Authorization": "Bearer secret-value",
        config.HOST_HEADER: "pc",
    }
    # The credential-only headers stay as they were (the daemon's panel and the CLI use them).
    assert config.auth_headers() == {"Authorization": "Bearer secret-value"}


# --- the log entry ---------------------------------------------------------------------------


@backend_mock.mock
def test_every_post_carries_the_origin_header(reload_config, tmp_path, monkeypatch):
    reload_config(LOCAL_DELEGATE_MACHINE_NAME="other-host")
    seen: list[httpx2.Request] = []
    _ok_answer(seen)
    backend_mock.get(RUNNING).mock(return_value=httpx2.Response(200, json={"running": None}))

    server.local_summarize(text=_text(2_000))

    assert seen, "the backend was never called"
    assert seen[-1].headers.get(config.HOST_HEADER) == "other-host"


@backend_mock.mock
def test_the_entry_has_host_phases_and_the_model_loaded_before(reload_config, tmp_path):
    reload_config(LOCAL_DELEGATE_MACHINE_NAME="other-host")
    _ok_answer()
    running = backend_mock.get(RUNNING).mock(
        return_value=httpx2.Response(
            200, json={"running": [{"model": "qwen36-35b-a3b", "state": "ready"}]}
        )
    )

    server.local_summarize(text=_text(2_000))

    event = _events(tmp_path)[-1]
    assert event["host"] == "other-host"
    trace = event["concurrency"]
    asked = trace["requested_model"]
    assert asked == event["model"]
    # Remote test backend: no turn, but a slot and a POST.
    assert set(trace["phases"]) == {"slot", "backend"}
    for phase in trace["phases"].values():
        start = datetime.fromisoformat(phase["start"])
        end = datetime.fromisoformat(phase["end"])
        assert start.utcoffset().total_seconds() == 0 and start <= end
        assert phase["n"] == 1 and phase["ms"] >= 0
    assert trace["phases"]["slot"]["end"] <= trace["phases"]["backend"]["start"]
    assert trace["backend_models"] == {"qwen36-35b-a3b": "ready"}
    # Another model was loaded: this call made llama-swap swap.
    assert trace["model_swap"] is True
    assert running.call_count == 1
    # The `/running` query carries the origin too.
    assert running.calls.last.request.headers.get(config.HOST_HEADER) == "other-host"


@backend_mock.mock
def test_no_swap_when_the_requested_model_was_ready(reload_config, tmp_path):
    reload_config()
    _ok_answer()
    server.local_summarize(text=_text(500))  # learns the model the role resolves to
    model = _events(tmp_path)[-1]["model"]
    concurrency.reset_cache()
    backend_mock.get(RUNNING).mock(
        return_value=httpx2.Response(200, json={"running": [{"model": model, "state": "ready"}]})
    )

    server.local_summarize(text=_text(500))

    assert _events(tmp_path)[-1]["concurrency"]["model_swap"] is False


@backend_mock.mock
def test_a_fast_call_asks_llama_swap_nothing(reload_config, tmp_path, monkeypatch):
    """With the real delay, a POST that answers at once never queries `/running` (the daemon
    does not ask llama-swap without a need: `test_affinity` pins it)."""
    reload_config()
    monkeypatch.setattr(concurrency, "BACKEND_SAMPLE_DELAY_S", 3.0)
    _ok_answer()
    running = backend_mock.get(RUNNING).mock(
        return_value=httpx2.Response(200, json={"running": []})
    )

    server.local_summarize(text=_text(500))

    assert running.call_count == 0
    assert "backend_models" not in _events(tmp_path)[-1]["concurrency"]


@backend_mock.mock
def test_a_waiting_call_samples_running_while_it_waits(reload_config, tmp_path, monkeypatch):
    reload_config()
    monkeypatch.setattr(concurrency, "BACKEND_SAMPLE_DELAY_S", 0.05)

    def slow(_request):
        time.sleep(0.4)
        return backend_mock.chat_response("resumen", tokens_in=10, tokens_out=5)

    backend_mock.post(CHAT).mock(side_effect=slow)
    backend_mock.get(RUNNING).mock(
        return_value=httpx2.Response(
            200, json={"running": [{"model": "qwen36-35b-a3b", "state": "ready"}]}
        )
    )

    server.local_summarize(text=_text(500))

    trace = _events(tmp_path)[-1]["concurrency"]
    assert trace["backend_models"] == {"qwen36-35b-a3b": "ready"}
    assert trace["backend_models_at_ms"] == 50
    assert trace["model_swap"] is True


@backend_mock.mock
def test_without_running_the_fields_are_left_out_and_the_call_works(reload_config, tmp_path):
    reload_config()
    _ok_answer()
    backend_mock.get(RUNNING).mock(return_value=httpx2.Response(404, text="no"))

    out = server.local_summarize(text=_text(500))

    event = _events(tmp_path)[-1]
    assert event["ok"] is True and "resumen" in out
    assert "backend_models" not in event["concurrency"]
    assert "model_swap" not in event["concurrency"]
    assert "backend" in event["concurrency"]["phases"]


@backend_mock.mock
def test_running_is_cached_between_close_calls(reload_config, tmp_path):
    reload_config()
    _ok_answer()
    running = backend_mock.get(RUNNING).mock(
        return_value=httpx2.Response(200, json={"running": []})
    )
    server.local_summarize(text=_text(500))
    server.local_summarize(text=_text(500))
    assert running.call_count == 1


def test_an_entry_without_an_operation_still_has_the_host(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MACHINE_NAME_OVERRIDE", "pc")
    server._log_event(
        tool="local_status",
        model="",
        source="inline",
        chars_in=0,
        chars_out=0,
        latency_ms=1,
        ok=True,
    )
    event = _events(tmp_path)[-1]
    assert event["host"] == "pc"
    assert "concurrency" not in event


# --- the turn phase --------------------------------------------------------------------------


def test_a_turn_wait_is_recorded_with_its_duration():
    op = server._OperationTurn(1, MODEL, "local_summarize")

    def wait(_on_wait, _stop):
        time.sleep(0.05)
        return turn.Grant(op.op_id, frozenset({MODEL}))

    op._waiting_for(server._turn, wait)

    phases = op.log_fields()["concurrency_trace"]["phases"]
    assert phases["turn"]["ms"] >= 40 and phases["turn"]["n"] == 1


def test_phases_aggregate_first_start_last_end_and_sum():
    trace = concurrency.Trace("m")
    trace.record("slot", 100.0, 101.0, 1000)
    trace.record("slot", 105.0, 105.5, 500)
    slot = trace.log_fields()["phases"]["slot"]
    assert slot["ms"] == 1500 and slot["n"] == 2
    assert slot["start"].startswith("1970-01-01T00:01:40.000")
    assert slot["end"].startswith("1970-01-01T00:01:45.500")


def test_phase_without_a_trace_does_nothing():
    import contextvars

    def body():
        with concurrency.phase("slot"):
            return 7

    assert contextvars.Context().run(body) == 7


# --- foreign requests in llama-swap's inflight ------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Local-Delegate-Host": ["other-host"], "Authorization": ["Bearer fake-key"]},
        {"x-local-delegate-host": "other-host", "Authorization": "Bearer fake-key"},
    ],
)
def test_inflight_requests_read_only_the_origin_header(headers):
    data = {"requests": [{"model": "a", "req_headers": headers}, {"model": "b", "req_headers": {}}]}
    found = llamaswap_api._requests_of(data)
    assert found == [{"model": "a", "host": "other-host"}, {"model": "b", "host": None}]
    assert "fake-key" not in json.dumps(found)


def test_the_operation_keeps_the_inflight_it_saw():
    op = server._OperationTurn(1, MODEL, "local_summarize")
    concurrency.note_inflight([{"model": "a", "host": "other-host"}])
    assert op.log_fields()["concurrency_trace"]["inflight_seen"] == [
        {"model": "a", "host": "other-host"}
    ]


# --- compatibility -----------------------------------------------------------------------------


def test_stats_read_old_and_new_entries_together(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    base = {"tool": "local_summarize", "model": "m", "chars_out": 10, "ok": True, "chars_in": 100}
    new = {
        **base,
        "ts": "2026-07-20T11:00:00+00:00",
        "host": "other-host",
        "concurrency": {
            "requested_model": "m",
            "phases": {
                "backend": {
                    "start": "2026-07-20T10:59:59.000+00:00",
                    "end": "2026-07-20T11:00:00.000+00:00",
                    "ms": 1000,
                    "n": 1,
                }
            },
            "backend_models": {"m": "ready"},
            "model_swap": False,
        },
    }
    (tmp_path / "usage-202607.jsonl").write_text(
        json.dumps({**base, "ts": "2026-07-20T10:00:00+00:00"}) + "\n" + json.dumps(new) + "\n",
        encoding="utf-8",
    )
    metrics._FILE_CACHE.clear()
    client = TestClient(metrics.app)
    stats = client.get("/api/stats?from=2026-07-01T00:00:00Z&to=2026-07-31T00:00:00Z")
    assert stats.status_code == 200
    assert sum(b["calls"] for b in stats.json()["by_backend"]) == 2
    assert (
        client.get("/api/events?from=2026-07-01T00:00:00Z&to=2026-07-31T00:00:00Z").json()["meta"][
            "count"
        ]
        == 2
    )


class _Snapshot:
    """The bits of `topology.Snapshot` that `_affinity_observe` reads."""

    clashes = staticmethod(lambda a, b: a != b)

    def resolve(self, model):
        return model

    def effective_ttl(self, _model):
        return None


def test_the_affinity_photo_feeds_inflight_seen(monkeypatch):
    """Where the daemon already reads `inflight` (affinity), the requests go into the trace."""
    monkeypatch.setattr(llamaswap_api, "running", lambda *a, **k: [])
    monkeypatch.setattr(
        llamaswap_api,
        "in_flight_requests",
        lambda *a, **k: [{"model": "a", "host": "other-host"}, {"model": "a", "host": None}],
    )
    op = server._OperationTurn(1, MODEL, "local_summarize")
    observed = server._affinity_observe(["a"], _Snapshot())
    assert observed.in_flight == {"a": 2}
    assert op.log_fields()["concurrency_trace"]["inflight_seen"] == [
        {"model": "a", "host": "other-host"},
        {"model": "a", "host": None},
    ]


# --- origin of a request over the daemon's /mcp -------------------------------------------------


class _Peer:
    def __init__(self, host):
        self.host = host


class _Request:
    """The bits of a Starlette request that `clients.origin_from_request` reads."""

    def __init__(self, peer, **headers):
        from starlette.datastructures import Headers

        self.client = _Peer(peer) if peer is not None else None
        self.headers = Headers({k.replace("_", "-"): v for k, v in headers.items()})


@pytest.mark.parametrize(
    ("request_", "expected"),
    [
        (
            _Request("100.64.0.7", **{"X-Local-Delegate-Host": "other-host"}),
            ("other-host", "header"),
        ),
        (
            _Request("127.0.0.1", x_forwarded_for="100.64.0.7, 10.0.0.1"),
            ("100.64.0.7", "forwarded"),
        ),
        (_Request("100.64.0.7"), ("100.64.0.7", "ip")),
        (_Request("127.0.0.1"), None),
        (_Request("100.64.0.7", x_forwarded_for="1.2.3.4"), ("100.64.0.7", "ip")),
        (None, None),
    ],
)
def test_origin_of_an_http_request(request_, expected):
    from local_delegate import clients

    assert clients.origin_from_request(request_) == expected


def _with_origin(origin, fn):
    import contextvars

    from local_delegate import clients

    def body():
        clients._CURRENT_ORIGIN.set(origin)
        return fn()

    return contextvars.copy_context().run(body)


def test_a_call_from_another_machine_logs_its_own_host(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MACHINE_NAME_OVERRIDE", "pc")
    _with_origin(
        ("other-host", "header"),
        lambda: server._log_event(
            tool="local_summarize",
            model="m",
            source="inline",
            chars_in=1,
            chars_out=1,
            latency_ms=1,
            ok=True,
        ),
    )
    event = _events(tmp_path)[-1]
    assert event["host"] == "other-host" and event["host_via"] == "header"


def test_the_inflight_entry_says_where_the_call_came_from(monkeypatch):
    monkeypatch.setattr(config, "MACHINE_NAME_OVERRIDE", "pc")

    def start_and_read():
        entry_id = server._inflight_start(tool="t", model="m", source="inline", chars_in=1)
        try:
            return [e for e in server.inflight_snapshot() if e.get("tool") == "t"]
        finally:
            server._inflight_end(entry_id)

    remote = _with_origin(("100.64.0.7", "ip"), start_and_read)
    local = _with_origin(None, start_and_read)
    assert remote[0]["host"] == "100.64.0.7" and remote[0]["host_via"] == "ip"
    # A local call keeps today's keys (the panel's tests pin them): no `host` means this machine.
    assert "host" not in local[0] and "host_via" not in local[0]


def test_the_mcp_middleware_reads_the_origin_of_the_request():
    """`observe_client` sets the origin before the tool runs, as it does with the client name."""
    import asyncio
    import contextvars
    from types import SimpleNamespace

    from local_delegate import clients

    ctx = SimpleNamespace(
        method="tools/call",
        session=None,
        params={},
        meta=None,
        request=_Request("100.64.0.7", **{"X-Local-Delegate-Host": "other-host"}),
    )

    async def call_next(_ctx):
        return clients.current_origin()

    seen = contextvars.Context().run(asyncio.run, clients.observe_client(ctx, call_next))
    assert seen == ("other-host", "header")
