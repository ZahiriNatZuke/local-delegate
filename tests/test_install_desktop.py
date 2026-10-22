"""`install --desktop`: the entry of the Claude Desktop chat, pointing at the bridge.

REQ-012 (SDD claude-plugin-and-mods, F1-install). The entry runs `local-delegate desktop-bridge`
by its absolute path; it never carries the token. Windows only.
"""

from __future__ import annotations

import json
import sys

import pytest
from conftest import FakeClaude, make_home

from local_delegate import claude_plugin, cli, desktop_config, install, install_state

LD_BIN = "C:/uv/tools/local-delegate-mcp/Scripts/python.exe"
FOREIGN_ENTRY = {
    "command": "npx",
    "args": ["mcp-remote", "http://127.0.0.1:8765/mcp", "--header", "Authorization: Bearer x"],
}


def _home(tmp_path):
    return make_home(tmp_path, codex=False, opencode=False, complete=False)


def _opts(home, tmp_path, **kwargs):
    fake = FakeClaude(present=False)
    return install.Options(
        home=home,
        targets={"claude"},
        components={"mcp"},
        python_exe="python",
        use_cli=False,
        claude_runner=fake,
        claude_which=fake.which,
        claude_ld_bin=claude_plugin.LdBin(LD_BIN, None),
        desktop_dir=tmp_path / "appdata",
        desktop_executable=tmp_path / "bin" / "local-delegate.exe",
        platform="win32",
        **kwargs,
    )


def _servers(tmp_path) -> dict:
    path = desktop_config.config_path(tmp_path / "appdata")
    return json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {})


def _run(actions, lines=None) -> int:
    sink = lines.append if lines is not None else (lambda _line: None)
    return install.apply(actions, dry_run=False, out=sink)


def test_desktop_flag_writes_bridge_entry(tmp_path):
    home = _home(tmp_path)

    assert _run(install.plan_install(_opts(home, tmp_path, desktop=True))) == 0

    entry = _servers(tmp_path)["local-delegate"]
    assert entry == {
        "command": str(tmp_path / "bin" / "local-delegate.exe"),
        "args": ["desktop-bridge"],
    }
    assert "env" not in entry
    piece = install_state.piece(install_state.load(home), "desktop_entry")
    assert piece is not None and piece.get("replaced_foreign") is False


def test_without_flag_desktop_is_not_touched(tmp_path):
    home = _home(tmp_path)

    assert _run(install.plan_install(_opts(home, tmp_path))) == 0

    assert not desktop_config.config_path(tmp_path / "appdata").exists()


def test_replaces_foreign_entry_only_with_flag_and_warns(tmp_path):
    home = _home(tmp_path)
    path = desktop_config.config_path(tmp_path / "appdata")
    path.parent.mkdir(parents=True)
    original = {"mcpServers": {"local-delegate": FOREIGN_ENTRY, "other": {"command": "x"}}}
    path.write_text(json.dumps(original), encoding="utf-8")

    # Without the flag the foreign entry stays as it was.
    assert _run(install.plan_install(_opts(home, tmp_path))) == 0
    assert _servers(tmp_path) == original["mcpServers"]

    lines = []
    assert _run(install.plan_install(_opts(home, tmp_path, desktop=True)), lines) == 0

    servers = _servers(tmp_path)
    assert servers["local-delegate"]["args"] == ["desktop-bridge"]
    assert servers["other"] == {"command": "x"}
    backups = desktop_config.backups(path)
    assert backups
    assert any(str(backups[0]) in line for line in lines), lines
    piece = install_state.piece(install_state.load(home), "desktop_entry")
    assert piece["replaced_foreign"] is True


def test_desktop_flag_on_macos_refuses_cleanly(tmp_path, monkeypatch, capsys):
    home = _home(tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")

    code = cli.run(["install", "--home", str(home), "--clients", "claude", "--desktop"])

    assert code == 2
    err = capsys.readouterr().err
    assert "--desktop" in err
    # It refused before writing anything: no settings, no state.
    assert not (home / ".claude" / "settings.json").exists()
    assert install_state.load(home) is None


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_desktop_action_is_not_planned_off_windows(tmp_path, platform):
    home = _home(tmp_path)
    opts = _opts(home, tmp_path, desktop=True)
    opts.platform = platform

    assert "desktop" not in [action.kind for action in install.plan_install(opts)]
