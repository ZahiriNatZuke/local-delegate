"""Progress while a call waits, and no call holding the turn out of sight (issue #479).

Measured on 2026-10-29 (0.44.2): Claude Code cut every delegation queued or in a long inference
with «sent no response or progress for 300s», and `/api/inflight` showed ONE entry at
`turn_position: 5` with four places ahead that appeared nowhere, while no delegation finished in
70 minutes.

- The daemon sent nothing while a call waited: now a live call sends `notifications/progress`
  every `PROGRESS_INTERVAL_S` with its phase, when the request carries a `progressToken`.
- The four invisible ones were live calls older than `_INFLIGHT_STALE_S` (1800 s): the TTL for
  orphans dropped them from `inflight.json` while their threads still held the turn. A live call
  of the process now stays, however old.

These run against the real MCP server: the SDK's in-memory client (the path of stdio) and the
daemon's real HTTP app (the path of Claude Code and of the Desktop bridge). The log goes to the
test's `tmp_path` (conftest), never to the real one.
"""

from __future__ import annotations

import json
import time

import anyio
import httpx2
import pytest
from mcp import Client
from test_desktop_bridge import (
    _HTTP_TIMEOUT,
    CLASSIFY,
    LONG_MODEL,
    SUMMARIZE,
    TOKEN,
    _RawSession,
    _settle,
    _until,
    real_daemon,
)
from test_desktop_bridge import slow_backend as _bridge_slow_backend

from local_delegate import cancellation, config, i18n, server

# Backend in ~20 slow calls (~8 s), two slots, today's topology: the long model of the summary and
# the mechanical one of the classification clash, so a classification waits for the turn.
slow_backend = _bridge_slow_backend

BEAT_S = 0.2


def _turn_prefix() -> str:
    """The start of the «waiting for the turn» phase, in the language the test runs with."""
    return i18n.t("mcp.progress.turn", position=1, models="\x00").split("1")[0]


def _with_id(message: dict, request_id: int, *, progress: bool = False) -> dict:
    copy = json.loads(json.dumps(message))
    copy["id"] = request_id
    if progress:
        copy["params"]["_meta"] = {"progressToken": f"p{request_id}"}
    return copy


def _turn_ops() -> set[str]:
    """The operations in the turn's queue or holding it: the keys `inflight.json` must show."""
    state = server._turn.snapshot()
    return {e.id for e in state.queue} | {a.id for a in state.actives}


def _inflight_by_tool() -> dict[str, list[dict]]:
    by_tool: dict[str, list[dict]] = {}
    for entry in server.inflight_snapshot():
        by_tool.setdefault(entry["tool"], []).append(entry)
    return by_tool


# --- 1. Progress -------------------------------------------------------------------------------


def _progress_in_memory(interval: float) -> tuple[list[tuple[float, str | None]], object]:
    """A summary holds the turn; a classification waits behind it with a progress callback."""
    received: list[tuple[float, str | None]] = []

    async def on_progress(progress: float, _total: float | None, message: str | None) -> None:
        received.append((progress, message))

    async def scenario() -> object:
        async with Client(server.mcp) as client, anyio.create_task_group() as group:
            group.start_soon(client.call_tool, "local_summarize", SUMMARIZE["params"]["arguments"])
            await _until(lambda: server._turn.snapshot().actives, cap=10)
            result = await client.call_tool(
                "local_classify",
                CLASSIFY["params"]["arguments"],
                progress_callback=on_progress,
            )
            group.cancel_scope.cancel()
            return result

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(config, "PROGRESS_INTERVAL_S", interval)
        result = anyio.run(scenario)
    return received, result


def test_queued_call_gets_progress_with_its_place_in_memory(slow_backend):
    """SDK client in memory: the waiting call hears from the daemon every beat, with its place."""
    received, result = _progress_in_memory(BEAT_S)
    assert getattr(result, "is_error", False) is not True, result
    # The classification waited the ~8 s of the summary: dozens of beats, never fewer than 5.
    assert len(received) >= 5, f"only {len(received)} progress notifications while queued"
    progress = [p for p, _m in received]
    assert progress == sorted(progress) and len(set(progress)) == len(progress), progress
    messages = [m or "" for _p, m in received]
    assert any(_turn_prefix() in m and LONG_MODEL in m for m in messages), messages[:3]


def test_progress_off_sends_nothing(slow_backend):
    """`PROGRESS_INTERVAL_S = 0` turns the heartbeat off: the control of the test above."""
    received, _result = _progress_in_memory(0.0)
    assert received == []


def test_queued_call_gets_progress_over_http(monkeypatch, slow_backend):
    """The daemon's HTTP app (Claude Code, Desktop bridge): progress on the request's stream."""
    monkeypatch.setattr(config, "PROGRESS_INTERVAL_S", BEAT_S)
    classify = _with_id(CLASSIFY, 21, progress=True)
    with real_daemon(monkeypatch, TOKEN) as url:

        async def scenario() -> str:
            async with httpx2.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                session = _RawSession(client, url)
                await session.open()
                async with anyio.create_task_group() as group:
                    group.start_soon(session.call, SUMMARIZE)
                    await _until(lambda: server._turn.snapshot().actives, cap=10)
                    async with client.stream(
                        "POST", url, json=classify, headers=session._headers()
                    ) as response:
                        body = (await response.aread()).decode("utf-8")
                    group.cancel_scope.cancel()
                return body

        body = anyio.run(scenario)
    notes = [
        json.loads(line[5:].strip())
        for line in body.splitlines()
        if line.startswith("data:") and "notifications/progress" in line
    ]
    assert len(notes) >= 5, f"only {len(notes)} progress notifications on the stream"
    assert {n["params"]["progressToken"] for n in notes} == {"p21"}
    assert any(_turn_prefix() in n["params"].get("message", "") for n in notes), notes[:2]


def test_progress_message_names_the_phase():
    """The text of each phase: queue place, slot, piece k/N, reduce."""
    token = cancellation.Token("local_summarize")
    token.status.update(wait="turn", position=3, in_use=("model-a",))
    assert i18n.t("mcp.progress.turn", position=3, models="model-a") in token.progress_message()
    token.status.update(wait="slot")
    assert i18n.t("mcp.progress.slot") in token.progress_message()
    token.status.pop("wait")
    token.status.update(chunks=4, chunk=2)
    assert i18n.t("mcp.progress.chunk", chunk=2, chunks=4) in token.progress_message()
    token.status.update(phase="reduce")
    assert i18n.t("mcp.progress.reduce") in token.progress_message()


# --- 2. Calls holding the turn out of sight ----------------------------------------------------


def test_live_call_older_than_the_orphan_ttl_stays_visible(monkeypatch, slow_backend):
    """The reproduction: a live call past `_INFLIGHT_STALE_S` stays in `/api/inflight`.

    Before, the orphan TTL dropped it while it still held the turn, and the one behind it showed a
    `turn_position` with nobody visible ahead (four of them in the measurement of #479).
    """
    monkeypatch.setattr(server, "_INFLIGHT_STALE_S", 0.3)
    with real_daemon(monkeypatch, TOKEN) as url:

        async def scenario() -> tuple[set[str], set[str]]:
            async with httpx2.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                session = _RawSession(client, url)
                await session.open()
                async with anyio.create_task_group() as group:
                    group.start_soon(session.call, SUMMARIZE)
                    await _until(lambda: server._turn.snapshot().actives, cap=10)
                    group.start_soon(session.call, _with_id(CLASSIFY, 31))
                    await _until(lambda: server._turn.snapshot().queue, cap=10)
                    await anyio.sleep(1.0)  # both past the (shortened) TTL, both still alive
                    turn_ops = _turn_ops()
                    visible = {e["id"] for e in server.inflight_snapshot()}
                    group.cancel_scope.cancel()
                return turn_ops, visible

        turn_ops, visible = anyio.run(scenario)
    assert len(turn_ops) == 2, turn_ops
    assert turn_ops <= visible, f"in the turn but not in /api/inflight: {turn_ops - visible}"


def test_old_orphan_of_this_process_is_still_dropped(monkeypatch, tmp_path):
    """The TTL still does its job: an entry of this process that is not running goes away."""
    import os

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    key = f"{os.getpid()}:987654"
    (tmp_path / "inflight.json").write_text(
        json.dumps({key: {"tool": "local_classify", "pid": os.getpid(), "started_at": 1.0}}),
        encoding="utf-8",
    )
    assert all(e["id"] != key for e in server.inflight_snapshot())
    assert key not in json.loads((tmp_path / "inflight.json").read_text(encoding="utf-8"))


def test_cancelled_waiter_leaves_the_queue_and_the_next_moves_up(monkeypatch, slow_backend):
    """A holds the turn, B and C wait; the client cancels B.

    B leaves the turn's queue and `/api/inflight` at once, C goes from place 2 to place 1, and no
    thread is left waiting for B's turn.
    """
    b = _with_id(CLASSIFY, 41)
    c = _with_id(CLASSIFY, 42)
    with real_daemon(monkeypatch, TOKEN) as url:

        async def scenario() -> dict:
            seen: dict = {}
            async with httpx2.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                session = _RawSession(client, url)
                await session.open()
                async with anyio.create_task_group() as group:
                    group.start_soon(session.call, SUMMARIZE)
                    await _until(lambda: server._turn.snapshot().actives, cap=10)
                    group.start_soon(session.call, b)
                    await _until(lambda: len(server._turn.snapshot().queue) == 1, cap=10)
                    group.start_soon(session.call, c)
                    await _until(lambda: len(server._turn.snapshot().queue) == 2, cap=10)
                    await _until(
                        lambda: (
                            sorted(
                                e.get("turn_position") or 0
                                for e in _inflight_by_tool().get("local_classify", [])
                            )
                            == [1, 2]
                        ),
                        cap=10,
                    )
                    seen["queue_before"] = [e.id for e in server._turn.snapshot().queue]
                    await session.notify(
                        {
                            "jsonrpc": "2.0",
                            "method": "notifications/cancelled",
                            "params": {"requestId": b["id"], "reason": "test"},
                        }
                    )
                    cancelled_at = time.monotonic()
                    # No `_until` here: what follows is the result under test, so a B that stays
                    # in the queue must fail on the asserts below, not as a script error.
                    with anyio.move_on_after(5):
                        while len(server._turn.snapshot().queue) != 1:
                            await anyio.sleep(0.02)
                    seen["left_after_s"] = time.monotonic() - cancelled_at
                    with anyio.move_on_after(5):
                        while [
                            e.get("turn_position")
                            for e in _inflight_by_tool().get("local_classify", [])
                        ] != [1]:
                            await anyio.sleep(0.02)
                    seen["queue_after"] = [e.id for e in server._turn.snapshot().queue]
                    seen["classify_after"] = _inflight_by_tool().get("local_classify", [])
                    group.cancel_scope.cancel()
            return seen

        seen = anyio.run(scenario)
    b_op, c_op = seen["queue_before"]
    assert seen["queue_after"] == [c_op], seen
    assert seen["left_after_s"] < 1.0, f"B left the queue {seen['left_after_s']:.1f} s later"
    assert [e["id"] for e in seen["classify_after"]] == [c_op], seen["classify_after"]
    assert b_op not in _turn_ops()
    # Nobody is left waiting for a turn once the calls are gone.
    assert _settle(lambda: not server._turn.snapshot().queue, cap=15)
