"""plugin_migration: the one orchestration that moves Claude Code from settings to the plugin.

REQ-004 (the read switch survives), REQ-006 (no duplicates, a copy, idempotent) and REQ-008 a/b
(SDD claude-plugin-and-mods, F1-delivery-core). Every test runs in a simulated HOME with an
injected `FakeClaude`; the data directory is the suite's `LOCAL_DELEGATE_LOG_DIR` (conftest).
"""

from __future__ import annotations

import json

import pytest
from conftest import FakeClaude, make_home, snapshot

from local_delegate import claude_plugin, config, install, install_state, plugin_migration

LD_BIN = "C:/uv/tools/local-delegate-mcp/Scripts/python.exe"
VERSION = "0.40.0"
NOW = "2026-10-21T10:00:00Z"
FOREIGN_SAME_EVENT = {"type": "command", "command": "python C:/mine/read_guard.py"}
FOREIGN_OTHER_EVENT = {"type": "command", "command": "node C:/mine/notify.js"}
LEGACY_ENTRY = {
    "type": "command",
    "command": "python",
    "args": ["C:/x/.claude/hooks/anotar_llamada.py"],
}


def _seed(tmp_path, *, read_hook: bool, foreign: bool = False, legacy: bool = False):
    """A 0.39 settings delivery: prompt and record_call always, the read trio when it was on."""
    home = make_home(tmp_path, codex=False, opencode=False)
    claude_dir = home / ".claude"
    hooks_dir = claude_dir / "hooks" / install.HOOKS_SUBDIR
    entries = [
        (event, matcher, install.hook_command(hooks_dir, script, "python"))
        for script, event, matcher in install._HOOK_EVENTS
    ]
    if read_hook:
        for script, event, matcher in (
            install._READ_HOOK,
            install._MCP_READ_HOOK,
            install._SHELL_HOOK,
        ):
            command = install.hook_command(hooks_dir, script, "python", (install.READ_HOOK_FLAG,))
            entries.append((event, matcher, command))
    settings, _ = install.merge_hook_settings({"model": "opus"}, entries, hooks_dir)
    if foreign:
        settings["hooks"]["PreToolUse"].append({"matcher": "Read", "hooks": [FOREIGN_SAME_EVENT]})
        settings["hooks"]["Stop"] = [{"hooks": [FOREIGN_OTHER_EVENT]}]
    if legacy:
        settings["hooks"]["PreToolUse"].append({"matcher": "mcp__.*", "hooks": [LEGACY_ENTRY]})
    # CRLF and a 3-space indent: bytes nobody else would produce, so a copy taken after the CLI
    # rewrote the file cannot pass for the original.
    text = json.dumps(settings, indent=3).replace("\n", "\r\n") + "\r\n"
    (claude_dir / "settings.json").write_bytes(text.encode("utf-8"))
    assert install.read_hook_registered(claude_dir) is read_hook
    return home


def _settings_path(home):
    return home / ".claude" / "settings.json"


def _switch_path():
    return config.LOG_DIR / plugin_migration.READ_SWITCH_FILE


def _switch_data() -> dict:
    """The content of `read-hook.json`, or `{}` when it was not written."""
    path = _switch_path()
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _apply(home, fake, **kwargs):
    return plugin_migration.apply_plugin_delivery(
        home,
        claude_bin=FakeClaude.BIN,
        ld_bin=LD_BIN,
        language="es",
        version=VERSION,
        runner=fake,
        env={"CLAUDE_CONFIG_DIR": str(home / ".claude")},
        now=NOW,
        **kwargs,
    )


def _fake(home, **kwargs):
    kwargs.setdefault("plugin_version", VERSION)
    return FakeClaude(settings_path=_settings_path(home), **kwargs)


def _ours_left(home) -> list[dict]:
    claude_dir = home / ".claude"
    hooks_dir = claude_dir / "hooks" / install.HOOKS_SUBDIR
    settings = json.loads(_settings_path(home).read_text(encoding="utf-8-sig"))
    return [
        hook
        for groups in settings.get("hooks", {}).values()
        for group in groups
        for hook in group.get("hooks", [])
        if install._is_ours(hook, hooks_dir)
    ]


def test_backup_is_pre_install_bytes(tmp_path):
    home = _seed(tmp_path, read_hook=True)
    original = _settings_path(home).read_bytes()
    fake = _fake(home)
    seen_at_marketplace = {}
    backup = home / ".claude" / plugin_migration.BACKUP_NAME
    fake.on_step["marketplace_add"] = lambda: seen_at_marketplace.setdefault(
        "exists", backup.exists()
    )

    result = _apply(home, fake)

    assert result.ok, result.messages
    assert result.backup == backup
    # The copy holds the bytes from before it all, and existed before the first `claude plugin …`.
    assert backup.read_bytes() == original
    assert seen_at_marketplace == {"exists": True}
    # The CLI rewrote settings.json, so from here on JSON is compared, never bytes.
    assert _settings_path(home).read_bytes() != original

    # Only the first time: a second pass does not overwrite the copy with migrated bytes.
    assert _apply(home, fake).ok
    assert backup.read_bytes() == original


def test_migration_carries_read_switch_on(tmp_path):
    home = _seed(tmp_path, read_hook=True)
    assert not _switch_path().exists()

    result = _apply(home, _fake(home))

    assert result.ok, result.messages
    data = _switch_data()
    assert data.get("active") is True
    assert set(data) == {"active", "since"} and data["since"] == NOW
    # …and only then the settings entries are gone.
    assert not install.read_hook_registered(home / ".claude")


def test_migration_carries_read_switch_off(tmp_path):
    home = _seed(tmp_path, read_hook=False)

    result = _apply(home, _fake(home))

    assert result.ok, result.messages
    assert _switch_data() == {"active": False, "since": NOW}


def test_existing_switch_state_never_turned_off(tmp_path):
    home = _seed(tmp_path, read_hook=False)
    before = {"active": True, "since": "2026-09-12T08:00:00Z"}
    _switch_path().write_text(json.dumps(before), encoding="utf-8")

    result = _apply(home, _fake(home))

    assert result.ok, result.messages
    assert _switch_data() == before


def test_migration_refuses_when_switch_cannot_be_written(tmp_path, monkeypatch):
    """B-2: with no data directory the switch would be lost, so nothing is removed."""
    home = _seed(tmp_path, read_hook=True)
    monkeypatch.delenv("LOCAL_DELEGATE_LOG_DIR", raising=False)  # simulated HOME rule
    original = _settings_path(home).read_bytes()
    fake = _fake(home)

    result = _apply(home, fake)

    assert not result.ok and result.failed_step == "read_switch"
    assert fake.calls == []
    assert _settings_path(home).read_bytes() == original


def test_migration_removes_every_settings_hook_we_wrote(tmp_path):
    home = _seed(tmp_path, read_hook=True, legacy=True)
    hooks_dir = home / ".claude" / "hooks" / install.HOOKS_SUBDIR
    assert len(_ours_left(home)) == 6  # guard: there was something to remove
    assert hooks_dir.is_dir()

    result = _apply(home, _fake(home))

    assert result.ok, result.messages
    assert result.removed == 6
    ours_left = _ours_left(home)
    assert ours_left == []
    assert not hooks_dir.exists()
    settings = json.loads(_settings_path(home).read_text(encoding="utf-8-sig"))
    assert "hooks" not in settings  # nothing foreign in there, so the key goes
    assert settings["model"] == "opus"
    assert settings["enabledPlugins"] == {claude_plugin.PLUGIN_ID: True}


def test_migration_keeps_foreign_hooks(tmp_path):
    home = _seed(tmp_path, read_hook=True, foreign=True)

    result = _apply(home, _fake(home))

    assert result.ok, result.messages
    settings = json.loads(_settings_path(home).read_text(encoding="utf-8-sig"))
    hooks = settings.get("hooks", {})
    assert hooks.get("PreToolUse") == [{"matcher": "Read", "hooks": [FOREIGN_SAME_EVENT]}]
    assert hooks.get("Stop") == [{"hooks": [FOREIGN_OTHER_EVENT]}]
    assert set(hooks) == {"PreToolUse", "Stop"}


def test_migration_is_idempotent(tmp_path):
    home = _seed(tmp_path, read_hook=True, foreign=True)
    fake = _fake(home)
    first = _apply(home, fake)
    assert first.ok and first.removed == 5
    state_after_first = install_state.load(home)
    settings_after_first = json.loads(_settings_path(home).read_text(encoding="utf-8-sig"))
    switch_after_first = _switch_path().read_bytes()

    second = _apply(home, fake)

    assert second.ok and second.removed == 0
    assert json.loads(_settings_path(home).read_text(encoding="utf-8-sig")) == settings_after_first
    assert _switch_path().read_bytes() == switch_after_first
    assert install_state.load(home) == state_after_first
    assert install_state.delivery(state_after_first) == claude_plugin.PLUGIN
    assert install_state.piece(state_after_first, "plugin")["id"] == claude_plugin.PLUGIN_ID
    assert install_state.piece(state_after_first, "marketplace") is not None
    # Every `claude plugin …` call carried the simulated config folder.
    assert {env["CLAUDE_CONFIG_DIR"] for _argv, env in fake.calls} == {str(home / ".claude")}


@pytest.mark.parametrize(
    "fake_kwargs",
    [
        {"fail": frozenset({"marketplace_add"})},
        {"fail": frozenset({"install"})},
        {"fail": frozenset({"list"})},
        {"listed": False},
        {"enabled": False},
        {"plugin_version": "0.39.0"},
    ],
    ids=["marketplace", "install", "list", "not_listed", "disabled", "stale_version"],
)
def test_plugin_failure_leaves_settings_untouched(tmp_path, fake_kwargs):
    home = _seed(tmp_path, read_hook=True)
    hooks_dir = home / ".claude" / "hooks" / install.HOOKS_SUBDIR
    before_settings = _settings_path(home).read_bytes()
    before_scripts = snapshot(hooks_dir)
    fake = _fake(home, rewrite_settings=False, **fake_kwargs)

    result = _apply(home, fake)

    assert not result.ok
    assert result.messages  # the user is told why
    assert _settings_path(home).read_bytes() == before_settings
    assert snapshot(hooks_dir) == before_scripts
    assert install_state.delivery(install_state.load(home)) != claude_plugin.PLUGIN
    # The switch was carried anyway: harmless, and the settings hooks read it too.
    assert _switch_data().get("active") is True


def test_mcp_skill_and_memory_untouched(tmp_path):
    home = _seed(tmp_path, read_hook=True)
    claude_dir = home / ".claude"
    watched = {
        "mcp": (home / ".claude.json").read_bytes(),
        "skills": snapshot(claude_dir / "skills"),
        "memory": (claude_dir / "CLAUDE.md").read_bytes(),
    }
    assert all(watched.values())  # guard: the seed has the three pieces

    assert _apply(home, _fake(home)).ok

    assert {
        "mcp": (home / ".claude.json").read_bytes(),
        "skills": snapshot(claude_dir / "skills"),
        "memory": (claude_dir / "CLAUDE.md").read_bytes(),
    } == watched


def test_foreign_plugin_is_not_recorded_as_ours(tmp_path):
    """REQ-007: a piece that existed before and is not in the state is never listed as ours."""
    home = _seed(tmp_path, read_hook=False)
    fake = _fake(home, already_installed=True)

    result = _apply(home, fake)

    assert result.ok, result.messages
    state = install_state.load(home)
    assert install_state.delivery(state) == claude_plugin.PLUGIN
    assert install_state.piece(state, "plugin") is None
    assert install_state.piece(state, "marketplace") is None


def test_revert_to_settings_in_one_step(tmp_path):
    home = _seed(tmp_path, read_hook=True, foreign=True)
    fake = _fake(home)
    assert _apply(home, fake).ok
    restored = []

    def restore_settings(read_hook_enabled: bool) -> None:
        # What install's settings delivery does, reduced to the registration.
        restored.append(read_hook_enabled)
        claude_dir = home / ".claude"
        hooks_dir = claude_dir / "hooks" / install.HOOKS_SUBDIR
        entries = [
            (event, matcher, install.hook_command(hooks_dir, script, "python"))
            for script, event, matcher in install._HOOK_EVENTS
        ]
        if read_hook_enabled:
            script, event, matcher = install._READ_HOOK
            flag = (install.READ_HOOK_FLAG,)
            entries.append(
                (event, matcher, install.hook_command(hooks_dir, script, "python", flag))
            )
        path = claude_dir / "settings.json"
        settings = json.loads(path.read_text(encoding="utf-8-sig"))
        settings, _ = install.merge_hook_settings(settings, entries, hooks_dir)
        path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    fake.calls.clear()
    result = plugin_migration.revert_to_settings(
        home,
        claude_bin=FakeClaude.BIN,
        runner=fake,
        restore_settings=restore_settings,
        env={"CLAUDE_CONFIG_DIR": str(home / ".claude")},
        now=NOW,
    )

    assert result.ok, result.messages
    assert result.delivery == claude_plugin.SETTINGS
    assert fake.steps() == ["uninstall", "marketplace_remove"]
    assert claude_plugin.PLUGIN_ID in fake.calls[0][0]
    assert restored == [True]  # the read switch travelled back to settings
    assert install.read_hook_registered(home / ".claude")
    settings = json.loads(_settings_path(home).read_text(encoding="utf-8-sig"))
    assert settings["hooks"]["Stop"] == [{"hooks": [FOREIGN_OTHER_EVENT]}]
    state = install_state.load(home)
    assert install_state.delivery(state) == claude_plugin.SETTINGS
    assert install_state.piece(state, "plugin") is None
    assert install_state.piece(state, "marketplace") is None


def test_revert_keeps_the_plugin_when_uninstall_fails(tmp_path):
    home = _seed(tmp_path, read_hook=False)
    fake = _fake(home)
    assert _apply(home, fake).ok
    restored = []

    result = plugin_migration.revert_to_settings(
        home,
        claude_bin=FakeClaude.BIN,
        runner=FakeClaude(fail=frozenset({"uninstall"})),
        restore_settings=restored.append,
        now=NOW,
    )

    assert not result.ok and result.failed_step == "uninstall"
    assert restored == []  # no settings hooks on top of a plugin that is still there
    assert install_state.delivery(install_state.load(home)) == claude_plugin.PLUGIN
