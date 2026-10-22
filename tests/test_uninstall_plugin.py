"""`uninstall` with the plugin delivery: it removes only what the installation state lists.

REQ-007 and REQ-011 (SDD claude-plugin-and-mods, F1-install). A piece that existed before and is
not in the state is not ours and stays.
"""

from __future__ import annotations

import json

from conftest import FakeClaude, make_home

from local_delegate import (
    claude_plugin,
    config,
    desktop_config,
    install,
    install_state,
    plugin_migration,
)
from local_delegate.version import get_version

LD_BIN = "C:/uv/tools/local-delegate-mcp/Scripts/python.exe"
VERSION = get_version()
FOREIGN_ENTRY = {
    "command": "npx",
    "args": ["mcp-remote", "http://127.0.0.1:8765/mcp", "--header", "Authorization: Bearer x"],
}


def _home(tmp_path):
    return make_home(tmp_path, codex=False, opencode=False, complete=False)


def _fake(home, **kwargs):
    kwargs.setdefault("plugin_version", VERSION)
    return FakeClaude(settings_path=home / ".claude" / "settings.json", **kwargs)


def _opts(home, fake, tmp_path, **kwargs):
    kwargs.setdefault("components", set(install.FULL_COMPONENTS))
    return install.Options(
        home=home,
        targets={"claude"},
        python_exe="python",
        use_cli=False,
        claude_runner=fake,
        claude_which=fake.which,
        claude_ld_bin=claude_plugin.LdBin(LD_BIN, None),
        desktop_dir=tmp_path / "appdata",
        desktop_executable=tmp_path / "bin" / "local-delegate.exe",
        # `--desktop` is planned only on Windows: pinned so the test runs on every runner.
        platform="win32",
        **kwargs,
    )


def _run(actions) -> int:
    return install.apply(actions, dry_run=False, out=lambda _line: None)


def _desktop_path(tmp_path):
    return desktop_config.config_path(tmp_path / "appdata")


def test_removes_only_what_state_lists(tmp_path):
    home = _home(tmp_path)
    fake = _fake(home)
    assert _run(install.plan_install(_opts(home, fake, tmp_path, enable_read_hook=True))) == 0
    assert install_state.piece(install_state.load(home), "plugin") is not None

    assert _run(install.plan_uninstall(_opts(home, fake, tmp_path))) == 0

    steps = fake.steps()
    assert "uninstall" in steps
    assert "marketplace_remove" in steps
    assert install_state.load(home) is None
    assert not (config.LOG_DIR / plugin_migration.READ_SWITCH_FILE).exists()


def test_preexisting_piece_not_in_state_is_kept(tmp_path):
    home = _home(tmp_path)
    # The plugin was already there, installed by hand: the state does not list it as ours.
    fake = _fake(home, already_installed=True)
    assert _run(install.plan_install(_opts(home, fake, tmp_path))) == 0
    assert install_state.piece(install_state.load(home), "plugin") is None
    fake.calls.clear()

    assert _run(install.plan_uninstall(_opts(home, fake, tmp_path))) == 0

    assert "uninstall" not in fake.steps()
    assert "marketplace_remove" not in fake.steps()


def test_unknown_state_removes_no_plugin(tmp_path):
    home = _home(tmp_path)
    fake = _fake(home, already_installed=True)

    assert _run(install.plan_uninstall(_opts(home, fake, tmp_path))) == 0

    # No state means unknown, never "ours": nothing of the plugin is touched.
    assert "uninstall" not in fake.steps()


def test_replaced_foreign_desktop_entry_not_restored_and_backup_reported(tmp_path):
    home = _home(tmp_path)
    fake = _fake(home)
    path = _desktop_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {"local-delegate": FOREIGN_ENTRY}}), encoding="utf-8")
    assert _run(install.plan_install(_opts(home, fake, tmp_path, desktop=True))) == 0
    backups = desktop_config.backups(path)
    assert backups

    lines = []
    failures = install.apply(
        install.plan_uninstall(_opts(home, fake, tmp_path)), dry_run=False, out=lines.append
    )

    assert failures == 0
    servers = json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {})
    # Ours is gone and the foreign entry, which could carry a token, is not put back.
    assert "local-delegate" not in servers
    assert any(str(backups[0]) in line for line in lines), lines
