"""A redirected cp1252 output never brings a CLI command down (SDD retire-legacy-aliases, L11,
REQ-028).

The live re-run of the BOM case after L10 found it: with the output going to a pipe or a file on
Windows (cp1252), `update` on a `settings.json` holding the retired name of `LD_HOOK_READ_BLOCK`
died with `UnicodeEncodeError` on the arrow of the migration description, half-way through the
migration and before registering the hooks. That is how Claude Code, a script or the scheduled task run it.
"""

from __future__ import annotations

import codecs
import io
import json
import os
import subprocess
import sys

import pytest
from conftest import DEAD_PORT, make_home

from local_delegate import config, deprecations, entrypoint, install, server

BOM = codecs.BOM_UTF8
# The real retired variable of the live case, taken from the registry (the old Spanish name only
# lives in `deprecations.py`, by rule of the Spanish-name detector).
NEW = "LD_HOOK_READ_BLOCK"
OLD = next(e.old for e in deprecations.DEPRECATED_NAMES if e.new == NEW)

# Runs the real console entry point; only the daemon probes are sent to the suite's dead port, so
# the subprocess never reaches a real daemon (the same cut the `real_daemon_down` fixture makes).
_BOOTSTRAP = """
import sys
from local_delegate import checks, cli, entrypoint
port = int(sys.argv[1])
cli._daemon_target = lambda: ("127.0.0.1", port, {})
checks._llamaswap_daemon_destination = lambda: ("127.0.0.1", port, {})
sys.argv = ["local-delegate", *sys.argv[2:]]
entrypoint.main()
"""


def _registered(data: dict) -> int:
    return sum(
        1
        for groups in (data.get("hooks") or {}).values()
        for group in groups
        for hook in group.get("hooks", [])
        if install.HOOKS_SUBDIR in hook.get("command", "")
    )


def _seed(tmp_path, *, bom: bool):
    home = make_home(tmp_path, complete=False)
    failures = install.apply(
        install.plan_install(
            install.Options(
                home=home, components={"hooks"}, targets={"claude"}, python_exe="python"
            )
        ),
        dry_run=False,
        out=lambda *_a: None,
    )
    assert failures == 0
    path = home / ".claude" / "settings.json"
    data = json.loads(path.read_bytes().decode("utf-8-sig"))
    data["env"] = {OLD: "1", "OTHER_TOOL_FLAG": "x"}
    data["hooks"] = {}
    payload = json.dumps(data, indent=2).encode("utf-8")
    path.write_bytes((BOM if bom else b"") + payload)
    return home, path


@pytest.mark.parametrize("bom", [True, False], ids=["bom", "no-bom"])
def test_update_finishes_with_the_output_piped_in_cp1252(request, tmp_path, bom):
    home, path = _seed(tmp_path / "h", bom=bom)
    fake_profile = tmp_path / "profile"
    fake_profile.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUTF8"}
    env.update(
        PYTHONIOENCODING="cp1252",
        USERPROFILE=str(fake_profile),
        HOME=str(fake_profile),
        LD_HOOK_TELEMETRY_LOG="",
        LOCAL_DELEGATE_AUTOSTART="0",
        LOCAL_DELEGATE_WEB="0",
    )
    args = ["update", "--home", str(home), "--no-restart", "--version", "0.37.0"]
    proc = subprocess.run(
        [sys.executable, "-c", _BOOTSTRAP, str(request.node.stash[DEAD_PORT]), *args],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=180,
    )
    text = proc.stdout.decode("cp1252", errors="replace")
    errors = proc.stderr.decode("cp1252", errors="replace")

    assert "UnicodeEncodeError" not in errors, errors
    assert proc.returncode == 0, text + errors
    assert f"{OLD} -> {NEW}" in text
    raw = path.read_bytes()
    assert raw.startswith(BOM) is bom
    final = json.loads(raw.decode("utf-8-sig"))
    assert final["env"] == {NEW: "1", "OTHER_TOOL_FLAG": "x"}
    assert _registered(final) == len(install._HOOK_EVENTS)


def test_migration_description_fits_in_cp1252():
    entry = deprecations.DeprecatedName(
        "retired", OLD, NEW, "0.38.0", "0.40.0", retired_from="env_var"
    )
    names = install._names([entry])
    assert names == f"{OLD} -> {NEW}"
    names.encode("cp1252")  # no UnicodeEncodeError


def _cp1252_stream() -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", write_through=True)


def test_cli_branch_replaces_what_the_console_cannot_encode(monkeypatch):
    out, err = _cp1252_stream(), _cp1252_stream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    monkeypatch.setattr(sys, "argv", ["local-delegate", "anything"])

    from local_delegate import cli

    def run(_argv):
        print("a → b")
        print("c ✓ d", file=sys.stderr)
        return 0

    monkeypatch.setattr(cli, "run", run)
    with pytest.raises(SystemExit) as exit_info:
        entrypoint.main()

    assert exit_info.value.code == 0
    assert out.buffer.getvalue() == b"a ? b" + os.linesep.encode()
    assert err.buffer.getvalue() == b"c ? d" + os.linesep.encode()


def test_guard_leaves_utf8_and_explicit_policies_alone(monkeypatch):
    utf8 = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    chosen = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="backslashreplace")
    monkeypatch.setattr(sys, "stdout", utf8)
    monkeypatch.setattr(sys, "stderr", chosen)
    entrypoint._tolerant_console_output()
    assert utf8.errors == "strict"
    assert chosen.errors == "backslashreplace"


def test_guard_survives_streams_that_are_not_text(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", object())
    entrypoint._tolerant_console_output()  # no exception


def test_stdio_server_keeps_the_strict_policy(monkeypatch):
    """Without arguments stdout is the MCP channel: the guard must not touch it."""
    out = _cp1252_stream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", _cp1252_stream())
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(sys, "argv", ["local-delegate"])
    monkeypatch.setattr(config, "AUTOSTART", False)
    monkeypatch.setattr(config, "WEB_ENABLED", False)
    monkeypatch.setattr(server, "prepare_ctrl_break", lambda: None)
    seen: list[tuple[object, str]] = []
    monkeypatch.setattr(server.mcp, "run", lambda *a, **k: seen.append((sys.stdout, out.errors)))

    entrypoint.main()

    assert seen == [(out, "strict")]
