"""The own repo left out of the dashboard's API (usage-log-project-and-own-repo-exclusion, T5).

`/api/stats`, `/api/events` and `/api/hooks` leave out by default what the own repo asked for
(`caller_project_kind: self` in the usage rows, `project_kind: self` in the hook events), with the
same set in the three; `include_self=1` keeps it; `?session=` never leaves anything out; the cost
follows the switch; and the caller columns add up to `calls`.

The fixed data carries a row that is a test AND `self` (so `excluded_self` and `self_in_range` can
differ), a row without the field (so `unknown_project` is not «the rest»), and a `self` row the
cost can value (so the cost has something to go down by).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from local_delegate import config
from local_delegate.web import metrics

SESSION = "0f8e2a41-5b6c-4d7e-9f80-a1b2c3d4e5f6"


@pytest.fixture
def logs(tmp_path, monkeypatch):
    """LOG_DIR, HOME and hook telemetry of the test, the reader's cache clean."""
    folder = tmp_path / "logs"
    folder.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(config, "LOG_DIR", folder)
    monkeypatch.setattr(config, "USAGE_LOG", folder / "usage.jsonl")
    monkeypatch.setattr(config, "COST_FALLBACK", "")
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", folder / "hooks.jsonl")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    metrics._FILE_CACHE.clear()
    yield folder
    metrics._FILE_CACHE.clear()


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _row(n: int, **extra) -> dict:
    """A Claude Code delegation the cost can value: a path read with real tokens."""
    row = {
        "ts": (_now() - timedelta(minutes=30 - n)).isoformat(timespec="seconds"),
        "tool": "local_summarize",
        "source": "path",
        "chars_in": 3_000_000,
        "chars_out": 0,
        "ok": True,
        "tokens_in": 9000,
        "tokens_out": 100,
        "client": "claude-code",
        "tool_use_id": f"toolu_{n:04d}",
    }
    row.update(extra)
    return row


def _main(kind: str) -> dict:
    return {"caller_src": "hook", "caller_kind": "main", "caller_project_kind": kind}


# A: other, main thread.  B: self, subagent.  C: self AND a test.  D: no project, the mod.
# E: other AND a test.  F: self, thread without real data.
ROWS = [
    _row(1, **_main("other")),
    _row(2, caller_src="hook", caller_kind="subagent", caller_project_kind="self"),
    _row(3, client="mcp", caller_project_kind="self"),
    _row(4, tool_use_id="toolu_plugin_0004", caller_kind="main"),
    _row(5, client="mcp", caller_project_kind="other"),
    _row(6, caller_project_kind="self"),
]


def _write(folder: Path, rows: list[dict]) -> None:
    with (folder / f"usage-{_now():%Y%m}.jsonl").open("a", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    metrics._FILE_CACHE.clear()


def _get(path: str, **params) -> dict:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return TestClient(metrics.app).get(path + ("?" + query if query else "")).json()


COUNTERS = ("excluded_tests", "tests_in_range", "excluded_self", "self_in_range", "unknown_project")


# --- REQ-009 ------------------------------------------------------------------------------------


def test_stats_and_events_leave_out_the_own_repo_with_the_same_set(logs):
    """Mutant 30 (`/api/events` without the filter): the two answers count the same set."""
    _write(logs, ROWS)
    stats = _get("/api/stats")
    events = _get("/api/events")
    assert stats["total"]["calls"] == 2  # A and D: the tests and the `self` rows leave
    assert events["meta"]["count"] == stats["total"]["calls"]
    assert {e["tool_use_id"] for e in events["events"]} == {"toolu_0001", "toolu_plugin_0004"}
    assert {k: events["meta"][k] for k in COUNTERS} == {k: stats[k] for k in COUNTERS}


@pytest.mark.parametrize("include_tests", [False, True])
def test_shown_plus_both_excluded_counts_is_the_whole_range(logs, include_tests):
    """Mutant 31 (`excluded_self` also counts the tests already left out): it adds up."""
    _write(logs, ROWS)
    params = {"include_tests": "1"} if include_tests else {}
    for answer in (_get("/api/stats", **params), _get("/api/events", **params)):
        shown = answer["total"]["calls"] if "total" in answer else answer["meta"]["count"]
        counts = answer if "total" in answer else answer["meta"]
        assert shown + counts["excluded_tests"] + counts["excluded_self"] == len(ROWS), counts
    stats = _get("/api/stats", **params)
    # Off: B and F leave by this filter (C already left as a test); on: B, C and F.
    assert stats["excluded_self"] == (3 if include_tests else 2)


def test_unknown_project_counts_only_the_rows_without_a_kind(logs):
    """Mutant 32 (`unknown_project` also counts the `other` rows): only D has no kind."""
    _write(logs, ROWS)
    assert _get("/api/stats")["unknown_project"] == 1
    assert _get("/api/events")["meta"]["unknown_project"] == 1
    # With everything shown, still one: A and E are `other`, B, C and F are `self`.
    assert _get("/api/stats", include_tests="1", include_self="1")["unknown_project"] == 1


@pytest.mark.parametrize("value", ["1", "true", "TRUE"])
def test_include_self_returns_every_row(logs, value):
    """Mutant 33 (`include_self=1` ignored): with the parameter every row comes back."""
    _write(logs, ROWS)
    stats = _get("/api/stats", include_self=value)
    assert stats["total"]["calls"] == 4  # A, B, D and F; the tests still leave
    assert stats["excluded_self"] == 0
    assert _get("/api/events", include_self=value)["meta"]["count"] == 4
    both = _get("/api/stats", include_self=value, include_tests="1")
    assert both["total"]["calls"] == len(ROWS)


@pytest.mark.parametrize("value", ["0", "yes", ""])
def test_any_other_value_keeps_the_own_repo_out(logs, value):
    _write(logs, ROWS)
    assert _get("/api/stats", include_self=value)["total"]["calls"] == 2


def test_self_in_range_counts_the_self_row_that_is_a_test(logs):
    """Mutant 34 (`self_in_range` does not count the tests): B, C and F, C being a test."""
    _write(logs, ROWS)
    for params in ({}, {"include_self": "1"}, {"include_tests": "1"}):
        assert _get("/api/stats", **params)["self_in_range"] == 3
        assert _get("/api/events", **params)["meta"]["self_in_range"] == 3


# --- REQ-010 ------------------------------------------------------------------------------------


def test_a_session_of_the_own_repo_keeps_its_figures(logs):
    """Mutant 35 (the filter also applies with `session=`): `total.calls == 1`."""
    key = metrics.hook_common.session_key(SESSION)
    assert key  # guard: the id has the shape the rule accepts
    _write(
        logs,
        [
            _row(1, caller_session_key=key, **_main("self")),
            _row(2, **_main("self")),  # another session of the repo: not this one
        ],
    )
    stats = _get("/api/stats", session=SESSION)
    assert stats["total"]["calls"] == 1
    assert stats["excluded_self"] == 0
    assert stats["self_in_range"] == 1
    # Guard: without `session=` the same row does leave.
    assert _get("/api/stats")["total"]["calls"] == 0


# --- REQ-011 ------------------------------------------------------------------------------------


def test_the_cost_follows_the_own_repo_switch_and_not_the_tests_one(logs):
    """Mutant 36 (the cost gets the rows unfiltered): the cost goes down without `include_self`."""
    _write(logs, [_row(1, **_main("other")), _row(2, **_main("self"))])
    off = _get("/api/stats")["cost"]
    on = _get("/api/stats", include_self="1")["cost"]
    assert on["figure"] is not None and off["figure"] is not None  # guard: both are valued
    assert off["figure"]["estimate"] < on["figure"]["estimate"]
    assert off["figure"]["low_bound"] < on["figure"]["low_bound"]
    assert on["bar"]["valued"] == 2
    assert off["bar"]["valued"] == 1
    # The tests switch still does not move the cost.
    assert _get("/api/stats", include_tests="1")["cost"] == off
    assert _get("/api/stats", include_tests="1", include_self="1")["cost"] == on


def test_a_session_cost_keeps_the_own_repo(logs):
    """With `session=` the cost of that session counts its `self` rows (REQ-010 and REQ-011)."""
    key = metrics.hook_common.session_key(SESSION)
    _write(logs, [_row(1, caller_session_key=key, **_main("self"))])
    assert _get("/api/stats", session=SESSION)["cost"]["bar"]["valued"] == 1


# --- REQ-012 ------------------------------------------------------------------------------------


def _hook_event(n: int, **extra) -> dict:
    event = {
        "ts": (_now() - timedelta(minutes=10 - n)).isoformat(timespec="seconds"),
        "event": "PreToolUse",
        "category": "read",
        "suggested": True,
        "reason": None,
    }
    event.update(extra)
    return event


HOOK_EVENTS = [
    _hook_event(1, project="a1b2c3d4e5f60718", project_kind="self"),
    _hook_event(2, project="0718a1b2c3d4e5f6", project_kind="other"),
    _hook_event(3),  # without the field: an older event, or a hook input without a transcript
]


def _write_hooks(folder: Path, events: list[dict]) -> None:
    (folder / "hooks.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8"
    )
    metrics._FILE_CACHE.clear()


def test_hooks_leave_out_the_self_events_by_default(logs):
    """Mutant 37 (`/api/hooks` does not filter): by default the `self` event does not count."""
    _write_hooks(logs, HOOK_EVENTS)
    data = _get("/api/hooks")
    assert data["total"] == 2
    assert data["excluded_self"] == 1
    assert data["unknown_project"] == 1


def test_hooks_keep_the_events_without_the_field(logs):
    """Mutant 38 (`/api/hooks` leaves out the events without the field): it stays."""
    _write_hooks(logs, [_hook_event(3), _hook_event(4, project_kind="unexpected")])
    data = _get("/api/hooks")
    assert data["total"] == 2
    assert data["excluded_self"] == 0
    assert data["unknown_project"] == 2


def test_hooks_with_include_self_count_the_self_event(logs):
    """Mutant 39 (`/api/hooks` ignores `include_self=1`): with it the `self` event counts."""
    _write_hooks(logs, HOOK_EVENTS)
    data = _get("/api/hooks", include_self="1")
    assert data["total"] == 3
    assert data["excluded_self"] == 0
    assert data["unknown_project"] == 1


def test_hooks_disabled_still_carry_the_counters(logs, monkeypatch):
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", None)
    data = _get("/api/hooks")
    assert data["enabled"] is False
    assert (data["excluded_self"], data["unknown_project"]) == (0, 0)


# --- REQ-014 ------------------------------------------------------------------------------------

CALLER_COLUMNS = ("main_calls", "subagent_calls", "mod_calls", "unknown_caller_calls")


def test_the_four_caller_columns_add_up_to_calls(logs):
    """Mutant 42 (a column is not counted): the sum of the four is `calls`, total and per client."""
    _write(logs, ROWS)
    stats = _get("/api/stats", include_tests="1", include_self="1")
    total = stats["total"]
    assert sum(total[k] for k in CALLER_COLUMNS) == total["calls"] == len(ROWS), total
    by_client = {c["client"]: c for c in stats["by_client"]}
    assert set(by_client) == {"claude-code", "mcp"}
    for client in by_client.values():
        assert sum(client[k] for k in CALLER_COLUMNS) == client["calls"], client
    assert {k: total[k] for k in CALLER_COLUMNS} == {
        "main_calls": 1,  # A
        "subagent_calls": 1,  # B
        "mod_calls": 1,  # D, although it says `caller_kind: main`
        "unknown_caller_calls": 3,  # C, E and F: no real thread data
    }
    assert by_client["mcp"]["unknown_caller_calls"] == 2
    # `mod_calls` keeps its meaning of today, also at the top level.
    assert stats["mod_calls"] == by_client["claude-code"]["mod_calls"] == 1


def test_the_columns_follow_the_filters(logs):
    """By default only A (main) and D (mod) are shown: the columns count what is shown."""
    _write(logs, ROWS)
    total = _get("/api/stats")["total"]
    assert {k: total[k] for k in CALLER_COLUMNS} == {
        "main_calls": 1,
        "subagent_calls": 0,
        "mod_calls": 1,
        "unknown_caller_calls": 0,
    }
