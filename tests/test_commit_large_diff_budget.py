"""#596: a chunked `local_commit_msg` stops its map before the tool's time limit, and says so.

A ~125 KB diff (24 files) went to the backend in 7 chunks in series plus the reduce and the model
load: 124 s, and the client cancelled the tool at 120 s. Now the map stops before a chunk that
would leave no time for itself and the reduce within `COMMIT_TIME_BUDGET_S` of the call; the
message is drafted from the chunks read and the whole inventory, with a warning. A diff that has
the time keeps its prompts byte for byte (the corpus `techo-commit-156k` checks it too). The
backend is faked (`_run_chat`) and so is the clock (`_monotonic`): no network, log in tmp.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_delegate import config, i18n, server

MAP_MARK = "Di qué cambia en este fragmento"


def _ok(text: str, finish: str = "stop"):
    return server.ChatResult(text=text, ok=True, finish_reason=finish)


@pytest.fixture
def backend(monkeypatch, tmp_path):
    """Every call recorded; each call advances the fake clock by `state["seconds"](n)`."""
    calls: list[dict] = []
    clock = {"now": 1000.0}
    state = {"seconds": lambda n: 0.0}

    def run_chat(model, system, user, max_tokens, temperature, **_):
        calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        clock["now"] += state["seconds"](len(calls))
        text = "- src/x.py: cambia algo" if MAP_MARK in user else "feat(core): cambia\n\n- a\n- b"
        return _ok(text), 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(server, "_monotonic", lambda: clock["now"])
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    monkeypatch.setenv("LOCAL_DELEGATE_COMMIT_LANGUAGE", "es")
    i18n.reset()
    return calls, clock, state


def _row(tmp_path: Path) -> dict:
    rows = [
        json.loads(line)
        for file in sorted(tmp_path.glob("*.jsonl"))
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line)["tool"] == "local_commit_msg"
    ]
    assert len(rows) == 1
    return rows[0]


def _file(n: int, hunks: int) -> str:
    out = [
        f"diff --git a/src/mod_{n}.py b/src/mod_{n}.py\n",
        f"index 0000000..1111111 100644\n--- a/src/mod_{n}.py\n+++ b/src/mod_{n}.py\n",
    ]
    for h in range(hunks):
        out.append(f"@@ -{h * 20 + 1},10 +{h * 20 + 1},10 @@ def func_{n}_{h}():\n")
        out += [f"     contexto {n} {h} {i} sin cambios en esta linea\n" for i in range(3)]
        out += [f"-    viejo_{n}_{h}_{i} = calcula(a, b)\n" for i in range(4)]
        out += [f"+    nuevo_{n}_{h}_{i} = calcula(a, b, c)\n" for i in range(4)]
        out += [f"     contexto {n} {h} {i} tras el cambio\n" for i in range(3)]
    return "".join(out)


def _issue_diff() -> str:
    """~125 000 chars in 24 files: 7–8 chunks for the `code` role at 20 000 chars."""
    diff = "".join(_file(n, 9) for n in range(24))
    assert 115_000 < len(diff) < 135_000, len(diff)  # guard: the size of the issue
    return diff


def _issue_pace(n: int) -> float:
    """The issue's pace: the first call also loads the model (36 s), the rest 14 s each."""
    return 36.0 if n == 1 else 14.0


def _maps(calls: list[dict]) -> list[dict]:
    return [c for c in calls if MAP_MARK in c["user"]]


def test_the_issue_diff_stops_the_map_in_time_and_says_so(backend, tmp_path):
    """Mutant `main` (no time budget): 7 map calls and 134 fake seconds; the `<= 120` assert
    fails, then the one on the warning."""
    calls, clock, state = backend
    state["seconds"] = _issue_pace
    diff = _issue_diff()
    start = clock["now"]
    pieces = len(server._chunk_text(diff, server._map_budget(config.max_chars_for_role("code"))))
    assert pieces >= 7  # guard: the chunks of the issue
    out = server.local_commit_msg(diff=diff)
    assert clock["now"] - start <= 120
    assert 2 <= len(_maps(calls)) < pieces
    head = i18n.t(
        "mcp.warning.time_budget", seconds=0, read=0, total=0, chars=0, total_chars=0
    ).split(" (")[0]
    assert head in out
    assert "leídos enteros" not in out
    row = _row(tmp_path)
    assert row["truncated_in"] is True and row["ok"] is True
    # The message is still drafted, over the whole inventory: every file is named there.
    reduce_user = calls[-1]["user"]
    assert MAP_MARK not in reduce_user
    assert all(f"src/mod_{n}.py" in reduce_user for n in range(24))


def test_with_time_left_the_prompts_are_unchanged(backend, monkeypatch, tmp_path):
    """A diff whose chunks fit the budget keeps every prompt and the answer byte for byte."""
    calls, _clock, state = backend
    state["seconds"] = lambda n: 5.0
    diff = _issue_diff()
    out = server.local_commit_msg(diff=diff)
    with_budget = [(c["system"], c["user"], c["max_tokens"]) for c in calls]
    calls.clear()
    monkeypatch.setattr(server, "COMMIT_TIME_BUDGET_S", 0)
    out_without = server.local_commit_msg(diff=diff)
    assert with_budget == [(c["system"], c["user"], c["max_tokens"]) for c in calls]
    assert out == out_without
    assert "leídos enteros" in out


def test_the_first_chunk_alone_never_stops_the_map():
    """The first chunk pays the model load: with fewer than two chunks read, no estimate."""
    assert server._map_time_left(10, [], 0.0)
    assert server._map_time_left(10, [500.0], 0.0)


def test_the_estimate_skips_the_first_chunk(monkeypatch):
    monkeypatch.setattr(server, "_monotonic", lambda: 50.0)
    # 50 s elapsed + 2 × 14 s (the slowest after the first) = 78 ≤ 95.
    assert server._map_time_left(95, [36.0, 14.0], 0.0)
    # 50 + 2 × 30 = 110 > 95.
    assert not server._map_time_left(95, [36.0, 14.0, 30.0], 0.0)
