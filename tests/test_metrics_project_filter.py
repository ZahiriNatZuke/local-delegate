"""The project filter and the per-project breakdown of the dashboard's API (dashboard-project-filter).

`/api/stats`, `/api/events` and `/api/hooks` show every project by default (the own-repo switch of
0.51.0 is gone: `include_self` is ignored); `?project=<hash>` keeps one project, `?project=none`
the rows without one, and any other value filters nothing. The three answers count the same set,
the cost follows the filter, `?session=` still works, and `/api/stats.by_project` gives the
delegations and the saving per project, most delegations first, with the local name of each hash
(`LOG_DIR/project-names.json`) or `null`.

The caller columns (REQ-014 of usage-log-project-and-own-repo-exclusion) keep their tests here.
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
P_A = "a1b2c3d4e5f60718"
P_B = "0718a1b2c3d4e5f6"


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
    monkeypatch.setattr(metrics, "_NAMES_BACKFILL_TRIED", {})
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


def _main(kind: str, project: str | None = None) -> dict:
    fields = {"caller_src": "hook", "caller_kind": "main", "caller_project_kind": kind}
    if project:
        fields["caller_project"] = project
    return fields


# A: project A, main thread.  B: project A (self), subagent.  C: project A AND a test.
# D: no project, the mod.  E: project B AND a test.  F: project B (self), thread without real data.
ROWS = [
    _row(1, **_main("other", P_A)),
    _row(
        2, caller_src="hook", caller_kind="subagent", caller_project_kind="self", caller_project=P_A
    ),
    _row(3, client="mcp", caller_project_kind="self", caller_project=P_A),
    _row(4, tool_use_id="toolu_plugin_0004", caller_kind="main"),
    _row(5, client="mcp", caller_project_kind="other", caller_project=P_B),
    _row(6, caller_project_kind="self", caller_project=P_B),
]


def _write(folder: Path, rows: list[dict]) -> None:
    with (folder / f"usage-{_now():%Y%m}.jsonl").open("a", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    metrics._FILE_CACHE.clear()


def _names(folder: Path, names: dict) -> None:
    (folder / "project-names.json").write_text(
        json.dumps({"version": 1, "names": names}), encoding="utf-8"
    )


def _get(path: str, **params) -> dict:
    return TestClient(metrics.app).get(path, params=params).json()


def _ids(events: dict) -> set[str]:
    return {e["tool_use_id"] for e in events["events"]}


# --- Everything by default, and the old switch is gone ------------------------------------------


@pytest.mark.parametrize("extra", [{}, {"include_self": "1"}, {"include_self": "0"}])
def test_every_project_is_shown_by_default_and_include_self_is_ignored(logs, extra):
    """Mutant: the own repo is still left out by default (it would give 2 instead of 4)."""
    _write(logs, ROWS)
    stats = _get("/api/stats", **extra)
    events = _get("/api/events", **extra)
    assert stats["total"]["calls"] == 4  # A, B, D and F: only the tests leave
    assert events["meta"]["count"] == 4
    assert _ids(events) == {"toolu_0001", "toolu_0002", "toolu_plugin_0004", "toolu_0006"}
    for gone in ("excluded_self", "self_in_range", "unknown_project"):
        assert gone not in stats and gone not in events["meta"]
    assert stats["project"] is None and events["meta"]["project"] is None


def test_the_page_has_no_own_repo_switch_and_has_the_project_filter():
    page = TestClient(metrics.app).get("/").text
    assert 'id="project"' in page and 'id="projectsCard"' in page
    for marker in ("include_self", "ld-self", "dlgSelf", "selfInfo", 'id="self"'):
        assert marker not in page, marker


# --- ?project= ------------------------------------------------------------------------------------


def test_a_project_keeps_only_its_rows_in_the_three_answers(logs):
    """Mutant: `/api/events` without the filter, or the filter on another field."""
    _write(logs, ROWS)
    _write_hooks(logs, HOOK_EVENTS)
    stats = _get("/api/stats", project=P_A)
    events = _get("/api/events", project=P_A)
    hooks = _get("/api/hooks", project=P_A)
    assert stats["total"]["calls"] == 2  # A and B; C is a test
    assert _ids(events) == {"toolu_0001", "toolu_0002"}
    assert stats["project"] == events["meta"]["project"] == hooks["project"] == P_A
    assert hooks["total"] == 1
    with_tests = _get("/api/stats", project=P_A, include_tests="1")
    assert with_tests["total"]["calls"] == 3


def test_none_keeps_the_rows_without_a_project(logs):
    _write(logs, [*ROWS, _row(7, caller_project="not-a-hash"), _row(8, caller_project=P_A.upper())])
    _write_hooks(logs, HOOK_EVENTS)
    events = _get("/api/events", project="none")
    assert _ids(events) == {"toolu_plugin_0004", "toolu_0007", "toolu_0008"}
    assert _get("/api/stats", project="NONE")["total"]["calls"] == 3
    assert _get("/api/hooks", project="none")["total"] == 1


@pytest.mark.parametrize(
    "value", ["", "x", "a1b2c3d4e5f6071", "a1b2c3d4e5f607189", "<script>", P_A + "%0A"]
)
def test_any_other_value_filters_nothing(logs, value):
    _write(logs, ROWS)
    _write_hooks(logs, HOOK_EVENTS)
    stats = _get("/api/stats", project=value)
    events = _get("/api/events", project=value)
    hooks = _get("/api/hooks", project=value)
    assert stats["total"]["calls"] == events["meta"]["count"] == 4
    assert hooks["total"] == 3
    assert stats["project"] is events["meta"]["project"] is hooks["project"] is None


def test_the_cost_follows_the_project_filter_and_not_the_tests_one(logs):
    """Mutant: the cost gets every project's rows while the KPIs show one."""
    _write(logs, [_row(1, **_main("other", P_A)), _row(2, **_main("self", P_B))])
    every = _get("/api/stats")["cost"]
    one = _get("/api/stats", project=P_A)["cost"]
    assert every["figure"] is not None and one["figure"] is not None  # guard: both are valued
    assert one["figure"]["estimate"] < every["figure"]["estimate"]
    assert every["bar"]["valued"] == 2
    assert one["bar"]["valued"] == 1
    assert _get("/api/stats", project=P_A, include_tests="1")["cost"] == one


def test_a_session_keeps_its_figures_whatever_its_project(logs):
    """The mod's status line (`?session=`) counts its whole session, `self` included."""
    key = metrics.hook_common.session_key(SESSION)
    assert key  # guard: the id has the shape the rule accepts
    _write(
        logs,
        [_row(1, caller_session_key=key, **_main("self", P_A)), _row(2, **_main("self", P_A))],
    )
    stats = _get("/api/stats", session=SESSION)
    assert stats["total"]["calls"] == 1
    assert stats["cost"]["bar"]["valued"] == 1


# --- by_project -----------------------------------------------------------------------------------


def test_by_project_counts_each_project_most_delegations_first_with_its_name(logs):
    _write(logs, [*ROWS, _row(7, **_main("other", P_B)), _row(8, **_main("other", P_B))])
    _names(logs, {P_B: "C--work-shop"})
    stats = _get("/api/stats")
    groups = stats["by_project"]
    assert [g["project"] for g in groups] == [P_B, P_A, "none"]  # 3, 2 and 1 (the tests leave)
    assert [g["calls"] for g in groups] == [3, 2, 1]
    assert [g["name"] for g in groups] == ["C--work-shop", None, None]
    assert sum(g["calls"] for g in groups) == stats["total"]["calls"]
    assert sum(g["tokens_net"] for g in groups) == stats["total"]["net"]
    assert sum(g["tokens_saved"] for g in groups) == stats["total"]["saved"]


def test_by_project_ignores_the_project_filter_and_follows_the_tests_one(logs):
    """It is what the selector offers: choosing a project does not empty the list."""
    _write(logs, ROWS)
    every = _get("/api/stats")["by_project"]
    assert _get("/api/stats", project=P_A)["by_project"] == every
    with_tests = {
        g["project"]: g["calls"] for g in _get("/api/stats", include_tests="1")["by_project"]
    }
    assert with_tests == {P_A: 3, P_B: 2, "none": 1}


@pytest.mark.parametrize(
    "content",
    [
        None,  # missing
        b"{not json",
        b"[]",
        json.dumps({"names": ["x"]}).encode(),
        json.dumps({"names": {"ZZZ": "bad hash", P_A: 7, P_B: "ok\x00name"}}).encode(),
        b"\xff\xfe\x00garbage",
        b" " * (600 * 1024),  # above the size cap
    ],
)
def test_a_missing_or_corrupt_map_gives_no_names_and_no_error(logs, content):
    _write(logs, ROWS)
    if content is not None:
        (logs / "project-names.json").write_bytes(content)
    response = TestClient(metrics.app).get("/api/stats")
    assert response.status_code == 200
    assert all(g["name"] is None for g in response.json()["by_project"])


def test_the_name_is_served_as_data_never_as_markup(logs):
    """The API returns the name as JSON text; escaping it is the panel's job (see the UI tests)."""
    hostile = '<img src=x onerror="alert(1)">'
    _write(logs, [_row(1, **_main("other", P_A))])
    _names(logs, {P_A: hostile})
    response = TestClient(metrics.app).get("/api/stats")
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["by_project"][0]["name"] == hostile


def test_the_old_rows_get_their_name_from_the_projects_root(logs, tmp_path):
    """The rows of 0.51.0 carry the hash but the map is new: the first read names them from the
    directory names under `~/.claude/projects` (never a transcript), with the local salt."""
    common = metrics.hook_common
    salt = "ab" * 32
    (logs / "project-salt").write_text(salt, encoding="ascii")
    root = Path.home() / ".claude" / "projects"
    for name in ("D--work-shop", "D--work-other"):
        (root / name).mkdir(parents=True)
    (root / "loose-file.jsonl").write_text("{}", encoding="utf-8")
    shop = common.project_hash("D--work-shop", salt)
    _write(logs, [_row(1, **_main("other", shop)), _row(2, **_main("other", P_A))])
    groups = {g["project"]: g["name"] for g in _get("/api/stats")["by_project"]}
    assert groups == {shop: "D--work-shop", P_A: None}
    stored = json.loads((logs / "project-names.json").read_text(encoding="utf-8"))["names"]
    assert stored == {shop: "D--work-shop"}  # only the hashes of the log, not every directory


# --- /api/hooks -----------------------------------------------------------------------------------


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
    _hook_event(1, project=P_A, project_kind="self"),
    _hook_event(2, project=P_B, project_kind="other"),
    _hook_event(3),  # without the field: an older event, or a hook input without a transcript
]


def _write_hooks(folder: Path, events: list[dict]) -> None:
    (folder / "hooks.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8"
    )
    metrics._FILE_CACHE.clear()


def test_hooks_count_every_event_by_default(logs):
    """Mutant: `/api/hooks` still leaves out the `self` events."""
    _write_hooks(logs, HOOK_EVENTS)
    data = _get("/api/hooks")
    assert data["total"] == 3
    assert "excluded_self" not in data
    assert _get("/api/hooks", include_self="0")["total"] == 3


def test_hooks_disabled_answer_without_the_old_counters(logs, monkeypatch):
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", None)
    data = _get("/api/hooks")
    assert data["enabled"] is False
    assert "excluded_self" not in data
    assert data["project"] is None
    assert _get("/api/hooks", project=P_A)["project"] == P_A


# --- REQ-014 of usage-log-project-and-own-repo-exclusion ------------------------------------------

CALLER_COLUMNS = ("main_calls", "subagent_calls", "mod_calls", "unknown_caller_calls")


def test_the_four_caller_columns_add_up_to_calls(logs):
    """Mutant 42 (a column is not counted): the sum of the four is `calls`, total and per client."""
    _write(logs, ROWS)
    stats = _get("/api/stats", include_tests="1")
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
    """With project A only A (main) and B (subagent) are shown: the columns count what is shown."""
    _write(logs, ROWS)
    total = _get("/api/stats", project=P_A)["total"]
    assert {k: total[k] for k in CALLER_COLUMNS} == {
        "main_calls": 1,
        "subagent_calls": 1,
        "mod_calls": 0,
        "unknown_caller_calls": 0,
    }


# --- The backfill from the dashboard: once per hash, retried after an incomplete pass ------------


def _old_rows_world(logs) -> str:
    common = metrics.hook_common
    salt = "ab" * 32
    (logs / "project-salt").write_text(salt, encoding="ascii")
    (Path.home() / ".claude" / "projects" / "D--work-shop").mkdir(parents=True)
    shop = common.project_hash("D--work-shop", salt)
    _write(logs, [_row(1, **_main("other", shop)), _row(2, **_main("other", P_A))])
    return shop


def test_the_backfill_walks_once_per_missing_hash(logs, monkeypatch):
    shop = _old_rows_world(logs)
    calls = []
    real = metrics.hook_common.backfill_project_names
    monkeypatch.setattr(
        metrics.hook_common,
        "backfill_project_names",
        lambda hashes, **kw: calls.append(set(hashes)) or real(hashes, **kw),
    )
    _get("/api/stats")
    _get("/api/stats")
    _get("/api/stats", project=P_A)
    assert calls == [{P_A, shop}]  # one pass, for both hashes; P_A has no directory


def test_an_incomplete_pass_is_tried_again(logs, monkeypatch):
    """Mutant: the hashes are settled before knowing the pass worked (busy lock on the first)."""
    shop = _old_rows_world(logs)
    common = metrics.hook_common
    real = common._add_project_names
    state = {"busy": True}

    def add(path, found):
        return None if state["busy"] else real(path, found)

    monkeypatch.setattr(common, "_add_project_names", add)
    first = {g["project"]: g["name"] for g in _get("/api/stats")["by_project"]}
    assert first[shop] is None
    state["busy"] = False
    second = {g["project"]: g["name"] for g in _get("/api/stats")["by_project"]}
    assert second[shop] == "D--work-shop"


def test_the_mods_status_line_neither_reads_nor_fills_the_map(logs, monkeypatch):
    _old_rows_world(logs)
    touched = []
    common = metrics.hook_common
    monkeypatch.setattr(common, "read_project_names", lambda *a, **k: touched.append("r") or {})
    monkeypatch.setattr(common, "backfill_project_names", lambda *a, **k: touched.append("b") or 0)
    stats = _get("/api/stats", session=SESSION)
    assert stats["by_project"] == []
    assert touched == []
    assert not (logs / "project-names.json").exists()
