"""A mod decision that could not be written is not reported as written (SDD mod-decision-record-lost).

Security review of 2026-10-23: `hook_common.record` swallowed the `OSError` of an unwritable
`LD_HOOK_TELEMETRY_LOG`, so `POST /api/hook/record-read` answered 204 and
`python -I -m local_delegate.hook record-read` exited 0. The mod took both as written and neither
retried the decision nor logged `ModRecordLost`: the line was lost without a trace. Promises:

- on the `record-read` road a write error reaches the caller: 500 from the daemon, exit 1 from the
  CLI, and the `hook-failures.jsonl` line names the decision and the via (never the path);
- a normal hook of `hooks.json` keeps its best-effort telemetry: same broken destination, exit 0;
- a successful `record-read`, or one with nothing to write, still answers 204 / exit 0.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from local_delegate import config, hook_entry, token_source
from local_delegate.web import metrics

TOKEN = "record-lost-token"
RECORD = "/api/hook/record-read"
LOOPBACK = ("127.0.0.1", 50000)
TIMEOUT_S = 60


def _env(base: Path, destination: Path) -> dict[str, str]:
    """What the mod sends (`RECORD_ENV`), with its own data folder and destination."""
    data = base / "data"
    data.mkdir(parents=True, exist_ok=True)
    return {
        "LOCAL_DELEGATE_LOG_DIR": str(data),
        "LD_HOOK_READ_SWITCH_FILE": str(base / "block-off"),
        "LD_HOOK_READ_ENABLED": "1",
        "LD_HOOK_READ_BLOCK": "1",
        "LD_HOOK_TELEMETRY_LOG": str(destination),
    }


def _broken_destination(base: Path) -> Path:
    """A destination that cannot be opened for append: a folder with the log's name."""
    target = base / "telemetry.jsonl"
    target.mkdir(parents=True)
    return target


def _entry(base: Path, decision: str = "summarized", via: str = "read_whole") -> dict:
    prose = base / "docs" / "report.md"
    prose.parent.mkdir(parents=True, exist_ok=True)
    prose.write_text("palabra\n" * 3000, encoding="utf-8")
    return {
        "kind": "read",
        "path": str(prose),
        "scope": "whole",
        "bytes": prose.stat().st_size,
        "range": None,
        "via": via,
        "read_switch": "on",
        "summarizable": True,
        "decision": decision,
        "session_id": "sess-lost",
    }


def _failures(base: Path) -> list[dict]:
    path = base / "data" / hook_entry.FAILURE_LOG
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _process_env(base: Path, destination: Path) -> dict[str, str]:
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in config.ENVIRONMENT_VARIABLES
        and name not in hook_entry.RECORD_ENV
        and name not in {"PYTHONUTF8", "PYTHONIOENCODING", "PYTHONPATH"}
    }
    tmp = base / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    env.update({"TMP": str(tmp), "TEMP": str(tmp), "TMPDIR": str(tmp)})
    env.update(_env(base, destination))
    return env


def _process(base: Path, name: str, stdin: bytes, destination: Path):
    env = _process_env(base, destination)
    return subprocess.run(
        [sys.executable, "-I", "-m", "local_delegate.hook", name],
        input=stdin,
        capture_output=True,
        env=env,
        timeout=TIMEOUT_S,
        cwd=env["TMP"],
    )


def _in_process(monkeypatch, entry_text: str, env: dict[str, str]) -> int:
    for name in hook_entry.RECORD_ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(sys, "stdin", io.StringIO(entry_text))
    return hook_entry.main(["record-read"])


# --- `record` itself ------------------------------------------------------------------------------


def test_record_ignores_outside_record_or_raise_and_raises_inside(tmp_path, monkeypatch):
    common = hook_entry._load_hook_module("hook_common")
    destination = _broken_destination(tmp_path)
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(destination))
    monkeypatch.delenv("LD_HOOK_ENABLED", raising=False)

    # A normal hook: best effort, as before.
    assert common.record("PreToolUse", suggested=False) is None
    with pytest.raises(OSError):
        common.record_or_raise(common.record, "PreToolUse")
    # The strict mode does not leak out of `record_or_raise`.
    assert common.record("PreToolUse", suggested=False) is None


# --- The CLI road ---------------------------------------------------------------------------------


def test_cli_in_process_reports_a_lost_line(tmp_path, monkeypatch):
    entry = _entry(tmp_path)
    env = _env(tmp_path, _broken_destination(tmp_path))

    assert _in_process(monkeypatch, json.dumps(entry), env) == 1
    failures = _failures(tmp_path)
    assert len(failures) == 1, failures
    line = failures[0]
    assert (line["hook"], line["decision"], line["via"]) == (
        "record-read",
        "summarized",
        "read_whole",
    )
    assert line["error"] in {"PermissionError", "IsADirectoryError", "OSError"}
    # Never the path or the message.
    assert str(tmp_path) not in json.dumps(line)


def test_cli_in_process_still_succeeds_when_written(tmp_path, monkeypatch):
    log = tmp_path / "telemetry.jsonl"
    assert _in_process(monkeypatch, json.dumps(_entry(tmp_path)), _env(tmp_path, log)) == 0
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1
    assert _failures(tmp_path) == []


def test_failure_line_keeps_only_short_names(tmp_path, monkeypatch):
    entry = _entry(tmp_path, decision="Weird Decision/../x", via="C:\\secret\\path")
    assert (
        _in_process(monkeypatch, json.dumps(entry), _env(tmp_path, _broken_destination(tmp_path)))
        == 1
    )
    (line,) = _failures(tmp_path)
    assert (line["decision"], line["via"]) == ("other", "other")


def test_real_process_exit_codes(tmp_path):
    """As the mod launches it (`runLd`): exit 1 for a line not written or a broken input."""
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    broken = tmp_path / "broken"
    entry = json.dumps(_entry(tmp_path)).encode("utf-8")

    written = _process(good, "record-read", entry, good / "telemetry.jsonl")
    lost = _process(bad, "record-read", entry, _broken_destination(bad))
    garbled = _process(broken, "record-read", b'{"payload": roto', broken / "telemetry.jsonl")

    assert written.returncode == 0, written.stderr
    assert len((good / "telemetry.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    assert lost.returncode == 1, lost.stderr
    assert [line["decision"] for line in _failures(bad)] == ["summarized"]
    assert garbled.returncode == 1, garbled.stderr
    assert [line["error"] for line in _failures(broken)] == ["JSONDecodeError"]
    # A broken input has no decision to name.
    assert "decision" not in _failures(broken)[0]


def test_a_normal_hook_with_the_same_broken_destination_exits_zero(tmp_path):
    payload = json.dumps({"session_id": "s", "prompt": "resume esto"}).encode("utf-8")
    result = _process(tmp_path, "prompt", payload, _broken_destination(tmp_path))
    assert result.returncode == 0, result.stderr
    # `record` swallowed the write error inside the hook: had it raised, `main` would have
    # caught it and left a failure line.
    assert _failures(tmp_path) == []


def test_a_trailing_newline_is_not_a_short_name(tmp_path, monkeypatch):
    entry = _entry(tmp_path, decision="summarized\n")
    destination = _broken_destination(tmp_path)
    assert _in_process(monkeypatch, json.dumps(entry), _env(tmp_path, destination)) == 1
    (line,) = _failures(tmp_path)
    assert line["decision"] == "other"


def test_a_failed_classify_exits_one_and_leaves_a_failure_line(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(tmp_path / "data"))

    def boom(args):
        raise RuntimeError("classifier broke")

    monkeypatch.setattr(hook_entry, "_classify", boom)
    assert hook_entry.main(["classify"]) == 1
    (line,) = _failures(tmp_path)
    assert (line["hook"], line["error"]) == ("classify", "RuntimeError")
    assert "decision" not in line


# --- The daemon road ------------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(token_source, "daemon_token", lambda: TOKEN)
    return TestClient(metrics.app, client=LOOPBACK, headers={"Authorization": f"Bearer {TOKEN}"})


def test_endpoint_answers_500_when_the_line_is_not_written(tmp_path, monkeypatch, client):
    destination = _broken_destination(tmp_path)
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", destination)
    # `_log_failure` writes where the daemon logs (its own environment).
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(tmp_path / "data"))
    env = _env(tmp_path, destination)

    response = client.post(RECORD, json={"payload": _entry(tmp_path), "env": env})

    assert response.status_code == 500, response.text
    (line,) = _failures(tmp_path)
    assert (line["hook"], line["decision"]) == ("record-read", "summarized")


def test_endpoint_still_answers_204_when_written(tmp_path, monkeypatch, client):
    log = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", log)
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(tmp_path / "data"))
    response = client.post(RECORD, json={"payload": _entry(tmp_path), "env": _env(tmp_path, log)})
    assert response.status_code == 204, response.text
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1
    assert _failures(tmp_path) == []
