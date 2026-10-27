"""Issue #454: pieces and backend calls are two numbers, and «In progress» shows the phase.

`chunks` in the log stays the number of backend CALLS (compatibility); `pieces` is the number of
pieces announced to the panel. The in-flight entry gets `phase: "reduce"` while the pieces are
combined and `phase: "retry"` while a truncated piece is split again.
"""

from __future__ import annotations

import json

from local_delegate import config, server


def _document(paragraphs: int, size: int) -> str:
    return "".join(f"## Sección {i}\n\n{'palabra ' * (size // 8)}\n\n" for i in range(paragraphs))


def _records(log_dir) -> list[dict]:
    return [
        json.loads(line)
        for path in sorted(log_dir.glob("*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)


def _recording_post(phases: list, finish_reasons: list[str] | None = None):
    """A `_post_chat` that records the in-flight entry seen by every call."""

    def _post(_model, _payload):
        snapshot = server.inflight_snapshot()
        entry = snapshot[0] if snapshot else {}
        phases.append((entry.get("chunk"), entry.get("phase")))
        reason = finish_reasons.pop(0) if finish_reasons else "stop"
        return server.ChatResult(text="ok", ok=True, finish_reason=reason)

    return _post


def test_chunked_logs_pieces_and_marks_the_retry(monkeypatch, tmp_path):
    """A truncated piece split again: 3 pieces, 5 calls; «In progress» says «retry» meanwhile.

    Positive control (main): no `pieces` in the event (KeyError) and no `phase` in the entry.
    """
    _setup(monkeypatch, tmp_path)
    text = _document(3, 3000)
    pieces = server._chunk_text(text, config.CHUNK_CHARS)
    assert len(pieces) == 3, len(pieces)
    assert len(pieces[0]) > config.CHUNK_MIN_CHARS * 2, "the first piece must be splittable"
    seen: list = []
    # First call cut by `length` → the piece is split in two and retried.
    monkeypatch.setattr(server, "_post_chat", _recording_post(seen, ["length"]))

    server.local_translate("inglés", text=text)

    (event,) = _records(tmp_path)
    assert event["pieces"] == 3
    assert event["chunks"] == len(seen) > 3, "`chunks` stays the number of backend calls"
    retries = len(seen) - 3  # the halves of the first piece
    assert seen[0] == (1, None), "the first call is plain map"
    assert seen[1 : 1 + retries] == [(1, "retry")] * retries, seen
    assert seen[1 + retries :] == [(2, None), (3, None)], "the next piece drops the retry phase"


def test_map_reduce_logs_pieces_and_marks_the_reduce(monkeypatch, tmp_path):
    """Map/reduce: N pieces + 1 reduce; the reduce call sees `phase: "reduce"`.

    Positive control (main): no `pieces` (KeyError) and the reduce call sees no phase.
    """
    _setup(monkeypatch, tmp_path)
    text = "\n\n".join(f"## Sección {i}\n\n" + ("contenido " * 200) for i in range(60))
    assert len(text) > config.max_chars_for_role("long")
    seen: list = []
    monkeypatch.setattr(server, "_post_chat", _recording_post(seen))

    server.local_summarize(text=text)

    (event,) = _records(tmp_path)
    maps = sum(1 for step in event["steps"] if step["kind"] == "map")
    assert event["pieces"] == maps > 1
    assert event["chunks"] == len(seen) == maps + 1
    assert [phase for _chunk, phase in seen[:-1]] == [None] * maps
    assert seen[-1][1] == "reduce", seen[-1]


def test_unchunked_event_has_no_pieces(monkeypatch, tmp_path):
    """One call: neither `chunks` nor `pieces` (the event keeps today's shape)."""
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "_post_chat", _recording_post([]))
    server.local_translate("inglés", text="hola mundo")
    (event,) = _records(tmp_path)
    assert "chunks" not in event and "pieces" not in event


def test_inflight_phase_is_best_effort_and_validated(monkeypatch, tmp_path):
    """`map` clears the phase, an unknown phase is ignored, and a missing entry does not raise."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    entry_id = server._inflight_start(tool="t", model="m", source="inline", chars_in=1, chunks=3)
    try:
        server._inflight_phase(entry_id, "reduce")
        assert server.inflight_snapshot()[0]["phase"] == "reduce"
        server._inflight_phase(entry_id, "bogus")
        assert server.inflight_snapshot()[0]["phase"] == "reduce"
        server._inflight_phase(entry_id, "map")
        assert "phase" not in server.inflight_snapshot()[0]
    finally:
        server._inflight_end(entry_id)
    server._inflight_phase(entry_id, "reduce")  # entry already gone: no error
    assert server.inflight_snapshot() == []
