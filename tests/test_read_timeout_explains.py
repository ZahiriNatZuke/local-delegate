"""Issue #572: a `read_timeout` says where its deadline went and which piece ran out.

Measured on 2026-11-04: `local_commit_msg` of a ~58 KB diff failed with «qwen36-35b-a3b estaba
cargado pero no respondió en 180 s». The usage event said otherwise: no turn or slot wait, the model
`starting` 3 s into the send, and the FIRST of several pieces using the whole deadline alone. The
deadline is per send and does not change; the text now says, only when known:

* the model was seen loading and then `ready` during the send (and when): REQ-002;
* the operation waited for the daemon's turn or a slot before sending: REQ-003;
* the piece of a chunked operation that ran out: REQ-001.

Without any of that the text is today's (REQ-004, `tests/test_read_timeout_cause.py`).
"""

from __future__ import annotations

import contextvars
import json
import threading
import time

import backend_mock
import httpx2
import pytest

from local_delegate import concurrency, config, i18n, server

CHAT = "http://test-backend/v1/chat/completions"
RUNNING = "http://test-backend/running"
ASKED = "qwen36-35b-a3b"
BODY = {"model": ASKED, "messages": [{"role": "user", "content": "hola"}]}


@pytest.fixture(autouse=True)
def quick_watch(reload_config, monkeypatch):
    """Test backend, no `/running` cache, a short watch (real ones: 3/10 s) and the PC's topology."""
    reload_config()
    concurrency.reset_cache()
    monkeypatch.setattr(concurrency, "BACKEND_SAMPLE_DELAY_S", 0.05)
    monkeypatch.setattr(concurrency, "BACKEND_WAIT_RESAMPLE_S", 0.05)
    monkeypatch.setattr(concurrency, "RUNNING_CACHE_S", 0.0)
    monkeypatch.setattr(server, "_resolved_model_name", lambda model: model)
    yield
    concurrency.reset_cache()


def _running(state: str) -> httpx2.Response:
    return httpx2.Response(200, json={"running": [{"model": ASKED, "state": state}]})


def _seconds() -> object:
    return server._machine(config.HTTP_TIMEOUT)


def _send_in_slot() -> server.ChatResult:
    """One send with its place and in-flight entry, as a tool's piece makes it."""
    entry_id = server._inflight_start(
        tool="local_commit_msg", model=ASKED, source="path", chars_in=10
    )
    try:
        with server._slot(entry_id):
            return server._send(ASKED, BODY)
    finally:
        server._inflight_end(entry_id)


def _timeout_after(seconds: float):
    def effect(_request):
        time.sleep(seconds)
        raise httpx2.ReadTimeout("timed out")

    return effect


def _starting_for_the_first_watch_sample():
    """`/running` that answers `starting` only to the first query of the send's watch thread and
    `ready` to everything else (the deadline's probe, the log's sample): by thread, not by clock,
    so a loaded machine cannot turn that first sample into `ready` (review of #572, judge 2)."""
    seen = {"watch": 0}
    lock = threading.Lock()

    def effect(_request):
        if threading.current_thread().name == "local-delegate-send-watch":
            with lock:
                seen["watch"] += 1
                first = seen["watch"] == 1
            if first:
                return _running("starting")
        return _running("ready")

    return effect


# --- REQ-002: the model loaded during the send ------------------------------------------------


@backend_mock.mock
def test_a_model_that_loaded_during_the_send_is_not_called_loaded(monkeypatch):
    """#572's case: `starting` at the first samples, `ready` before the deadline, no answer.

    Positive control (main): the text is «estaba cargado…» (`read_timeout_busy`) and
    `read_timeout_load_ms` does not exist.
    """
    monkeypatch.setattr(server, "_probe_delay", lambda: 0.2)  # the deadline's sample: ready
    running = backend_mock.get(RUNNING).mock(side_effect=_starting_for_the_first_watch_sample())
    backend_mock.post(CHAT).mock(side_effect=_timeout_after(0.7))

    result = _send_in_slot()

    assert running.call_count >= 3  # guard: watch `starting`, watch `ready`, the probe
    assert result.error == "read_timeout"
    assert result.read_timeout_cause == "busy"  # the cause keeps its value
    assert result.read_timeout_load_ms is not None
    assert 50 <= result.read_timeout_load_ms < 700, result.read_timeout_load_ms
    load_s = result.read_timeout_load_ms / 1000
    expected = i18n.t(
        "mcp.error.read_timeout_loaded_late",
        model=ASKED,
        seconds=_seconds(),
        load=round(load_s),
        left=max(0, round(config.HTTP_TIMEOUT - load_s)),
    )
    assert result.text == server.ERROR_PREFIX + expected
    assert i18n.t("mcp.error.read_timeout_busy", model=ASKED, seconds=_seconds()) not in result.text


@backend_mock.mock
def test_a_model_ready_from_the_first_sample_keeps_the_busy_text(monkeypatch):
    """Ready all along: that IS «it was loaded»; the text stays today's, with no load."""
    monkeypatch.setattr(server, "_probe_delay", lambda: 0.2)
    running = backend_mock.get(RUNNING).mock(return_value=_running("ready"))
    backend_mock.post(CHAT).mock(side_effect=_timeout_after(0.35))

    result = _send_in_slot()

    assert running.call_count >= 1  # guard: there was a photo
    assert result.read_timeout_cause == "busy"
    assert result.read_timeout_load_ms is None
    assert result.text == server.ERROR_PREFIX + i18n.t(
        "mcp.error.read_timeout_busy", model=ASKED, seconds=_seconds()
    )


@backend_mock.mock
def test_the_load_reaches_the_usage_event(monkeypatch, tmp_path):
    """Positive control (main): no `read_timeout_load_ms` in the event (KeyError)."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(server, "_probe_delay", lambda: 0.2)
    backend_mock.get(RUNNING).mock(side_effect=_starting_for_the_first_watch_sample())
    backend_mock.post(CHAT).mock(side_effect=_timeout_after(0.7))

    out = server.local_commit_msg(diff=_diff(1, 40))

    assert out.startswith(server.ERROR_PREFIX)
    (event,) = [e for e in _events(tmp_path) if e.get("error") == "read_timeout"]
    assert event["read_timeout_cause"] == "busy"
    assert 50 <= event["read_timeout_load_ms"] < 700


@backend_mock.mock
def test_a_model_ready_only_in_the_deadline_probe_is_ready_at_the_end(monkeypatch):
    """The watch samples every 10 s: a model ready after its last sample is seen ready only by
    the deadline's probe. Still not «it was loaded» (review of #572, judge 1).

    Positive control (before the review fix): the busy text, «it was loaded».
    """
    monkeypatch.setattr(concurrency, "BACKEND_WAIT_RESAMPLE_S", 30.0)  # one watch sample only
    monkeypatch.setattr(server, "_probe_delay", lambda: 0.3)
    running = backend_mock.get(RUNNING).mock(side_effect=_starting_for_the_first_watch_sample())
    backend_mock.post(CHAT).mock(side_effect=_timeout_after(0.6))

    result = _send_in_slot()

    assert running.call_count == 2  # guard: the watch saw `starting`, the probe saw `ready`
    assert result.read_timeout_cause == "busy"
    assert result.text == server.ERROR_PREFIX + i18n.t(
        "mcp.error.read_timeout_loaded_at_end", model=ASKED, seconds=_seconds()
    )
    assert result.read_timeout_load_ms == 300  # the probe's moment: an upper bound


@backend_mock.mock
def test_a_swap_gets_no_load_note(monkeypatch):
    """`model_swap`: not ready at the deadline; the watch's view adds nothing to that text."""
    other = "gemma4-26b-a4b"
    monkeypatch.setattr(server, "_probe_delay", lambda: 0.2)
    backend_mock.get(RUNNING).mock(
        return_value=httpx2.Response(
            200,
            json={
                "running": [
                    {"model": other, "state": "ready"},
                    {"model": ASKED, "state": "starting"},
                ]
            },
        )
    )
    backend_mock.post(CHAT).mock(side_effect=_timeout_after(0.35))

    result = _send_in_slot()

    assert result.read_timeout_cause == "model_swap"
    assert result.read_timeout_load_ms is None
    assert result.text == server.ERROR_PREFIX + i18n.t(
        "mcp.error.read_timeout_swap", model=ASKED, seconds=_seconds(), loaded=other, hosts=""
    )


# --- REQ-003: the wait before the send ---------------------------------------------------------


@backend_mock.mock
def test_a_turn_wait_before_the_send_is_named(monkeypatch):
    """Positive control (main): the text ends at the busy text, without the wait."""
    monkeypatch.setattr(server, "_probe_delay", lambda: 0.0)
    backend_mock.get(RUNNING).mock(return_value=_running("ready"))
    backend_mock.post(CHAT).mock(side_effect=_timeout_after(0.2))

    def in_an_operation() -> server.ChatResult:
        trace = concurrency.start(ASKED)
        now = time.time()
        trace.record("turn", now - 2.4, now, 2400)  # 2.4 s waiting for the daemon's turn
        trace.record("slot", now, now, 0)
        return server._post_chat(ASKED, BODY)

    result = contextvars.copy_context().run(in_an_operation)

    busy = i18n.t("mcp.error.read_timeout_busy", model=ASKED, seconds=_seconds())
    queued = i18n.t("mcp.error.read_timeout_queued", queued=2)
    assert result.text == server.ERROR_PREFIX + busy + " " + queued


@backend_mock.mock
def test_a_wait_under_a_second_says_nothing(monkeypatch):
    monkeypatch.setattr(server, "_probe_delay", lambda: 0.0)
    backend_mock.get(RUNNING).mock(return_value=_running("ready"))
    backend_mock.post(CHAT).mock(side_effect=_timeout_after(0.2))

    def in_an_operation() -> server.ChatResult:
        trace = concurrency.start(ASKED)
        now = time.time()
        trace.record("turn", now, now, 400)
        return server._post_chat(ASKED, BODY)

    result = contextvars.copy_context().run(in_an_operation)

    assert result.text == server.ERROR_PREFIX + i18n.t(
        "mcp.error.read_timeout_busy", model=ASKED, seconds=_seconds()
    )


# --- REQ-001: which piece ran out --------------------------------------------------------------


def _diff(files: int, lines: int) -> str:
    out = []
    for f in range(files):
        out.append(
            f"diff --git a/pkg/mod{f}.py b/pkg/mod{f}.py\n--- a/pkg/mod{f}.py\n+++ b/pkg/mod{f}.py\n"
        )
        out.append(f"@@ -1,{lines} +1,{lines} @@\n")
        out.extend(f"+value_{f}_{i} = compute_something({i}, flag=True)\n" for i in range(lines))
    return "".join(out)


def _events(log_dir) -> list[dict]:
    return [
        json.loads(line)
        for path in sorted(log_dir.glob("*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _timeout_on(call: int):
    """A `_post_chat` that answers every call but number `call` (1-based), which runs out."""
    count = {"n": 0}
    lock = threading.Lock()

    def _post(model, _payload):
        with lock:
            count["n"] += 1
            n = count["n"]
        if n == call:
            return server.ChatResult(
                text=server.ERROR_PREFIX
                + i18n.t("mcp.error.read_timeout_busy", model=model, seconds=_seconds()),
                ok=False,
                error="read_timeout",
                error_class="read_timeout",
                read_timeout_cause="busy",
            )
        return server.ChatResult(text="- pkg: cambia valores", ok=True, finish_reason="stop")

    return _post


def _setup_log(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)


def test_the_first_piece_of_a_chunked_commit_is_named(monkeypatch, tmp_path):
    """#572's shape: a diff in several pieces whose first one runs out.

    Positive control (main): the text ends at the busy text, and the event has neither
    `read_timeout_piece` nor `pieces` (the first call failed, so `chunks` was 1).
    """
    _setup_log(monkeypatch, tmp_path)
    diff = _diff(12, 120)
    assert len(diff) > config.max_chars_for_role("code"), len(diff)
    monkeypatch.setattr(server, "_post_chat", _timeout_on(1))

    out = server.local_commit_msg(diff=diff)

    (event,) = _events(tmp_path)
    pieces = event["pieces"]
    assert pieces > 1, event
    assert event["read_timeout_piece"] == 1
    assert out.endswith(" " + i18n.t("mcp.error.read_timeout_piece", piece=1, pieces=pieces)), out


def test_a_later_piece_of_a_chunked_summary_is_named(monkeypatch, tmp_path):
    _setup_log(monkeypatch, tmp_path)
    text = "\n\n".join(f"## Sección {i}\n\n" + ("contenido " * 200) for i in range(60))
    assert len(text) > config.max_chars_for_role("long")
    monkeypatch.setattr(server, "_post_chat", _timeout_on(2))

    out = server.local_summarize(text=text)

    (event,) = _events(tmp_path)
    assert event["read_timeout_piece"] == 2
    assert out.endswith(
        " " + i18n.t("mcp.error.read_timeout_piece", piece=2, pieces=event["pieces"])
    ), out


def test_the_reduce_is_named_when_it_runs_out(monkeypatch, tmp_path):
    _setup_log(monkeypatch, tmp_path)
    text = "\n\n".join(f"## Sección {i}\n\n" + ("contenido " * 200) for i in range(60))
    real = _timeout_on(10_000)
    seen: list[str | None] = []

    def _post(model, payload):
        snapshot = server.inflight_snapshot()
        seen.append(snapshot[0].get("phase") if snapshot else None)
        if seen[-1] == "reduce":  # every map answered: the reduce runs out
            return _timeout_on(1)(model, payload)
        return real(model, payload)

    monkeypatch.setattr(server, "_post_chat", _post)

    out = server.local_summarize(text=text)

    assert seen.count("reduce") == 1 and len(seen) > 2, seen  # guard: maps, then the reduce
    (event,) = _events(tmp_path)
    assert event["read_timeout_piece"] == 0
    assert out.endswith(" " + i18n.t("mcp.error.read_timeout_reduce", pieces=event["pieces"])), out


def test_a_piece_of_a_chunked_translation_is_named(monkeypatch, tmp_path):
    """The other chunked path (`_chat_chunked`)."""
    _setup_log(monkeypatch, tmp_path)
    text = "".join(f"## Sección {i}\n\n{'palabra ' * 375}\n\n" for i in range(3))
    assert len(server._chunk_text(text, config.CHUNK_CHARS)) == 3
    monkeypatch.setattr(server, "_post_chat", _timeout_on(2))

    out = server.local_translate("inglés", text=text)

    (event,) = _events(tmp_path)
    assert event["read_timeout_piece"] == 2 and event["pieces"] == 3
    assert out.endswith(" " + i18n.t("mcp.error.read_timeout_piece", piece=2, pieces=3)), out


def test_an_unchunked_timeout_names_no_piece(monkeypatch, tmp_path):
    _setup_log(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "_post_chat", _timeout_on(1))

    out = server.local_translate("inglés", text="hola mundo")

    (event,) = _events(tmp_path)
    assert "read_timeout_piece" not in event and "pieces" not in event
    assert out == server.ERROR_PREFIX + i18n.t(
        "mcp.error.read_timeout_busy", model=event["model"], seconds=_seconds()
    )
