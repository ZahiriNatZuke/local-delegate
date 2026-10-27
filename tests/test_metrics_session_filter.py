"""REQ-017 (SDD claude-plugin-and-mods, F3-status): the savings of ONE session for the status line.

The mod's status line asks `/api/stats?session=<id>` for the savings of its own session. For that,
each log line has to say which session asked for it, and REQ-003/REQ-072 of `coste-api-y-cuota`
forbid the session id in the line. The chain keeps that rule: the `record-call` hook stores in its
note a one-way key of the session (`hook_common.session_key`), the daemon copies the key to the
line as `caller_session_key`, and `/api/stats` hashes the `session` it receives the same way. The
raw id never reaches the note or the log.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from local_delegate import attribution, clients, config, server
from local_delegate.resources.hooks import hook_common
from local_delegate.web import metrics

HOOK = Path(hook_common.__file__).parent / "record_call.py"
OPUS = "claude-opus-5-5"


def _key(session_id: str) -> str:
    """The contract, written out here so a test fails on its assert and not on a missing name."""
    return hashlib.sha256(f"local-delegate-session:{session_id}".encode()).hexdigest()[:32]


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _stats(query: str) -> dict:
    response = TestClient(metrics.app).get(
        "/api/stats?from=2026-07-01T00:00:00%2B00:00&to=2026-08-01T00:00:00%2B00:00" + query
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_stats_filters_by_session(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    base = {"tool": "local_summarize", "model": "m", "source": "path", "chars_out": 10, "ok": True}
    _write_jsonl(
        tmp_path / "usage-202607.jsonl",
        [
            {
                **base,
                "ts": "2026-07-20T10:00:00+00:00",
                "chars_in": 4000,
                "caller_session_key": _key("sess-a"),
            },
            {
                **base,
                "ts": "2026-07-20T11:00:00+00:00",
                "chars_in": 8000,
                "caller_session_key": _key("sess-a"),
            },
            {
                **base,
                "ts": "2026-07-20T12:00:00+00:00",
                "chars_in": 2000,
                "caller_session_key": _key("sess-b"),
            },
            # A line from before this change, or from a client without the hook: no session.
            {**base, "ts": "2026-07-20T13:00:00+00:00", "chars_in": 1000},
        ],
    )
    metrics._FILE_CACHE.clear()

    everything = _stats("")
    assert everything["total"]["calls"] == 4

    only_a = _stats("&session=sess-a")
    assert only_a["total"]["calls"] == 2
    # The savings are those of the two lines of the session, not of the range.
    assert only_a["tokens_context_saved"] == 4000 * 100 // 241 + 8000 * 100 // 241
    assert 0 < only_a["tokens_context_net"] < everything["tokens_context_net"]

    assert _stats("&session=sess-b")["total"]["calls"] == 1
    # A session that delegated nothing: zero, never the whole range.
    assert _stats("&session=sess-none")["total"]["calls"] == 0
    # An empty parameter is no filter (the panel never sends it, the mod always fills it).
    assert _stats("&session=")["total"]["calls"] == 4


def test_connection_failures_spend_no_backend_call(tmp_path, monkeypatch):
    """Issue #436, the session as the Mac logged it: 2 delegations that answered, 14 attempts with
    the backend's name unresolved (`connection_failure: dns`) and one `capacity_or_load` failure.
    The mod shows `total.calls - total.errors` as delegations; the DNS failures spend no call."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    key = _key("sess-down")
    base = {"tool": "local_summarize", "model": "m", "source": "path", "caller_session_key": key}
    ok = {**base, "ok": True, "chars_in": 4000, "chars_out": 10, "tokens_in": 1100}
    dns = {
        **base,
        "ok": False,
        "chars_in": 4000,
        "chars_out": 144,
        "latency_ms": 22,
        "error": "connect_error",
        "error_class": "endpoint",
        "connection_failure": "dns",
    }
    load = {**base, "ok": False, "chars_in": 4000, "error": "http_503"}
    load["error_class"] = "capacity_or_load"
    rows = [{**ok, "ts": "2026-07-20T10:00:00+00:00"}, {**ok, "ts": "2026-07-20T10:01:00+00:00"}]
    rows += [{**dns, "ts": f"2026-07-20T11:{minute:02d}:00+00:00"} for minute in range(14)]
    # A split delegation that lost the backend on its third chunk: the two chunks before it
    # did reach the backend (`chunks` counts the real calls), so those two still count.
    rows.append({**dns, "ts": "2026-07-20T12:00:00+00:00", "chunks": 2})
    rows.append({**load, "ts": "2026-07-20T13:00:00+00:00"})
    _write_jsonl(tmp_path / "usage-202607.jsonl", rows)
    metrics._FILE_CACHE.clear()

    stats = _stats("&session=sess-down")
    total = stats["total"]
    # Guard: every line reached the aggregate, so a zero below means something.
    assert total["calls"] == 18
    assert total["errors"] == 16
    # What the band shows as delegations: the two that answered.
    assert total["calls"] - total["errors"] == 2
    assert total["connection_failures"] == 15
    # 2 answered + 2 chunks before the drop + 1 for the overloaded backend; the 14 DNS ones, 0.
    assert stats["backend_calls"] == 5
    assert total["backend_calls"] == 5


def _hook_env(tmp_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update({"TEMP": str(tmp_dir), "TMP": str(tmp_dir), "TMPDIR": str(tmp_dir)})
    return env


def test_record_call_stores_session_id(tmp_path):
    """The hook (a process apart, as Claude Code runs it) keeps the session as its key, never raw."""
    marker = "session-marker-5c1e"
    entry = {
        "session_id": marker,
        "transcript_path": "C:/x/other.jsonl",
        "cwd": "C:/proyecto",
        "hook_event_name": "PreToolUse",
        "tool_name": "mcp__local-delegate__local_summarize",
        "tool_use_id": "toolu_session",
    }
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(entry).encode("utf-8"),
        env=_hook_env(tmp_path),
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    note_path = tmp_path / "local-delegate-calls" / "toolu_session.json"
    assert note_path.is_file(), "the hook left no note"
    note = json.loads(note_path.read_text(encoding="utf-8"))
    assert note.get("session_key") == _key(marker)
    # REQ-072 of coste-api-y-cuota: the raw id stays out of the note.
    assert "session_id" not in note
    assert marker not in note_path.read_text(encoding="utf-8")


def test_without_session_id_the_note_has_no_key(tmp_path):
    entry = {"tool_use_id": "toolu_no_session", "transcript_path": "C:/x/s.jsonl"}
    assert hook_common.record_call(entry, tmp_path)
    note = json.loads((tmp_path / "toolu_no_session.json").read_text(encoding="utf-8"))
    assert note.get("session_key") is None


@pytest.fixture
def log_and_notes(tmp_path, monkeypatch):
    log = tmp_path / "usage.jsonl"
    notes = tmp_path / "notes"
    root = tmp_path / "home" / ".claude" / "projects"
    (root / "D--proyecto").mkdir(parents=True)
    monkeypatch.setattr(server, "_current_log_path", lambda: log)
    monkeypatch.setattr(hook_common, "call_notes_dir", lambda: notes)
    monkeypatch.setattr(attribution, "_projects_root", lambda: root)
    return log, notes, root


def test_the_log_line_carries_the_session_key_and_never_the_id(log_and_notes):
    """The use, not the piece: hook note → daemon's log line → `/api/stats?session=`."""
    log, notes, root = log_and_notes
    marker = "session-marker-9d2b"
    transcript = root / "D--proyecto" / f"{marker}.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    assert hook_common.record_call(
        {"tool_use_id": "toolu_line", "transcript_path": str(transcript), "session_id": marker},
        notes,
    )
    t1 = clients._CURRENT_TOOL_USE_ID.set("toolu_line")
    t2 = clients._REQUEST_MEMORY.set({})
    try:
        server._log_event(
            tool="local_summarize",
            model="m",
            source="inline",
            chars_in=10,
            chars_out=5,
            latency_ms=1,
            ok=True,
        )
    finally:
        clients._REQUEST_MEMORY.reset(t2)
        clients._CURRENT_TOOL_USE_ID.reset(t1)
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 1
    assert lines[0].get("caller_session_key") == _key(marker)
    assert marker not in json.dumps(lines[0])
    # The daemon matches it the same way it hashes the mod's `session`.
    assert metrics._session_matches(lines[0], marker)
    assert not metrics._session_matches(lines[0], "another-session")
