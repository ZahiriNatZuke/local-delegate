"""The project in every usage row written at call time (usage-log-project-and-own-repo-exclusion,
REQ-004, REQ-006 and REQ-023).

The log, the notes directory, `LOG_DIR` (salt) and the projects root are all synthetic and live
in `tmp_path`; the backend is a stub of `server._run_chat`.
"""

from __future__ import annotations

import builtins
import io
import json
import os
import time
from pathlib import Path

import pytest

from local_delegate import attribution, cancellation, clients, config, server
from local_delegate.resources.hooks import hook_common

SESSION = "0b9c3f9e-1d2a-4c5b-8e7f-123456789abc"
REPO_DIR = "D--Projects-local-delegate"
OTHER_DIR = "D--work-shop"
OPUS = "claude-opus-5-5"


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Log, notes and projects root in `tmp_path`; a backend that always answers."""
    log = tmp_path / "usage.jsonl"
    notes = tmp_path / "notes"
    root = tmp_path / "home" / ".claude" / "projects"
    (root / REPO_DIR).mkdir(parents=True)
    (root / OTHER_DIR).mkdir(parents=True)
    monkeypatch.setattr(server, "_current_log_path", lambda: log)
    monkeypatch.setattr(hook_common, "call_notes_dir", lambda: notes)
    monkeypatch.setattr(attribution, "_projects_root", lambda: root)

    def run_chat(model, system, user, max_tokens, temperature, **_):
        result = server.ChatResult(text="nota", ok=True, finish_reason="stop")
        return result, 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    return log, notes, root


def _transcript(root: Path, project: str) -> Path:
    path = root / project / f"{SESSION}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("{}\n", encoding="utf-8")
    return path


def _note(notes: Path, tool_use_id: str, transcript: Path, **extra) -> None:
    entry = {
        "session_id": SESSION,
        "transcript_path": str(transcript),
        "cwd": "C:/somewhere",
        "hook_event_name": "PreToolUse",
        "tool_name": "mcp__local-delegate__local_summarize",
        "tool_use_id": tool_use_id,
        **extra,
    }
    assert hook_common.record_call(entry, notes)


def _expected_hash(tmp_path: Path, project: str) -> str:
    """The hash recomputed by hand from the salt on disk (not by the rule under test)."""
    import hashlib

    salt = (tmp_path / "project-salt").read_text(encoding="ascii")
    digest = hashlib.sha256(f"local-delegate-project:{salt}:{project.lower()}".encode())
    return digest.hexdigest()[:16]


def _lines(log: Path) -> list[dict]:
    if not log.is_file():
        return []
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]


def _in_request(tool_use_id: str | None, function):
    t1 = clients._CURRENT_TOOL_USE_ID.set(tool_use_id)
    t2 = clients._REQUEST_MEMORY.set({})
    try:
        return function()
    finally:
        clients._REQUEST_MEMORY.reset(t2)
        clients._CURRENT_TOOL_USE_ID.reset(t1)


def _chat():
    server._chat("m", "sys", "texto de prueba", max_tokens=8, tool="local_summarize")


def _chunked():
    server._chat_chunked(
        "m", "sys", "a b c " * 60, str, tool="local_summarize", source="inline", chunk_chars=120
    )


def _map_reduce():
    server._chat_map_reduce(
        "m",
        "sys",
        "a b c " * 60,
        lambda piece: f"G:{piece}",
        max_chars=120,
        tool="local_summarize",
        source="inline",
        max_words=50,
    )


def _stopped():
    token = cancellation.Token("local_summarize")
    token.entry = {"tool": "local_summarize", "model": "m", "source": "inline", "chars_in": 10}
    server._log_stopped(token, error="exception")


PATHS = {"chat": _chat, "chunked": _chunked, "map_reduce": _map_reduce, "stopped": _stopped}


def _minimal_log() -> None:
    server._log_event(
        tool="local_summarize",
        model="m",
        source="inline",
        chars_in=10,
        chars_out=5,
        latency_ms=1,
        ok=True,
    )


# --- REQ-004 ----------------------------------------------------------------------------------


@pytest.mark.parametrize("path", sorted(PATHS))
@pytest.mark.parametrize("caller", ["main", "subagent", "mod"])
def test_every_path_writes_the_project_of_the_main_session(world, tmp_path, path, caller):
    """Mutant 13 (`resolve_call` does not add the fields): no line carries them."""
    log, notes, root = world
    tool_use_id = {"main": "toolu_main01", "subagent": "toolu_sub01", "mod": "toolu_plugin_m01"}[
        caller
    ]
    extra = {"agent_id": "a1", "agent_type": "general-purpose"} if caller == "subagent" else {}
    _note(notes, tool_use_id, _transcript(root, REPO_DIR), **extra)
    _in_request(tool_use_id, PATHS[path])
    lines = _lines(log)
    assert lines, "guard: the path wrote its line"
    for line in lines:
        assert line.get("tool_use_id") == tool_use_id
        assert line.get("caller_project_kind") == "self"
        assert line.get("caller_project") == _expected_hash(tmp_path, REPO_DIR)


def test_a_subagent_carries_the_hash_of_its_main_session(world, tmp_path):
    """Mutant 14 (the subagent uses its own directory): the subagent's line differs from the main's.

    The subagent's own transcript is `<session>/subagents/agent-<id>.jsonl` inside the same
    project directory, and `project_directory` takes the first directory under the root, so this
    mutant gives the same project: recorded as equivalent in `verification.md`.
    """
    log, notes, root = world
    main = _transcript(root, OTHER_DIR)
    sub = main.with_suffix("") / "subagents" / "agent-a1.jsonl"
    sub.parent.mkdir(parents=True)
    sub.write_text("{}\n", encoding="utf-8")
    _note(notes, "toolu_main02", main)
    _note(notes, "toolu_sub02", main, agent_id="a1", agent_type="general-purpose")
    _in_request("toolu_main02", _minimal_log)
    _in_request("toolu_sub02", _minimal_log)
    main_line, sub_line = _lines(log)
    assert sub_line["caller_kind"] == "subagent"
    assert sub_line["caller_project"] == main_line["caller_project"]
    assert sub_line["caller_project"] == _expected_hash(tmp_path, OTHER_DIR)
    assert sub_line["caller_project_kind"] == "other"


def test_without_tool_use_id_or_note_there_is_no_field(world):
    log, _notes, _root = world
    _minimal_log()
    _in_request("toolu_without_note", _minimal_log)
    for line in _lines(log):
        assert "caller_project" not in line
        assert "caller_project_kind" not in line


def test_a_stale_note_gives_no_field(world):
    """Mutant 15 (sealed even with a stale note)."""
    log, notes, root = world
    _note(notes, "toolu_stale01", _transcript(root, REPO_DIR))
    note_file = notes / "toolu_stale01.json"
    note = json.loads(note_file.read_text(encoding="utf-8"))
    note["ts"] = time.time() - 2 * hook_common.NOTE_TTL_S
    note_file.write_text(json.dumps(note), encoding="utf-8")
    _in_request("toolu_stale01", _minimal_log)
    (line,) = _lines(log)
    assert line.get("tool_use_id") == "toolu_stale01", "guard: the line was written"
    assert not [k for k in line if k.startswith("caller_")]


# --- REQ-006 ----------------------------------------------------------------------------------


def test_a_rule_that_raises_keeps_the_rest_of_the_attribution(world, monkeypatch):
    """Mutant 17 (the rule's own `try` is removed): the line loses every `caller_*`."""
    log, notes, root = world
    _note(notes, "toolu_boom01", _transcript(root, REPO_DIR))

    def blows_up(*_a, **_k):
        raise RuntimeError("project rule broken")

    monkeypatch.setattr(attribution, "project_identity", blows_up)
    _in_request("toolu_boom01", _minimal_log)
    (line,) = _lines(log)
    assert line["caller_kind"] == "main"
    assert line["caller_src"] == "hook"
    assert line["caller_session_key"] == hook_common.session_key(SESSION)
    assert "caller_project" not in line
    assert "caller_project_kind" not in line


class _Touched:
    """Every path `open`, `io.open`, `os.stat`, `os.scandir` and `os.listdir` see."""

    def __init__(self, monkeypatch) -> None:
        self.paths: list[str] = []
        self._monkeypatch = monkeypatch
        self._real = {
            "open": builtins.open,
            "io.open": io.open,
            "stat": os.stat,
            "scandir": os.scandir,
            "listdir": os.listdir,
        }

    def _spy(self, name):
        real = self._real[name]

        def spy(path=".", *args, **kwargs):
            self.paths.append(os.fspath(path) if not isinstance(path, int) else f"fd:{path}")
            return real(path, *args, **kwargs)

        return spy

    def __enter__(self):
        self._monkeypatch.setattr(builtins, "open", self._spy("open"))
        self._monkeypatch.setattr(io, "open", self._spy("io.open"))
        self._monkeypatch.setattr(os, "stat", self._spy("stat"))
        self._monkeypatch.setattr(os, "scandir", self._spy("scandir"))
        self._monkeypatch.setattr(os, "listdir", self._spy("listdir"))
        return self

    def __exit__(self, *_exc):
        for target, name in (
            (builtins, "open"),
            (io, "open"),
            (os, "stat"),
            (os, "scandir"),
            (os, "listdir"),
        ):
            key = "io.open" if target is io else name
            self._monkeypatch.setattr(target, name, self._real[key])


def test_resolving_the_project_touches_no_new_path(world, monkeypatch):
    """Mutant 18 (the rule checks on disk that the project directory exists): the spy sees the
    project directory, which the call never touched before."""
    _log, notes, root = world
    transcript = _transcript(root, REPO_DIR)
    _note(notes, "toolu_spy01", transcript)
    # Salt and list once per process and per path: warm them first.
    warm = attribution.resolve_call("toolu_spy01", notes=notes, projects=root)
    assert warm.get("caller_project_kind") == "self", "guard: the rule ran"

    with _Touched(monkeypatch) as with_rule:
        resolved = attribution.resolve_call("toolu_spy01", notes=notes, projects=root)
    monkeypatch.setattr(attribution, "project_identity", lambda *_a, **_k: {})
    with _Touched(monkeypatch) as without_rule:
        attribution.resolve_call("toolu_spy01", notes=notes, projects=root)

    assert resolved.get("caller_project_kind") == "self"
    assert without_rule.paths, "guard: the spy saw the paths the call touches anyway"
    assert sorted(set(with_rule.paths)) == sorted(set(without_rule.paths))


# --- REQ-023 ----------------------------------------------------------------------------------


def test_a_note_of_an_older_hook_is_enough(world, tmp_path):
    """Mutant 65 (`resolve_call` requires a new field in the note)."""
    log, notes, root = world
    notes.mkdir(parents=True)
    old_note = {
        "tool_use_id": "toolu_old01",
        "ts": time.time(),
        "agent_id": None,
        "agent_type": None,
        "effort": "high",
        "transcript_path": str(_transcript(root, OTHER_DIR)),
        "session_key": hook_common.session_key(SESSION),
    }
    (notes / "toolu_old01.json").write_text(json.dumps(old_note), encoding="utf-8")
    _in_request("toolu_old01", _minimal_log)
    (line,) = _lines(log)
    assert line["caller_project_kind"] == "other"
    assert line["caller_project"] == _expected_hash(tmp_path, OTHER_DIR)
