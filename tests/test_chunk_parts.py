"""A chunk split again says, apart, how far its split has got: «chunk 3/4 · split in 3 · part 2».

Decision of 2026-10-30: the chunk total (`chunks` in flight) stays the chunks of the document and
`chunk` keeps its meaning. While a chunk is split again (a cut output or a context overflow) the
in-flight entry carries `part` (1-based, in sending order, never back) and `parts` (the parts known
so far of THAT chunk, growing with a nested split); both go when the split is over. The usage log
does not change. The backend is faked (`_post_chat`): no network, log and `inflight.json` in tmp.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from local_delegate import config, server, turn_leases
from local_delegate.web import turn_api


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


def _recording_post(seen: list, finish_reasons: list[str]):
    """A `_post_chat` that records `(chunk, chunks, part, parts)` of the entry at each call."""

    def _post(_model, _payload):
        snapshot = server.inflight_snapshot()
        e = snapshot[0] if snapshot else {}
        seen.append((e.get("chunk"), e.get("chunks"), e.get("part"), e.get("parts")))
        reason = finish_reasons.pop(0) if finish_reasons else "stop"
        return server.ChatResult(text="ok", ok=True, finish_reason=reason)

    return _post


def _three_chunks() -> str:
    text = _document(3, 3000)
    pieces = server._chunk_text(text, config.CHUNK_CHARS)
    assert len(pieces) == 3, len(pieces)
    assert len(pieces[0]) > config.CHUNK_MIN_CHARS * 4, "the first chunk must split twice"
    return text


def _assert_rules(seen: list, chunks: int) -> None:
    assert {total for _c, total, _p, _ps in seen} == {chunks}, f"the chunk total moved: {seen}"
    chunk_numbers = [c for c, *_ in seen]
    assert chunk_numbers == sorted(chunk_numbers), seen
    for chunk in set(chunk_numbers):
        parts = [(p, ps) for c, _t, p, ps in seen if c == chunk and p is not None]
        assert [p for p, _ in parts] == sorted(p for p, _ in parts), f"a part went back: {seen}"
        assert [ps for _, ps in parts] == sorted(ps for _, ps in parts), seen
        assert all(1 <= p <= ps for p, ps in parts), seen


def test_chunked_a_split_publishes_the_parts_and_clears_them(monkeypatch, tmp_path):
    """Chunk 1 is cut and split in two: «1/3», «1/3 · 2 parts · part 1», «… part 2», then «2/3».

    Positive control (main): no `part`/`parts` in the entry during the split.
    """
    _setup(monkeypatch, tmp_path)
    seen: list = []
    monkeypatch.setattr(server, "_post_chat", _recording_post(seen, ["length"]))

    server.local_translate("inglés", text=_three_chunks())

    assert seen == [
        (1, 3, None, None),
        (1, 3, 1, 2),
        (1, 3, 2, 2),
        (2, 3, None, None),
        (3, 3, None, None),
    ], seen
    _assert_rules(seen, 3)
    (event,) = _records(tmp_path)
    assert (event["pieces"], event["chunks"]) == (3, 5), "the log keeps pieces and calls"


def test_chunked_a_nested_split_grows_the_parts(monkeypatch, tmp_path):
    """Chunk 1 is cut, and so is its first half: the parts go 2 → 3; the part never goes back."""
    _setup(monkeypatch, tmp_path)
    seen: list = []
    monkeypatch.setattr(server, "_post_chat", _recording_post(seen, ["length", "length"]))

    server.local_translate("inglés", text=_three_chunks())

    assert seen == [
        (1, 3, None, None),
        (1, 3, 1, 2),
        (1, 3, 1, 3),
        (1, 3, 2, 3),
        (1, 3, 3, 3),
        (2, 3, None, None),
        (3, 3, None, None),
    ], seen
    _assert_rules(seen, 3)
    (event,) = _records(tmp_path)
    assert (event["pieces"], event["chunks"]) == (3, 7)


def test_chunked_without_a_split_has_no_parts(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    seen: list = []
    monkeypatch.setattr(server, "_post_chat", _recording_post(seen, []))

    server.local_translate("inglés", text=_three_chunks())

    assert seen == [(1, 3, None, None), (2, 3, None, None), (3, 3, None, None)], seen
    (event,) = _records(tmp_path)
    assert (event["pieces"], event["chunks"]) == (3, 3)


def test_a_failed_split_leaves_nothing_behind(monkeypatch, tmp_path):
    """A part that fails ends the operation: the entry goes, with its parts."""
    _setup(monkeypatch, tmp_path)
    calls = {"n": 0}

    def _post(_model, _payload):
        calls["n"] += 1
        if calls["n"] == 1:
            return server.ChatResult(text="ok", ok=True, finish_reason="length")
        if calls["n"] == 2:
            entry = server.inflight_snapshot()[0]
            assert (entry["part"], entry["parts"]) == (1, 2), entry
        return server.ChatResult(text="", ok=False, error="boom")

    monkeypatch.setattr(server, "_post_chat", _post)
    server.local_translate("inglés", text=_three_chunks())
    assert server.inflight_snapshot() == []


def _map_reduce_text() -> str:
    text = "\n\n".join(f"## Sección {i}\n\n" + ("contenido " * 200) for i in range(60))
    assert len(text) > config.max_chars_for_role("long")
    return text


def test_map_reduce_a_split_publishes_the_parts_and_the_reduce_has_none(monkeypatch, tmp_path):
    """Map/reduce: a cut map step split in two shows its parts; the next chunk and the reduce
    have none; the chunk total never moves.

    Positive control (main): no `part`/`parts` during the split.
    """
    _setup(monkeypatch, tmp_path)
    seen: list = []
    monkeypatch.setattr(server, "_post_chat", _recording_post(seen, ["length"]))

    server.local_summarize(text=_map_reduce_text())

    (event,) = _records(tmp_path)
    pieces = event["pieces"]
    assert seen[0] == (1, pieces, None, None)
    assert seen[1:3] == [(1, pieces, 1, 2), (1, pieces, 2, 2)], seen
    assert seen[3] == (2, pieces, None, None), seen
    assert all(p is None for _c, _t, p, _ps in seen[3:]), "the reduce and the rest have no parts"
    _assert_rules(seen, pieces)
    assert event["chunks"] == len(seen), "`chunks` stays the number of backend calls"


def test_map_reduce_a_nested_split_grows_the_parts(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    seen: list = []
    monkeypatch.setattr(server, "_post_chat", _recording_post(seen, ["length", "length"]))

    server.local_summarize(text=_map_reduce_text())

    (event,) = _records(tmp_path)
    pieces = event["pieces"]
    assert seen[1:5] == [
        (1, pieces, 1, 2),
        (1, pieces, 1, 3),
        (1, pieces, 2, 3),
        (1, pieces, 3, 3),
    ], seen
    assert seen[5] == (2, pieces, None, None), seen
    _assert_rules(seen, pieces)


# --- the remote heartbeat --------------------------------------------------------------------


def test_the_daemon_takes_part_and_parts_and_refuses_bad_ones():
    """The heartbeat body takes small positive counts; anything else is a 400 as before."""
    body = turn_api.HeartbeatBody.model_validate({"lease": "x", "part": 2, "parts": 3})
    assert (body.part, body.parts) == (2, 3)
    for bad in ({"part": 0}, {"parts": 10_001}, {"part": "2"}, {"part": True}):
        with pytest.raises(ValidationError):
            turn_api.HeartbeatBody.model_validate({"lease": "x", **bad})


def test_beat_dataclass_carries_the_parts():
    beat = turn_leases.Beat(chunk=3, phase="retry", part=2, parts=3)
    assert (beat.part, beat.parts) == (2, 3)
