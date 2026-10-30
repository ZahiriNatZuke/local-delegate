"""Concurrency PC+Mac, lot 4: the client of the remote turn (REQ-020..027, REQ-030 client side).

The daemon of lot 3 runs in this same process (`daemon.build_app` behind a `TestClient`, which is
an `httpx2.Client`) and is the client's transport: `remote_turn.set_client_factory`. One process
plays both machines:

- the PC's daemon: the topology of today (`tests/fixtures/topology/today.yaml`, every model in one
  `swap` group, so they all clash) on a loopback backend, and its lease table;
- the Mac: an `_OperationTurn` whose own topology is `NoTopology(remote backend)`
  (`server._operation_topology`, the seam for this) and whose `TURN_URL` names the daemon.

A "local" operation of the PC is driven straight on `server._turn` with its non-blocking API.
Threads always wait with their own cap and fail with their own message.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient

from local_delegate import (
    cancellation,
    config,
    daemon,
    remote_turn,
    server,
    topology,
    turn,
    turn_leases,
)
from local_delegate.turn import PendingRequest
from local_delegate.web import turn_api

_DAEMON_PORT = 19393
_URL = f"http://127.0.0.1:{_DAEMON_PORT}/"
BASE = "http://127.0.0.1:9292/v1"
TODAY = Path(__file__).parent / "fixtures" / "topology" / "today.yaml"
LONG = "gemma4-26b-a4b"
CODE = "qwen36-35b-a3b"
BACKEND_KEY = "the-backend-key-0123456789"
MAC = "mac-test"


class Counting:
    """The client's transport: counts what it sends and passes it on (or answers by itself)."""

    def __init__(self, inner: httpx2.Client | None = None, answer: Callable | None = None) -> None:
        self.inner = inner
        self.answer = answer
        self.requests: list[tuple[str, dict]] = []
        self.headers: list[dict] = []
        self._lock = threading.Lock()

    def stream(self, method: str, url: str, *, json: dict, headers: dict, timeout=None):
        path = url.split("/api/turn/", 1)[-1]
        with self._lock:
            self.requests.append((path, dict(json)))
            self.headers.append(dict(headers))
        if self.answer is not None:
            return _Loaded(self.answer(path, json))
        assert self.inner is not None
        return self.inner.stream(method, url, json=json, headers=headers)

    def count(self, path: str | None = None) -> int:
        with self._lock:
            return sum(1 for p, _ in self.requests if path is None or p == path)

    def close(self) -> None:
        pass


class _Loaded:
    """A whole `httpx2.Response` behind the `stream(...)` context manager the client uses."""

    def __init__(self, response: httpx2.Response) -> None:
        self.response = response

    def __enter__(self) -> httpx2.Response:
        return self.response

    def __exit__(self, *_exc) -> None:
        self.response.close()


def _heartbeat_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "remote-turn-heartbeat" and t.is_alive()]


@pytest.fixture
def env(tmp_path, monkeypatch):
    """The PC's daemon (topology on loopback, the backend key as its secret) and a clean client."""
    copy = tmp_path / "llamaswap.yaml"
    copy.write_bytes(TODAY.read_bytes())
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(copy))
    monkeypatch.setattr(config, "BASE_URL", BASE)
    monkeypatch.setattr(config, "API_KEY", BACKEND_KEY)
    monkeypatch.setattr(config, "WEB_TOKEN", "")
    monkeypatch.setattr(config, "REMOTE_WEB_TOKEN", "")
    monkeypatch.setattr(config, "TURN_SERVER", True)
    monkeypatch.setattr(config, "TURN_LEASE_S", 30.0)
    monkeypatch.setattr(config, "TURN_MAX_LEASES", 16)
    monkeypatch.setattr(config, "TURN_URL", _URL)
    monkeypatch.setattr(config, "MACHINE_NAME_OVERRIDE", MAC)
    # Short long waits and heartbeats: a queued answer comes back in 0.2 s, a beat every 0.2 s.
    monkeypatch.setattr(turn_leases, "MAX_HEARTBEAT_S", 0.2)
    use_turn(monkeypatch, server._new_turn())
    turn_leases.reset()
    remote_turn.reset()
    yield tmp_path
    # No heartbeat thread may outlive its test: it would beat into the next test's transport.
    left = _wait(lambda: not _heartbeat_threads(), cap=3.0)
    remote_turn.set_client_factory(remote_turn._new_client)
    remote_turn.reset()
    turn_leases.reset()
    turn_api.disable()
    assert left, f"heartbeat threads left alive: {_heartbeat_threads()}"


def use_turn(monkeypatch, turn_state: turn.Turn) -> turn.Turn:
    monkeypatch.setattr(server, "_turn", turn_state)
    monkeypatch.setattr(server._turn_version, "value", None)
    server._topology()
    return turn_state


@pytest.fixture
def transport(env):
    """The daemon in process as the client's transport, counted."""
    with TestClient(daemon.build_app("127.0.0.1", _DAEMON_PORT), base_url=_URL) as c:
        counting = Counting(c)
        remote_turn.set_client_factory(lambda: counting)
        yield counting


@pytest.fixture
def mac(monkeypatch, env):
    """This process's operations see no topology and a remote backend: they ask the daemon."""
    monkeypatch.setattr(
        server,
        "_operation_topology",
        lambda: topology.NoTopology(server.NO_TURN_REMOTE_BACKEND),
    )


def _remote_entries() -> list[dict]:
    return [e for e in server.inflight_snapshot() if str(e["id"]).startswith("remote:")]


def _wait(condition: Callable[[], object], cap: float = 3.0) -> object:
    end = time.monotonic() + cap
    while time.monotonic() < end:
        value = condition()
        if value:
            return value
        time.sleep(0.01)
    return None


def _local(op_id: str, model: str) -> object:
    return server._turn.enqueue(PendingRequest(op_id, frozenset({model}), model))


def _lease(
    model: str = LONG, op: str = "op1", beat=None, chunks: int | None = None
) -> remote_turn.RemoteLease:
    return remote_turn.RemoteLease(
        _URL,
        op=op,
        host=MAC,
        tool="local_summarize",
        model=model,
        role="long",
        chunks=chunks,
        beat=beat,
    )


class _Thread(threading.Thread):
    def __init__(self, function: Callable, *args, token: cancellation.Token | None = None):
        super().__init__(daemon=True)
        self._call = (function, args)
        self._token = token
        self.result: object = None
        self.error: Exception | None = None

    def run(self) -> None:
        if self._token is not None:
            cancellation._CURRENT.set(self._token)
        function, args = self._call
        try:
            self.result = function(*args)
        except Exception as e:  # the test looks at it
            self.error = e


def _operation(entry_id: int | None = None, model: str = LONG) -> server._OperationTurn:
    if entry_id is None:
        entry_id = server._inflight_start(
            tool="local_summarize", model=model, source="text", chars_in=100
        )
    return server._OperationTurn(entry_id, model, "local_summarize", role_name="long")


# --- the lease alone -------------------------------------------------------------------------


def test_granted_at_once_then_released(transport):
    lease = _lease()
    grant = lease.acquire(lambda *_: None)
    assert isinstance(grant, turn.Grant) and grant.model == LONG and not grant.forced
    entries = _remote_entries()
    assert [e["id"] for e in entries] == [f"remote:{MAC}/op1"]
    assert entries[0]["state"] == "running"
    lease.release()
    assert _remote_entries() == []
    lease.release()  # idempotent
    assert transport.count("release") == 1
    assert transport.count("acquire") == 1


def test_the_credential_is_the_backend_key_as_bearer(transport):
    lease = _lease()
    lease.acquire(lambda *_: None)
    lease.release()
    assert transport.headers[0] == {"Authorization": f"Bearer {BACKEND_KEY}"}


def test_the_remote_port_token_goes_first_when_there_is_one(monkeypatch, env):
    monkeypatch.setattr(config, "REMOTE_WEB_TOKEN", "the-remote-port-token-0123")
    assert remote_turn.credential() == "the-remote-port-token-0123"
    monkeypatch.setattr(config, "REMOTE_WEB_TOKEN", "")
    assert remote_turn.credential() == BACKEND_KEY


def test_a_wrong_remote_port_token_is_unauthorized(transport, monkeypatch):
    monkeypatch.setattr(config, "REMOTE_WEB_TOKEN", "not-the-secret-0123456789")
    with pytest.raises(remote_turn.Unusable) as raised:
        _lease().acquire(lambda *_: None)
    assert raised.value.reason == remote_turn.UNAUTHORIZED


def test_queued_heartbeats_on_the_same_lease_then_granted(transport):
    """The contract of lot 3: `acquire` once, then `heartbeat` (never a second `acquire`)."""
    assert isinstance(_local("111:1", CODE), turn.Grant)
    seen: list[tuple[int, tuple[str, ...]]] = []
    lease = _lease()
    waiting = _Thread(lease.acquire, lambda p, u: seen.append((p, u)))
    waiting.start()
    try:
        assert _wait(lambda: transport.count("heartbeat") >= 3), "no heartbeats while queued"
        assert waiting.is_alive()
        assert seen and seen[0] == (1, (CODE,))
        server._turn.release_slot("111:1")
        waiting.join(3.0)
        assert not waiting.is_alive(), "never granted after the release"
        assert waiting.error is None
        assert transport.count("acquire") == 1, "acquire repeated while queued"
        leases = {body["lease"] for path, body in transport.requests if path == "heartbeat"}
        assert len(leases) == 1
    finally:
        lease.release()


def test_the_heartbeat_publishes_in_backend_and_chunk(transport):
    state = {"in_backend": True, "chunk": 2, "phase": "reduce"}
    lease = _lease(beat=lambda: dict(state), chunks=3)
    lease.acquire(lambda *_: None)
    try:
        entry = _wait(
            lambda: next(
                (e for e in _remote_entries() if e.get("phase") == "reduce"),
                None,
            )
        )
        assert entry is not None, "the heartbeat thread never published the state"
        assert entry["chunk"] == 2
        held = turn_leases.table().get(lease.lease_id)
        assert held is not None and held.in_backend  # a call in flight for `TURN_MAX_S` (REQ-013)
    finally:
        lease.release()


def test_without_heartbeat_thread_the_lease_expires(transport, monkeypatch):
    """The beat keeps the lease: with a short lease, it is still there after several lease times."""
    monkeypatch.setattr(config, "TURN_LEASE_S", 3.0)
    monkeypatch.setattr(turn_leases, "MAX_HEARTBEAT_S", 0.2)
    lease = _lease()
    lease.acquire(lambda *_: None)
    try:
        time.sleep(1.0)
        # 2.5 s on: without beats it expired at acquire + 3 s (now + 2 s); with them, later.
        turn_leases.table().reap(now=time.monotonic() + 2.5)
        assert _remote_entries(), "the lease expired: the heartbeat thread does not keep it"
        assert not lease.lost.is_set()
    finally:
        lease.release()


def test_expired_midway_sets_lost(transport):
    lease = _lease()
    lease.acquire(lambda *_: None)
    try:
        turn_leases.table().release(lease.lease_id)  # the daemon forgot it (restart, expiry)
        assert _wait(lease.lost.is_set), "an `expired` heartbeat did not mark the lease lost"
    finally:
        lease.release()


def test_429_waits_and_then_is_granted(transport, monkeypatch):
    monkeypatch.setattr(config, "TURN_MAX_LEASES", 1)
    # A 429 carries no `heartbeat_s`: the wait before the first answer is the default one.
    monkeypatch.setattr(remote_turn, "DEFAULT_HEARTBEAT_S", 0.2)
    other = _lease(op="other")
    other.acquire(lambda *_: None)
    seen: list[int] = []
    lease = _lease()
    waiting = _Thread(lease.acquire, lambda p, _u: seen.append(p))
    waiting.start()
    try:
        assert _wait(lambda: transport.count("acquire") >= 3), "it did not retry after the 429"
        assert waiting.is_alive(), f"a 429 made it leave: {waiting.error!r}"
        assert seen and seen[0] == 0  # busy, not queued: no position yet
        other.release()
        waiting.join(3.0)
        assert not waiting.is_alive() and waiting.error is None
        assert isinstance(waiting.result, turn.Grant)
    finally:
        other.release()
        lease.release()


def test_should_stop_releases_the_queued_lease(transport):
    assert isinstance(_local("111:1", CODE), turn.Grant)
    stop = threading.Event()
    waiting = _Thread(_lease().acquire, lambda *_: None, stop.is_set)
    waiting.start()
    assert _wait(lambda: _remote_entries()), "never queued"
    stop.set()
    waiting.join(3.0)
    assert not waiting.is_alive()
    assert isinstance(waiting.error, turn.AbandonedWait)
    assert _wait(lambda: _remote_entries() == []), "the abandoned lease stayed at the daemon"
    assert transport.count("release") == 1


# --- the guard «never to itself» (REQ-020) ---------------------------------------------------


def test_self_by_port_sends_nothing(transport, monkeypatch):
    monkeypatch.setattr(config, "WEB_PORT", _DAEMON_PORT)
    with pytest.raises(remote_turn.Unusable) as raised:
        _lease().acquire(lambda *_: None)
    assert raised.value.reason == remote_turn.SELF
    assert transport.count() == 0


def test_self_by_daemon_id_releases_and_goes_without_turn(transport, env):
    (env / "daemon.json").write_text(
        json.dumps({"daemon_id": turn_leases.DAEMON_ID}), encoding="utf-8"
    )
    with pytest.raises(remote_turn.Unusable) as raised:
        _lease().acquire(lambda *_: None)
    assert raised.value.reason == remote_turn.SELF
    assert _remote_entries() == []
    assert transport.count("release") == 1
    # Remembered: the next operation does not ask again.
    with pytest.raises(remote_turn.Unusable):
        _lease(op="op2").acquire(lambda *_: None)
    assert transport.count("acquire") == 1


def test_another_daemon_id_is_not_self(transport, env):
    (env / "daemon.json").write_text(json.dumps({"daemon_id": "another-one"}), encoding="utf-8")
    lease = _lease()
    assert isinstance(lease.acquire(lambda *_: None), turn.Grant)
    lease.release()


# --- unusable daemon (REQ-025 case 1) -------------------------------------------------------


def _answering(status: int, body: bytes | None = None, *, raises: Exception | None = None):
    def answer(_path: str, _json: dict) -> httpx2.Response:
        if raises is not None:
            raise raises
        content = body if body is not None else b"{}"
        return httpx2.Response(
            status, content=content, headers={"content-type": "application/json"}
        )

    return answer


_GOOD = {
    "v": 1,
    "daemon_id": "x",
    "lease": "L",
    "status": "granted",
    "position": None,
    "in_use": [],
    "model": LONG,
    "forced": False,
    "lease_s": 30.0,
    "heartbeat_s": 0.2,
    "stalled_s": 0.0,
}


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (_answering(404, b'{"detail": "Not Found"}'), remote_turn.UNSUPPORTED),
        (_answering(405), remote_turn.UNSUPPORTED),
        (_answering(401, b'{"error": "unauthorized"}'), remote_turn.UNAUTHORIZED),
        (_answering(403, b'{"error": "turn_needs_secret"}'), remote_turn.NEEDS_SECRET),
        (_answering(403, b'{"error": "origin_not_allowed"}'), remote_turn.UNAUTHORIZED),
        (
            _answering(0, raises=httpx2.ConnectError("refused")),
            remote_turn.UNREACHABLE,
        ),
        (_answering(200, b"{not json"), remote_turn.BAD_RESPONSE),
        (_answering(200, b"[1, 2]"), remote_turn.BAD_RESPONSE),
        (_answering(500, b"{}"), remote_turn.BAD_RESPONSE),
        (_answering(200, json.dumps({**_GOOD, "v": 2}).encode()), remote_turn.UNSUPPORTED),
        (
            _answering(200, json.dumps({**_GOOD, "status": "what"}).encode()),
            remote_turn.BAD_RESPONSE,
        ),
    ],
    ids=[
        "404",
        "405",
        "401",
        "403-needs-secret",
        "403-other",
        "refused",
        "broken-json",
        "not-an-object",
        "500",
        "v2",
        "unknown-status",
    ],
)
def test_each_unusable_reason_is_remembered(env, answer, reason, monkeypatch, caplog):
    counting = Counting(answer=answer)
    remote_turn.set_client_factory(lambda: counting)
    caplog.set_level(logging.WARNING, logger="local_delegate.remote_turn")
    with pytest.raises(remote_turn.Unusable) as raised:
        _lease().acquire(lambda *_: None)
    assert raised.value.reason == reason
    sent = counting.count()
    with pytest.raises(remote_turn.Unusable) as again:
        _lease(op="op2").acquire(lambda *_: None)
    assert again.value.reason == reason
    assert counting.count() == sent, "the remembered reason did not spare the request"
    warnings = [r for r in caplog.records if r.name == "local_delegate.remote_turn"]
    assert len(warnings) == 1 and reason in warnings[0].getMessage()


def test_the_memory_of_an_unusable_daemon_lasts_its_time(env, monkeypatch):
    monkeypatch.setattr(remote_turn, "UNUSABLE_TTL_S", 0.05)
    counting = Counting(answer=_answering(401))
    remote_turn.set_client_factory(lambda: counting)
    with pytest.raises(remote_turn.Unusable):
        _lease().acquire(lambda *_: None)
    time.sleep(0.1)
    with pytest.raises(remote_turn.Unusable):
        _lease().acquire(lambda *_: None)
    assert counting.count() == 2


def test_404_is_remembered_longer_than_401():
    assert remote_turn.UNSUPPORTED_TTL_S == 600.0 and remote_turn.UNUSABLE_TTL_S == 60.0


def test_a_lost_answer_asks_again_once_then_is_unreachable(env):
    counting = Counting(answer=_answering(0, raises=httpx2.ReadTimeout("slow")))
    remote_turn.set_client_factory(lambda: counting)
    with pytest.raises(remote_turn.Unusable) as raised:
        _lease().acquire(lambda *_: None)
    assert raised.value.reason == remote_turn.UNREACHABLE
    assert counting.count("acquire") == 2


# --- discovery (REQ-020/021) and local-only use (REQ-040) ------------------------------------


def test_discovery(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://pc.tailnet.ts.net:9292/v1")
    monkeypatch.setattr(config, "WEB_PORT", 9393)
    monkeypatch.setattr(config, "TURN_URL", "auto")
    assert remote_turn.turn_url(remote_backend=True) == "http://pc.tailnet.ts.net:9393/"
    monkeypatch.setattr(config, "TURN_URL", "off")
    assert remote_turn.turn_url(remote_backend=True) is None
    monkeypatch.setattr(config, "TURN_URL", "http://127.0.0.1:19393")
    assert remote_turn.turn_url(remote_backend=False) == "http://127.0.0.1:19393/"
    for bad in ("ftp://pc:1/", "http://user:pw@pc:9393/", "not a url", "http://pc:99999/"):
        monkeypatch.setattr(config, "TURN_URL", bad)
        assert remote_turn.turn_url(remote_backend=True) is None, bad
    monkeypatch.setattr(config, "BASE_URL", BASE)
    monkeypatch.setattr(config, "TURN_URL", "auto")
    assert remote_turn.turn_url(remote_backend=False) is None


def test_local_only_use_sends_nothing(env, monkeypatch):
    """REQ-040: loopback backend, `TURN_URL=auto`, no topology → zero requests, not even a client."""
    monkeypatch.setattr(config, "TURN_URL", "auto")
    monkeypatch.delenv("LLAMASWAP_CONFIG")
    built: list[int] = []

    def factory() -> httpx2.Client:
        built.append(1)
        return Counting(answer=_answering(200, json.dumps(_GOOD).encode()))  # type: ignore[return-value]

    remote_turn.set_client_factory(factory)
    snapshot = server._operation_topology()
    assert isinstance(snapshot, topology.NoTopology)
    assert snapshot.reason != server.NO_TURN_REMOTE_BACKEND
    op = _operation()
    op.ensure(LONG)
    op.release_slot()
    assert built == [], "a local-only process created the remote turn's client"
    assert op.remote_turn is None and "remote_turn" not in op.log_fields()
    assert server._describe_remote_turn() == []


def test_a_local_topology_rules_even_with_turn_url(transport):
    """REQ-020: topology and loopback backend → the local turn, with `TURN_URL` set."""
    op = _operation()
    op.ensure(LONG)
    try:
        assert op._turn is server._turn and op._remote is None
    finally:
        op.release_slot()
    assert transport.count() == 0


# --- the operation (REQ-022..026, REQ-030) ---------------------------------------------------


def test_operation_granted_logs_and_releases(transport, mac):
    op = _operation()
    op.ensure(LONG)
    assert op._remote is not None and op.remote_turn == remote_turn.GRANTED
    assert op.log_fields()["remote_turn"] == "granted"
    assert len(_remote_entries()) == 1
    op.ensure(LONG)  # the next chunk: same turn, no request
    assert transport.count("acquire") == 1
    op.release_slot()
    assert _remote_entries() == []
    assert op._remote is None


def test_operation_queued_shows_the_wait_and_progress(transport, mac):
    assert isinstance(_local("111:1", CODE), turn.Grant)
    token = cancellation.Token("local_summarize")
    op = _operation()
    key = f"{os.getpid()}:{op.entry_id}"
    waiting = _Thread(op.ensure, LONG, token=token)
    waiting.start()
    mine = _wait(
        lambda: next(
            (e for e in server.inflight_snapshot() if e["id"] == key and e.get("local_wait")),
            None,
        )
    )
    assert mine is not None, "the client's own entry never said it waits for the turn"
    assert mine["local_wait"] == "turn" and mine["turn_position"] == 1
    assert mine["turn_in_use"] == [CODE]
    progress = token.progress_message()
    assert "127.0.0.1" in progress and "1" in progress, progress
    server._turn.release_slot("111:1")
    waiting.join(3.0)
    assert not waiting.is_alive() and waiting.error is None
    assert op.remote_turn == "granted" and op.wait_ms > 0
    after = next(e for e in server.inflight_snapshot() if e["id"] == key)
    assert "local_wait" not in after
    op.release_slot()


def test_operation_cancelled_while_queued_releases(transport, mac):
    assert isinstance(_local("111:1", CODE), turn.Grant)
    token = cancellation.Token("local_summarize")
    op = _operation()
    waiting = _Thread(op.ensure, LONG, token=token)
    waiting.start()
    assert _wait(lambda: _remote_entries()), "never queued"
    token.cancel(cancellation.REASON_ABORTED)
    waiting.join(3.0)
    assert not waiting.is_alive()
    assert isinstance(waiting.error, cancellation.CallCancelled), repr(waiting.error)
    assert _wait(lambda: _remote_entries() == []), "the cancelled lease stayed at the daemon"
    assert op._remote is None


def test_operation_saturated_names_the_machine(transport, mac, monkeypatch):
    monkeypatch.setattr(config, "QUEUE_MAX_WAIT_S", 0.5)
    assert isinstance(_local("111:1", CODE), turn.Grant)
    op = _operation()
    with pytest.raises(server.QueueSaturated) as raised:
        op.ensure(LONG)
    assert "127.0.0.1" in str(raised.value)
    assert _wait(lambda: _remote_entries() == [])
    server._turn.release_slot("111:1")


def test_operation_expired_midway_asks_again_before_the_next_send(transport, mac):
    op = _operation()
    op.ensure(LONG)
    first = op._remote
    assert first is not None
    turn_leases.table().release(first.lease_id)
    assert _wait(first.lost.is_set)
    op.ensure(LONG)  # the next chunk
    assert transport.count("acquire") == 2, transport.requests
    assert op._remote is not None and op._remote is not first
    assert op.remote_turn == "granted"
    op.release_slot()


def test_operation_yields_before_the_next_chunk(transport, mac, monkeypatch):
    monkeypatch.setattr(config, "TURN_YIELD_S", 0.3)
    use_turn(monkeypatch, server._new_turn())
    op = _operation()
    op.ensure(LONG)
    lease = op._remote
    assert lease is not None
    assert _local("111:1", CODE) is not None  # a clashing local operation queues behind
    assert _wait(lease.yield_requested.is_set, cap=5.0), "the heartbeat never said `yield`"
    again = _Thread(op.ensure, LONG)
    again.start()
    # It gave the turn back: the local operation gets it and the remote one queues behind.
    assert _wait(
        lambda: (
            isinstance(server._turn.poll("111:1"), turn.Grant)
            or (server._turn.snapshot().active("111:1") is not None)
        )
    ), "the local operation never got the turn the remote one yielded"
    assert again.is_alive()
    server._turn.release_slot("111:1")
    again.join(3.0)
    assert not again.is_alive() and again.error is None
    assert op.yields == 1 and op.log_fields()["turn_yields"] == 1
    assert op._remote is not lease
    op.release_slot()


def test_operation_degrades_without_turn_and_says_why(env, mac, caplog):
    counting = Counting(answer=_answering(404, b'{"detail": "Not Found"}'))
    remote_turn.set_client_factory(lambda: counting)
    op = _operation()
    op.ensure(LONG)
    assert op._remote is None and op.model == LONG
    assert op.log_fields()["remote_turn"] == "unsupported"
    op.release_slot()


def test_the_usage_event_carries_remote_turn(transport, mac, monkeypatch, env):
    """End to end in process: a real tool call logs `remote_turn` (REQ-026)."""

    def fake_post(_model: str, _payload: dict) -> server.ChatResult:
        return server.ChatResult(text="a", ok=True, finish_reason="stop")

    monkeypatch.setattr(server, "_post_chat", fake_post)
    server.local_classify(text="hola", labels=["a", "b"])
    events = []
    for file in sorted(Path(config.LOG_DIR).glob("usage*.jsonl")):
        events += [json.loads(x) for x in file.read_text(encoding="utf-8").splitlines() if x]
    mine = [e for e in events if e.get("tool") == "local_classify"]
    assert mine and mine[-1].get("remote_turn") == "granted", mine
    assert _remote_entries() == []


# --- `local_status` (REQ-027) ----------------------------------------------------------------


def test_status_line(env, monkeypatch):
    monkeypatch.setattr(config, "TURN_URL", "auto")
    monkeypatch.setattr(config, "BASE_URL", "http://pc.tail1234.ts.net:9292/v1")
    assert "pc.tail1234.ts.net:9393" in remote_turn.status_line(remote_backend=True)
    remote_turn.remember("http://pc.tail1234.ts.net:9393/", remote_turn.UNAUTHORIZED)
    assert "unauthorized" in remote_turn.status_line(remote_backend=True)
    monkeypatch.setattr(config, "TURN_URL", "off")
    assert remote_turn.status_line(remote_backend=True) == i18n_off()
    assert remote_turn.status_line(remote_backend=False) is None
    monkeypatch.setattr(config, "TURN_URL", "auto")
    monkeypatch.setattr(config, "BASE_URL", BASE)
    assert remote_turn.status_line(remote_backend=False) is None


def i18n_off() -> str:
    from local_delegate import i18n

    return i18n.t("mcp.status.remote_turn.off")


# --- review of #502 --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("base", "asks"),
    [
        ("https://own-pc.tail1234.ts.net:9292/v1", True),  # the Mac's, measured (research §2)
        ("http://100.101.102.103:9292/v1", True),  # the tailnet's CGNAT
        ("http://pc:9292/v1", True),  # MagicDNS short name
        ("http://[fd7a:115c:a1e0::1]:9292/v1", True),  # the tailnet's ULA
        ("http://192.168.1.5:9292/v1", True),
        ("http://10.0.0.7:9292/v1", True),
        ("http://pc.lan:9292/v1", True),
        ("http://pc.home.arpa:9292/v1", True),
        ("https://api.example.com/v1", False),
        ("https://api.openai.com/v1", False),
        ("http://8.8.8.8:9292/v1", False),
        ("http://[2001:4860::8888]:9292/v1", False),
        ("http://100.128.0.1:9292/v1", False),  # just outside 100.64/10
    ],
)
def test_auto_discovers_only_private_hosts(monkeypatch, base, asks):
    monkeypatch.setattr(config, "BASE_URL", base)
    monkeypatch.setattr(config, "TURN_URL", "auto")
    found = remote_turn.turn_url(remote_backend=True)
    assert (found is not None) == asks, (base, found)


def test_a_public_backend_with_auto_sends_nothing(env, mac, monkeypatch):
    """Review of #502: `auto` never sends the backend key to a public host's port 9393."""
    monkeypatch.setattr(config, "BASE_URL", "https://api.example.com/v1")
    monkeypatch.setattr(config, "TURN_URL", "auto")
    built: list[int] = []

    def factory() -> httpx2.Client:
        built.append(1)
        return Counting(answer=_answering(200, json.dumps(_GOOD).encode()))  # type: ignore[return-value]

    remote_turn.set_client_factory(factory)
    op = _operation()
    op.ensure(LONG)
    op.release_slot()
    assert built == [], "the client was created for a public backend"
    assert op.remote_turn is None and "remote_turn" not in op.log_fields()
    line = remote_turn.status_line(remote_backend=True)
    assert line is not None and remote_turn.PUBLIC_HOST in line


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_filtered_port_costs_one_request_per_ten_minutes(env, monkeypatch):
    """`ConnectTimeout` without a lease: `unreachable` at once, remembered 10 min if never granted."""
    clock = FakeClock()
    monkeypatch.setattr(remote_turn, "_now", clock)
    counting = Counting(answer=_answering(0, raises=httpx2.ConnectTimeout("filtered")))
    remote_turn.set_client_factory(lambda: counting)
    for n in range(3):
        with pytest.raises(remote_turn.Unusable) as raised:
            _lease(op=f"op{n}").acquire(lambda *_: None)
        assert raised.value.reason == remote_turn.UNREACHABLE
        clock.now += 61
    assert counting.count() == 1, counting.requests
    # After a grant in this process, an unreachable daemon is remembered 60 s only.
    remote_turn.reset()
    remote_turn.set_client_factory(lambda: counting)
    remote_turn.note_result(_URL, remote_turn.GRANTED)
    for n in range(2):
        with pytest.raises(remote_turn.Unusable):
            _lease(op=f"again{n}").acquire(lambda *_: None)
        clock.now += 61
    assert counting.count() == 3


class _Listener:
    """A loopback TCP server that hands each connection to `handle`, in daemon threads."""

    def __init__(self, handle: Callable) -> None:
        import socket

        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self._sock.settimeout(0.2)
        self.port = self._sock.getsockname()[1]
        self.stop = threading.Event()
        self._handle = handle
        self._threads: list[threading.Thread] = []
        self._accepting = threading.Thread(target=self._accept, daemon=True)
        self._accepting.start()

    def _accept(self) -> None:
        while not self.stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                continue
            worker = threading.Thread(target=self._serve, args=(conn,), daemon=True)
            self._threads.append(worker)
            worker.start()

    def _serve(self, conn) -> None:
        with conn:
            try:
                self._handle(conn)
            except OSError:
                pass

    def close(self) -> None:
        self.stop.set()
        self._accepting.join(5)
        self._sock.close()
        for worker in self._threads:
            worker.join(5)
        assert not any(t.is_alive() for t in [self._accepting, *self._threads])


def test_the_environment_proxy_is_ignored(env, monkeypatch):
    """`trust_env=False`: `HTTP(S)_PROXY` never sees the request (nor the credential)."""
    seen: list[bytes] = []
    proxy = _Listener(lambda conn: seen.append(conn.recv(4096)))
    try:
        monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy.port}")
        monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{proxy.port}")
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.setattr(remote_turn, "CONNECT_TIMEOUT_S", 0.3)
        remote_turn.set_client_factory(remote_turn._new_client)
        lease = remote_turn.RemoteLease(
            "http://10.255.255.1:9/", op="op1", host=MAC, tool="t", model=LONG
        )
        with pytest.raises(remote_turn.Unusable):
            lease.acquire(lambda *_: None)
        time.sleep(0.2)
    finally:
        proxy.close()
    assert seen == [], f"the proxy got the request: {seen[:1]}"


def _dripping(stop: threading.Event, every: float = 2.0, cap: float = 20.0) -> Callable:
    """A daemon that answers 200 and then one byte every `every` seconds."""

    def handle(conn) -> None:
        conn.settimeout(1.0)
        data = b""
        while b"\r\n\r\n" not in data:
            data += conn.recv(4096)
        conn.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 4096\r\n\r\n"
        )
        end = time.monotonic() + cap
        while not stop.is_set() and time.monotonic() < end:
            conn.sendall(b" ")
            if stop.wait(every):
                return

    return handle


@pytest.fixture
def drip(env, monkeypatch):
    stop = threading.Event()
    listener = _Listener(_dripping(stop))
    # Read timeout 3 s (longer than the drip): only the total deadline can end the read.
    monkeypatch.setattr(remote_turn, "CONNECT_TIMEOUT_S", 0.5)
    monkeypatch.setattr(remote_turn, "DEFAULT_HEARTBEAT_S", 0.5)
    monkeypatch.setattr(remote_turn, "READ_MARGIN_S", 2.5)
    remote_turn.set_client_factory(remote_turn._new_client)
    try:
        yield f"http://127.0.0.1:{listener.port}/"
    finally:
        stop.set()
        listener.close()


def test_a_dripping_daemon_does_not_hold_acquire(drip):
    lease = remote_turn.RemoteLease(drip, op="op1", host=MAC, tool="t", model=LONG)
    t0 = time.monotonic()
    with pytest.raises(remote_turn.Unusable) as raised:
        lease.acquire(lambda *_: None)
    elapsed = time.monotonic() - t0
    assert raised.value.reason == remote_turn.UNREACHABLE
    # Two tries (a lost answer is asked again once), each within connection + read = 3.5 s.
    assert elapsed < 2 * 3.5 + 2.5, f"acquire took {elapsed:.1f} s"


def test_a_dripping_daemon_respects_cancellation(drip):
    lease = remote_turn.RemoteLease(drip, op="op1", host=MAC, tool="t", model=LONG)
    t0 = time.monotonic()
    with pytest.raises(turn.AbandonedWait):
        lease.acquire(lambda *_: None, lambda: time.monotonic() - t0 > 1.0)
    elapsed = time.monotonic() - t0
    assert elapsed < 3.5, f"the cancellation waited {elapsed:.1f} s"


def test_a_release_against_a_dripping_daemon_is_bounded(drip):
    lease = remote_turn.RemoteLease(drip, op="op1", host=MAC, tool="t", model=LONG)
    lease.lease_id = "some-lease"
    t0 = time.monotonic()
    lease.release()
    elapsed = time.monotonic() - t0
    assert elapsed < remote_turn.RELEASE_READ_S + 2.5, f"the release took {elapsed:.1f} s"


def test_a_huge_answer_is_a_bad_response(env):
    padded = json.dumps(_GOOD).encode()[:-1] + b" " * (1024 * 1024) + b"}"
    counting = Counting(answer=_answering(200, padded))
    remote_turn.set_client_factory(lambda: counting)
    with pytest.raises(remote_turn.Unusable) as raised:
        _lease().acquire(lambda *_: None)
    assert raised.value.reason == remote_turn.BAD_RESPONSE


def _with_position_inf() -> bytes:
    body = json.dumps({**_GOOD, "status": "queued", "position": 12345})
    return body.replace("12345", "1e999").encode()


@pytest.mark.parametrize(
    "body",
    [
        b"[" * 30000 + b"]" * 30000,  # deeper than the parser's limit, under 64 KiB
        _with_position_inf(),
        json.dumps({**_GOOD, "lease": "bad lease!"}).encode(),
        json.dumps({**_GOOD, "lease": "x" * 129}).encode(),
    ],
    ids=["deep-json", "position-inf", "lease-bad-chars", "lease-too-long"],
)
def test_broken_answers_degrade(env, body):
    counting = Counting(answer=_answering(200, body))
    remote_turn.set_client_factory(lambda: counting)
    with pytest.raises(remote_turn.Unusable) as raised:
        _lease().acquire(lambda *_: None)
    assert raised.value.reason == remote_turn.BAD_RESPONSE


def test_answers_are_cleaned():
    body = {
        **_GOOD,
        "status": "queued",
        "in_use": ["ok-model", "bad model", "x" * 129, *[f"m{i}" for i in range(30)]],
        "heartbeat_s": float("nan"),
        "stalled_s": float("inf"),
    }
    answer = remote_turn._parse(200, json.dumps(body).encode())
    assert answer.in_use[0] == "ok-model" and "bad model" not in answer.in_use
    assert "x" * 129 not in answer.in_use
    assert len(answer.in_use) <= remote_turn.MAX_IN_USE
    assert answer.heartbeat_s == remote_turn.DEFAULT_HEARTBEAT_S
    assert answer.stalled_s == 0.0


def test_an_exception_in_the_heartbeat_thread_marks_the_lease_lost(transport, monkeypatch):
    lease = _lease()
    lease.acquire(lambda *_: None)
    try:

        def broken(*_args, **_kwargs):
            raise RuntimeError("something nobody expected")

        monkeypatch.setattr(remote_turn, "_post", broken)
        assert _wait(lease.lost.is_set), "the heartbeat thread died in silence"
        monkeypatch.undo()
    finally:
        lease.release()


def test_our_own_cap_saturates_when_the_daemon_says_zero(env, mac, monkeypatch):
    monkeypatch.setattr(config, "QUEUE_MAX_WAIT_S", 0.3)
    queued = {**_GOOD, "status": "queued", "position": 1, "heartbeat_s": 0.05, "stalled_s": 0}
    counting = Counting(answer=_answering(200, json.dumps(queued).encode()))
    remote_turn.set_client_factory(lambda: counting)
    op = _operation()
    t0 = time.monotonic()
    with pytest.raises(server.QueueSaturated):
        op.ensure(LONG)
    assert time.monotonic() - t0 < 3.0


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "127.1", "127.9.9.9", "0.0.0.0", "localhost", "localhost.", "a.localhost"]
)
def test_self_by_address_variants(monkeypatch, host):
    monkeypatch.setattr(config, "WEB_PORT", 9393)
    assert remote_turn.points_to_itself(f"http://{host}:9393/")
    assert not remote_turn.points_to_itself(f"http://{host}:9394/")


@pytest.mark.parametrize(
    "url",
    ["http://pc:9393/?x=1", "http://pc:9393/#frag", "http://pc:9393/api/", "http://pc:9393/x"],
)
def test_turn_url_with_query_fragment_or_path_is_refused(monkeypatch, url):
    monkeypatch.setattr(config, "TURN_URL", url)
    assert remote_turn.turn_url(remote_backend=True) is None


def test_plaintext_to_a_public_host_warns_once(env, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="local_delegate.remote_turn")
    monkeypatch.setattr(config, "TURN_URL", "http://203.0.113.5:9393/")
    assert remote_turn.turn_url(remote_backend=True) == "http://203.0.113.5:9393/"
    remote_turn.turn_url(remote_backend=True)
    warnings = [r for r in caplog.records if r.name == "local_delegate.remote_turn"]
    assert len(warnings) == 1 and "203.0.113.5" in warnings[0].getMessage()
    line = remote_turn.status_line(remote_backend=True)
    active = remote_turn.i18n.t("mcp.status.remote_turn.active", url="http://203.0.113.5:9393/")
    assert line is not None and "203.0.113.5" in line and line != active
    caplog.clear()
    for quiet in ("https://203.0.113.5:9393/", "http://pc.tail1234.ts.net:9393/"):
        monkeypatch.setattr(config, "TURN_URL", quiet)
        remote_turn.turn_url(remote_backend=True)
    assert not [r for r in caplog.records if r.name == "local_delegate.remote_turn"]
