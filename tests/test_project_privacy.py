"""Neither the project's name nor the list of own projects leaves the machine's salt behind
(usage-log-project-and-own-repo-exclusion, REQ-005).

End to end, in one synthetic world: two project directories whose names carry a marker, and a
`self-projects.json` whose one entry is another marker that matches one of them. Every surface the
change touches is written by its real code path and then searched for both markers:

- the usage row written at call time (`server._chat` with the hook's note);
- the backfill (`recompute.run` → `attribution-AAAAMM.json`), by cross and by session key;
- a hook event (the prompt hook run as its own process) and the mod's line (`record_read`);
- the output of `local_status`;
- the answers of `/api/stats`, `/api/events` and `/api/hooks`, with and without a project filter.

Since dashboard-project-filter the name has exactly ONE home on purpose: the local map
`LOG_DIR/project-names.json`, which `/api/stats` serves back as `by_project[].name` (the panel of
this machine shows it). The test checks that the name is there and nowhere else: not in the log,
the backfill, the telemetry, `local_status`, `/api/events`, `/api/hooks` or any other field of
`/api/stats`; and not in a map under the `LOG_DIR` the mod's request names (D12).

Each surface has a guard that it really carries the project (its kind and, where there is one, the
16-hex hash), so an absent marker means "hashed", not "nothing was written". The markers have
letters outside hex, so a hash can never contain them by chance.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import backend_mock
import httpx2
import pytest
from fastapi.testclient import TestClient
from test_transcripts import (
    BASE,
    log_line,
    main_transcript,
    request_entry,
    result_entry,
    write_jsonl,
    write_log,
)

from local_delegate import attribution, clients, config, hook_entry, recompute, server
from local_delegate.resources.hooks import hook_common as package_common
from local_delegate.web import metrics

#: The marker of the other project's directory name.
NAME_MARKER = "Zqx7PrivMark"
#: The marker of the one entry of `self-projects.json`; the own project's directory holds it.
LIST_MARKER = "Wv9ListMark"
MARKERS = (NAME_MARKER.lower(), LIST_MARKER.lower())
SELF_DIR = f"D--work-{LIST_MARKER}"
OTHER_DIR = f"D--work-{NAME_MARKER}"
S_SELF = "5a5a5a5a-1b1b-4c2c-8d3d-0e4e5f6a7b8c"
S_OTHER = "6b6b6b6b-2c2c-4d3d-9e4e-1f5a6b7c8d9e"
HOOKS = Path(config.__file__).parent / "resources" / "hooks"
CACHES = ("_SALTS", "_SELF_ENTRIES", "_SESSION_TRANSCRIPTS")
WIDE_SEARCH_BUDGET_S = 30.0
HEX16 = re.compile(r"^[0-9a-f]{16}$")
OLD_MONTH = "202610"
NOW_OF_BACKFILL = BASE + timedelta(days=1)
TIMEOUT_S = 60


def _assert_no_marker(text: str, where: str) -> None:
    lowered = text.lower()
    for marker in MARKERS:
        assert marker not in lowered, f"{where} carries the marker {marker!r}"


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Process home, projects root, `LOG_DIR` with the list, telemetry and empty caches."""
    home = tmp_path / "home"
    claude = home / ".claude"
    root = claude / "projects"
    root.mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(logs))
    monkeypatch.setattr(config, "LOG_DIR", logs)
    monkeypatch.setattr(config, "USAGE_LOG", logs / "usage.jsonl")
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", True)
    monkeypatch.setattr(config, "COST_FALLBACK", "")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    telemetry = logs / "hooks.jsonl"
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", telemetry)
    (logs / "self-projects.json").write_text(json.dumps({"names": [LIST_MARKER]}), encoding="utf-8")
    loose = hook_entry._load_hook_module("hook_common")
    for module in (loose, package_common):
        for name in CACHES:
            monkeypatch.setattr(module, name, {})
        # A loaded Windows CI runner spends the 50 ms of production on the walk (PR #654).
        monkeypatch.setattr(module, "PROJECT_SEARCH_BUDGET_S", WIDE_SEARCH_BUDGET_S)
    notes = tmp_path / "notes"
    monkeypatch.setattr(package_common, "call_notes_dir", lambda: notes)
    monkeypatch.setattr(attribution, "_projects_root", lambda: root)
    current = logs / f"usage-{datetime.now(UTC):%Y%m}.jsonl"
    monkeypatch.setattr(server, "_current_log_path", lambda: current)

    def run_chat(model, system, user, max_tokens, temperature, **_):
        result = server.ChatResult(text="nota", ok=True, finish_reason="stop")
        return result, 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    metrics._FILE_CACHE.clear()
    yield SimpleNamespace(
        tmp=tmp_path,
        claude=claude,
        root=root,
        logs=logs,
        notes=notes,
        current=current,
        telemetry=telemetry,
    )
    metrics._FILE_CACHE.clear()


def _transcripts(world) -> dict[str, Path]:
    """The two main transcripts, each with one real delegation for the backfill to cross."""
    paths = {}
    for session, project, tool_use_id in (
        (S_SELF, SELF_DIR, "toolu_px_self"),
        (S_OTHER, OTHER_DIR, "toolu_px_other"),
    ):
        paths[session] = write_jsonl(
            main_transcript(world.claude, session=session, project=project),
            [
                request_entry(
                    0,
                    f"r-{session[:4]}",
                    session=session,
                    tool_use=(tool_use_id, "local_summarize", None),
                ),
                result_entry(1, tool_use_id, session=session),
            ],
        )
    return paths


def _delegate_now(world, transcript: Path, session: str, tool_use_id: str) -> None:
    """A delegation at call time: the hook's note, then the tool through `server._chat`."""
    entry = {
        "session_id": session,
        "transcript_path": str(transcript),
        "cwd": "C:/somewhere",
        "hook_event_name": "PreToolUse",
        "tool_name": "mcp__local-delegate__local_summarize",
        "tool_use_id": tool_use_id,
    }
    assert package_common.record_call(entry, world.notes)
    t1 = clients._CURRENT_TOOL_USE_ID.set(tool_use_id)
    t2 = clients._REQUEST_MEMORY.set({})
    try:
        server._chat("m", "sys", "texto de prueba", max_tokens=8, tool="local_summarize")
    finally:
        clients._REQUEST_MEMORY.reset(t2)
        clients._CURRENT_TOOL_USE_ID.reset(t1)


def _lines(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _run_prompt_hook(world, transcript: Path) -> None:
    """The prompt hook as Claude Code runs it, in its own process, into the shared telemetry."""
    env = {**os.environ, "LD_HOOK_TELEMETRY_LOG": str(world.telemetry)}
    payload = {"session_id": S_SELF, "cwd": "C:/somewhere", "transcript_path": str(transcript)}
    payload["prompt"] = "hola, ¿qué tal?"
    result = subprocess.run(
        [sys.executable, str(HOOKS / "suggest_delegate_prompt.py")],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        env=env,
        capture_output=True,
        timeout=TIMEOUT_S,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")


def _record_mod_line(world) -> None:
    """The mod's decision through `hook record-read`, with the environment the mod sends."""
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
        "session_id": S_SELF,
    }
    request_data = world.tmp / "request-data"
    request_data.mkdir(exist_ok=True)
    env = {
        "LOCAL_DELEGATE_LOG_DIR": str(request_data),
        "LD_HOOK_READ_SWITCH_FILE": str(world.tmp / "block-off"),
        "LD_HOOK_READ_ENABLED": "1",
        "LD_HOOK_READ_BLOCK": "1",
        "LD_HOOK_TELEMETRY_LOG": str(world.telemetry),
    }
    hook_entry.record_read(entry, env)


def _backfill(world) -> None:
    """Old rows (an exact cross per project and a mod row by session key), then the backfill."""
    rows = [
        log_line(
            1, tool_use_id="toolu_px_self", caller_session_key=package_common.session_key(S_SELF)
        ),
        log_line(1, tool_use_id="toolu_px_other"),
        log_line(
            30,
            tool_use_id="toolu_plugin_px",
            caller_kind="main",
            caller_session_key=package_common.session_key(S_SELF),
        ),
    ]
    write_log(world.logs, rows, month=OLD_MONTH)
    recompute.run(world.claude, world.logs, now=NOW_OF_BACKFILL)


def _status() -> str:
    backend_mock.get("http://test-backend/v1/models").mock(side_effect=httpx2.ConnectError("down"))
    backend_mock.get("http://test-backend/running").mock(side_effect=httpx2.ConnectError("down"))
    return server.local_status()


def _api(path: str, **params: str) -> tuple[dict, str]:
    metrics._FILE_CACHE.clear()
    response = TestClient(metrics.app).get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json(), response.text


@backend_mock.mock
def test_neither_the_name_nor_the_list_entry_reaches_any_surface(world):
    """Mutants 16 (the field keeps the name) and 16a (a row or an answer keeps the matching list
    entry): the marker shows up in the first surface that carries it."""
    transcripts = _transcripts(world)
    for session in (S_SELF, S_OTHER):  # control: the search does see a marker where there is one
        with pytest.raises(AssertionError):
            _assert_no_marker(str(transcripts[session]), "the transcript path")

    # 1. The usage rows written at call time.
    _delegate_now(world, transcripts[S_SELF], S_SELF, "toolu_now_self")
    _delegate_now(world, transcripts[S_OTHER], S_OTHER, "toolu_now_other")
    rows = _lines(world.current)
    assert {r.get("caller_project_kind") for r in rows} == {"self", "other"}, "guard: both rows"
    for row in rows:
        _assert_no_marker(json.dumps(row), f"the usage row {row.get('tool_use_id')}")
        assert HEX16.match(row.get("caller_project", "")), "guard: the row carries the hash"
    own_hash = next(r["caller_project"] for r in rows if r["caller_project_kind"] == "self")

    # 2. The backfill, by cross and by session key.
    _backfill(world)
    files = sorted(world.logs.glob("attribution-*.json"))
    assert files, "guard: the backfill wrote its file"
    for path in files:
        _assert_no_marker(path.read_text(encoding="utf-8"), path.name)
    entries = attribution.read_backfill(world.logs, OLD_MONTH)
    kinds = sorted(
        e.get("caller_project_kind") for e in entries.values() if e.get("caller_project")
    )
    assert kinds == ["other", "self", "self"], (
        "guard: both crosses and the mod row carry the project"
    )

    # 3. A hook event and the mod's line, in the telemetry the panel reads.
    _run_prompt_hook(world, transcripts[S_SELF])
    _record_mod_line(world)
    events = _lines(world.telemetry)
    assert len(events) == 2, "guard: the hook and the mod each wrote their line"
    _assert_no_marker(world.telemetry.read_text(encoding="utf-8"), "the hook telemetry")
    for event in events:
        assert event.get("project_kind") == "self", "guard: the event carries the kind"
        assert event.get("project") == own_hash, "guard: the event carries the row's hash"

    # 4. `local_status`: no own-repo line any more, and no names.
    status = _status()
    assert "propio repo" not in status and "from this repo" not in status
    _assert_no_marker(status, "local_status")

    # 5. The local map: the one file that holds the names, written in the process's `LOG_DIR`,
    #    never in the one the mod's request named (D12).
    names = package_common.read_project_names(world.logs)
    assert sorted(names.values()) == sorted([SELF_DIR, OTHER_DIR]), "guard: the map has both"
    assert not (world.tmp / "request-data" / "project-names.json").exists()

    # 6. The panel's API, with and without a project filter. The name only comes back as
    #    `by_project[].name` of `/api/stats`, read from the map.
    span = {
        "from": (BASE - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        "to": (datetime.now(UTC) + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }
    stats, _ = _api("/api/stats", **span, lang="es")
    shown = {g["name"] for g in stats["by_project"] if g["name"]}
    assert shown == {SELF_DIR, OTHER_DIR}, "guard: by_project serves the local names"
    rest = {k: v for k, v in stats.items() if k != "by_project"}
    _assert_no_marker(json.dumps(rest), "/api/stats")
    groups = [{k: v for k, v in g.items() if k != "name"} for g in stats["by_project"]]
    _assert_no_marker(json.dumps(groups), "/api/stats by_project")
    for extra in ({}, {"project": own_hash}):
        events_answer, text = _api("/api/events", **span, **extra)
        assert events_answer["events"], "guard: /api/events answered rows"
        _assert_no_marker(text, f"/api/events {extra}")
        hooks_answer, text = _api("/api/hooks", **span, **extra, lang="es")
        assert hooks_answer["total"] >= 1, "guard: the hook events were counted"
        _assert_no_marker(text, f"/api/hooks {extra}")
