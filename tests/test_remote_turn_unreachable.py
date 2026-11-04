"""Issue #577: with the remote turn unreachable, operations do not compete blindly for the backend.

Measured on 2026-11-04 from a Mac client: the PC's turn daemon stopped answering while its backend
was busy with the PC's own long delegation. Five `local_describe_image` went to the backend without
a turn, two at a time, and each ran out of its 180 s (two of them after 180 s more queued for a
slot: ~415 s). Now:

- without a turn because its daemon is unreachable, operations go one at a time (REQ-001);
- one of them that runs out of time at the backend opens the remote turn's cut (REQ-002), and the
  ones waiting, and the new ones, fail at once without calling the backend (REQ-003);
- the error of an attempt made without a turn says so (REQ-004);
- several turn waits at once stop probing as soon as one decides the daemon is unusable (REQ-005).

The turn daemon is a fake transport that refuses or never answers; the backend is `_post_chat`.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

import httpx2
import pytest

from local_delegate import cancellation, config, cooldown, i18n, remote_turn, server, topology

_URL = "http://127.0.0.1:19393/"
BASE = "http://127.0.0.1:9292/v1"
MODEL = "gemma4-26b-a4b"
CAP_S = 10.0
_dumps = json.dumps  # `json` is also the name of a `stream` argument below


class _Daemon:
    """The turn daemon as the client's transport: every request fails the way `raises` says."""

    def __init__(self, raises: Callable[[str], Exception]) -> None:
        self.raises = raises
        self.requests: list[str] = []
        self._lock = threading.Lock()

    def stream(self, method: str, url: str, *, json: dict, headers: dict, timeout=None):
        path = url.split("/api/turn/", 1)[-1]
        with self._lock:
            self.requests.append(path)
        raise self.raises(path)

    def count(self, path: str | None = None) -> int:
        with self._lock:
            return sum(1 for p in self.requests if path is None or p == path)

    def close(self) -> None:
        pass


class _Backend:
    """`_post_chat`: counts the calls, how many run at once, and answers what `answer` says."""

    def __init__(self, answer: Callable[[int], server.ChatResult], hold_s: float = 0.0) -> None:
        self.answer = answer
        self.hold_s = hold_s
        self.calls = 0
        self.running = 0
        self.most = 0
        self._lock = threading.Lock()

    def __call__(self, _model: str, _payload: dict) -> server.ChatResult:
        with self._lock:
            self.calls += 1
            number = self.calls
            self.running += 1
            self.most = max(self.most, self.running)
        try:
            time.sleep(self.hold_s)
            return self.answer(number)
        finally:
            with self._lock:
                self.running -= 1


def _ok(_number: int) -> server.ChatResult:
    return server.ChatResult(text="a", ok=True, finish_reason="stop")


def _read_timeout_text() -> str:
    return server.ERROR_PREFIX + i18n.t("mcp.error.read_timeout", model=MODEL, seconds="180")


def _timed_out(_number: int) -> server.ChatResult:
    """What `_post_chat` returns for a read deadline with the model not loaded (the Mac's case in
    the issue): `error: "read_timeout"`, class `capacity_or_load`, no cause known."""
    return server.ChatResult(
        text=_read_timeout_text(),
        ok=False,
        error="read_timeout",
        error_class="capacity_or_load",
        read_timeout_cause=None,
    )


def _loading_503(_number: int) -> server.ChatResult:
    """A 5xx at once that the classifier calls `capacity_or_load` (a 503 "loading")."""
    return server.ChatResult(
        text=server.ERROR_PREFIX + "HTTP 503: loading model",
        ok=False,
        error="http_503",
        error_class="capacity_or_load",
    )


@pytest.fixture
def mac(monkeypatch):
    """This process: a remote backend without topology, and a turn daemon at `_URL`."""
    monkeypatch.setattr(config, "BASE_URL", BASE)
    monkeypatch.setattr(config, "TURN_URL", _URL)
    monkeypatch.setattr(config, "WEB_PORT", 9393)
    monkeypatch.setattr(config, "FALLBACK", False)
    monkeypatch.setattr(
        server,
        "_operation_topology",
        lambda: topology.NoTopology(server.NO_TURN_REMOTE_BACKEND),
    )
    monkeypatch.setattr(remote_turn, "BLIND_POLL_S", 0.02)
    remote_turn.reset()
    yield
    remote_turn.set_client_factory(remote_turn._new_client)
    remote_turn.reset()


def _refusing(monkeypatch) -> _Daemon:
    daemon = _Daemon(lambda _path: httpx2.ConnectError("refused"))
    remote_turn.set_client_factory(lambda: daemon)
    return daemon


def _classify_in_threads(n: int) -> list[object]:
    """`n` real tool calls at once; each slot holds what it returned or raised."""
    results: list[object] = [None] * n
    start = threading.Barrier(n)

    def run(i: int) -> None:
        start.wait(CAP_S)
        try:
            results[i] = server.local_classify(text=f"hola {i}", labels=["a", "b"])
        except Exception as error:  # the test looks at it
            results[i] = error

    threads = [threading.Thread(target=run, args=(i,), daemon=True) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(CAP_S)
    assert not any(t.is_alive() for t in threads), "a call never ended"
    return results


def _events(log_dir: Path) -> list[dict]:
    events: list[dict] = []
    for file in sorted(log_dir.glob("usage*.jsonl")):
        events += [json.loads(x) for x in file.read_text(encoding="utf-8").splitlines() if x]
    return events


# --- REQ-001: without a turn, one at a time --------------------------------------------------


def test_without_turn_the_calls_go_one_at_a_time_and_all_succeed(mac, monkeypatch, tmp_path):
    """The daemon stopped with a healthy backend (#512): everything still works, in series."""
    _refusing(monkeypatch)
    backend = _Backend(_ok, hold_s=0.15)
    monkeypatch.setattr(server, "_post_chat", backend)
    results = _classify_in_threads(3)
    assert not any(isinstance(r, Exception) for r in results), results
    assert backend.calls == 3
    assert backend.most == 1, f"{backend.most} calls ran at once at the backend without a turn"
    mine = [e for e in _events(tmp_path) if e.get("tool") == "local_classify"]
    assert len(mine) == 3 and all(e.get("remote_turn") == "unreachable" for e in mine), mine
    assert cooldown.remote_turn_cut().lookup(cooldown.backend_key()) is None


def test_a_cancelled_wait_for_the_blind_place_leaves_and_frees_nothing(mac, monkeypatch):
    _refusing(monkeypatch)
    first = server._OperationTurn(1, MODEL, "local_classify")
    first.ensure(MODEL)
    assert first.remote_turn == "unreachable" and first._blind == _URL
    token = cancellation.Token("local_classify")
    second = server._OperationTurn(2, MODEL, "local_classify")
    outcome: list[object] = []

    def run() -> None:
        cancellation._CURRENT.set(token)
        try:
            second.ensure(MODEL)
            outcome.append("got it")
        except BaseException as error:  # the test looks at it
            outcome.append(error)

    waiting = threading.Thread(target=run, daemon=True)
    waiting.start()
    time.sleep(0.1)
    assert waiting.is_alive(), outcome
    token.cancel(cancellation.REASON_ABORTED)
    waiting.join(CAP_S)
    assert not waiting.is_alive()
    assert isinstance(outcome[0], cancellation.CallCancelled), outcome
    assert second._blind is None
    first.release_slot()
    third = server._OperationTurn(3, MODEL, "local_classify")
    third.ensure(MODEL)  # free again: at once
    assert third._blind == _URL
    third.release_slot()


# --- REQ-002/003: the cut --------------------------------------------------------------------


def test_a_timeout_without_turn_cuts_the_calls_waiting_behind_it(mac, monkeypatch):
    """Four at once, the backend saturated: one goes, the other three fail at once."""
    _refusing(monkeypatch)
    backend = _Backend(_timed_out, hold_s=0.3)
    monkeypatch.setattr(server, "_post_chat", backend)
    t0 = time.monotonic()
    results = _classify_in_threads(4)
    elapsed = time.monotonic() - t0
    assert backend.calls == 1, f"{backend.calls} calls went to a backend known to be saturated"
    cut = [r for r in results if isinstance(r, server.RemoteTurnDown)]
    assert len(cut) == 3, results
    assert all("127.0.0.1" in str(r) for r in cut), cut
    assert elapsed < 3.0, f"the calls waiting behind took {elapsed:.1f} s to leave"
    active = cooldown.remote_turn_cut().lookup(cooldown.backend_key())
    assert active is not None and 0 < active.remaining_s <= config.REMOTE_TURN_CUT_S


def test_with_the_cut_open_a_new_call_fails_at_once(mac, monkeypatch):
    _refusing(monkeypatch)
    cooldown.remote_turn_cut().record_failure(cooldown.backend_key(), "read_timeout")
    backend = _Backend(_ok)
    monkeypatch.setattr(server, "_post_chat", backend)
    with pytest.raises(server.RemoteTurnDown) as raised:
        server.local_classify(text="hola", labels=["a", "b"])
    assert backend.calls == 0
    text = str(raised.value)
    template = i18n.t("mcp.error.remote_turn_down", host="@@", until="@@", remaining="@@")
    pieces = [p for p in template.split("@@") if p.strip()]
    assert pieces and all(p in text for p in pieces), text
    assert "127.0.0.1" in text, text


def _cut_entry(key: str) -> dict | None:
    state = Path(config.LOG_DIR) / cooldown.REMOTE_TURN_CUT_STATE_FILE
    if not state.exists():
        return None
    return json.loads(state.read_text(encoding="utf-8")).get(key)


def _expired_cut(monkeypatch) -> str:
    """A cut that was opened and has just expired: the next call is its probe."""
    key = cooldown.backend_key()
    monkeypatch.setattr(config, "REMOTE_TURN_CUT_S", 0.2)
    monkeypatch.setattr(config, "REMOTE_TURN_CUT_MAX_S", 0.2)
    cooldown.remote_turn_cut().record_failure(key, "read_timeout")
    assert _cut_entry(key) is not None
    time.sleep(0.25)
    return key


def test_a_success_without_turn_closes_the_cut(mac, monkeypatch):
    _refusing(monkeypatch)
    key = _expired_cut(monkeypatch)
    monkeypatch.setattr(server, "_post_chat", _Backend(_ok))
    server.local_classify(text="hola", labels=["a", "b"])
    assert _cut_entry(key) is None, "a success without a turn did not clear the cut"


class _Granting:
    """A turn daemon that grants at once (and accepts releases)."""

    def stream(self, method: str, url: str, *, json: dict, headers: dict, timeout=None):
        body = {
            "v": 1,
            "daemon_id": "the-pc",
            "lease": "L1",
            "status": "granted" if url.endswith("acquire") else "expired",
            "position": None,
            "in_use": [],
            "model": MODEL,
            "forced": False,
            "heartbeat_s": 5.0,
            "stalled_s": 0.0,
        }
        response = httpx2.Response(200, content=_dumps(body).encode())
        return _Held(response)

    def close(self) -> None:
        pass


class _Held:
    def __init__(self, response: httpx2.Response) -> None:
        self.response = response

    def __enter__(self) -> httpx2.Response:
        return self.response

    def __exit__(self, *_exc) -> None:
        self.response.close()


def test_a_granted_turn_closes_the_cut(mac, monkeypatch):
    key = _expired_cut(monkeypatch)
    remote_turn.set_client_factory(_Granting)
    op = server._OperationTurn(1, MODEL, "local_classify")
    try:
        op.ensure(MODEL)
        assert op.remote_turn == "granted" and op._blind is None
    finally:
        op.release_slot()
    assert _cut_entry(key) is None, "a granted turn did not clear the cut"


def test_the_cut_off_keeps_the_series_but_never_cuts(mac, monkeypatch):
    monkeypatch.setattr(config, "REMOTE_TURN_CUT", False)
    _refusing(monkeypatch)
    backend = _Backend(_timed_out, hold_s=0.05)
    monkeypatch.setattr(server, "_post_chat", backend)
    results = _classify_in_threads(3)
    assert backend.calls == 3 and backend.most == 1
    assert not any(isinstance(r, server.RemoteTurnDown) for r in results), results


# --- REQ-004: the error says there was no turn -----------------------------------------------


def test_the_error_of_a_call_without_turn_says_so(mac, monkeypatch):
    _refusing(monkeypatch)
    monkeypatch.setattr(server, "_post_chat", _Backend(_timed_out))
    op = server._OperationTurn(None, MODEL, "local_classify")
    try:
        result, _schema, attempts = server._with_fallback(
            MODEL,
            {"messages": []},
            role=None,
            explicit=False,
            size=10,
            json_schema_fallback=False,
            op=op,
        )
    finally:
        op.release_slot()
    note = i18n.t("mcp.error.no_remote_turn_note", host="127.0.0.1")
    assert result.text.endswith(note), result.text
    assert result.error == "read_timeout" and result.error_class == "capacity_or_load"
    assert attempts[-1].error == "read_timeout"


def test_a_granted_or_local_call_has_no_note(monkeypatch):
    """Nothing changes outside the case: a local operation's error stays as it was."""
    monkeypatch.setattr(server, "_post_chat", _Backend(_timed_out))
    monkeypatch.setattr(config, "FALLBACK", False)
    op = server._OperationTurn(None, MODEL, "local_classify")
    try:
        result, _schema, _attempts = server._with_fallback(
            MODEL,
            {"messages": []},
            role=None,
            explicit=False,
            size=10,
            json_schema_fallback=False,
            op=op,
        )
    finally:
        op.release_slot()
    assert result.text == _read_timeout_text()


# --- REQ-005: concurrent waits do not each pay the probing -----------------------------------


def test_a_wait_leaves_when_another_already_found_the_daemon_unreachable(mac, monkeypatch):
    def lost(_path: str) -> Exception:
        # Meanwhile, another operation's second lost answer decided: unreachable.
        remote_turn.remember(_URL, remote_turn.UNREACHABLE)
        return httpx2.ReadTimeout("slow")

    daemon = _Daemon(lost)
    remote_turn.set_client_factory(lambda: daemon)
    lease = remote_turn.RemoteLease(_URL, op="op1", host="mac", tool="local_classify", model=MODEL)
    with pytest.raises(remote_turn.Unusable) as raised:
        lease.acquire(lambda *_: None)
    assert raised.value.reason == remote_turn.UNREACHABLE
    assert daemon.count("acquire") == 1, "it probed again after another had already decided"


# --- REQ-006: the event ----------------------------------------------------------------------


def test_the_event_of_a_cut_call_says_why(tmp_path):
    token = cancellation.Token("local_classify")
    token.failure = server.RemoteTurnDown("cut")
    server._log_aborted(token)
    events = [e for e in _events(tmp_path) if e.get("tool") == "local_classify"]
    assert len(events) == 1, events
    event = events[0]
    assert event["ok"] is False and event["error"] == "remote_turn_unreachable", event
    assert event["remote_turn"] == "unreachable", event


# --- review of #579 ---------------------------------------------------------------------------


def _without_turn_attempt(answer) -> server.ChatResult:
    op = server._OperationTurn(None, MODEL, "local_classify")
    try:
        result, _schema, _attempts = server._with_fallback(
            MODEL,
            {"messages": []},
            role=None,
            explicit=False,
            size=10,
            json_schema_fallback=False,
            op=op,
        )
    finally:
        op.release_slot()
    return result


def test_a_5xx_at_once_neither_opens_the_cut_nor_says_no_turn(mac, monkeypatch):
    """A 503 "loading" is `capacity_or_load` but says nothing of a busy backend."""
    _refusing(monkeypatch)
    monkeypatch.setattr(server, "_post_chat", _Backend(_loading_503))
    result = _without_turn_attempt(_loading_503)
    assert cooldown.remote_turn_cut().lookup(cooldown.backend_key()) is None, (
        "a 5xx at once opened the remote turn's cut"
    )
    assert result.text == server.ERROR_PREFIX + "HTTP 503: loading model", result.text
    monkeypatch.setattr(server, "_post_chat", _Backend(_ok))
    server.local_classify(text="hola", labels=["a", "b"])  # the next call is not cut


def test_a_429_wait_is_not_cut_short_by_another(mac, monkeypatch):
    """A `429` means the daemon is alive: the wait goes on even if another gave up on it."""
    monkeypatch.setattr(remote_turn, "DEFAULT_HEARTBEAT_S", 0.05)
    answers = []

    class Busy:
        def stream(self, method, url, *, json, headers, timeout=None):
            answers.append(url)
            if len(answers) == 1:
                remote_turn.remember(_URL, remote_turn.UNREACHABLE)  # another one decided
                return _Held(httpx2.Response(429, content=b"{}"))
            return _Granting().stream(method, url, json=json, headers=headers)

        def close(self) -> None:
            pass

    remote_turn.set_client_factory(Busy)
    lease = remote_turn.RemoteLease(_URL, op="op1", host="mac", tool="local_classify", model=MODEL)
    try:
        grant = lease.acquire(lambda *_: None)
        assert grant is not None and lease.granted
    finally:
        lease.release()


def _hold(op: server._OperationTurn) -> threading.Thread:
    def run() -> None:
        try:
            op.ensure(MODEL)
        except BaseException as error:  # the test looks at it
            op.error = error  # type: ignore[attr-defined]

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def _until(condition: Callable[[], object], cap: float = 3.0) -> bool:
    end = time.monotonic() + cap
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_a_chunked_operation_gives_the_blind_place_between_chunks(mac, monkeypatch):
    _refusing(monkeypatch)
    first = server._OperationTurn(1, MODEL, "local_summarize")
    first.ensure(MODEL)  # the first chunk
    assert first._blind == _URL
    second = server._OperationTurn(2, MODEL, "local_classify")
    waiting = _hold(second)
    assert _until(lambda: remote_turn.blind_contended(_URL)), "the second never queued"
    next_chunk = _hold(first)  # the first one's next chunk
    assert _until(lambda: second._blind == _URL), "the place was never given between chunks"
    assert next_chunk.is_alive(), "the first one went on without the place"
    second.release_slot()
    next_chunk.join(CAP_S)
    waiting.join(CAP_S)
    assert not next_chunk.is_alive() and first._blind == _URL
    first.release_slot()


def test_a_wait_for_the_blind_place_that_does_not_move_is_saturated(mac, monkeypatch):
    monkeypatch.setattr(config, "QUEUE_MAX_WAIT_S", 0.3)
    _refusing(monkeypatch)
    first = server._OperationTurn(1, MODEL, "local_summarize")
    first.ensure(MODEL)
    second = server._OperationTurn(2, MODEL, "local_classify")
    t0 = time.monotonic()
    waiting = _hold(second)
    waiting.join(3.0)
    try:
        assert not waiting.is_alive(), "the wait never said the queue was saturated"
        error = getattr(second, "error", None)
        assert isinstance(error, server.QueueSaturated), repr(error)
        assert "127.0.0.1" in str(error)
        assert time.monotonic() - t0 < 2.0
        assert not remote_turn.blind_contended(_URL), "the saturated wait stayed in the queue"
    finally:
        first.release_slot()
        waiting.join(CAP_S)
