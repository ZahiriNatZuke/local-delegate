"""#487: the split retry of a cut map step keeps its parent's output cap, and the notice adds up.

After #455 a map step cut by `length` was split and retried, but `local_explain_code` sizes the
cap of each map step by the piece (`len // 8`). Halving the piece halved the cap, so each half was
asked for the same notes per character that had already not fitted, and was cut again down to the
depth limit (`length` + `retried` ~7 400 → ~3 300 → ~2 800 characters in the issue). Now each part
keeps at least its parent's cap. And the notice «N of M calls» only counted the cuts left in the
result while `steps` also showed the retried ones («1 of 13» against 4 `length` steps): it now
names the retried ones apart, so both add up. The backend is faked (`_run_chat`): no network.
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


_TRUNCATED = "salida truncada por max_tokens"
_RETRIED = re.compile(r"aparte, (\d+) llamadas cortadas se repitieron")
_COUNTS = re.compile(r"en (\d+) de (\d+) llamadas")

#: Dense code needs one output token per 5 characters of the fragment: more than the `len // 8`
#: cap of the explain map, so every whole piece is cut, as in the issue.
_NEED_CHARS_PER_TOKEN = 5


def _dense_code(functions: int = 300) -> str:
    return "".join(
        f"def handler_{i:03d}(request, config):\n    return route(request, {i}, config)  # ok\n\n"
        for i in range(functions)
    )


def _is_explain_map(call) -> bool:
    return call["user"].startswith("Toma notas")


def _cut_by_density(call):
    """`length` when the cap is below what the fragment's notes need, like a dense TS file."""
    if _is_explain_map(call):
        need = len(call["user"]) // _NEED_CHARS_PER_TOKEN
        return _ok("- nota", "length" if call["max_tokens"] < need else "stop")
    return _ok("explicación final")


def test_explain_code_split_retry_keeps_the_parent_cap_and_is_not_cut(backend, tmp_path):
    """Mutant `main` (the cap halves with the piece): the halves and quarters are cut again, the
    notice is there and `finish_reason` is `length`: the `_TRUNCATED not in out` assert fails."""
    calls, state = backend
    state["answer"] = _cut_by_density
    code = _dense_code()
    max_chars = config.max_chars_for_role("code")
    assert len(code) > max_chars  # guard: the chunked path
    out = server.local_explain_code(code=code)
    maps = [c for c in calls if _is_explain_map(c)]
    row = _row(tmp_path, "local_explain_code")
    retried = [s for s in row["steps"] if s.get("retried")]
    # Guard: the case reaches the retry branch (a whole piece was cut and split).
    assert retried and len(maps) > row["pieces"]
    assert _TRUNCATED not in out
    assert row["finish_reason"] == "stop"
    assert row.get("truncated_out") is not True
    # Every map step ends in `stop` except the replaced ones.
    assert all(
        s["finish_reason"] == "stop"
        for s in row["steps"]
        if s["kind"] == "map" and s not in retried
    )
    # The parts of a cut piece were asked with at least the parent's cap (the first cut one).
    first_cut = next(c for c in maps if c["max_tokens"] < len(c["user"]) // _NEED_CHARS_PER_TOKEN)
    after = maps[maps.index(first_cut) + 1 :][:2]
    assert all(c["max_tokens"] >= first_cut["max_tokens"] for c in after)
    assert all(len(c["user"]) < len(first_cut["user"]) for c in after)


def test_a_cap_that_does_not_grow_with_the_piece_is_unchanged(backend):
    """Tools with a fixed map cap (summarize, extract, lint) send the same cap on the retry."""
    calls, state = backend
    content = "".join(f"line {i:04d} " + "x" * 60 + "\n" for i in range(1, 401))
    state["answer"] = lambda c: _ok(
        "nota", "length" if c["user"].startswith("MAP:") and len(c["user"]) > 7000 else "stop"
    )
    server._chat_map_reduce(
        "m",
        "MAP",
        content,
        lambda piece: f"GRP:{piece}",
        max_chars=12_500,
        tool="local_summarize",
        source="inline",
        max_words=100,
        user_for=lambda piece: f"MAP:{piece}",
        reduce_system="RED",
        build_reduce=lambda joined: f"RED:{joined}",
    )
    maps = [c for c in calls if c["user"].startswith("MAP:")]
    assert len(maps) > 3  # guard: it did split
    assert {c["max_tokens"] for c in maps} == {2 * 100 + 64}


def test_the_notice_counts_the_retried_cuts_like_the_log_steps(backend, tmp_path):
    """Mutant `main` (the notice counts only the cuts left): no «aparte, N llamadas cortadas»,
    so the `_RETRIED` search fails; and N of the notice is lower than the `length` steps."""
    calls, state = backend
    content = "".join(f"line {i:04d} " + "x" * 60 + "\n" for i in range(1, 401))
    pieces = server._chunk_text(content, server._map_budget(12_500))
    second = pieces[1]
    # Every map call on (a part of) the second chunk is cut, at every depth.
    state["answer"] = lambda c: _ok(
        "nota",
        "length" if c["user"].startswith("MAP:") and c["user"][4:].strip() in second else "stop",
    )
    out = server._chat_map_reduce(
        "m",
        "MAP",
        content,
        lambda piece: f"GRP:{piece}",
        max_chars=12_500,
        tool="local_summarize",
        source="inline",
        max_words=100,
        user_for=lambda piece: f"MAP:{piece}",
        reduce_system="RED",
        build_reduce=lambda joined: f"RED:{joined}",
    )
    row = _row(tmp_path, "local_summarize")
    cut = [s for s in row["steps"] if s["finish_reason"] == "length"]
    retried = [s for s in cut if s.get("retried")]
    assert retried  # guard: the retry branch ran
    counts = _COUNTS.search(out)
    again = _RETRIED.search(out)
    assert counts and again, out
    assert int(counts.group(1)) == len(cut) - len(retried) == 4
    assert int(again.group(1)) == len(retried) == 3
    assert int(counts.group(2)) == row["chunks"] == len(calls)
    assert row["finish_reason"] == "length" and row["truncated_out"] is True


def test_extract_reports_the_retried_cuts_in_their_own_field(backend, tmp_path):
    """Mutant `main`: `_local_delegate` has no `retried_calls`. The `warning` text is the extract
    contract (REQ-010) and stays as it was; the two numbers add up to the `length` steps."""
    _calls, state = backend
    marker = "a = ONLY_IN_THE_SECOND\n"
    lines = "".join(f"line {i:04d} " + "x" * 60 + "\n" for i in range(1, 701))
    text = lines + marker + lines.replace("line", "otra")

    def answer(c):
        if "Combina" in c["system"]:
            return _ok('{"a": "x"}')
        cut = "ONLY_IN_THE_SECOND" in c["user"]
        return _ok('{"a": null}', "length" if cut else "stop")

    state["answer"] = answer
    data = server.local_extract(fields=["a"], text=text)
    meta = data["_local_delegate"]
    row = _row(tmp_path, "local_extract")
    cut = [s for s in row["steps"] if s["finish_reason"] == "length"]
    retried = [s for s in cut if s.get("retried")]
    assert retried  # guard: the retry branch ran
    counts = _COUNTS.search(meta["warning"])
    assert counts, meta["warning"]
    assert not _RETRIED.search(meta["warning"])  # the contract text does not change
    assert meta["retried_calls"] == len(retried)
    assert int(counts.group(1)) + meta["retried_calls"] == len(cut)
