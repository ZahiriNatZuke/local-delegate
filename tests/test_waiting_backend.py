"""Concurrency PC+Mac, lot 1: `waiting_backend` in `/api/inflight` and in the progress heartbeat.

A send that is still pending `BACKEND_SAMPLE_DELAY_S` after it went out samples llama-swap's
`/running`; when the requested model is not `ready` there, the send marks itself in the entry's
`backend_wait` (its own sub-key) and the entry's `state` is `waiting_backend` until the model is
ready or the send ends. Spec: `.sdd/changes/concurrencia-pc-mac/spec.md` REQ-001..004; plan, lot 1.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import backend_mock
import httpx2
import pytest

from local_delegate import cancellation, concurrency, config, i18n, server

CHAT = "http://test-backend/v1/chat/completions"
RUNNING = "http://test-backend/running"
ASKED = "gemma4-26b-a4b"
OTHER = "qwen36-35b-a3b"
BODY = {"model": ASKED, "messages": [{"role": "user", "content": "hola"}]}


@pytest.fixture(autouse=True)
def quick_watch(reload_config, monkeypatch):
    """Test backend, an empty `/running` cache and a short delay and resample (real ones: 3/10 s)."""
    reload_config()
    concurrency.reset_cache()
    monkeypatch.setattr(concurrency, "BACKEND_SAMPLE_DELAY_S", 0.05)
    monkeypatch.setattr(concurrency, "BACKEND_WAIT_RESAMPLE_S", 0.05)
    monkeypatch.setattr(concurrency, "RUNNING_CACHE_S", 0.0)
    yield
    concurrency.reset_cache()


def _running(*pairs: tuple[str, str]) -> httpx2.Response:
    return httpx2.Response(200, json={"running": [{"model": m, "state": s} for m, s in pairs]})


def _entry(entry_id: int) -> dict:
    key = f"{server.os.getpid()}:{entry_id}"
    return next(e for e in server.inflight_snapshot() if e["id"] == key)


def _until(check: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.01)
    return check()


class _HeldChat:
    """`/chat/completions` that answers only when released, one gate per POST, in order."""

    def __init__(self, posts: int = 1) -> None:
        self.gates = [threading.Event() for _ in range(posts)]
        self.arrived = threading.Semaphore(0)
        self._next = 0
        self._lock = threading.Lock()

    def __call__(self, _request: httpx2.Request) -> httpx2.Response:
        with self._lock:
            gate = self.gates[self._next]
            self._next += 1
        self.arrived.release()
        gate.wait(10)
        return backend_mock.chat_response("hecho")


def _send_in_slot(entry_id: int, token: cancellation.Token | None = None) -> threading.Thread:
    """One send of `entry_id`, with its place, in its own thread (as a tool's thread would)."""
    errors: list[Exception] = []

    def run() -> None:
        if token is not None:
            cancellation._CURRENT.set(token)
        try:
            with server._slot(entry_id):
                server._send(ASKED, BODY)
        except Exception as e:  # surfaced by the test through `errors` (CallCancelled too)
            errors.append(e)

    thread = threading.Thread(target=run, daemon=True)
    thread.errors = errors  # type: ignore[attr-defined]
    thread.start()
    return thread


def _start(tool: str = "local_summarize") -> int:
    return server._inflight_start(tool=tool, model=ASKED, source="inline", chars_in=10)


# --- (a) the requested model is not ready: `waiting_backend` --------------------------------


@backend_mock.mock
def test_a_send_waiting_for_a_switch_is_waiting_backend():
    chat = _HeldChat()
    backend_mock.post(CHAT).mock(side_effect=chat)
    running = backend_mock.get(RUNNING).mock(
        return_value=_running((OTHER, "ready"), (ASKED, "starting"))
    )
    entry_id = _start()
    try:
        thread = _send_in_slot(entry_id)
        assert _until(lambda: _entry(entry_id).get("state") == "waiting_backend")
        entry = _entry(entry_id)
        # The other models llama-swap has, never the requested one (that is what it waits for).
        assert entry["backend_wait"] == {OTHER: "ready"}
        assert running.call_count >= 1  # guard: the case did reach the watch
        chat.gates[0].set()
        thread.join(5)
        assert not thread.errors
    finally:
        server._inflight_end(entry_id)


# --- (b) a later sample sees the model ready: back to `running` -----------------------------


@backend_mock.mock
def test_a_later_sample_with_the_model_ready_unmarks_it():
    chat = _HeldChat()
    backend_mock.post(CHAT).mock(side_effect=chat)
    loaded = threading.Event()  # the test decides when llama-swap has switched (no timing race)

    def running_now(_request):
        if loaded.is_set():
            return _running((ASKED, "ready"))
        return _running((OTHER, "ready"), (ASKED, "starting"))

    running = backend_mock.get(RUNNING).mock(side_effect=running_now)
    entry_id = _start()
    try:
        thread = _send_in_slot(entry_id)
        assert _until(lambda: _entry(entry_id).get("state") == "waiting_backend")
        seen = running.call_count
        loaded.set()
        # Still pending, but the model is ready now: the call is processing.
        assert _until(lambda: _entry(entry_id).get("state") == "running")
        assert "backend_wait" not in _entry(entry_id)
        assert running.call_count > seen  # guard: a later sample did the unmarking
        chat.gates[0].set()
        thread.join(5)
    finally:
        chat.gates[0].set()
        server._inflight_end(entry_id)


# --- (c) the send ends: nothing left --------------------------------------------------------


@backend_mock.mock
def test_the_end_of_the_send_clears_its_mark():
    chat = _HeldChat()
    backend_mock.post(CHAT).mock(side_effect=chat)
    backend_mock.get(RUNNING).mock(return_value=_running((OTHER, "ready"), (ASKED, "starting")))
    entry_id = _start()
    try:
        thread = _send_in_slot(entry_id)
        assert _until(lambda: _entry(entry_id).get("state") == "waiting_backend")
        chat.gates[0].set()
        thread.join(5)
        entry = _entry(entry_id)
        assert "backend_wait" not in entry
        assert entry["state"] == "running"  # between pieces, as before
        key = f"{server.os.getpid()}:{entry_id}"
        assert key not in server._backend_waits
    finally:
        server._inflight_end(entry_id)


# --- (d) a quick send asks llama-swap nothing -----------------------------------------------


@backend_mock.mock
def test_a_quick_send_queries_nothing(monkeypatch):
    """With the real delay, a POST that answers at once never queries `/running` (the affinity
    rule, `test_affinity`). The delay is checked after the call, so a watch that sampled at once
    would have been seen."""
    monkeypatch.setattr(concurrency, "BACKEND_SAMPLE_DELAY_S", 3.0)
    backend_mock.post(CHAT).mock(return_value=backend_mock.chat_response("hecho"))
    running = backend_mock.get(RUNNING).mock(return_value=_running((OTHER, "ready")))
    entry_id = _start()
    try:
        with server._slot(entry_id):
            result = server._send(ASKED, BODY)
        time.sleep(0.2)
        assert result.ok is True
        assert running.call_count == 0
        assert "backend_wait" not in _entry(entry_id)
    finally:
        server._inflight_end(entry_id)


# --- (e) precedence: queued > retrying > waiting_backend > running --------------------------


def test_the_precedence_of_the_states():
    waits = {"1": {OTHER: "ready"}}
    assert server._inflight_state({"in_backend": True, "backend_wait": waits}) == "waiting_backend"
    assert (
        server._inflight_state({"in_backend": True, "backend_wait": waits, "phase": "retry"})
        == "retrying"
    )
    assert (
        server._inflight_state({"in_backend": False, "backend_wait": waits, "local_wait": "slot"})
        == "queued"
    )
    assert server._inflight_state({"backend_wait": waits}) == "queued"  # never at the backend
    assert server._inflight_state({"in_backend": True, "backend_wait": {}}) == "running"
    assert "waiting_backend" in server.INFLIGHT_STATES


# --- (f) two sends of the same entry at once ------------------------------------------------


@backend_mock.mock
def test_the_send_that_ends_first_leaves_the_other_ones_mark(monkeypatch):
    monkeypatch.setattr(server, "_chat_slots", threading.BoundedSemaphore(2))
    chat = _HeldChat(posts=2)
    backend_mock.post(CHAT).mock(side_effect=chat)
    backend_mock.get(RUNNING).mock(return_value=_running((OTHER, "ready"), (ASKED, "starting")))
    entry_id = _start()
    key = f"{server.os.getpid()}:{entry_id}"
    try:
        first = _send_in_slot(entry_id)
        assert chat.arrived.acquire(timeout=5)
        second = _send_in_slot(entry_id)
        assert chat.arrived.acquire(timeout=5)
        assert _until(lambda: len(server._backend_waits.get(key, {})) == 2)
        chat.gates[0].set()
        first.join(5)
        # The other send still waits: its mark stays, and so does the state.
        entry = _entry(entry_id)
        assert entry["state"] == "waiting_backend"
        assert entry["backend_wait"] == {OTHER: "ready"}
        assert len(server._backend_waits.get(key, {})) == 1
        chat.gates[1].set()
        second.join(5)
        assert "backend_wait" not in _entry(entry_id)
    finally:
        for gate in chat.gates:
            gate.set()
        server._inflight_end(entry_id)


# --- (g) the second piece of an operation is marked too -------------------------------------


@backend_mock.mock
def test_the_second_piece_of_an_operation_is_marked_too():
    """The log's sample is one per operation; the watch is one per send."""
    chat = _HeldChat(posts=2)
    backend_mock.post(CHAT).mock(side_effect=chat)
    backend_mock.get(RUNNING).mock(return_value=_running((OTHER, "ready"), (ASKED, "starting")))
    entry_id = _start()
    trace = concurrency.Trace(ASKED)
    trace.claim_backend_sample()  # the first piece already took the operation's single sample
    try:

        def two_pieces() -> None:
            concurrency._CURRENT.set(trace)
            for _ in range(2):
                with server._slot(entry_id):
                    server._send(ASKED, BODY)

        thread = threading.Thread(target=two_pieces, daemon=True)
        thread.start()
        assert _until(lambda: _entry(entry_id).get("state") == "waiting_backend")
        chat.gates[0].set()
        assert chat.arrived.acquire(timeout=5) and chat.arrived.acquire(timeout=5)
        # Piece 2 is pending now: it is marked on its own.
        assert _until(lambda: _entry(entry_id).get("state") == "waiting_backend")
        assert _entry(entry_id)["backend_wait"] == {OTHER: "ready"}
        chat.gates[1].set()
        thread.join(5)
        assert "backend_wait" not in _entry(entry_id)
    finally:
        for gate in chat.gates:
            gate.set()
        server._inflight_end(entry_id)


# --- (h) the race: a `/running` query that outlives the send --------------------------------


@backend_mock.mock
def test_a_query_that_outlives_the_send_writes_nothing_after_the_cleanup():
    chat = _HeldChat()
    backend_mock.post(CHAT).mock(side_effect=chat)
    query_started = threading.Event()
    release_query = threading.Event()

    def slow_running(_request):
        query_started.set()
        release_query.wait(10)
        return _running((OTHER, "ready"), (ASKED, "starting"))

    backend_mock.get(RUNNING).mock(side_effect=slow_running)
    entry_id = _start()
    key = f"{server.os.getpid()}:{entry_id}"
    try:
        thread = _send_in_slot(entry_id)
        assert query_started.wait(5)
        # The send ends while its watch is still inside the query.
        chat.gates[0].set()
        thread.join(5)
        assert not thread.is_alive()
        release_query.set()
        time.sleep(0.3)  # let the watch thread finish its answer
        assert "backend_wait" not in _entry(entry_id)
        assert key not in server._backend_waits
    finally:
        release_query.set()
        server._inflight_end(entry_id)


# --- (i) without topology and an unknown name: nothing is marked ----------------------------


@backend_mock.mock
def test_without_topology_an_absent_name_is_not_marked():
    """The Mac has no topology: `gemma` absent and `qwen` ready may be an alias of the same."""
    chat = _HeldChat()
    backend_mock.post(CHAT).mock(side_effect=chat)
    running = backend_mock.get(RUNNING).mock(return_value=_running((OTHER, "ready")))
    entry_id = _start()
    try:
        thread = _send_in_slot(entry_id)
        assert _until(lambda: running.call_count >= 2)  # guard: the watch did look, twice
        assert _entry(entry_id)["state"] == "running"
        assert "backend_wait" not in _entry(entry_id)
        chat.gates[0].set()
        thread.join(5)
    finally:
        chat.gates[0].set()
        server._inflight_end(entry_id)


@backend_mock.mock
def test_with_topology_an_absent_model_is_marked(monkeypatch):
    """With topology the alias is resolved: the model is not loaded at all, so it waits."""
    monkeypatch.setattr(server, "_resolved_model_name", lambda model: f"{model}-real")
    chat = _HeldChat()
    backend_mock.post(CHAT).mock(side_effect=chat)
    backend_mock.get(RUNNING).mock(return_value=_running((OTHER, "ready")))
    entry_id = _start()
    try:
        thread = _send_in_slot(entry_id)
        assert _until(lambda: _entry(entry_id).get("state") == "waiting_backend")
        assert _entry(entry_id)["backend_wait"] == {OTHER: "ready"}
        chat.gates[0].set()
        thread.join(5)
    finally:
        chat.gates[0].set()
        server._inflight_end(entry_id)


def test_the_decision_with_both_names():
    assert concurrency.waiting_for(None, ASKED, None) is None
    assert concurrency.waiting_for({ASKED: "ready"}, ASKED, None) is None
    assert concurrency.waiting_for({"real": "ready"}, ASKED, "real") is None  # alias, loaded
    assert concurrency.waiting_for({OTHER: "ready"}, ASKED, None) is None  # undecidable
    assert concurrency.waiting_for({OTHER: "ready"}, ASKED, "real") == {OTHER: "ready"}
    assert concurrency.waiting_for({ASKED: "starting"}, ASKED, None) == {}
    many = {f"m{i}": "ready" for i in range(12)} | {ASKED: "starting"}
    assert len(concurrency.waiting_for(many, ASKED, None)) == concurrency.BACKEND_WAIT_MAX_MODELS


# --- (j) the progress heartbeat --------------------------------------------------------------


def test_the_progress_text_names_the_loaded_model():
    token = cancellation.Token("local_summarize")
    token.status["backend_wait"] = [OTHER]
    assert i18n.t("mcp.progress.backend_wait", loaded=OTHER) in token.progress_message()
    token.status["backend_wait"] = []
    assert i18n.t("mcp.progress.backend_wait_unknown") in token.progress_message()
    # The turn and slot waits keep their texts and go first.
    token.status["wait"] = "slot"
    assert i18n.t("mcp.progress.slot") in token.progress_message()


@backend_mock.mock
def test_a_waiting_send_changes_the_heartbeat_of_its_call():
    """In use: a `tools/call` token (the abandonable send path) gets the text from the watch."""
    chat = _HeldChat()
    backend_mock.post(CHAT).mock(side_effect=chat)
    backend_mock.get(RUNNING).mock(
        return_value=_running((OTHER, "ready"), ("other-b", "starting"), (ASKED, "starting"))
    )
    token = cancellation.Token("local_summarize")
    entry_id = _start()
    try:
        thread = _send_in_slot(entry_id, token)
        expected = i18n.t("mcp.progress.backend_wait", loaded=f"other-b, {OTHER}")
        assert _until(lambda: expected in token.progress_message())
        assert i18n.t("mcp.progress.running") not in token.progress_message()
        chat.gates[0].set()
        thread.join(5)
        assert not thread.errors
        assert "backend_wait" not in token.status
        assert i18n.t("mcp.progress.running") in token.progress_message()
    finally:
        chat.gates[0].set()
        server._inflight_end(entry_id)


# --- the slot stops an abandoned send's watch -----------------------------------------------


@backend_mock.mock
def test_letting_the_place_go_stops_the_watch_of_an_abandoned_send():
    chat = _HeldChat()
    backend_mock.post(CHAT).mock(side_effect=chat)
    backend_mock.get(RUNNING).mock(return_value=_running((OTHER, "ready"), (ASKED, "starting")))
    token = cancellation.Token("local_summarize")
    entry_id = _start()
    try:
        thread = _send_in_slot(entry_id, token)
        assert _until(lambda: _entry(entry_id).get("state") == "waiting_backend")
        token.cancel(cancellation.REASON_ABORTED)  # the send is abandoned, its POST still pending
        thread.join(5)
        assert thread.errors and isinstance(thread.errors[0], cancellation.CallCancelled)
        assert "backend_wait" not in _entry(entry_id)
        time.sleep(0.2)  # the watch would have sampled again by now
        assert "backend_wait" not in _entry(entry_id)
    finally:
        chat.gates[0].set()
        server._inflight_end(entry_id)


def test_the_snapshot_keeps_old_entries_as_they_were(tmp_path, monkeypatch):
    """REQ-042: an entry without `backend_wait` (an older process) reads as before."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    entry_id = _start()
    try:
        with server._slot(entry_id):
            entry = _entry(entry_id)
            assert entry["state"] == "running"
            assert "backend_wait" not in entry
    finally:
        server._inflight_end(entry_id)
