"""Aborted delegations are logged, and a saturated queue says so (issue #476).

Measured on 2026-10-29: three `local_explain_code` calls aborted by the client after 1800 s left
no line in `usage-YYYYMM.jsonl`, and the panel showed 0 % errors. The client that gives up does not
always tell the daemon (an aborted call was seen still running chunk after chunk), so the daemon
keeps its own budget (`LOCAL_DELEGATE_CALL_MAX_S`), logs an operation that dies with an exception,
and turns a queue that does not move into a fast, clear error (`LOCAL_DELEGATE_QUEUE_MAX_WAIT_S`).

These run against the daemon's real app (the helpers of `test_desktop_bridge`), so the whole path
is covered: the call, the middleware, the usage log and `/api/stats`, which feeds the panel's
Errors card.
"""

from __future__ import annotations

import json
import threading
import time

import anyio
import httpx2
import pytest
from test_desktop_bridge import (
    _HTTP_TIMEOUT,
    CLASSIFY,
    LONG_MODEL,
    SUMMARIZE,
    TOKEN,
    _events,
    _RawSession,
    real_daemon,
)
from test_desktop_bridge import slow_backend as _bridge_slow_backend

from local_delegate import config, server, turn
from local_delegate.web import metrics

# The fixture of `test_desktop_bridge` (backend in ~20 slow calls, two slots, today's topology),
# registered here under its own name.
slow_backend = _bridge_slow_backend


def _call(url: str, message: dict) -> tuple[dict | None, float]:
    async def scenario() -> tuple[dict | None, float]:
        async with httpx2.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            session = _RawSession(client, url)
            await session.open()
            started = time.monotonic()
            answer = await session.call(message)
            return answer, time.monotonic() - started

    return anyio.run(scenario)


def _error_text(answer: dict | None) -> str:
    assert answer is not None and "result" in answer, answer
    result = answer["result"]
    assert result.get("isError") is True, result
    return " ".join(c.get("text", "") for c in result.get("content", []))


def _panel_errors() -> int:
    """What the panel's Errors card reads: `/api/stats` over the test's log directory."""
    response = metrics.stats(from_=None, to=None, include_tests=None, lang="en", session=None)
    return json.loads(response.body)["total"]["errors"]


def test_deadline_cancels_the_call_and_logs_it_once(monkeypatch, slow_backend, tmp_path):
    """Past `CALL_MAX_S` the call stops, the caller is told why, and ONE failed event is written.

    Without the fix the ~8 s chunked summary runs to the end and is logged as a success.
    """
    monkeypatch.setattr(config, "CALL_MAX_S", 1.0)
    with real_daemon(monkeypatch, TOKEN) as url:
        answer, elapsed = _call(url, SUMMARIZE)
    text = _error_text(answer)
    assert "LOCAL_DELEGATE_CALL_MAX_S" in text, text
    assert elapsed < 4.0, f"the deadline did not cut the call: {elapsed:.1f} s"
    events = [e for e in _events(tmp_path) if e.get("tool") == "local_summarize"]
    assert len(events) == 1, events  # one line for the whole chunked operation, not per piece
    event = events[0]
    assert event["ok"] is False and event["error"] == "cancelled", event
    assert event["cancel_reason"] == "deadline", event
    assert 900 <= event["latency_ms"] < 4000, event
    assert event["model"] == LONG_MODEL and event["chars_in"] > 0, event
    # What it measured until the cut: the real backend calls it made and the pieces it announced.
    assert event.get("chunks", 1) >= 2 and event.get("pieces", 0) >= 2, event
    assert _panel_errors() == 1


def test_unexpected_exception_mid_delegation_is_logged(monkeypatch, slow_backend, tmp_path):
    """An exception the operation does not handle leaves a failed event with its type only."""

    def broken(_model: str, _payload: dict) -> server.ChatResult:
        raise RuntimeError("secret-content-never-logged")

    monkeypatch.setattr(server, "_post_chat", broken)
    with real_daemon(monkeypatch, TOKEN) as url:
        answer, _elapsed = _call(url, CLASSIFY)
    _error_text(answer)
    events = [e for e in _events(tmp_path) if e.get("tool") == "local_classify"]
    assert len(events) == 1, events
    event = events[0]
    assert event["ok"] is False and event["error"] == "exception", event
    assert event["exception_type"] == "RuntimeError", event
    lines = "".join(p.read_text(encoding="utf-8") for p in tmp_path.glob("usage*.jsonl"))
    assert "secret-content-never-logged" not in lines
    assert _panel_errors() == 1


def test_slot_wait_past_the_limit_fails_fast_and_is_logged(monkeypatch, slow_backend, tmp_path):
    """Every slot taken for longer than `QUEUE_MAX_WAIT_S`: a clear error now, not at 1800 s."""
    monkeypatch.setattr(config, "QUEUE_MAX_WAIT_S", 0.5)
    slots = server._chat_slots  # two, from the fixture
    assert slots.acquire(blocking=False) and slots.acquire(blocking=False)
    held = [True]
    lock = threading.Lock()

    def free() -> None:
        with lock:
            if held[0]:
                held[0] = False
                slots.release()
                slots.release()

    # Without the limit the call would wait forever: the slots come back after 5 s, so the test
    # ends (and fails on its asserts) instead of hanging.
    timer = threading.Timer(5.0, free)
    timer.start()
    try:
        with real_daemon(monkeypatch, TOKEN) as url:
            answer, elapsed = _call(url, CLASSIFY)
    finally:
        timer.cancel()
        free()
    text = _error_text(answer)
    assert "LOCAL_DELEGATE_QUEUE_MAX_WAIT_S" in text and "2" in text, text
    assert elapsed < 3.0, f"the saturated queue held the caller {elapsed:.1f} s"
    assert slow_backend.calls == [], "a call that never got a slot reached the backend"
    events = [e for e in _events(tmp_path) if e.get("tool") == "local_classify"]
    assert len(events) == 1, events
    event = events[0]
    assert event["ok"] is False and event["error"] == "queue_saturated", event
    assert event["slot_wait_ms"] >= 450, event
    assert _panel_errors() == 1


def test_turn_wait_past_the_limit_raises_queue_saturated(monkeypatch, tmp_path):
    """The turn's queue: one wait past the limit leaves the queue with the position it had."""
    monkeypatch.setattr(config, "QUEUE_MAX_WAIT_S", 0.2)
    op = server._OperationTurn(1, "some-model", "local_summarize")

    def wait(on_wait, stop):
        on_wait(3, ("model-a", "model-b"))
        cap = time.monotonic() + 3
        while stop is None or not stop():
            if time.monotonic() > cap:
                raise AssertionError("the turn wait never gave up")
            time.sleep(0.02)
        raise turn.AbandonedWait("op")

    with pytest.raises(server.QueueSaturated) as raised:
        op._waiting_for(object(), wait)
    assert "3" in str(raised.value) and "model-a" in str(raised.value)
    assert op.wait_ms >= 150


def test_a_call_alone_keeps_todays_behaviour(slow_backend, tmp_path):
    """Defaults: a call without a queue is untouched, and it is logged once, as before."""
    assert config.CALL_MAX_S == 1800.0 and config.QUEUE_MAX_WAIT_S == 900.0
    with pytest.MonkeyPatch.context() as monkeypatch, real_daemon(monkeypatch, TOKEN) as url:
        answer, _elapsed = _call(url, CLASSIFY)
    assert answer is not None and answer["result"].get("isError") is not True, answer
    events = [e for e in _events(tmp_path) if e.get("tool") == "local_classify"]
    assert len(events) == 1 and events[0]["ok"] is True, events
    assert "slot_wait_ms" not in events[0] and "exception_type" not in events[0], events[0]
