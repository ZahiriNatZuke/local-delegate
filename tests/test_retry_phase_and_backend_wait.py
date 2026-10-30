"""Issue #508: a wait for llama-swap is shown as `waiting_backend`, also during a retry.

Two parts:

1. `_inflight_state` checks `backend_wait` before `phase: "retry"`. Positive control (old order,
   `retry` first): `test_a_retry_that_waits_for_the_backend_is_waiting_backend` fails.
2. The `retry` phase is cleared when the split of a cut piece is over, not when the next piece
   starts. Only the outermost split (`depth == 0`) clears it; a failed split does not. Each test
   names the mutant that makes it fail.
"""

from __future__ import annotations

from local_delegate import config, server

WAITS = {"1": {"other-model": "ready"}}


# --- 1. precedence --------------------------------------------------------------------------


def test_a_retry_that_waits_for_the_backend_is_waiting_backend():
    entry = {"in_backend": True, "phase": "retry", "backend_wait": WAITS}
    assert server._inflight_state(entry) == "waiting_backend"


def test_a_retry_without_a_backend_wait_is_still_retrying():
    assert server._inflight_state({"in_backend": True, "phase": "retry"}) == "retrying"
    assert server._inflight_state({"in_backend": True, "phase": "retry", "backend_wait": {}}) == (
        "retrying"
    )


def test_a_backend_wait_without_a_phase_is_waiting_backend_as_before():
    assert server._inflight_state({"in_backend": True, "backend_wait": WAITS}) == "waiting_backend"


def test_queued_still_wins_over_both():
    entry = {"in_backend": False, "local_wait": "slot", "phase": "retry", "backend_wait": WAITS}
    assert server._inflight_state(entry) == "queued"


# --- 2. clearing the retry phase ------------------------------------------------------------


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)


def _trace(monkeypatch, finish_reasons, fail_after: int | None = None) -> list:
    """Record, in order, every backend call (`("call", chunk)`) and every phase set
    (`("phase", name)`). `finish_reasons` is a list consumed call by call, or a function of the
    payload. Calls past `fail_after` fail."""
    events: list = []
    original = server._inflight_phase

    def _phase(entry_id, phase):
        events.append(("phase", phase))
        original(entry_id, phase)

    def _post(_model, _payload):
        snapshot = server.inflight_snapshot()
        events.append(("call", (snapshot[0] if snapshot else {}).get("chunk")))
        calls = sum(1 for kind, _ in events if kind == "call")
        if fail_after is not None and calls > fail_after:
            return server.ChatResult(text="", ok=False, error="boom")
        if callable(finish_reasons):
            reason = finish_reasons(_payload)
        else:
            reason = finish_reasons.pop(0) if finish_reasons else "stop"
        return server.ChatResult(text="ok", ok=True, finish_reason=reason)

    monkeypatch.setattr(server, "_inflight_phase", _phase)
    monkeypatch.setattr(server, "_post_chat", _post)
    return events


def _chunked_text() -> str:
    text = "".join(f"## Sección {i}\n\n{'palabra ' * (3000 // 8)}\n\n" for i in range(3))
    pieces = server._chunk_text(text, config.CHUNK_CHARS)
    assert len(pieces) == 3 and len(pieces[0]) > config.CHUNK_MIN_CHARS * 2
    return text


def _phases(events: list) -> list:
    return [name for kind, name in events if kind == "phase"]


def test_chunked_clears_the_retry_when_the_split_is_over(monkeypatch, tmp_path):
    """Mutant: drop the `depth == 0` clearing in `_process` → no «map» before piece 2."""
    _setup(monkeypatch, tmp_path)
    events = _trace(monkeypatch, ["length"])

    server.local_translate("inglés", text=_chunked_text())

    assert _phases(events) == ["retry", "map"], events
    map_at = events.index(("phase", "map"))
    first_of_piece_2 = events.index(("call", 2))
    assert map_at < first_of_piece_2, events
    assert all(e == ("call", 1) for e in events[1:map_at] if e[0] == "call"), events


def test_chunked_a_nested_split_does_not_clear_the_outer_retry(monkeypatch, tmp_path):
    """Mutant: `if depth == 0` → `if True` in `_process` → a «map» right after the inner split,
    while the outer one still has halves of the same chunk to send."""
    _setup(monkeypatch, tmp_path)

    def _cut_big(payload) -> str:  # every big send is cut: halves of a piece are split again
        return "length" if len(payload["messages"][-1]["content"]) > 1200 else "stop"

    events = _trace(monkeypatch, _cut_big)

    server.local_translate("inglés", text=_chunked_text())

    phases = _phases(events)
    assert phases.count("retry") > phases.count("map") >= 1, "the test needs a nested split"
    for i, event in enumerate(events):
        if event != ("phase", "map"):
            continue
        before = [e[1] for e in events[:i] if e[0] == "call"][-1]
        after = [e[1] for e in events[i:] if e[0] == "call"]
        assert before not in after, f"«map» while chunk {before} is still being split: {events}"


def test_chunked_a_failed_split_does_not_clear_the_retry(monkeypatch, tmp_path):
    """Mutant: clear in a `finally` around the loop of halves → a «map» after the failure."""
    _setup(monkeypatch, tmp_path)
    events = _trace(monkeypatch, ["length"], fail_after=1)

    server.local_translate("inglés", text=_chunked_text())

    assert "retry" in _phases(events), events
    assert "map" not in _phases(events), events


def test_map_reduce_clears_the_retry_when_the_split_is_over(monkeypatch, tmp_path):
    """Mutant: drop the `depth == 0` clearing in `_map_parts` → no «map» before piece 2."""
    _setup(monkeypatch, tmp_path)
    text = "\n\n".join(f"## Sección {i}\n\n" + ("contenido " * 200) for i in range(60))
    events = _trace(monkeypatch, ["length"])

    server.local_summarize(text=text)

    phases = _phases(events)
    assert phases[:2] == ["retry", "map"], events
    assert phases[-1] == "reduce", events
    map_at = events.index(("phase", "map"))
    assert map_at < events.index(("call", 2)), events
