"""`scripts/measure_adoption.py` leaves the repo's own use out by default (REQ-017, REQ-018).

usage-log-project-and-own-repo-exclusion. A world in `tmp_path`: a projects root with one session
of the repo and one of another project, the hook telemetry and the usage log, never the real ones.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from local_delegate import config

ROOT = Path(__file__).parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "measure_adoption", ROOT / "scripts" / "measure_adoption.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["measure_adoption"] = module
    spec.loader.exec_module(module)
    return module


measure_adoption = _load()

SELF_SESSION = "11111111-2222-3333-4444-555555555555"
OTHER_SESSION = "66666666-7777-8888-9999-000000000000"
TS = "2026-11-05T10:00:00Z"


class World:
    """A projects root, a `LOG_DIR` and a hook telemetry file, all in `tmp_path`."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.projects = root / "projects"
        self.log_dir = root / "logs"
        self.telemetry = root / "telemetry.jsonl"
        self.log_dir.mkdir()
        self._hooks: list[dict] = []
        self._usage: list[dict] = []
        self.transcript("D--Projects-local-delegate", SELF_SESSION)
        self.transcript("D--work-app", OTHER_SESSION)
        monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(self.telemetry))
        monkeypatch.setattr(config, "LOG_DIR", self.log_dir)

    def transcript(self, project: str, session: str) -> None:
        folder = self.projects / project
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{session}.jsonl").write_text("{}\n", encoding="utf-8")

    def read(self, session: str, kind: str | None = None, **extra) -> None:
        event = {
            "ts": TS,
            "category": "read",
            "reason": "small",
            "suggested": False,
            "session_id": session,
            "version": "abc12345",
            **extra,
        }
        if kind is not None:
            event["project"] = "0123456789abcdef"
            event["project_kind"] = kind
        self._hooks.append(event)
        self.telemetry.write_text(
            "".join(json.dumps(e) + "\n" for e in self._hooks), encoding="utf-8"
        )

    def delegation(self, kind: str | None, caller: str | None = "main", **extra) -> None:
        row = {"ts": TS, "tool": "local_summarize", "ok": True, "client": "claude-code", **extra}
        if caller is not None:
            row["caller_kind"] = caller
            row["caller_src"] = "hook"
        if kind is not None:
            row["caller_project"] = "0123456789abcdef"
            row["caller_project_kind"] = kind
        self._usage.append(row)
        (self.log_dir / "usage-202611.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in self._usage), encoding="utf-8"
        )

    def measure(self, **kwargs) -> dict:
        return measure_adoption.measure(None, projects=self.projects, **kwargs)


@pytest.fixture
def world(tmp_path, monkeypatch) -> World:
    return World(tmp_path, monkeypatch)


def test_hook_events_of_the_own_repo_are_left_out(world):
    """Mutant 51: the events that carry `project_kind: self` do not count by default."""
    world.read(SELF_SESSION, "self", suggested=True, blocked=True, id="b-self")
    world.read(SELF_SESSION, "self")
    world.read(OTHER_SESSION, "other")

    result = world.measure()

    assert result["reads"] == 1, "the reads are only those of the other session"
    assert result["sessions"] == 1
    assert (result["offered"], result["blocks"]) == (0, 0)
    assert result["excluded_self"]["hooks"] == 2


def test_usage_rows_of_the_own_repo_are_left_out(world):
    """Mutant 52: the usage rows with `caller_project_kind: self` do not count by default."""
    world.delegation("self")
    world.delegation("self")
    world.delegation("other")

    result = world.measure()

    assert result["total_delegations"] == 1, "total_delegations counts only the other one"
    assert result["excluded_self"]["usage"] == 2
    assert result["unknown_project"]["usage"] == 0


def test_an_old_event_is_resolved_by_its_session(world):
    """Mutant 53: an event without `project_kind` takes the kind of its session's directory."""
    world.read(SELF_SESSION)  # from before the field: its session is the repo's
    world.read(OTHER_SESSION)

    result = world.measure()

    assert result["excluded_self"]["hooks"] == 1, "the old event of the self session is left out"
    assert result["reads"] == 1
    assert result["unknown_project"]["hooks"] == 0


def test_an_event_whose_session_is_not_found_is_unknown_and_stays(world):
    world.read("77777777-8888-9999-0000-111111111111")  # a UUID with no transcript
    world.read("s-not-a-uuid")

    result = world.measure()

    assert result["reads"] == 2
    assert result["excluded_self"]["hooks"] == 0
    assert result["unknown_project"]["hooks"] == 2


def test_an_event_whose_session_is_in_two_directories_is_unknown(world):
    world.transcript("D--work-other-copy", SELF_SESSION)  # the same id in a second directory
    world.read(SELF_SESSION)

    result = world.measure()

    assert result["reads"] == 1
    assert result["unknown_project"]["hooks"] == 1


def test_include_self_counts_both_sessions(world, monkeypatch, capsys):
    """Mutant 54: with `--include-self` the two sessions count, events and rows."""
    world.read(SELF_SESSION, "self")
    world.read(SELF_SESSION)
    world.read(OTHER_SESSION, "other")
    world.delegation("self")
    world.delegation("other")
    argv = ["measure_adoption.py", "--json", "--include-self", "--projects", str(world.projects)]
    monkeypatch.setattr(sys, "argv", argv)

    assert measure_adoption.main() == 0
    result = json.loads(capsys.readouterr().out)

    assert (result["reads"], result["total_delegations"]) == (3, 2), "both sessions count"
    assert result["sessions"] == 2
    assert result["excluded_self"] == {"hooks": 0, "usage": 0}
    assert result["delegations_by_project_kind"] == {"self": 1, "other": 1, "unknown": 0}


def test_exclude_self_is_the_default_of_the_command(world, monkeypatch, capsys):
    world.read(SELF_SESSION)
    world.read(OTHER_SESSION)
    for extra in ([], ["--exclude-self"]):
        argv = ["measure_adoption.py", "--json", "--projects", str(world.projects), *extra]
        monkeypatch.setattr(sys, "argv", argv)
        assert measure_adoption.main() == 0
        result = json.loads(capsys.readouterr().out)
        assert (result["reads"], result["include_self"]) == (1, False)


def test_the_two_options_cannot_go_together(world, monkeypatch):
    argv = ["measure_adoption.py", "--include-self", "--exclude-self"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit):
        measure_adoption.main()


def test_delegations_by_caller_counts_the_mod_first(world):
    """Mutant 55: a mod row arrives with `caller_kind: main` and still sums in `mod`."""
    world.delegation("other", "main")
    world.delegation("other", "subagent")
    world.delegation("other", "main", tool_use_id="toolu_plugin_01Mod")
    world.delegation("other", None)

    result = world.measure()

    by_caller = result["delegations_by_caller"]
    assert by_caller["mod"] == 1, "the mod row sums in mod"
    assert by_caller == {"main": 1, "subagent": 1, "mod": 1, "unknown": 1}
    assert sum(by_caller.values()) == result["total_delegations"]


def test_delegations_by_project_kind_keeps_the_unknown_apart(world):
    """Mutant 56: a row without kind sums in `unknown`, never in `other`."""
    world.delegation("other")
    world.delegation(None)
    world.delegation("self")

    result = world.measure()

    assert result["delegations_by_project_kind"] == {"other": 1, "unknown": 1}, (
        "the row without kind sums in unknown"
    )
    assert result["unknown_project"]["usage"] == 1


def test_the_text_output_says_what_was_left_out(world, monkeypatch, capsys):
    world.read(SELF_SESSION)
    world.delegation("self")
    monkeypatch.setattr(sys, "argv", ["measure_adoption.py", "--projects", str(world.projects)])

    assert measure_adoption.main() == 0
    out = capsys.readouterr().out

    assert "Propio repo fuera: 1 eventos de hooks y 1 filas del log de uso" in out


def test_each_session_is_searched_once(world, monkeypatch):
    """One search per session and run, however many events it has."""
    for _ in range(5):
        world.read(SELF_SESSION)
    calls: list[str] = []
    real = measure_adoption.hook_common.project_of_session

    def counting(session_id, **kwargs):
        calls.append(session_id)
        return real(session_id, **kwargs)

    monkeypatch.setattr(measure_adoption.hook_common, "project_of_session", counting)

    result = world.measure()

    assert result["excluded_self"]["hooks"] == 5
    assert calls == [SELF_SESSION]
