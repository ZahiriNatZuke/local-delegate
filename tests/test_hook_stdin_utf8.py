"""The hooks of the settings delivery read and write UTF-8 whatever the system code page.

Claude Code writes the hook input in UTF-8. With the settings delivery the hook runs as
`python "<script>"`, and on Windows that interpreter opens its pipes in cp1252: a path with `ñ`
arrived as `Ã±`, the read hook lost the file and went quiet (no block, no telemetry); `diseño` in a
prompt stopped matching the host-only rule; a byte with no cp1252 character (`Á` = C3 81) broke
`json.load`. `PYTHONIOENCODING=cp1252` reproduces that code page on any system, so these tests
discriminate on Linux CI too.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from local_delegate import config

ROOT = Path(__file__).parents[1]
HOOKS = ROOT / "src" / "local_delegate" / "resources" / "hooks"
TIMEOUT_S = 60


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


common = _load("_utf8_hook_common", HOOKS / "hook_common.py")


def _env(base: Path) -> dict[str, str]:
    tmp = base / "tmp"
    data = base / "data"
    for folder in (tmp, data):
        folder.mkdir(parents=True, exist_ok=True)
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in config.ENVIRONMENT_VARIABLES
        and name not in {"PYTHONUTF8", "PYTHONPATH"}
        and not name.startswith("CLAUDE_PLUGIN")
    }
    env.update(
        {
            # The Windows ANSI code page, on any system.
            "PYTHONIOENCODING": "cp1252",
            "PYTHONUTF8": "0",
            "TMP": str(tmp),
            "TEMP": str(tmp),
            "TMPDIR": str(tmp),
            "LOCAL_DELEGATE_LOG_DIR": str(data),
            "LOCAL_DELEGATE_LANG": "es",
            "LD_HOOK_TELEMETRY_LOG": str(base / "telemetry.jsonl"),
            "LD_HOOK_READ_SWITCH_FILE": str(base / "block-off"),
            "LD_HOOK_READ_ENABLED": "1",
            "LD_HOOK_READ_BLOCK": "1",
        }
    )
    # A fresh health mark: the hook decides without probing the network.
    marker = tmp / common._health_path().name
    marker.write_text(json.dumps({"ts": time.time(), "ok": True}), encoding="utf-8")
    return env


def _run(script: str, payload: dict, env: dict[str, str]) -> bytes:
    """The hook as the settings entry runs it: the script by path, the input as UTF-8 bytes."""
    result = subprocess.run(
        [sys.executable, str(HOOKS / script), "--enabled"],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        env=env,
        capture_output=True,
        timeout=TIMEOUT_S,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout


def _telemetry(base: Path) -> list[dict]:
    log = base / "telemetry.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


def _prose(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(("Párrafo de prosa con tildes y eñes. " * 40 + "\n") * 25, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "folder", ["ñandú", "Ácido"], ids=["latin-letters", "letter-outside-cp1252"]
)
def test_read_hook_finds_a_file_with_a_non_ascii_path(tmp_path, folder):
    document = _prose(tmp_path / folder / "report.md")
    env = _env(tmp_path)
    payload = {"session_id": "s1", "tool_name": "Read", "tool_input": {"file_path": str(document)}}

    stdout = _run("suggest_delegate_read.py", payload, env)

    lines = _telemetry(tmp_path)
    assert len(lines) == 1, "the hook went quiet: no telemetry line for the read"
    assert lines[0]["path_sha"] == common.path_digest(str(document))
    assert lines[0]["size_kb"] > 8
    # Whatever it says, it says it in UTF-8, with the path as the user wrote it.
    text = stdout.decode("utf-8")
    if text:
        reason = json.loads(text)["hookSpecificOutput"].get("permissionDecisionReason", "")
        assert document.as_posix() in reason.replace("\\", "/") or str(document) in reason


def test_read_hook_records_why_it_stops_when_the_file_is_missing(tmp_path):
    env = _env(tmp_path)
    missing = tmp_path / "ñandú" / "missing.md"
    payload = {"session_id": "s1", "tool_name": "Read", "tool_input": {"file_path": str(missing)}}

    assert _run("suggest_delegate_read.py", payload, env) == b""

    lines = _telemetry(tmp_path)
    assert [line.get("reason") for line in lines] == ["no_file"]
    assert lines[0]["suggested"] is False
    assert lines[0]["path_sha"] == common.path_digest(str(missing))


def test_prompt_hook_reads_accented_words_of_the_host_only_rule(tmp_path):
    env = _env(tmp_path)

    stdout = _run("suggest_delegate_prompt.py", {"prompt": "Resume el diseño del panel"}, env)

    assert stdout == b"", "«diseño» is host-only work: the hook must not suggest delegating"
    lines = _telemetry(tmp_path)
    assert len(lines) == 1 and lines[0]["suggested"] is False


def test_prompt_hook_survives_a_letter_outside_cp1252(tmp_path):
    env = _env(tmp_path)

    _run("suggest_delegate_prompt.py", {"prompt": "Resume el Ánálisis del informe"}, env)

    lines = _telemetry(tmp_path)
    assert len(lines) == 1, "json.load failed on the input and the hook went quiet"
    assert lines[0]["prompt_chars"] == len("Resume el Ánálisis del informe")


# --- utf8_stdio on its own ---------------------------------------------------------------------


def test_utf8_stdio_switches_a_cp1252_pipe_to_utf8(monkeypatch):
    raw = "Resume el diseño".encode()
    stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="cp1252")
    out_bytes = io.BytesIO()
    stdout = io.TextIOWrapper(out_bytes, encoding="cp1252")
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    common.utf8_stdio()
    read = sys.stdin.read()
    sys.stdout.write("ñ→")
    sys.stdout.flush()

    assert read == "Resume el diseño"
    assert out_bytes.getvalue().decode("utf-8") == "ñ→"


def test_utf8_stdio_leaves_streams_without_reconfigure_alone(monkeypatch):
    stdin = io.StringIO('{"prompt": "diseño"}')
    monkeypatch.setattr(sys, "stdin", stdin)

    common.utf8_stdio()

    assert sys.stdin is stdin
    assert json.load(sys.stdin) == {"prompt": "diseño"}
