"""#497: the map/reduce regroup converges or stops, and the split retries have a budget.

`local_explain_code` on a ~48 000 character file took ~18 minutes and 65 backend calls: each
regroup step was cut by `length`, split and retried with the same cap, so a level returned about
as much as it was given and the next level regrouped the same again, three times, to end in the
joined notes anyway. The backend is faked (`_run_chat`): no network, log in tmp.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from local_delegate import config, i18n, server

CHARS_PER_TOKEN = 4.08  # what the log of the issue shows: 764 tokens cut at ~3 115 characters


def _ok(text: str, finish: str = "stop"):
    return server.ChatResult(text=text, ok=True, finish_reason=finish)


def _notes(n: int, tag: int) -> str:
    """`n` characters of distinct note lines, so no two outputs are the same text."""
    line = f"nota {tag:04d} " + "n" * 50 + "\n"
    return (line * (n // len(line) + 1))[:n]


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


def _verbose(share: float | None):
    """A model that writes `share` of what it reads, or fills any cap with `None`; cut at the cap."""

    def answer(call):
        cap = int(call["max_tokens"] * CHARS_PER_TOKEN)
        need = cap + 1 if share is None else int(len(call["user"]) * share)
        return _ok(_notes(min(need, cap), len(call["user"])), "length" if need > cap else "stop")

    return answer


def _issue_file() -> str:
    """~48 000 characters of code in four top-level functions: four chunks for `local_explain_code`."""
    body = "".join(f"    x_{j} = compute_{j}(a, b)  # step {j}\n" for j in range(300))
    code = "".join(f"def part_{i}():\n{body}\n" for i in range(4))[:48_000]
    budget = server._map_budget(config.max_chars_for_role("code"))
    assert len(server._code_pieces(code, budget)) == 4  # guard: the four chunks of the issue
    return code


# --- 1. The case of the issue -------------------------------------------------------------------


def test_the_issue_file_regroups_once_and_reaches_the_reduce(backend, tmp_path):
    """Mutant `main`: 53 calls (37 regroup steps, no reduce); the call and kind asserts fail."""
    calls, state = backend
    state["answer"] = _verbose(0.7)  # notes at 70 % of their input: map and regroup get cut
    server.local_explain_code(code=_issue_file())
    row = _row(tmp_path, "local_explain_code")
    kinds = Counter(s["kind"] for s in row["steps"])
    assert kinds["map"] >= 4  # guard: it chunked
    assert kinds["regroup"] >= 1  # guard: the notes did not fit one reduce
    assert kinds["regroup"] <= 6
    assert row["steps"][-1]["kind"] == "reduce"
    assert len(calls) <= 18


def test_a_model_that_fills_any_cap_stays_bounded(backend, tmp_path):
    """Mutant `main`: 539 calls. Mutant "no retry budget": 61 calls, the bound assert fails."""
    calls, state = backend
    state["answer"] = _verbose(None)
    server.local_explain_code(code=_issue_file())
    row = _row(tmp_path, "local_explain_code")
    assert row["pieces"] == 4  # guard
    retry_budget = server.MAP_REDUCE_RETRY_CALLS_PER_PIECE * row["pieces"]
    # The budget, plus the calls that never retry: some regroup groups and the reduce.
    assert len(calls) <= retry_budget + 8
    assert row["truncated_out"] is True and row["finish_reason"] == "length"


# --- 2. The regroup split ------------------------------------------------------------------------


def test_a_cut_regroup_is_not_split_when_the_halves_cannot_halve_it():
    # A 16 000 character group cut at 3 115: two halves of up to 3 115 each still halve it.
    assert server._regroup_split_shrinks(16_000, 3_115, 2)
    # An 8 000 character half cut at 3 115: its halves would bring back 6 230, not 4 000.
    assert not server._regroup_split_shrinks(8_000, 3_115, 2)
    # A three-part split counts its three parts.
    assert not server._regroup_split_shrinks(16_000, 3_115, 3)


MAX_CHARS = 12_500  # budget 10 000


def _map_reduce(content: str, report: dict | None = None) -> str:
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
    )


def _distinct_lines(n: int, width: int = 60) -> str:
    return "".join(f"line {i:04d} " + "x" * width + "\n" for i in range(1, n + 1))


def test_a_level_that_does_not_shrink_stops_and_is_marked(backend, tmp_path):
    """Mutant `main`: three levels of regroup over the same and no notice; the level count and
    the notice asserts fail."""
    calls, state = backend

    def answer(c):
        if c["user"].startswith("MAP:"):
            return _ok(_notes(3_000, len(c["user"])))
        if c["user"].startswith("GRP:"):
            # A regroup that returns as much as it reads, without being cut.
            return _ok(_notes(len(c["user"]) - 4, len(c["user"])))
        return _ok("final")

    state["answer"] = answer
    out = _map_reduce(_distinct_lines(560))  # four chunks: ~12 000 of notes > the 10 000 budget
    regroups = [c for c in calls if c["user"].startswith("GRP:")]
    assert regroups  # guard: it regrouped
    assert len(regroups) <= 2  # one level: the groups of the first one, never a second
    assert not any(c["user"].startswith("RED:") for c in calls)
    assert i18n.t("mcp.warning.regroup_stopped", calls=len(calls)) in out
    row = _row(tmp_path, "local_summarize")
    assert row["finish_reason"] == "length" and row["truncated_out"] is True


def test_legitimate_convergence_in_two_rounds_reaches_the_reduce(backend, tmp_path):
    """A regroup that keeps 85 % of what it reads, uncut, is under the 20 % rule but makes the
    notes fit: the next turn reduces. Mutant "the 20 % rule without the fit check": no reduce,
    6 calls and `length`; the reduce and call-count asserts fail."""
    calls, state = backend

    def answer(c):
        if c["user"].startswith("MAP:"):
            return _ok(_notes(2_750, len(c["user"])))
        if c["user"].startswith("GRP:"):
            return _ok(_notes(int(len(c["user"]) * 0.85), len(c["user"])))
        return _ok("final")

    state["answer"] = answer
    out = _map_reduce(_distinct_lines(560))  # four chunks: 4 x 2 750 of notes > the budget
    kinds = [c["user"][:4] for c in calls]
    assert kinds.count("MAP:") == 4 and kinds.count("GRP:") >= 1  # guard: it regrouped
    assert kinds[-1] == "RED:"
    assert len(calls) == 7
    assert out.startswith("final")
    row = _row(tmp_path, "local_summarize")
    assert row["finish_reason"] == "stop" and row.get("truncated_out") is not True


def test_extract_hears_that_the_regroup_stopped(backend, tmp_path):
    """Mutant "extract ignores `unreduced`": `not_json` without `truncated` nor the notice, while
    the log says `truncated_out`."""
    _calls, state = backend

    def answer(c):
        if "Combina" in c["system"]:
            return _ok('{"a": "x"}')
        # Every map and regroup step answers about as long as it reads: the regroup never shrinks.
        return _ok('{"a": "' + "v" * int(len(c["user"]) * 0.9) + '"}')

    state["answer"] = answer
    text = _distinct_lines(700) + _distinct_lines(700).replace("line", "otra")  # > 48 000
    data = server.local_extract(fields=["a"], text=text)
    meta = data["_local_delegate"]
    assert _row(tmp_path, "local_extract")["truncated_out"] is True  # guard: it stopped
    assert meta["truncated"] is True
    assert i18n.t("mcp.warning.regroup_stopped", calls=0).split(" tras ")[0] in meta["warning"]


def test_a_single_cut_piece_stays_near_the_retry_budget(backend):
    """One chunk whose every map step is cut: the retries stop at the budget of one chunk, plus
    at most the two sibling parts still pending (documented next to `_retry_fits`)."""
    calls, state = backend
    state["answer"] = lambda c: _ok("nota", "length" if c["user"].startswith("MAP:") else "stop")
    report: dict = {}
    _map_reduce(_distinct_lines(140), report=report)  # ~9 500 characters: one chunk
    assert report["pieces"] == 1  # guard
    maps = sum(1 for c in calls if c["user"].startswith("MAP:"))
    assert maps > 1  # guard: it did retry
    assert maps <= server.MAP_REDUCE_RETRY_CALLS_PER_PIECE + 2


def test_the_report_says_the_regroup_stopped(backend):
    _calls, state = backend
    state["answer"] = lambda c: (
        _ok(_notes(len(c["user"]), 1)) if c["user"].startswith("GRP:") else _ok(_notes(3_000, 2))
    )
    report: dict = {}
    _map_reduce(_distinct_lines(560), report=report)
    assert report["unreduced"] is True
    # A run that reaches the reduce says so too.
    state["answer"] = lambda c: _ok("corto")
    report = {}
    _map_reduce(_distinct_lines(560), report=report)
    assert report["unreduced"] is False


# --- 3. The split in two -------------------------------------------------------------------------


def test_the_split_retry_gives_two_parts_instead_of_a_scrap():
    """Mutant `main` (cap at exactly half): three parts, the last of a few dozen characters."""
    text = "".join(f"    x_{j} = compute_{j}(a, b)  # step {j}\n" for j in range(300))
    half = server._chunk_text(text, max(config.CHUNK_MIN_CHARS, len(text) // 2))
    assert len(half) == 3 and len(half[-1]) < 100  # guard: the scrap of the issue's shape
    parts = server._split_in_two(text)
    assert len(parts) == 2
    assert "".join(parts) == text


def test_the_split_in_two_keeps_exact_halves_when_they_already_fit():
    text = _distinct_lines(100)
    assert server._split_in_two(text) == server._chunk_text(text, len(text) // 2)
