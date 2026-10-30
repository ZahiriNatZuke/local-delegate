"""Concurrency PC+Mac, lot 3: the daemon's turn endpoint (`/api/turn/*`, REQ-010..017, REQ-030).

Over the real app (`daemon.build_app`) with TestClient, a loopback `Host` (the port's guard refuses
`testserver`) and the suite's isolated environment (`LOG_DIR` in `tmp_path`, no real keychain). The
topology is today's (`tests/fixtures/topology/today.yaml`, every model in one `swap` group: they
all clash), copied to `tmp_path`.

A "local" operation is driven straight on `server._turn` with its non-blocking API and an id
shaped like a local one (`<pid>:<n>`); a remote one goes through HTTP. Threads always wait with
their own cap and fail with their own message.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from local_delegate import config, daemon, server, turn, turn_leases
from local_delegate.turn import PendingRequest
from local_delegate.web import auth, metrics, turn_api

_LOCAL = "http://127.0.0.1:19393"
BASE = "http://127.0.0.1:9292/v1"
TODAY = Path(__file__).parent / "fixtures" / "topology" / "today.yaml"
LONG = "gemma4-26b-a4b"
CODE = "qwen36-35b-a3b"
SMALL = "gemma3-4b"
BACKEND_KEY = "the-backend-key-0123456789"
PORT_TOKEN = "the-port-token-0123456789"
ACQUIRE = auth.TURN_ACQUIRE_PATH
HEARTBEAT = auth.TURN_HEARTBEAT_PATH
RELEASE = auth.TURN_RELEASE_PATH


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Topology on loopback, the backend key as the only secret, a fresh turn and lease table."""
    copy = tmp_path / "llamaswap.yaml"
    copy.write_bytes(TODAY.read_bytes())
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(copy))
    monkeypatch.setattr(config, "BASE_URL", BASE)
    monkeypatch.setattr(config, "API_KEY", BACKEND_KEY)
    monkeypatch.setattr(config, "WEB_TOKEN", "")
    monkeypatch.setattr(config, "TURN_SERVER", True)
    monkeypatch.setattr(config, "TURN_LEASE_S", 30.0)
    monkeypatch.setattr(config, "TURN_MAX_LEASES", 16)
    # Short long waits: a queued answer comes back in 0.2 s (the long-wait tests put 5 s back).
    monkeypatch.setattr(turn_leases, "MAX_HEARTBEAT_S", 0.2)
    use_turn(monkeypatch, server._new_turn())
    turn_leases.reset()
    yield tmp_path
    turn_leases.reset()
    turn_api.disable()  # `daemon.build_app` enabled it for this process: other tests start clean


def use_turn(monkeypatch, turn_state: turn.Turn) -> turn.Turn:
    monkeypatch.setattr(server, "_turn", turn_state)
    # The next topology photo applies its clashes to THIS turn (REQ-009).
    monkeypatch.setattr(server._turn_version, "value", None)
    server._topology()
    return turn_state


@pytest.fixture
def client(env):
    with TestClient(daemon.build_app("127.0.0.1", 19393), base_url=_LOCAL) as c:
        yield c


@pytest.fixture
def port_client(env, monkeypatch):
    """The app built WITH a port token: `PortToken` wraps it (it is decided at build time)."""
    monkeypatch.setattr(config, "WEB_TOKEN", PORT_TOKEN)
    with TestClient(daemon.build_app("127.0.0.1", 19393), base_url=_LOCAL) as c:
        yield c


def _bearer(secret: str = BACKEND_KEY) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def _acquire_body(op: str = "op1", host: str = "mac", model: str = LONG, **extra) -> dict:
    body = {"op": op, "host": host, "tool": "local_summarize", "model": model, "role": "long"}
    body.update(extra)
    return body


def _acquire(c: TestClient, op: str = "op1", host: str = "mac", model: str = LONG, **extra):
    return c.post(ACQUIRE, json=_acquire_body(op, host, model, **extra), headers=_bearer())


def _beat(c: TestClient, lease: str, **fields):
    return c.post(HEARTBEAT, json={"lease": lease, **fields}, headers=_bearer())


def _release(c: TestClient, lease: str):
    return c.post(RELEASE, json={"lease": lease}, headers=_bearer())


def _local(op_id: str, model: str) -> object:
    """A local operation asks for the turn (no thread: the non-blocking API)."""
    return server._turn.enqueue(PendingRequest(op_id, frozenset({model}), model))


def _entry(op_key: str) -> dict | None:
    return next((e for e in server.inflight_snapshot() if e["id"] == op_key), None)


def _wait(condition: Callable[[], object], cap: float = 3.0) -> object:
    end = time.monotonic() + cap
    while time.monotonic() < end:
        value = condition()
        if value:
            return value
        time.sleep(0.01)
    return None


class _Thread(threading.Thread):
    def __init__(self, function: Callable, *args) -> None:
        super().__init__(daemon=True)
        self._call = (function, args)
        self.result: object = None
        self.error: BaseException | None = None

    def run(self) -> None:
        function, args = self._call
        try:
            self.result = function(*args)
        except BaseException as e:  # the test looks at it
            self.error = e


# --- authentication (REQ-016) ---------------------------------------------------------------


def test_without_any_secret_the_endpoint_refuses_with_403(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "")
    response = _acquire(client)
    assert response.status_code == 403
    assert response.json() == {"error": "turn_needs_secret"}


def test_the_backend_key_and_the_port_token_open_it_and_a_wrong_one_does_not(port_client):
    assert _acquire(port_client).status_code == 200  # the backend key
    ok = port_client.post(ACQUIRE, json=_acquire_body("op2"), headers=_bearer(PORT_TOKEN))
    assert ok.status_code == 200
    wrong = port_client.post(ACQUIRE, json=_acquire_body("op3"), headers=_bearer("not-the-secret"))
    assert wrong.status_code == 401
    assert wrong.json() == {"error": "unauthorized"}
    assert port_client.post(ACQUIRE, json=_acquire_body("op4")).status_code == 401  # nothing


def test_the_port_token_is_the_one_the_port_guard_got_at_build_time(port_client, monkeypatch):
    """A token rotated after the start does not open the routes while `PortToken` has the old one."""
    monkeypatch.setattr(config, "API_KEY", "")
    monkeypatch.setattr(config, "WEB_TOKEN", "rotated-token-0123456789")
    old = port_client.post(ACQUIRE, json=_acquire_body(), headers=_bearer(PORT_TOKEN))
    assert old.status_code == 200
    new = port_client.post(
        ACQUIRE, json=_acquire_body("op2"), headers=_bearer("rotated-token-0123456789")
    )
    assert new.status_code == 401
    assert (
        port_client.get("/api/daemon", headers=_bearer("rotated-token-0123456789")).status_code
        == 401
    )


def test_the_auth_dependency_is_sync():
    """It reads the backend key (on macOS, maybe the Keychain): never on the event loop."""
    import inspect

    assert not inspect.iscoroutinefunction(turn_api._require_turn_client)


def test_a_stdio_process_does_not_serve_the_endpoint(env):
    """Only `daemon.build_app` enables it: the stdio web (`metrics.app`) answers 404."""
    turn_api.disable()
    with TestClient(metrics.app, base_url=_LOCAL) as c:
        response = _acquire(c)
        assert response.status_code == 404
        assert turn_leases.table().live() == 0
    with TestClient(daemon.build_app("127.0.0.1", 19393), base_url=_LOCAL) as c:
        assert _acquire(c).status_code == 200  # guard: the daemon's app does serve it


def test_basic_with_a_valid_secret_is_refused(client):
    raw = base64.b64encode(f"user:{BACKEND_KEY}".encode()).decode()
    response = client.post(ACQUIRE, json=_acquire_body(), headers={"Authorization": f"Basic {raw}"})
    assert response.status_code == 401


def test_a_valid_session_cookie_is_refused(port_client, monkeypatch):
    session = auth.create_session(PORT_TOKEN, 3600)
    port_client.cookies.set(auth.COOKIE, session)
    try:
        # The cookie opens the rest of the port (guard: it IS a valid session)...
        assert port_client.get("/api/daemon").status_code == 200
        # ...but not the turn routes.
        assert port_client.post(ACQUIRE, json=_acquire_body()).status_code == 401
    finally:
        port_client.cookies.clear()


def test_an_origin_header_is_refused(client):
    response = client.post(
        ACQUIRE, json=_acquire_body(), headers={**_bearer(), "Origin": "http://127.0.0.1:19393"}
    )
    assert response.status_code == 403


def test_without_json_it_is_415_and_bad_json_is_400(client):
    plain = client.post(
        ACQUIRE, content=b"op=1", headers={**_bearer(), "Content-Type": "text/plain"}
    )
    assert plain.status_code == 415
    bad = client.post(
        ACQUIRE, content=b"{not json", headers={**_bearer(), "Content-Type": "application/json"}
    )
    assert bad.status_code == 400
    assert client.post(ACQUIRE, json=[1, 2], headers=_bearer()).status_code == 400


def test_with_a_port_token_the_backend_key_opens_only_the_three_routes(port_client, monkeypatch):
    granted = _acquire(port_client).json()
    assert granted["status"] == "granted"
    assert _beat(port_client, granted["lease"]).status_code == 200
    assert _release(port_client, granted["lease"]).status_code == 200
    assert port_client.get("/api/inflight", headers=_bearer()).status_code == 401
    mcp = port_client.post("/mcp", json={}, headers={**_bearer(), "Accept": "application/json"})
    assert mcp.status_code == 401


# --- the PortToken exemption: enumeration and variants ----------------------------------------


def _flat_routes() -> list:
    """The dashboard's routes, with included routers opened (FastAPI keeps them nested)."""
    found = []
    for route in metrics.app.routes:
        candidates = getattr(route, "effective_candidates", None)
        if callable(candidates):
            found.extend(candidates())
        else:
            found.append(route)
    return found


def _app_routes() -> list[tuple[str, str]]:
    """(method, path) of every route the daemon serves: the MCP app's and the dashboard's."""
    found: list[tuple[str, str]] = [("GET", "/api/daemon"), ("POST", "/mcp"), ("GET", "/mcp")]
    for route in _flat_routes():
        path = getattr(route, "path", None)
        for method in sorted(getattr(route, "methods", None) or ()):
            if path:
                found.append((method, path))
    return found


def test_the_turn_routes_are_exactly_three_and_all_carry_the_dependency():
    turn_routes = [r for r in _flat_routes() if getattr(r, "path", "").startswith("/api/turn")]
    pairs = {(m, r.path) for r in turn_routes for m in r.methods}
    assert pairs == set(auth.TURN_ROUTES)
    for route in turn_routes:
        # What actually runs: the solved dependencies, not only the declared ones.
        calls = [d.call for d in route.dependant.dependencies]
        assert turn_api._require_turn_client in calls, route.path
    # Guard: the enumeration sees the rest of the dashboard too.
    assert ("GET", "/api/inflight") in _app_routes()


def test_every_other_route_still_asks_for_the_port_token(port_client, monkeypatch):
    checked = 0
    for method, path in _app_routes():
        if (method, path) in auth.TURN_ROUTES or method == "HEAD":
            continue
        concrete = path.replace("{wid}", "x").replace("{", "").replace("}", "")
        response = port_client.request(method, concrete, headers=_bearer())  # the backend key
        assert response.status_code == 401, f"{method} {path} skipped the port token"
        assert "token del puerto" in response.text, f"{method} {path}: not PortToken's 401"
        checked += 1
    assert checked >= 20  # guard: the enumeration reached the dashboard's routes


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/turn/x"),
        ("POST", "/api/turn/acquire/"),
        ("POST", "/api/turn/../inflight"),
        ("POST", "/api/turn/%2e%2e/inflight"),
        ("POST", "//api/turn/acquire"),
        ("GET", "/api/turn/acquire"),
        ("PUT", "/api/turn/heartbeat"),
        ("POST", "/api/turn"),
        ("POST", "/api/turn/acquirex"),
    ],
)
def test_route_variants_still_ask_for_the_port_token(port_client, monkeypatch, method, path):
    response = port_client.request(method, _LOCAL + path, json=_acquire_body(), headers=_bearer())
    assert response.status_code == 401, f"{method} {path}"
    assert "token del puerto" in response.text


def test_the_exemption_is_exact():
    assert auth.is_exempt("POST", "/api/turn/acquire")
    assert not auth.is_exempt("POST", "/api/turn/acquire/")
    assert not auth.is_exempt("GET", "/api/turn/acquire")
    assert not auth.is_exempt("POST", "/api/turn/x")


# --- cycle (REQ-010, REQ-011, REQ-014) --------------------------------------------------------


def test_free_turn_is_granted_and_visible_as_running(client):
    answer = _acquire(client).json()
    assert answer["status"] == "granted"
    assert answer["v"] == turn_leases.API_VERSION
    assert answer["model"] == LONG
    assert answer["daemon_id"] == turn_leases.DAEMON_ID
    assert len(answer["lease"]) >= 43  # 32 random bytes, url-safe base64
    entry = _entry("remote:mac/op1")
    assert entry is not None
    assert (entry["host"], entry["host_via"], entry["state"]) == ("mac", "lease", "running")
    assert _release(client, answer["lease"]).json()["status"] == "released"
    assert _entry("remote:mac/op1") is None
    assert server._turn.snapshot().actives == ()


def test_queued_behind_a_clashing_local_then_granted_during_the_long_wait(client, monkeypatch):
    monkeypatch.setattr(turn_leases, "MAX_HEARTBEAT_S", 5.0)
    assert isinstance(_local("111:1", CODE), turn.Grant)
    t0 = time.monotonic()
    waiting = _Thread(_acquire, client)
    waiting.start()
    entry = _wait(lambda: _entry("remote:mac/op1"))
    assert entry is not None, "the remote operation never showed up in inflight"
    assert entry["state"] == "queued"
    assert (entry["host"], entry["host_via"], entry["local_wait"]) == ("mac", "lease", "turn")
    assert _wait(lambda: (_entry("remote:mac/op1") or {}).get("queue_position") == 1)
    time.sleep(0.3)
    assert waiting.is_alive(), "the long wait did not wait"
    server._turn.release_slot("111:1")
    waiting.join(4.0)
    assert not waiting.is_alive(), "the long wait did not come back after the release"
    assert waiting.error is None
    answer = waiting.result.json()
    assert answer["status"] == "granted"
    assert time.monotonic() - t0 < 4.5  # before the 5 s bound: it answered on the change
    assert _entry("remote:mac/op1")["state"] == "running"
    _release(client, answer["lease"])
    assert _entry("remote:mac/op1") is None


def test_a_queued_answer_comes_back_by_heartbeat_s(client):
    assert isinstance(_local("111:1", CODE), turn.Grant)
    t0 = time.monotonic()
    answer = _acquire(client).json()
    assert answer["status"] == "queued"
    assert answer["position"] == 1
    assert answer["in_use"] == [CODE]
    assert 0.15 <= time.monotonic() - t0 < 2.0
    assert answer["heartbeat_s"] == 0.2
    assert answer["lease_s"] == 30.0


def test_heartbeat_fields_show_in_inflight(client):
    answer = _acquire(client, chunks=3).json()
    lease = answer["lease"]
    _beat(client, lease, in_backend=True, chunk=2, phase="reduce")
    entry = _entry("remote:mac/op1")
    assert (entry["chunks"], entry["chunk"], entry["phase"], entry["state"]) == (
        3,
        2,
        "reduce",
        "running",
    )
    _beat(client, lease, in_backend=True, waiting_backend={CODE: "ready"})
    assert _entry("remote:mac/op1")["state"] == "waiting_backend"
    assert _entry("remote:mac/op1")["backend_wait"] == {CODE: "ready"}
    _beat(client, lease, in_backend=False)
    assert _entry("remote:mac/op1")["state"] == "running"
    _release(client, lease)


# --- expiry (REQ-012) ------------------------------------------------------------------------


def test_without_heartbeat_the_lease_expires_out_of_queue_actives_and_inflight(client):
    clock = FakeClock()
    turn_leases.reset(clock=clock)
    assert isinstance(_local("111:1", CODE), turn.Grant)
    queued = _acquire(client, op="q").json()
    granted_local_free = queued["status"] == "queued"
    assert granted_local_free
    server._turn.release_slot("111:1")
    assert isinstance(_local("111:2", SMALL), tuple)  # behind the remote one now granted
    state = server._turn.snapshot()
    assert state.active("mac/q") is not None
    clock.advance(31)
    assert turn_leases.table().reap() == 1
    state = server._turn.snapshot()
    assert state.active("mac/q") is None and state.queued("mac/q") is None
    assert _entry("remote:mac/q") is None
    # What waited behind it got the turn on the spot.
    assert isinstance(server._turn.poll("111:2"), turn.Grant)
    assert _beat(client, queued["lease"]).json()["status"] == "expired"


def test_a_queued_lease_expires_out_of_the_queue(client):
    clock = FakeClock()
    turn_leases.reset(clock=clock)
    assert isinstance(_local("111:1", CODE), turn.Grant)
    assert _acquire(client, op="q").json()["status"] == "queued"
    clock.advance(31)
    assert _beat(client, "unrelated-lease").json()["status"] == "expired"  # every request reaps
    assert server._turn.snapshot().queued("mac/q") is None
    assert _entry("remote:mac/q") is None


def test_an_unknown_lease_is_expired_and_release_is_idempotent(client):
    answer = _beat(client, "never-issued").json()
    assert answer["status"] == "expired" and answer["lease"] is None
    assert answer["daemon_id"] == turn_leases.DAEMON_ID
    assert _release(client, "never-issued").json() == {
        "v": turn_leases.API_VERSION,
        "daemon_id": turn_leases.DAEMON_ID,
        "status": "released",
    }


def test_a_local_tick_reaps_expired_leases(client):
    clock = FakeClock()
    turn_leases.reset(clock=clock)
    assert _acquire(client).json()["status"] == "granted"
    clock.advance(31)
    server._refresh_topology()  # the hook every local turn wait calls on each tick
    assert turn_leases.table().live() == 0
    assert _entry("remote:mac/op1") is None


def test_a_local_wait_behind_a_remote_one_is_not_saturated_while_remote_events_move(
    client, monkeypatch
):
    """REQ-012/REQ-024: the remote events move `_note_queue_progress` (#476)."""
    monkeypatch.setattr(config, "QUEUE_MAX_WAIT_S", 1.0)
    remote = _acquire(client).json()
    assert remote["status"] == "granted"
    operation = server._OperationTurn(9001, CODE, "local_summarize", role_name="code")
    waiting = _Thread(operation.ensure, CODE)
    waiting.start()
    assert _wait(lambda: server._turn.snapshot().queued(operation.op_id) is not None)
    end = time.monotonic() + 2.5
    flag = True
    while time.monotonic() < end:
        _beat(client, remote["lease"], in_backend=flag)
        flag = not flag
        time.sleep(0.25)
    assert waiting.is_alive(), f"the local wait left the queue: {waiting.error!r}"
    _release(client, remote["lease"])
    waiting.join(3.0)
    assert not waiting.is_alive()
    assert waiting.error is None, repr(waiting.error)
    operation.release_slot()


# --- yield (REQ-030, server side) -------------------------------------------------------------


def test_an_active_remote_that_ignores_yield_expires_at_the_cap_and_queues_at_the_end(
    client, monkeypatch
):
    clock = FakeClock()
    monkeypatch.setattr(config, "HTTP_TIMEOUT", 10.0)
    use_turn(
        monkeypatch,
        turn.Turn(lambda _a, _b: False, clock=clock, yield_s=120.0, turn_max_s=10_000.0),
    )
    turn_leases.reset(clock=clock)
    remote = _acquire(client).json()
    assert remote["status"] == "granted"
    assert isinstance(_local("111:1", CODE), tuple)  # the head, blocked by the remote one
    for _ in range(5):  # 100 s with a heartbeat every 20 s: the lease stays alive
        clock.advance(20)
        assert _beat(client, remote["lease"]).json()["status"] == "granted"  # not yet 120 s
    clock.advance(21)
    assert _beat(client, remote["lease"]).json()["status"] == "yield"
    cap = turn_leases.yield_cap_seconds()
    assert cap == pytest.approx(0.2 * 2 + 10.0)
    clock.advance(cap / 2)
    assert _beat(client, remote["lease"]).json()["status"] == "yield"  # still within the cap
    clock.advance(cap / 2 + 0.1)
    assert _beat(client, remote["lease"]).json()["status"] == "expired"
    assert isinstance(server._turn.poll("111:1"), turn.Grant)  # the head got it
    assert isinstance(_local("111:2", SMALL), tuple)  # someone else waits now
    again = _acquire(client).json()
    assert again["status"] == "queued"
    assert again["position"] == 2  # at the end, not back in its old place


def test_in_backend_blocks_the_forced_local_grant_until_the_lease_expires(client, monkeypatch):
    turn_clock = FakeClock()
    lease_clock = FakeClock()
    use_turn(
        monkeypatch,
        turn.Turn(lambda _a, _b: False, clock=turn_clock, yield_s=0.0, turn_max_s=600.0),
    )
    turn_leases.reset(clock=lease_clock)
    assert isinstance(_local("111:1", LONG), turn.Grant)  # a local active, no call in flight
    remote = _acquire(client, op="r", model=LONG).json()
    assert remote["status"] == "granted"  # same model: compatible
    _beat(client, remote["lease"], in_backend=True)
    assert isinstance(_local("111:2", CODE), tuple)
    turn_clock.advance(601)
    assert isinstance(server._turn.poll("111:2"), tuple)  # the remote call counts as flight
    lease_clock.advance(31)
    assert turn_leases.table().reap() == 1
    turn_clock.advance(601)
    grant = server._turn.poll("111:2")
    assert isinstance(grant, turn.Grant) and grant.forced  # once expired, it no longer counts


# --- no_turn, limits, cleaning, kill switch (REQ-011, REQ-017) --------------------------------


def test_no_turn_without_topology_or_with_an_unknown_model(client, monkeypatch):
    unknown = _acquire(client, model="not-a-model").json()
    assert (unknown["status"], unknown["lease"]) == ("no_turn", None)
    monkeypatch.delenv("LLAMASWAP_CONFIG")
    assert _acquire(client, op="op2").json()["status"] == "no_turn"
    assert turn_leases.table().live() == 0


def test_429_past_8_per_host_and_16_in_total(client):
    for i in range(8):
        assert _acquire(client, op=f"a{i}", host="mac").json()["status"] == "granted"
    over = _acquire(client, op="a8", host="mac")
    assert over.status_code == 429
    assert over.json() == {"error": "too_many_leases"}
    for i in range(8):
        assert _acquire(client, op=f"b{i}", host="mac2").status_code == 200
    assert _acquire(client, op="c0", host="mac3").status_code == 429


def test_bad_bodies(client):
    assert _acquire(client, host="///").status_code == 400  # empty once cleaned
    assert _acquire(client, op="").status_code == 400
    assert _acquire(client, surprise=1).status_code == 400  # extra="forbid"
    assert _acquire(client, chars_in="12").status_code == 400  # strict types
    big = client.post(ACQUIRE, json=_acquire_body(role="x" * 5000), headers=_bearer())
    assert big.status_code == 413
    assert _beat(client, "x", phase="other").status_code == 400


def test_names_are_cleaned(client):
    answer = _acquire(client, op="op 1;rm", host="mac<script>").json()
    assert answer["status"] == "granted"
    assert _entry("remote:macscript/op1rm") is not None


def test_turn_server_off_answers_404(client, monkeypatch):
    monkeypatch.setattr(config, "TURN_SERVER", False)
    old_daemon = client.post("/api/no-such-route", json={"lease": "x"}, headers=_bearer())
    assert old_daemon.status_code == 404  # guard: what a daemon without the endpoint answers
    for path in (ACQUIRE, HEARTBEAT, RELEASE):
        response = client.post(path, json={"lease": "x"}, headers=_bearer())
        assert response.status_code == 404
        assert response.json() == old_daemon.json()


# --- daemon_id, no usage event, no credential leaked (REQ-010, REQ-015, REQ-016) ---------------


def test_daemon_id_is_stable_and_new_on_another_start(client):
    first = client.get("/api/daemon").json()["daemon_id"]
    assert first == turn_leases.DAEMON_ID == _acquire(client).json()["daemon_id"]
    assert client.get("/api/daemon").json()["daemon_id"] == first
    code = "import local_delegate.turn_leases as t; print(t.DAEMON_ID)"
    other = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, env=os.environ
    )
    assert other.returncode == 0, other.stderr
    assert other.stdout.strip() and other.stdout.strip() != first


def test_no_usage_event_and_no_credential_in_answers_or_logs(port_client, env, monkeypatch):
    answers = [
        _acquire(port_client),
        port_client.post(ACQUIRE, json=_acquire_body("op2"), headers=_bearer("wrong-secret-xyz")),
        port_client.post(ACQUIRE, json=_acquire_body("op3"), headers=_bearer(PORT_TOKEN)),
    ]
    lease = answers[0].json()["lease"]
    answers.append(_beat(port_client, lease, in_backend=True))
    answers.append(_release(port_client, lease))
    for response in answers:
        for secret in (BACKEND_KEY, PORT_TOKEN, "wrong-secret-xyz"):
            assert secret not in response.text
    assert not list(env.glob("usage*.jsonl")) or all(
        not p.read_text(encoding="utf-8").strip() for p in env.glob("usage*.jsonl")
    )
    for path in env.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            for secret in (BACKEND_KEY, PORT_TOKEN, "wrong-secret-xyz"):
                assert secret not in text, path.name


# --- load ------------------------------------------------------------------------------------


def test_sixteen_long_waits_do_not_block_inflight(client, monkeypatch):
    monkeypatch.setattr(turn_leases, "MAX_HEARTBEAT_S", 5.0)
    assert isinstance(_local("111:1", CODE), turn.Grant)
    threads = [_Thread(_acquire, client, f"op{i}", f"host{i % 2}", LONG) for i in range(16)]
    for thread in threads:
        thread.start()
    assert _wait(lambda: turn_leases.table().live() == 16, cap=5.0), "not all 16 got a lease"
    time.sleep(0.2)
    assert all(t.is_alive() for t in threads), "the long waits did not wait"
    t0 = time.monotonic()
    response = client.get("/api/inflight")
    elapsed = time.monotonic() - t0
    assert response.status_code == 200
    assert elapsed < 1.0, f"/api/inflight took {elapsed:.2f} s with 16 long waits open"
    server._turn.release_slot("111:1")
    for thread in threads:
        thread.join(6.0)
    assert not any(t.is_alive() for t in threads)
    statuses = sorted(t.result.json()["status"] for t in threads)
    assert statuses == ["granted"] * 16


# --- review of #500: threadpool, deep JSON, pid, the local tick --------------------------------


def _pending_after(threads: list[_Thread], seconds: float) -> int:
    time.sleep(seconds)
    return sum(1 for t in threads if t.is_alive())


def test_many_heartbeats_on_one_queued_lease_open_one_long_wait(client, monkeypatch):
    """More than the threadpool's 40 workers on ONE lease: one waits, the rest answer at once."""
    monkeypatch.setattr(turn_leases, "MAX_HEARTBEAT_S", 5.0)
    assert isinstance(_local("111:1", CODE), turn.Grant)
    lease = _Thread(_acquire, client)
    lease.start()
    lease.join(7.0)  # its own long wait ends after 5 s, still queued
    answer = lease.result.json()
    assert answer["status"] == "queued"
    beats = [_Thread(_beat, client, answer["lease"]) for _ in range(60)]
    for beat in beats:
        beat.start()
    pending = _pending_after(beats, 1.0)
    t0 = time.monotonic()
    response = client.get("/api/inflight")
    elapsed = time.monotonic() - t0
    assert response.status_code == 200
    assert elapsed < 1.0, f"/api/inflight took {elapsed:.2f} s with 60 heartbeats open"
    assert pending <= 1, f"{pending} long waits open on one lease"
    server._turn.release_slot("111:1")
    for beat in beats:
        beat.join(6.0)
    assert not any(b.is_alive() for b in beats)
    assert all(b.result.status_code == 200 for b in beats)


def test_long_waits_have_a_global_cap(client, monkeypatch):
    monkeypatch.setattr(turn_leases, "MAX_HEARTBEAT_S", 5.0)
    monkeypatch.setattr(turn_leases, "MAX_LONG_WAITS", 4)
    turn_leases.reset()
    assert isinstance(_local("111:1", CODE), turn.Grant)
    acquires = [_Thread(_acquire, client, f"op{i}", f"host{i % 3}", LONG) for i in range(6)]
    for thread in acquires:
        thread.start()
    pending = _pending_after(acquires, 1.0)
    assert turn_leases.table().live() == 6  # guard: all six are queued with a lease
    assert pending == 4, f"{pending} long waits open with a cap of 4"
    server._turn.release_slot("111:1")
    for thread in acquires:
        thread.join(6.0)
    assert not any(t.is_alive() for t in acquires)


def test_deeply_nested_json_under_4_kb_is_a_400(client):
    body = b"[" * 2000 + b"]" * 2000
    response = client.post(
        ACQUIRE, content=body, headers={**_bearer(), "Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert response.json() == {"error": "bad_request"}


def test_the_remote_entry_has_the_daemons_pid(client):
    assert _acquire(client).json()["status"] == "granted"
    data = json.loads((config.LOG_DIR / "inflight.json").read_text(encoding="utf-8"))
    assert data["remote:mac/op1"]["pid"] == os.getpid()


def test_a_local_tick_does_not_wait_for_a_busy_table(client):
    assert _acquire(client).json()["status"] == "granted"  # registers the tick hook
    assert turn_leases._tick in server.TURN_TICK_HOOKS  # guard: the tick does reach the table
    table = turn_leases.table()
    held = threading.Event()
    done = threading.Event()

    def hold() -> None:
        with table._lock:
            held.set()
            done.wait(3.0)

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert held.wait(2.0)
    try:
        t0 = time.monotonic()
        server._refresh_topology()  # the hook of every local wait's tick
        elapsed = time.monotonic() - t0
    finally:
        done.set()
        holder.join(5.0)
    assert elapsed < 0.5, f"the local tick waited {elapsed:.2f} s for the lease table"
