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

    def post(self, url: str, *, json: dict, headers: dict, timeout=None) -> httpx2.Response:
        path = url.split("/api/turn/", 1)[-1]
        with self._lock:
            self.requests.append((path, dict(json)))
            self.headers.append(dict(headers))
        if self.answer is not None:
            return self.answer(path, json)
        assert self.inner is not None
        return self.inner.post(url, json=json, headers=headers)

    def count(self, path: str | None = None) -> int:
        with self._lock:
            return sum(1 for p, _ in self.requests if path is None or p == path)

    def close(self) -> None:
        pass


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
    remote_turn.set_client_factory(remote_turn._new_client)
    remote_turn.reset()
    turn_leases.reset()
    turn_api.disable()


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
    waiting = _Thread(_lease().acquire, lambda p, u: seen.append((p, u)))
    waiting.start()
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
    waiting = _Thread(_lease().acquire, lambda p, _u: seen.append(p))
    waiting.start()
    assert _wait(lambda: transport.count("acquire") >= 3), "it did not retry after the 429"
    assert waiting.is_alive(), f"a 429 made it leave: {waiting.error!r}"
    assert seen and seen[0] == 0  # busy, not queued: no position yet
    other.release()
    waiting.join(3.0)
    assert not waiting.is_alive() and waiting.error is None
    assert isinstance(waiting.result, turn.Grant)


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
    monkeypatch.setattr(config, "BASE_URL", "http://pc.example:9292/v1")
    assert "pc.example:9393" in remote_turn.status_line(remote_backend=True)
    remote_turn.remember("http://pc.example:9393/", remote_turn.UNAUTHORIZED)
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
