"""#575 + #579: a read deadline's text counts the wait without a turn before its send.

#575 says «it waited N s for the turn or a slot» from the trace's phases. #579 made the operations
without a turn (its daemon unreachable) wait one at a time for a blind place, but that wait was
only added to `turn_wait_ms`: no phase in the trace, so the error of #577's case (~55 s between the
dead turn and the blind queue) said nothing of the wait. Now the attempt at an unusable daemon and
the blind wait are unpublished phases of the trace (`concurrency.QUEUE_PHASES`); the usage event's
`phases` stay as they were (no `turn` with the daemon unusable, REQ-026 of lot 4).

The turn daemon is a fake transport that refuses; the backend goes through the real `_post_chat`.
"""

from __future__ import annotations

import contextvars
import json
import re
import threading
import time
from pathlib import Path

import backend_mock
import httpx2
import pytest

from local_delegate import concurrency, config, i18n, remote_turn, server, topology

_URL = "http://127.0.0.1:19393/"
BASE = "http://127.0.0.1:9292/v1"
CHAT = BASE + "/chat/completions"
RUNNING = "http://127.0.0.1:9292/running"
#: What `/running` says is loaded: another model, so the text is the swap one; the note on the wait
#: goes after the text of any cause.
LOADED = "gemma4-26b-a4b"
CAP_S = 15.0
FIRST_SEND_S = 1.6  # what the second operation waits for the blind place: over the 1 s threshold


class _Refusing:
    """The turn daemon as the client's transport: every request is refused."""

    def stream(self, method: str, url: str, *, json: dict, headers: dict, timeout=None):
        raise httpx2.ConnectError("refused")

    def close(self) -> None:
        pass


@pytest.fixture
def mac(monkeypatch, tmp_path):
    """A remote backend without topology, a refusing turn daemon at `_URL`, a temporary log."""
    monkeypatch.setattr(config, "BASE_URL", BASE)
    monkeypatch.setattr(config, "TURN_URL", _URL)
    monkeypatch.setattr(config, "WEB_PORT", 9393)
    monkeypatch.setattr(config, "FALLBACK", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(
        server,
        "_operation_topology",
        lambda: topology.NoTopology(server.NO_TURN_REMOTE_BACKEND),
    )
    monkeypatch.setattr(remote_turn, "BLIND_POLL_S", 0.02)
    monkeypatch.setattr(concurrency, "BACKEND_SAMPLE_DELAY_S", 0.05)
    monkeypatch.setattr(concurrency, "BACKEND_WAIT_RESAMPLE_S", 0.05)
    monkeypatch.setattr(concurrency, "RUNNING_CACHE_S", 0.0)
    monkeypatch.setattr(server, "_resolved_model_name", lambda model: model)
    monkeypatch.setattr(server, "_probe_delay", lambda: 0.0)
    concurrency.reset_cache()
    remote_turn.reset()
    remote_turn.set_client_factory(_Refusing)
    yield tmp_path
    remote_turn.set_client_factory(remote_turn._new_client)
    remote_turn.reset()
    concurrency.reset_cache()


def _queued_note() -> re.Pattern[str]:
    """`read_timeout_queued` with any number of seconds."""
    template = i18n.t("mcp.error.read_timeout_queued", queued="@@")
    return re.compile(re.escape(template).replace("@@", r"(\d+)"))


def _first_ok_then_timeout():
    """The first send answers after `FIRST_SEND_S`; the next one runs out of its read deadline."""
    calls = {"n": 0}
    lock = threading.Lock()

    def effect(_request):
        with lock:
            calls["n"] += 1
            number = calls["n"]
        if number == 1:
            # The wait is timed from when the other one is queued for the blind place, so a slow
            # runner that starts it late does not shorten it below the threshold.
            deadline = time.monotonic() + CAP_S / 3
            while not remote_turn.blind_contended(_URL) and time.monotonic() < deadline:
                time.sleep(0.01)
            time.sleep(FIRST_SEND_S)
            return backend_mock.chat_response("a")
        raise httpx2.ReadTimeout("timed out")

    return effect, calls


def _classify_in_threads(n: int) -> list[object]:
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


@backend_mock.mock
def test_the_blind_wait_before_a_read_timeout_is_named(mac):
    """#577's case in small: two at once without a turn; the second waits for the blind place
    and then runs out of its deadline. Positive control: without the `blind` phase the text ends
    at the read-timeout text, with no wait."""
    backend_mock.get(RUNNING).mock(
        return_value=httpx2.Response(200, json={"running": [{"model": LOADED, "state": "ready"}]})
    )
    effect, calls = _first_ok_then_timeout()
    backend_mock.post(CHAT).mock(side_effect=effect)

    results = _classify_in_threads(2)

    assert calls["n"] == 2, f"{calls['n']} sends: the test did not reach the second one"
    texts = [str(r) for r in results]
    timed_out = [t for t in texts if server.ERROR_PREFIX in t]
    assert len(timed_out) == 1, texts
    found = _queued_note().search(timed_out[0])
    assert found is not None, f"the read-timeout text does not name the blind wait: {timed_out[0]}"
    waited_s = int(found.group(1))
    assert waited_s >= 1, timed_out[0]

    mine = [e for e in _events(mac) if e.get("tool") == "local_classify"]
    assert len(mine) == 2 and all(e.get("remote_turn") == "unreachable" for e in mine), mine
    waited = [e for e in mine if e.get("error") == "read_timeout"]
    assert len(waited) == 1, mine
    event = waited[0]
    # The event's counters and phases stay as #579 left them.
    assert int(event.get("turn_wait_ms") or 0) >= 1000, event
    phases = (event.get("concurrency") or {}).get("phases") or {}
    assert set(phases) <= {"turn", "slot", "backend"}, phases  # the internal ones are not logged
    assert "turn" not in phases, phases
    # Here the note and the event agree (rounded seconds) because the daemon refuses at once: an
    # unusable daemon that takes long to answer is in the note, not in `turn_wait_ms`.
    assert abs(waited_s - event["turn_wait_ms"] / 1000) <= 1, (waited_s, event["turn_wait_ms"])


def test_an_unusable_daemon_leaves_its_attempt_in_the_trace_but_not_in_the_log():
    """`_remote_wait`: the attempt that ends in `Unusable` is `turn_unusable`, never `turn`."""

    def unusable(_on_wait, _stop):
        time.sleep(0.05)
        raise remote_turn.Unusable(remote_turn.UNREACHABLE)

    def in_an_operation() -> concurrency.Trace:
        trace = concurrency.start(LOADED)
        with pytest.raises(remote_turn.Unusable):
            server._OperationTurn._remote_wait(unusable, lambda *_: None, lambda: False)
        return trace

    trace = contextvars.copy_context().run(in_an_operation)
    assert trace.phase_ms(concurrency.TURN_UNUSABLE_PHASE) >= 40
    assert trace.phase_ms("turn") == 0
    assert trace.phase_ms(*concurrency.QUEUE_PHASES) >= 40
    assert "phases" not in trace.log_fields(), trace.log_fields()


def _explained_with(phase: str, ms: int) -> str:
    """`_read_timeout_explained` with a real trace holding only `phase`, outside any send."""

    def in_an_operation() -> str:
        trace = concurrency.start(LOADED)
        now = time.time()
        trace.record(phase, now - ms / 1000, now, ms)
        text, _load = server._read_timeout_explained(LOADED, "timed out.", None)
        return text

    return contextvars.copy_context().run(in_an_operation)


@pytest.mark.parametrize("phase", [concurrency.TURN_UNUSABLE_PHASE, concurrency.BLIND_PHASE])
def test_each_internal_wait_alone_is_named(phase):
    """A daemon slow to fail (#577: two lost answers) is named even with `turn_wait_ms` at 0."""
    text = _explained_with(phase, 1600)
    assert text == "timed out. " + i18n.t("mcp.error.read_timeout_queued", queued=2), text


@pytest.mark.parametrize("phase", [concurrency.TURN_UNUSABLE_PHASE, concurrency.BLIND_PHASE])
def test_an_internal_wait_under_a_second_says_nothing(phase):
    assert _explained_with(phase, 400) == "timed out."
