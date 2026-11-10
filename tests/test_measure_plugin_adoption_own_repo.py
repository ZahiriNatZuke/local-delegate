"""`scripts/measure_plugin_adoption.py`: the repo's own sessions and the three columns.

usage-log-project-and-own-repo-exclusion, REQ-019 and REQ-020. A `LOG_DIR` and a projects root in
`tmp_path`, never the real ones.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from local_delegate import test_windows
from local_delegate.resources.hooks import hook_common

ROOT = Path(__file__).parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "measure_plugin_adoption", ROOT / "scripts" / "measure_plugin_adoption.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["measure_plugin_adoption"] = module
    spec.loader.exec_module(module)
    return module


measure_plugin_adoption = _load()

SINCE = "2026-10-10T00:00:00Z"
UNTIL = "2026-10-20T00:00:00Z"
TS = "2026-10-12T10:00:00Z"
SELF_PROJECT = "D--Projects-local-delegate"
OTHER_PROJECT = "D--work-app"


def _tool_use(tool_use_id: str) -> dict:
    return {
        "type": "assistant",
        "timestamp": TS,
        "message": {"content": [{"type": "tool_use", "id": tool_use_id, "name": "x"}]},
    }


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")


class World:
    def __init__(self, root: Path) -> None:
        self.log_dir = root / "logs"
        self.projects = root / "projects"
        self.log_dir.mkdir()
        self.projects.mkdir()
        self._rows: list[dict] = []

    def delegation(self, tool_use_id: str, *, caller: str | None = "main", **extra) -> None:
        row = {
            "ts": TS,
            "tool": "local_summarize",
            "ok": True,
            "client": "claude-code",
            "tool_use_id": tool_use_id,
            **extra,
        }
        if caller is not None:
            row["caller_kind"] = caller
            row["caller_src"] = "hook"
        self._rows.append(row)
        _write_jsonl(self.log_dir / "usage-202610.jsonl", self._rows)

    def session(
        self, project: str, name: str, ids: list[str], *, subagent_ids: list[str] | None = None
    ) -> None:
        head = {"type": "user", "entrypoint": "cli", "timestamp": TS, "sessionId": name}
        folder = self.projects / project
        _write_jsonl(folder / f"{name}.jsonl", [head, *(_tool_use(t) for t in ids)])
        if subagent_ids:
            body = [{**head, "isSidechain": True}, *(_tool_use(t) for t in subagent_ids)]
            _write_jsonl(folder / name / "subagents" / "agent-a1.jsonl", body)

    def measure(self, **kwargs) -> dict:
        return measure_plugin_adoption.measure(
            self.log_dir,
            self.projects,
            since=test_windows.parse_instant(SINCE),
            until=test_windows.parse_instant(UNTIL),
            **kwargs,
        )

    def main(self, *extra: str) -> dict:
        argv = ["--log-dir", str(self.log_dir), "--projects", str(self.projects)]
        argv += ["--since", SINCE, "--now", UNTIL, *extra]
        assert measure_plugin_adoption.main(argv) == 0
        return argv


@pytest.fixture
def world(tmp_path) -> World:
    return World(tmp_path)


def _self_delegates_other_does_not(world: World) -> None:
    """A session of the repo that delegates and another one that does not (REQ-019)."""
    world.delegation("toolu_01Self", caller_project_kind="self")
    world.session(SELF_PROJECT, "s-self", ["toolu_01Self"])
    world.session(OTHER_PROJECT, "s-other", [])


def test_the_sessions_of_the_own_repo_are_left_out_by_default(world):
    """Mutant 57."""
    _self_delegates_other_does_not(world)

    m = world.measure()

    assert m["pct"] == 0.0, "pct is 0.0 by default"
    assert (m["sessions"], m["with_delegation"]) == (1, 0)
    assert m["excluded_self_sessions"] == 1


def test_include_self_counts_them(world, capsys):
    """Mutant 58: through `main()`, as the cut of the measurement is taken."""
    _self_delegates_other_does_not(world)

    world.main("--include-self")
    out = json.loads(capsys.readouterr().out)

    assert out["base"]["pct"] == 50.0, "pct is 50.0 with the option"
    assert out["base"]["excluded_self_sessions"] == 0
    assert out["include_self"] is True


def test_exclude_self_is_the_default_of_the_command(world, capsys):
    _self_delegates_other_does_not(world)
    for extra in ((), ("--exclude-self",)):
        world.main(*extra)
        out = json.loads(capsys.readouterr().out)
        assert (out["base"]["pct"], out["include_self"]) == (0.0, False)


def test_the_two_options_cannot_go_together(world):
    with pytest.raises(SystemExit):
        world.main("--include-self", "--exclude-self")


def test_the_list_of_the_log_dir_marks_a_clone_as_own(world):
    """The kind of a session follows `LOG_DIR/self-projects.json`, the same list as the row."""
    (world.log_dir / "self-projects.json").write_text(
        json.dumps({"names": ["my-fork"]}), encoding="utf-8"
    )
    world.session("D--work-my-fork", "s-fork", [])
    world.session(OTHER_PROJECT, "s-other", [])

    m = world.measure()

    assert (m["sessions"], m["excluded_self_sessions"]) == (1, 1)


def _other_session_with_a_subagent_and_the_mod(world: World) -> None:
    """A session of another project: its main thread does not delegate, a subagent does, and so
    does the mod with the session's key (REQ-020)."""
    world.delegation("toolu_01Sub", caller="subagent", caller_project_kind="other")
    world.delegation(
        "toolu_plugin_01Mod",
        caller_project_kind="other",
        caller_session_key=hook_common.session_key("s-other"),
    )
    world.session(OTHER_PROJECT, "s-other", [], subagent_ids=["toolu_01Sub"])
    world.session(OTHER_PROJECT, "s-idle", [])


def test_a_delegation_in_a_subagent_transcript_counts_in_its_column(world):
    """Mutant 59."""
    _other_session_with_a_subagent_and_the_mod(world)

    m = world.measure()

    assert m["with_subagent_delegation"] == 1, "with_subagent_delegation is 1"
    assert m["delegations_by_caller"]["subagent"] == 1


def test_a_mod_row_counts_by_the_session_key(world):
    """Mutant 60."""
    _other_session_with_a_subagent_and_the_mod(world)

    m = world.measure()

    assert m["with_mod_delegation"] == 1, "with_mod_delegation is 1"
    assert m["delegations_by_caller"]["mod"] == 1


def test_pct_comes_only_from_the_main_thread(world):
    """Mutant 61: a subagent or the mod do not make a session count in `pct`."""
    _other_session_with_a_subagent_and_the_mod(world)

    m = world.measure()

    assert (m["sessions"], m["with_delegation"], m["pct"]) == (2, 0, 0.0), (
        "pct comes only from the main thread"
    )
    assert (m["with_subagent_delegation"], m["with_mod_delegation"]) == (1, 1)


def test_delegations_by_caller_sums_the_columns(world):
    _self_delegates_other_does_not(world)
    _other_session_with_a_subagent_and_the_mod(world)
    world.delegation("toolu_01Bare", caller=None)  # no thread from the note: unknown
    world.delegation("toolu_01Test", bench=True)  # a test: not a delegation of the measurement

    default = world.measure()["delegations_by_caller"]
    included = world.measure(include_self=True)["delegations_by_caller"]

    assert default == {"main": 0, "subagent": 1, "mod": 1, "unknown": 1}
    assert included == {"main": 1, "subagent": 1, "mod": 1, "unknown": 1}


def test_the_mod_column_ignores_the_mod_of_other_sessions(world):
    world.delegation(
        "toolu_plugin_01Mod",
        caller_project_kind="other",
        caller_session_key=hook_common.session_key("s-elsewhere"),
    )
    world.session(OTHER_PROJECT, "s-other", [])

    m = world.measure()

    assert (m["sessions"], m["with_mod_delegation"]) == (1, 0)
