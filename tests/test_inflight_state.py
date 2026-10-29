"""Issue #477: each `/api/inflight` entry says whether it is at the backend or waits.

`state` comes from the real wait (`local_wait`) and the slot the call holds (`_slot`), never from
the text of the phase: `running`, `retrying` (a cut piece split again) or `queued`.
"""

from __future__ import annotations

import json
import threading
import time

from fastapi.testclient import TestClient

from local_delegate import config, server
from local_delegate.web import metrics


def _entry(entry_id: int) -> dict:
    key = f"{server.os.getpid()}:{entry_id}"
    return next(e for e in server.inflight_snapshot() if e["id"] == key)


def test_state_from_the_wait_and_the_slot():
    assert server._inflight_state({}) == "queued"  # never got to the backend
    assert server._inflight_state({"in_backend": True}) == "running"
    assert server._inflight_state({"in_backend": False}) == "running"  # between its pieces
    assert server._inflight_state({"in_backend": True, "phase": "retry"}) == "retrying"
    assert server._inflight_state({"in_backend": True, "phase": "reduce"}) == "running"
    assert server._inflight_state({"in_backend": False, "local_wait": "slot"}) == "queued"
    assert (
        server._inflight_state({"in_backend": False, "local_wait": "turn", "phase": "retry"})
        == "queued"
    )
    assert set(server.INFLIGHT_STATES) == {"running", "retrying", "queued"}


def test_the_slot_marks_the_call_at_the_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    entry_id = server._inflight_start(tool="t", model="m", source="inline", chars_in=5)
    try:
        assert _entry(entry_id)["state"] == "queued"
        with server._slot(entry_id):
            assert _entry(entry_id)["state"] == "running"
            server._inflight_phase(entry_id, "retry")
            assert _entry(entry_id)["state"] == "retrying"
        # Let go of the place between two pieces: still the operation at work, not a queued one.
        assert _entry(entry_id)["state"] == "retrying"
        server._inflight_phase(entry_id, "map")
        assert _entry(entry_id)["state"] == "running"
    finally:
        server._inflight_end(entry_id)


def test_a_call_waiting_for_a_place_is_queued_while_the_other_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(server, "_chat_slots", threading.BoundedSemaphore(1))
    first = server._inflight_start(tool="first", model="m", source="inline", chars_in=5)
    second = server._inflight_start(tool="second", model="m", source="inline", chars_in=5)
    entered = threading.Event()
    try:
        with server._slot(first):

            def wait_for_a_place():
                with server._slot(second):
                    entered.set()

            waiter = threading.Thread(target=wait_for_a_place, daemon=True)
            waiter.start()
            deadline = time.monotonic() + 5
            while _entry(second).get("local_wait") != "slot" and time.monotonic() < deadline:
                time.sleep(0.01)
            assert _entry(first)["state"] == "running"
            assert _entry(second)["state"] == "queued"
            assert not entered.is_set()
        waiter.join(5)
        assert entered.is_set()
        assert _entry(second)["state"] == "running"
    finally:
        server._inflight_end(first)
        server._inflight_end(second)


def test_a_turn_wait_is_queued_with_its_position(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    entry_id = server._inflight_start(tool="t", model="m", source="inline", chars_in=5)
    try:
        server._inflight_turn(entry_id, ["other-model"], 3)
        server._inflight_local_wait(entry_id, "turn")
        e = _entry(entry_id)
        assert e["state"] == "queued" and e["queue_position"] == 3
        server._inflight_local_wait(entry_id, None)
        server._inflight_turn(entry_id, None, None)
        assert "queue_position" not in _entry(entry_id)
    finally:
        server._inflight_end(entry_id)


def test_api_inflight_carries_the_state(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    entry_id = server._inflight_start(tool="t", model="m", source="inline", chars_in=5)
    try:
        with server._slot(entry_id):
            data = TestClient(metrics.app).get("/api/inflight").json()
        assert [e["state"] for e in data["inflight"]] == ["running"]
    finally:
        server._inflight_end(entry_id)


# --- The panel: «Processing (n)» and «Queued (m)» apart -------------------------------------------


def _render(tmp_path, items: list[dict]) -> str:
    from test_dashboard_states import _DOM, _f, _js

    return _js(
        tmp_path,
        [_f("renderInflight")],
        f"""
        const state = {{inflight: {json.dumps(items)}, activity: {{skewMs: 0}}, lastEvent: null}};
        renderInflight();
        emit(_els.inflightBody.innerHTML);
        """,
        _DOM,
    )


def _row(tool: str, state: str | None, **extra) -> dict:
    item = {"tool": tool, "model": "m", "elapsed_s": 5, "chars_in": 1, **extra}
    if state is not None:
        item["state"] = state
    return item


def test_panel_splits_processing_from_queued(tmp_path):
    html = _render(
        tmp_path,
        [
            _row("old_queued", "queued", local_wait="slot"),
            _row("retry", "retrying", chunks=9, chunk=3, phase="retry"),
            _row(
                "turn_wait",
                "queued",
                local_wait="turn",
                turn_in_use=["x"],
                turn_position=3,
                queue_position=3,
            ),
            _row("at_backend", "running"),
        ],
    )
    head_running = html.index('data-group="running"')
    head_queued = html.index('data-group="queued"')
    assert 'Procesando <span class="num">(2)</span>' in html
    assert 'En cola <span class="num">(2)</span>' in html
    # The two at the backend are under «Procesando», the two waiting under «En cola».
    for tool in ("retry", "at_backend"):
        assert head_running < html.index(f">{tool}<") < head_queued, tool
    for tool in ("old_queued", "turn_wait"):
        assert html.index(f">{tool}<") > head_queued, tool
    assert html.count('class="ifrow queued"') == 2
    assert html.count('class="queue-dot"') == 2 and html.count('class="spin"') == 2
    assert ">#3<" in html


def test_panel_without_state_keeps_one_list(tmp_path):
    """A daemon from before #477 sends no `state`: the list is drawn as it always was."""
    html = _render(tmp_path, [_row("a", None), _row("b", None, local_wait="slot")])
    assert "ifgroup" not in html
    assert html.count('class="spin"') == 2 and "queue-dot" not in html


def test_panel_shows_the_host_only_when_it_comes(tmp_path):
    """Entries from another machine may carry `host`; the panel shows it, and never needs it."""
    html = _render(
        tmp_path, [_row("from_mac", "queued", host="remote-mac"), _row("here", "running")]
    )
    assert html.count(">remote-mac<") == 1
    assert 'title="Pedida desde remote-mac"' in html
