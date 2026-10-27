"""#455: a map (or regroup) step cut by `length` is split and retried, like `_chat_chunked`.

Before, `_map_piece` only split a piece when the INPUT overflowed the context; a partial whose
OUTPUT was cut was handed to the reduce as good, with a generic notice. Now it is split and
retried (two levels, the same as the overflow), the regroup does the same, `local_explain_code`
has its own map cap, and a partial still cut after the retries is named in the notice (number and
lines of the input). The backend is faked (`_run_chat`): no network.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from local_delegate import config, i18n, server


def _ok(text: str, finish: str = "stop"):
    return server.ChatResult(text=text, ok=True, finish_reason=finish)


@pytest.fixture
def backend(monkeypatch, tmp_path):
    """Every call recorded; `answer(call)` decides the response; log in tmp."""
    calls: list[dict] = []
    state = {"answer": lambda call: _ok("nota")}

    def run_chat(model, system, user, max_tokens, temperature, **_):
        call = {"system": system, "user": user, "max_tokens": max_tokens}
        calls.append(call)
        return state["answer"](call), 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.delenv("LOCAL_DELEGATE_DUMP_CHUNK_NOTES", raising=False)
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    monkeypatch.delenv("LOCAL_DELEGATE_OUTPUT_LANGUAGE", raising=False)
    i18n.reset()
    return calls, state


def _row(tmp_path: Path, tool: str) -> dict:
    rows = [
        json.loads(line)
        for file in sorted(tmp_path.glob("*.jsonl"))
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line)["tool"] == tool
    ]
    assert len(rows) == 1
    return rows[0]


def _distinct_lines(n: int, width: int = 60) -> str:
    """`n` distinct lines (`line 0001 xxx…`), so every chunk is found once in the content."""
    return "".join(f"line {i:04d} " + "x" * width + "\n" for i in range(1, n + 1))


MAX_CHARS = 12_500  # budget 10 000: chunks of <= 10 000 characters
_TRUNCATED = "salida truncada por max_tokens"  # the notice, in `es` (the fixture)


def _map_reduce(content: str, report: dict | None = None, **kwargs) -> str:
    return server._chat_map_reduce(
        "m",
        "MAP",
        content,
        lambda piece: f"GRP:{piece}",
        max_chars=MAX_CHARS,
        tool="local_summarize",
        source="inline",
        max_words=100,
        user_for=lambda piece: f"MAP:{piece}",
        reduce_system="RED",
        build_reduce=lambda joined: f"RED:{joined}",
        report=report,
        **kwargs,
    )


def _is_map(call) -> bool:
    return call["user"].startswith("MAP:")


# --- 1. The map ----------------------------------------------------------------------------------


def test_a_cut_map_partial_is_split_and_the_result_has_no_notice(backend, tmp_path):
    """Mutant `main` (no retry on `length`): three map calls, the split assert fails."""
    calls, state = backend
    # A whole chunk (~10 000) does not fit in its notes; its halves (~5 000) do.
    state["answer"] = lambda c: _ok(
        "nota", "length" if _is_map(c) and len(c["user"]) > 7000 else "stop"
    )
    content = _distinct_lines(400)  # ~27 000 characters: three chunks
    out = _map_reduce(content)
    assert sum(1 for c in calls if _is_map(c)) > 3  # guard: it did split
    assert _TRUNCATED not in out
    row = _row(tmp_path, "local_summarize")
    assert row["finish_reason"] == "stop"
    assert row.get("truncated_out") is not True
    retried = [s for s in row["steps"] if s.get("retried")]
    assert retried and all(s["finish_reason"] == "length" for s in retried)
    # The other steps keep the format the panel reads.
    assert all(
        set(s) == {"kind", "chars_out", "finish_reason"} for s in row["steps"] if s not in retried
    )


def test_with_the_depth_exhausted_the_notice_names_the_chunk_and_its_lines(backend):
    """Mutant `main`: the notice has no `trozos afectados`. Mutant "lines off by one": the line
    check of the last assert fails."""
    calls, state = backend
    content = _distinct_lines(400)
    pieces = server._chunk_text(content, server._map_budget(MAX_CHARS))
    assert len(pieces) == 3  # guard
    second = pieces[1]
    # Every map call on (a part of) the second chunk is cut, at every depth.
    state["answer"] = lambda c: _ok(
        "nota", "length" if _is_map(c) and c["user"][4:].strip() in second else "stop"
    )
    report: dict = {}
    _map_reduce(content, report=report)
    entries = report["truncated_pieces"]
    assert len(entries) == 4  # split twice: four quarters, all still cut
    assert report["truncated_calls"] == 4
    assert all(e["piece"] == 2 for e in entries)
    lines = content.splitlines()
    first_line = content[: content.find(second)].count("\n") + 1
    assert entries[0]["lines"][0] == first_line
    assert entries[-1]["lines"][1] == first_line + second.strip().count("\n")
    for e in entries:
        a, b = e["lines"]
        assert lines[a - 1] in second and lines[b - 1] in second
    # Without `report`, the same goes into the notice of the text.
    calls.clear()
    out = _map_reduce(content)
    a, b = entries[0]["lines"]
    assert f"trozos afectados: 2 (líneas {a}-{b})" in out


def test_a_cut_partial_too_small_to_split_stays_with_the_notice(backend):
    """A chunk not above `CHUNK_MIN_CHARS` is not split again: truncated as before, one call."""
    calls, state = backend
    state["answer"] = lambda c: _ok("nota", "length" if _is_map(c) else "stop")
    report: dict = {}
    _map_reduce("tiny", report=report, pieces=["tiny one", "tiny two"])
    assert sum(1 for c in calls if _is_map(c)) == 2
    assert report["truncated_calls"] == 2
    assert [e["piece"] for e in report["truncated_pieces"]] == [1, 2]


# --- 2. The regroup ------------------------------------------------------------------------------


def test_a_cut_regroup_step_is_split_and_retried(backend, tmp_path):
    """Mutant `main` (the regroup accepts `length`): two regroup calls, the split assert fails."""
    calls, state = backend
    note = "".join(f"nota {i:03d} " + "n" * 40 + "\n" for i in range(60))  # ~3 000 characters

    def answer(c):
        if _is_map(c):
            return _ok(note)
        if c["user"].startswith("GRP:"):
            return _ok("grupo", "length" if len(c["user"]) > 6000 else "stop")
        return _ok("final")

    state["answer"] = answer
    out = _map_reduce(_distinct_lines(560))  # four chunks: ~12 000 of notes > the 10 000 budget
    regroup_calls = [c for c in calls if c["user"].startswith("GRP:")]
    assert len(regroup_calls) > 2  # guard: it regrouped, and split a group
    assert _TRUNCATED not in out
    assert out.startswith("final")
    row = _row(tmp_path, "local_summarize")
    assert row["finish_reason"] == "stop"
    assert any(s["kind"] == "regroup" and s.get("retried") for s in row["steps"])


def test_a_cut_reduce_is_not_split_and_keeps_the_notice(backend):
    calls, state = backend
    state["answer"] = lambda c: _ok("final", "length") if c["user"].startswith("RED:") else _ok("n")
    out = _map_reduce(_distinct_lines(400))
    assert sum(1 for c in calls if c["user"].startswith("RED:")) == 1
    assert _TRUNCATED in out
    assert "trozos afectados" not in out  # the reduce is no chunk of the input


# --- 3. explain_code: its own map cap -----------------------------------------------------------


def test_explain_code_maps_with_its_own_cap(backend):
    """Mutant `main` (shared `2·350+64 = 764`): the map caps are 764, not the new ones."""
    calls, _state = backend
    body = "    return 1  # " + "y" * 11_000 + "\n"
    code = "".join(f"def part_{i}():\n{body}\n" for i in range(4))
    budget = server._map_budget(config.max_chars_for_role("code"))
    pieces = server._code_pieces(code, budget)
    assert len(pieces) == 4  # guard
    server.local_explain_code(code=code)
    maps = [c for c in calls if c["user"].startswith("Toma notas")]
    assert [c["max_tokens"] for c in maps] == [
        server._explain_map_max_tokens(p, 350) for p in pieces
    ]
    assert all(800 < c["max_tokens"] <= config.CHUNK_MAX_TOKENS for c in maps)


def test_the_explain_cap_has_floor_and_ceiling():
    assert server._explain_map_max_tokens("x" * 100, 350) == 764
    assert server._explain_map_max_tokens("x" * 12_000, 350) == 1500
    assert server._explain_map_max_tokens("x" * 40_000, 350) == config.CHUNK_MAX_TOKENS


# --- 4. extract: the `report` contract ----------------------------------------------------------


def test_extract_names_the_cut_chunk_in_its_warning_and_keeps_its_contract(backend):
    """Mutant `main`: the warning has no `trozos afectados`."""
    _calls, state = backend
    marker = "a = ONLY_IN_THE_SECOND\n"
    text = _distinct_lines(700) + marker + _distinct_lines(700).replace("line", "otra")  # > 48 000

    def answer(c):
        if "Combina" in c["system"]:
            return _ok('{"a": "x"}')
        cut = "ONLY_IN_THE_SECOND" in c["user"]
        return _ok('{"a": null}', "length" if cut else "stop")

    state["answer"] = answer
    data = server.local_extract(fields=["a"], text=text)
    meta = data["_local_delegate"]
    assert set(meta) >= {"truncated", "warning"} and meta["truncated"] is True
    assert "a" in data  # still the parsed object
    match = re.search(r"trozos afectados: (\d+) \(líneas (\d+)-(\d+)\)", meta["warning"])
    assert match, meta["warning"]
    first, last = int(match.group(2)), int(match.group(3))
    assert first <= 701 <= last  # the cut chunk holds the marker line
