"""Issue #442: only the session that started a delegation sees it at work in the mod's band.

With several Claude Code sessions open, `/api/inflight` listed every session's delegations and the
mod's band read them all as its own. Now the daemon keeps, in each `inflight.json` entry, the
one-way key of the session that asked for it (`caller_session_key`, the same key as the log line;
never the id), and `/api/inflight?session=<id>` marks each entry `mine` and says `mine_count`.
Without `session` the answer is the panel's, as before: the key never leaves the daemon.
"""

from __future__ import annotations

import hashlib
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from local_delegate import attribution, clients, config, server
from local_delegate.resources.hooks import hook_common
from local_delegate.web import metrics

SESSION_A = "session-a-7f31"
SESSION_B = "session-b-02c9"

#: The keys of an entry in `/api/inflight` before #442: the panel's answer must not change.
PANEL_KEYS = {"id", "tool", "model", "source", "chars_in", "backend", "elapsed_s"}


def _key(session_id: str) -> str:
    """The contract, written out here so a test fails on its assert and not on a missing name."""
    return hashlib.sha256(f"local-delegate-session:{session_id}".encode()).hexdigest()[:32]


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    """A log dir of its own, the hook's notes in it, and no transcript root to read."""
    notes = tmp_path / "notes"
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(hook_common, "call_notes_dir", lambda: notes)
    monkeypatch.setattr(attribution, "_projects_root", lambda: tmp_path / "projects")
    metrics._FILE_CACHE.clear()
    return tmp_path, notes


def _start_as(tool_use_id: str | None, tool: str, memory: dict | None = None) -> int:
    """`_inflight_start` inside a request with that `tool_use_id`, as the MCP middleware sets it."""
    t1 = clients._CURRENT_TOOL_USE_ID.set(tool_use_id)
    t2 = clients._REQUEST_MEMORY.set({} if memory is None else memory)
    try:
        return server._inflight_start(tool=tool, model="m", source="inline", chars_in=10)
    finally:
        clients._REQUEST_MEMORY.reset(t2)
        clients._CURRENT_TOOL_USE_ID.reset(t1)


def _inflight(query: str = "") -> dict:
    response = TestClient(metrics.app).get("/api/inflight" + query)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_entry_carries_the_session_key_and_never_the_id(daemon):
    """The use: hook note → `_inflight_start` → `inflight.json` → `/api/inflight?session=`."""
    log_dir, notes = daemon
    assert hook_common.record_call(
        {"tool_use_id": "toolu_a", "transcript_path": "C:/x/a.jsonl", "session_id": SESSION_A},
        notes,
    )
    memory: dict = {}
    entry_id = _start_as("toolu_a", "local_summarize", memory)
    try:
        raw = (log_dir / "inflight.json").read_text(encoding="utf-8")
        (entry,) = json.loads(raw).values()
        assert entry["caller_session_key"] == _key(SESSION_A)
        assert SESSION_A not in raw
        # Only the note is read at the start: the per-request resolution (with the caller's model,
        # which the transcript may not carry yet) is left for the log line.
        assert memory == {}

        mine = _inflight(f"?session={SESSION_A}")
        assert mine["count"] == 1
        assert mine["mine_count"] == 1
        assert mine["inflight"][0]["mine"] is True
        other = _inflight(f"?session={SESSION_B}")
        assert other["count"] == 1
        assert other["mine_count"] == 0
        assert other["inflight"][0]["mine"] is False
        for answer in (mine, other):
            assert "caller_session_key" not in answer["inflight"][0]
    finally:
        server._inflight_end(entry_id)


def test_two_sessions_and_one_unknown_each_own_only_their_entry(daemon):
    log_dir, notes = daemon
    for tool_use_id, session_id in (("toolu_a", SESSION_A), ("toolu_b", SESSION_B)):
        assert hook_common.record_call(
            {
                "tool_use_id": tool_use_id,
                "transcript_path": "C:/x/s.jsonl",
                "session_id": session_id,
            },
            notes,
        )
    ids = [
        _start_as("toolu_a", "local_summarize"),
        _start_as("toolu_b", "local_extract"),
        # A client without the hook (Codex, a script): no note, no session.
        _start_as(None, "local_translate"),
    ]
    try:
        stored = json.loads((log_dir / "inflight.json").read_text(encoding="utf-8")).values()
        assert sorted(e.get("caller_session_key", "") for e in stored) == sorted(
            ["", _key(SESSION_A), _key(SESSION_B)]
        )
        for session_id, tool in ((SESSION_A, "local_summarize"), (SESSION_B, "local_extract")):
            answer = _inflight(f"?session={session_id}")
            assert answer["count"] == 3
            assert answer["mine_count"] == 1
            assert [e["tool"] for e in answer["inflight"] if e["mine"]] == [tool]
        # An unknown session owns nothing, not even the entry without a session.
        nobody = _inflight("?session=session-c")
        assert nobody["mine_count"] == 0
        assert not any(e["mine"] for e in nobody["inflight"])
    finally:
        for entry_id in ids:
            server._inflight_end(entry_id)


def test_without_session_the_answer_is_the_panels_as_before(daemon):
    _log_dir, notes = daemon
    assert hook_common.record_call(
        {"tool_use_id": "toolu_a", "transcript_path": "C:/x/a.jsonl", "session_id": SESSION_A},
        notes,
    )
    entry_id = _start_as("toolu_a", "local_summarize")
    try:
        answer = _inflight()
        assert answer["count"] == 1
        assert "mine_count" not in answer
        assert set(answer["inflight"][0]) == PANEL_KEYS
    finally:
        server._inflight_end(entry_id)


def test_an_entry_from_before_442_has_no_owner(daemon):
    """An `inflight.json` written by an older daemon has no key: it is never taken for one's own."""
    log_dir, _notes = daemon
    entry = {"tool": "local_summarize", "model": "m", "source": "inline", "chars_in": 1}
    entry.update({"started_at": time.time(), "pid": os.getpid(), "backend": "b"})
    (log_dir / "inflight.json").write_text(
        json.dumps({f"{os.getpid()}:9001": entry}), encoding="utf-8"
    )
    answer = _inflight(f"?session={SESSION_A}")
    assert answer["count"] == 1
    assert answer["mine_count"] == 0
    assert answer["inflight"][0]["mine"] is False


def test_a_stale_note_gives_no_session(daemon, monkeypatch):
    _log_dir, notes = daemon
    assert hook_common.record_call(
        {"tool_use_id": "toolu_old", "transcript_path": "C:/x/a.jsonl", "session_id": SESSION_A},
        notes,
    )
    note_path = notes / "toolu_old.json"
    note = json.loads(note_path.read_text(encoding="utf-8"))
    note["ts"] = float(note["ts"]) - attribution.NOTE_TTL_S - 5
    note_path.write_text(json.dumps(note), encoding="utf-8")
    t1 = clients._CURRENT_TOOL_USE_ID.set("toolu_old")
    try:
        assert attribution.current_session_key() is None
    finally:
        clients._CURRENT_TOOL_USE_ID.reset(t1)
