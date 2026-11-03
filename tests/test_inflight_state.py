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
    # REQ-001 of concurrencia-pc-mac adds `waiting_backend` (its own tests: test_waiting_backend.py).
    assert set(server.INFLIGHT_STATES) == {"running", "retrying", "queued", "waiting_backend"}


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


# --- Issue #547: a queued chunked call says which chunk waits, why and for how long ---------------


def test_inflight_reports_how_long_it_waits(tmp_path, monkeypatch):
    """`wait_s` counts from when the current local wait began, only while there is one.

    Positive control: without `local_wait_since` in `_inflight_local_wait`, `wait_s` never comes
    and the first assert fails.
    """
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    clock = [1000.0]
    monkeypatch.setattr(server.time, "time", lambda: clock[0])
    entry_id = server._inflight_start(tool="t", model="m", source="inline", chars_in=5)
    try:
        clock[0] = 1030.0  # 30 s into the call, the wait for a place begins
        server._inflight_local_wait(entry_id, "slot")
        clock[0] = 1042.5
        e = _entry(entry_id)
        assert e["wait_s"] == 12.5 and e["elapsed_s"] == 42.5, e
        # Going on waiting for another reason keeps the start of the wait.
        server._inflight_local_wait(entry_id, "turn")
        clock[0] = 1050.0
        assert _entry(entry_id)["wait_s"] == 20.0
        # The wait ends: no `wait_s`, and the next wait counts from its own start.
        server._inflight_local_wait(entry_id, None)
        assert "wait_s" not in _entry(entry_id)
        clock[0] = 1060.0
        server._inflight_local_wait(entry_id, "slot")
        clock[0] = 1061.0
        assert _entry(entry_id)["wait_s"] == 1.0
    finally:
        server._inflight_end(entry_id)


def test_api_inflight_carries_the_wait(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    entry_id = server._inflight_start(tool="t", model="m", source="inline", chars_in=5)
    try:
        server._inflight_local_wait(entry_id, "slot")
        (item,) = TestClient(metrics.app).get("/api/inflight").json()["inflight"]
        assert item["state"] == "queued" and item["local_wait"] == "slot"
        assert isinstance(item["wait_s"], int | float) and item["wait_s"] >= 0
    finally:
        server._inflight_end(entry_id)


def test_panel_queued_chunk_says_it_waits(tmp_path):
    """A queued chunk is «Espera trozo 2/3», never «Trozo 2/3»; one at the backend keeps «Trozo».

    Positive control: drawing a queued chunk with `backend.chunk` gives «Trozo 2/3» under «En cola»
    and the first assert fails.
    """
    html = _render(
        tmp_path,
        [
            _row("between", "queued", local_wait="slot", chunks=3, chunk=2, wait_s=40),
            _row("sending", "running", chunks=4, chunk=2),
            _row("to_reduce", "queued", local_wait="slot", chunks=3, chunk=3, phase="reduce"),
        ],
    )
    queued = html[html.index('data-group="queued"') :]
    running = html[: html.index('data-group="queued"')]
    assert ">Espera trozo 2/3<" in queued and ">Trozo 2/3<" not in queued, queued
    assert ">Espera combinar 3 trozos<" in queued and "Combinando" not in queued, queued
    assert '<span class="chunkchip">Trozo 2/4</span>' in running and "Espera" not in running
    assert 'title="1 de 3 trozos hechos; el trozo 2 espera para enviarse"' in queued, queued


def test_panel_queued_row_title_says_why(tmp_path):
    """The why of a queued row is in its title, in words; `slot`/`turn` never show as text.

    Positive control: without `queuedTitle` the row has no title and the first assert fails.
    """
    rows = {
        "a": _row("a", "queued", local_wait="slot"),
        "b": _row("b", "queued", local_wait="turn", queue_position=2, turn_in_use=["x"]),
        "c": _row("c", "queued", local_wait="turn"),
        "d": _row("d", "queued"),
        "e": _row("e", "running"),
    }
    html = {k: _render(tmp_path, [v]) for k, v in rows.items()}
    assert 'title="Espera una plaza libre en el backend"' in html["a"], html["a"]
    assert 'title="Espera su turno (puesto 2)"' in html["b"], html["b"]
    assert 'title="Espera su turno"' in html["c"], html["c"]
    assert 'title="Aún no ha empezado"' in html["d"], html["d"]
    assert '<div class="ifrow">' in html["e"], html["e"]  # a running row has no wait title
    for k, h in html.items():
        assert ">slot<" not in h and ">turn<" not in h, (k, h)


def test_panel_queued_row_shows_the_wait(tmp_path):
    """A chip «espera 40,0 s», explained in its title; the total stays in the time column.

    Positive control: without `waited` the row has no wait chip and the first assert fails.
    """
    html = _render(
        tmp_path,
        [
            _row("q", "queued", local_wait="slot", wait_s=40, elapsed_s=115),
            _row("old", "queued", local_wait="slot", elapsed_s=115),
        ],
    )
    first, second = html.split('class="ifrow queued"')[1:]
    title = 'title="Lleva 40,0 s esperando; 1 min 55 s desde que empezó la llamada"'
    assert f'<span class="chunkchip" {title}>espera 40,0 s</span>' in first, first
    assert '<span class="num ifmeta">1 min 55 s · ' in first, first
    assert ">espera " not in second, second  # older daemon: total only
    assert '<span class="num ifmeta">1 min 55 s · ' in second, second


def test_panel_queued_titles_are_escaped(tmp_path):
    """What comes from `/api/inflight` is escaped in the waiting chip and its title."""
    html = _render(
        tmp_path,
        [_row("q", "queued", local_wait="slot", chunks=3, chunk='2"><img src=x>')],
    )
    assert "<img" not in html and "&lt;img src=x&gt;" in html, html
