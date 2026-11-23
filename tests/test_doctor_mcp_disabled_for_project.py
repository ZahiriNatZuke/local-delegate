"""#705: `doctor` warns when Claude Code has `local-delegate` disabled for the current project.

`/mcp` → disable stores the server name under `projects.<path>.disabledMcpServers` (user and local
servers) or `disabledMcpjsonServers` (the `.mcp.json` ones) of `~/.claude.json`. The session then
has no `local_*` tools, and `doctor` said everything was fine. Every `~/.claude.json` here is
synthetic: disabled in this project, in another one, through an ancestor, with the path written
with the other slash, and without the keys at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_delegate import checks, install, update

PROJECT = Path("D:/Work/app") if __import__("os").name == "nt" else Path("/work/app")


def _home(tmp_path: Path, projects: dict | None) -> Path:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    data: dict = {"mcpServers": {install.SERVER_NAME: {"type": "http", "url": "http://x/mcp"}}}
    if projects is not None:
        data["projects"] = projects
    (home / ".claude.json").write_text(json.dumps(data), encoding="utf-8")
    return home


def _probe(home: Path, cwd: Path = PROJECT) -> checks.Result:
    return checks._probe_mcp_claude(checks.Context(home=home, cwd=cwd))


@pytest.mark.parametrize("key", ["disabledMcpServers", "disabledMcpjsonServers"])
def test_disabled_in_this_project_is_a_warning_with_the_remedy(tmp_path, key):
    home = _home(tmp_path, {PROJECT.as_posix(): {key: ["other", install.SERVER_NAME]}})
    result = _probe(home)
    assert result.status == checks.WARN
    assert "/mcp" in result.fix_hint
    assert PROJECT.as_posix() in result.detail or str(PROJECT) in result.detail


def test_disabled_in_another_project_is_ok(tmp_path):
    other = (PROJECT.parent / "other").as_posix()
    home = _home(
        tmp_path,
        {
            other: {"disabledMcpServers": [install.SERVER_NAME]},
            PROJECT.as_posix(): {"disabledMcpServers": ["something-else"]},
        },
    )
    assert _probe(home).status == checks.OK


@pytest.mark.parametrize("projects", [None, {}, {PROJECT.as_posix(): {}}])
def test_without_the_keys_it_is_ok(tmp_path, projects):
    assert _probe(_home(tmp_path, projects)).status == checks.OK


def test_odd_types_are_ignored(tmp_path):
    home = _home(tmp_path, {PROJECT.as_posix(): {"disabledMcpServers": install.SERVER_NAME}})
    assert _probe(home).status == checks.OK
    assert _probe(_home(tmp_path / "b", [install.SERVER_NAME])).status == checks.OK  # type: ignore[arg-type]


def test_the_nearest_ancestor_entry_applies(tmp_path):
    home = _home(tmp_path, {PROJECT.as_posix(): {"disabledMcpServers": [install.SERVER_NAME]}})
    assert _probe(home, PROJECT / "src" / "pkg").status == checks.WARN
    # A nearer entry that does not disable it wins over the ancestor.
    home2 = _home(
        tmp_path / "b",
        {
            PROJECT.as_posix(): {"disabledMcpServers": [install.SERVER_NAME]},
            (PROJECT / "src").as_posix(): {"disabledMcpServers": []},
        },
    )
    assert _probe(home2, PROJECT / "src" / "pkg").status == checks.OK


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows paths")
def test_the_path_is_compared_normalized_on_windows(tmp_path):
    key = str(PROJECT).replace("/", "\\").upper()  # «D:\WORK\APP»
    home = _home(tmp_path, {key: {"disabledMcpjsonServers": [install.SERVER_NAME]}})
    assert _probe(home, Path("d:/work/app")).status == checks.WARN


def test_doctor_does_not_write_the_file_and_update_does_not_repair_it(tmp_path):
    home = _home(tmp_path, {PROJECT.as_posix(): {"disabledMcpServers": [install.SERVER_NAME]}})
    before = (home / ".claude.json").read_bytes()
    assert _probe(home).status == checks.WARN
    assert (home / ".claude.json").read_bytes() == before
    repair = next(r for r in update.REPAIRS if r.check_id == "scaffold.mcp_claude")
    assert checks.WARN not in repair.states
