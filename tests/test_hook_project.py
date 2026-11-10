"""The project in the hook telemetry and in the mod's line (usage-log-project-and-own-repo-exclusion,
REQ-016 and REQ-032; decisions D12, D13 and D14).

- A hook event takes `project` and `project_kind` from the `transcript_path` of its input, with the
  rule and from the directory of the usage row; nothing comes from the `cwd`.
- The mod's line (`hook record-read`) has no `transcript_path`: `hook_entry.record_read` finds the
  session's transcript from its `session_id` (`hook_common.project_of_session`) under the projects
  root of the PROCESS, hashes it with the salt of the PROCESS's `LOG_DIR`, and hands the fields to
  the LOOSE `hook_common` (the one `record_decision` and `context_of` read). Neither the root nor
  `LOG_DIR` comes from the environment the mod sends.

Every root, name and `LOG_DIR` is synthetic and lives in `tmp_path`; the process home is a fake
home in `tmp_path`, so nothing walks or writes the real `~/.claude`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from local_delegate import attribution, config, hook_entry, token_source
from local_delegate.resources.hooks import hook_common as package_common
from local_delegate.web import metrics

HOOKS = Path(config.__file__).parent / "resources" / "hooks"
SESSION = "0b9c3f9e-1d2a-4c5b-8e7f-123456789abc"
REPO_DIR = "D--work-local-delegate"
OTHER_DIR = "D--work-shop"
TOKEN = "hook-project-token"
LOOPBACK = ("127.0.0.1", 50000)
TIMEOUT_S = 60
CACHES = ("_SALTS", "_SELF_ENTRIES", "_SESSION_TRANSCRIPTS")


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A process home with an empty projects root, a process `LOG_DIR` and empty caches."""
    home = tmp_path / "home"
    root = home / ".claude" / "projects"
    root.mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    logs = tmp_path / "logs"
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(logs))
    loose = hook_entry._load_hook_module("hook_common")
    for module in (loose, package_common):
        for name in CACHES:
            monkeypatch.setattr(module, name, {})
    telemetry = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", telemetry)
    return SimpleNamespace(
        tmp=tmp_path, home=home, root=root, logs=logs, loose=loose, telemetry=telemetry
    )


def _session(root: Path, project: str, session: str = SESSION) -> Path:
    transcript = root / project / f"{session}.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("{}\n", encoding="utf-8")
    return transcript


def _row_project(transcript: Path) -> dict:
    """What the usage row of that session carries (`attribution.resolve_call`, the same call)."""
    return attribution.project_identity(str(transcript), root=attribution._projects_root())


def _lines(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


def _request_env(world, **extra: str) -> dict[str, str]:
    """What the mod sends (`RECORD_ENV`), with its own `LOG_DIR` and the daemon's telemetry."""
    data = world.tmp / "request-data"
    data.mkdir(parents=True, exist_ok=True)
    env = {
        "LOCAL_DELEGATE_LOG_DIR": str(data),
        "LD_HOOK_READ_SWITCH_FILE": str(world.tmp / "block-off"),
        "LD_HOOK_READ_ENABLED": "1",
        "LD_HOOK_READ_BLOCK": "1",
        "LD_HOOK_TELEMETRY_LOG": str(world.telemetry),
    }
    env.update(extra)
    return env


def _entry(world, session_id: object = SESSION, **extra) -> dict:
    """What `readRecord` sends: the output of `hook classify` plus `decision` and `session_id`."""
    target = world.tmp / "work" / "report.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("palabra\n" * 3000, encoding="utf-8")
    entry = {
        "kind": "read",
        "path": str(target),
        "scope": "whole",
        "bytes": target.stat().st_size,
        "range": None,
        "via": "read_whole",
        "read_switch": "on",
        "summarizable": True,
        "decision": "read_whole",
        **extra,
    }
    if session_id is not None:
        entry["session_id"] = session_id
    return entry


def _record(world, entry: dict, env: dict[str, str] | None = None) -> dict:
    hook_entry.record_read(entry, env if env is not None else _request_env(world))
    lines = _lines(world.telemetry)
    assert len(lines) == 1, "record-read wrote no line, or more than one"
    return lines[0]


# --- Hook events: from `transcript_path`, never from the `cwd` ------------------------------------


def _hook_payloads(world, transcript: Path | None) -> list[tuple[str, dict]]:
    small = world.tmp / "work" / "notes.md"
    small.parent.mkdir(parents=True, exist_ok=True)
    small.write_text("hola\n", encoding="utf-8")
    cwd = str(world.tmp / "work" / "local-delegate")
    base: dict = {"session_id": SESSION, "cwd": cwd}
    if transcript is not None:
        base["transcript_path"] = str(transcript)
    return [
        ("suggest_delegate_prompt.py", {**base, "prompt": "hola, ¿qué tal?"}),
        (
            "suggest_delegate_shell.py",
            {**base, "tool_name": "Bash", "tool_input": {"command": "echo hola"}},
        ),
        (
            "suggest_delegate_read.py",
            {**base, "tool_name": "Read", "tool_input": {"file_path": str(small)}},
        ),
    ]


def _run_hook(world, script: str, payload: dict) -> list[dict]:
    """The hook as the settings delivery runs it (`python "<script>"`), with its own process."""
    log = world.tmp / f"hook-{script}.jsonl"
    env = {
        **os.environ,
        "LD_HOOK_TELEMETRY_LOG": str(log),
        "LD_HOOK_READ_ENABLED": "1",
        "LD_HOOK_READ_SWITCH_FILE": str(world.tmp / "block-off"),
    }
    result = subprocess.run(
        [sys.executable, str(HOOKS / script)],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        env=env,
        capture_output=True,
        timeout=TIMEOUT_S,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    lines = _lines(log)
    assert lines, f"{script} wrote no telemetry line, so the test checks nothing"
    return lines


def test_each_hook_event_carries_the_project_of_its_transcript(world):
    transcript = world.root / REPO_DIR / f"{SESSION}.jsonl"  # the rule is lexical: no file needed
    expected = _row_project(transcript)
    assert expected["caller_project_kind"] == "self" and len(expected["caller_project"]) == 16
    for script, payload in _hook_payloads(world, transcript):
        for line in _run_hook(world, script, payload):
            assert line["project_kind"] == "self", script
            assert line["project"] == expected["caller_project"], script


def test_a_hook_event_without_transcript_path_has_no_project_even_with_a_cwd(world):
    for script, payload in _hook_payloads(world, None):
        for line in _run_hook(world, script, payload):
            assert "project" not in line and "project_kind" not in line, script


def test_context_of_takes_an_invalid_transcript_path_as_no_project(world):
    outside = world.tmp / "elsewhere" / REPO_DIR / f"{SESSION}.jsonl"
    context = world.loose.context_of({"session_id": SESSION, "transcript_path": str(outside)}, "x")
    assert context == {"version": "", "session_id": SESSION}


def test_a_rule_that_raises_leaves_the_event_without_project(world, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("rule")

    monkeypatch.setattr(world.loose, "project_identity", broken)
    payload = {"session_id": SESSION, "transcript_path": str(world.root / REPO_DIR / "a.jsonl")}
    assert world.loose.context_of(payload, "x") == {"version": "", "session_id": SESSION}


# --- The mod's line: from `session_id` ------------------------------------------------------------


def test_the_mods_line_carries_the_project_of_its_sessions_row(world):
    transcript = _session(world.root, REPO_DIR)
    line = _record(world, _entry(world))
    expected = _row_project(transcript)
    assert line["project_kind"] == "self"
    assert line["project"] == expected["caller_project"]
    assert line["source"] == "mod"


def test_the_cli_road_writes_the_same_project(world, monkeypatch):
    import io

    transcript = _session(world.root, OTHER_DIR)
    for name, value in _request_env(world).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(world.logs))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_entry(world))))
    assert hook_entry.main(["record-read"]) == 0
    (line,) = _lines(world.telemetry)
    assert line["project_kind"] == "other"
    assert line["project"] == _row_project(transcript)["caller_project"]


@pytest.mark.parametrize(
    "session_id",
    [f"x/../{SESSION}", f"x\\..\\{SESSION}", f"../{SESSION}", "", "sess-1", 7, None],
)
def test_a_session_id_without_uuid_shape_gives_no_project_and_walks_nothing(
    world, monkeypatch, session_id
):
    # Data where an unchecked id WOULD reach a transcript: `<dir>/x/../<id>.jsonl` is the repo's.
    _session(world.root, REPO_DIR)
    (world.root / REPO_DIR / "x").mkdir()
    walked: list = []
    real_scandir = os.scandir
    monkeypatch.setattr(
        world.loose.os, "scandir", lambda p: walked.append(str(p)) or real_scandir(p)
    )
    line = _record(world, _entry(world, session_id=session_id))
    assert "project" not in line and "project_kind" not in line
    assert walked == []


def test_a_session_in_two_directories_gives_no_project(world):
    _session(world.root, REPO_DIR)
    _session(world.root, OTHER_DIR)
    line = _record(world, _entry(world))
    assert "project" not in line and "project_kind" not in line


def test_a_session_that_is_nowhere_gives_no_project(world):
    _session(world.root, REPO_DIR, session="10000000-1d2a-4c5b-8e7f-123456789abc")
    line = _record(world, _entry(world))
    assert "project" not in line and "project_kind" not in line


def test_a_search_that_raises_still_writes_the_line(world, monkeypatch):
    _session(world.root, REPO_DIR)

    def broken(*_args, **_kwargs):
        raise RuntimeError("search")

    monkeypatch.setattr(world.loose, "project_of_session", broken)
    line = _record(world, _entry(world))
    assert line["decision"] == "read_whole"
    assert "project" not in line and "project_kind" not in line


def test_the_salt_and_the_list_come_from_the_process_log_dir(world):
    transcript = _session(world.root, OTHER_DIR)
    env = _request_env(world)
    request_dir = Path(env["LOCAL_DELEGATE_LOG_DIR"])
    # A list in the request's `LOG_DIR` that would mark the session's project as own.
    (request_dir / "self-projects.json").write_text('{"names": ["shop"]}', encoding="utf-8")
    line = _record(world, _entry(world), env)
    assert not (request_dir / "project-salt").exists(), "a request chose where the salt goes"
    assert line["project_kind"] == "other"
    assert line["project"] == _row_project(transcript)["caller_project"]
    assert (world.logs / "project-salt").is_file()


def test_the_projects_root_is_the_process_one_not_the_requests(world):
    transcript = _session(world.root, OTHER_DIR)
    request_home = world.tmp / "request-home"
    _session(request_home / ".claude" / "projects", REPO_DIR)
    env = _request_env(world, HOME=str(request_home), USERPROFILE=str(request_home))
    line = _record(world, _entry(world), env)
    assert line["project_kind"] == "other"
    assert line["project"] == _row_project(transcript)["caller_project"]


class _SlowEntries:
    """`os.scandir` of a root whose entries take `delay_s` each, the session's directory last."""

    def __init__(self, real, last: str, delay_s: float) -> None:
        self._entries = sorted(real, key=lambda e: e.name == last)
        self._delay_s = delay_s

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def __iter__(self):
        for entry in self._entries:
            time.sleep(self._delay_s)
            yield entry


def test_a_slow_search_stops_at_its_budget_and_the_line_has_no_project(world, monkeypatch):
    for letter in "abcdefg":
        (world.root / f"D--work-{letter}").mkdir()
    _session(world.root, REPO_DIR)
    real_scandir = os.scandir

    def slow(path):
        with real_scandir(path) as entries:
            return _SlowEntries(list(entries), REPO_DIR, 0.040)

    hook_entry._load_hook_module("suggest_delegate_read")  # its import is not the search's time
    monkeypatch.setattr(world.loose.os, "scandir", slow)
    start = time.monotonic()
    line = _record(world, _entry(world))
    elapsed = time.monotonic() - start
    assert "project" not in line and "project_kind" not in line
    # Walking all eight entries takes 320 ms; the budget cuts it at the second one (~80 ms).
    assert elapsed < 0.250, f"the search did not stop at its budget ({elapsed:.3f} s)"


def test_a_found_session_is_not_walked_again(world, monkeypatch):
    _session(world.root, REPO_DIR)
    walked: list = []
    real_scandir = os.scandir
    monkeypatch.setattr(
        world.loose.os, "scandir", lambda p: walked.append(str(p)) or real_scandir(p)
    )
    first = _record(world, _entry(world))
    world.telemetry.unlink()
    second = _record(world, _entry(world, decision="dismissed"))
    assert first["project"] == second["project"]
    assert len(walked) == 1, "the second decision of the session walked the root again"


def test_a_session_that_shows_up_later_is_found_the_next_time(world):
    first = _record(world, _entry(world))
    assert "project_kind" not in first
    world.telemetry.unlink()
    _session(world.root, REPO_DIR)
    second = _record(world, _entry(world, decision="dismissed"))
    assert second["project_kind"] == "self"


# --- The daemon road: the variable reaches the LOOSE `hook_common` --------------------------------


def test_the_daemon_endpoint_writes_the_project_into_the_line(world, monkeypatch):
    transcript = _session(world.root, REPO_DIR)
    monkeypatch.setattr(token_source, "daemon_token", lambda: TOKEN)
    client = TestClient(metrics.app, client=LOOPBACK, headers={"Authorization": f"Bearer {TOKEN}"})
    response = client.post(
        "/api/hook/record-read", json={"payload": _entry(world), "env": _request_env(world)}
    )
    assert response.status_code == 204, response.text
    (line,) = _lines(world.telemetry)
    assert line["project_kind"] == "self"
    assert line["project"] == _row_project(transcript)["caller_project"]
