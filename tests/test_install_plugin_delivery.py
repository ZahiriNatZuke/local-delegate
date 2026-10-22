"""`install` and the Claude Code delivery: plugin by default, settings as the fallback.

REQ-005, REQ-006 and REQ-008 b (SDD claude-plugin-and-mods, F1-install). `install` decides the
delivery with `claude_plugin.decide` and carries it out with `plugin_migration`; it does not
repeat any step of its own. Every test runs in a simulated HOME with an injected `FakeClaude`.
"""

from __future__ import annotations

import json

from conftest import FakeClaude, make_home

from local_delegate import claude_plugin, config, install, install_state, plugin_migration
from local_delegate.version import get_version

LD_BIN = "C:/uv/tools/local-delegate-mcp/Scripts/python.exe"
VERSION = get_version()


def _home(tmp_path):
    return make_home(tmp_path, codex=False, opencode=False, complete=False)


def _fake(home, **kwargs):
    kwargs.setdefault("plugin_version", VERSION)
    return FakeClaude(settings_path=home / ".claude" / "settings.json", **kwargs)


def _opts(home, fake, **kwargs):
    kwargs.setdefault("components", {"hooks"})
    return install.Options(
        home=home,
        targets={"claude"},
        python_exe="python",
        claude_runner=fake,
        claude_which=fake.which,
        claude_ld_bin=claude_plugin.LdBin(LD_BIN, None),
        **kwargs,
    )


def _switch() -> dict:
    path = config.LOG_DIR / plugin_migration.READ_SWITCH_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _kinds(actions) -> list[str]:
    return [action.kind for action in actions]


def test_default_is_plugin_when_cli_new_enough(tmp_path):
    home = _home(tmp_path)
    fake = _fake(home)

    actions = install.plan_install(_opts(home, fake))

    assert "plugin" in _kinds(actions)
    # The settings delivery is not planned next to it: that would be the duplicates of REQ-006.
    assert "settings" not in _kinds(actions)
    assert install.apply(actions, dry_run=False, out=lambda _line: None) == 0
    assert fake.steps()[-1] == "list"
    state = install_state.load(home)
    assert install_state.delivery(state) == claude_plugin.PLUGIN
    assert not (home / ".claude" / "hooks" / install.HOOKS_SUBDIR).exists()


def test_falls_back_to_settings_with_warning(tmp_path):
    home = _home(tmp_path)
    fake = _fake(home, version="2.1.200")

    actions = install.plan_install(_opts(home, fake))

    assert "plugin" not in _kinds(actions)
    settings = [action for action in actions if action.kind == "settings"]
    assert settings, _kinds(actions)
    # The warning says why, with the version found and the minimum.
    assert "2.1.200" in settings[0].detail
    assert claude_plugin.MIN_CLAUDE_PLUGIN_VERSION in settings[0].detail


def test_cli_that_cannot_run_falls_back_to_settings(tmp_path):
    home = _home(tmp_path)
    fake = _fake(home)

    def broken(argv, env=None):
        raise RuntimeError("cannot start")

    opts = _opts(home, fake)
    opts.claude_runner = broken

    actions = install.plan_install(opts)

    assert "plugin" not in _kinds(actions)
    assert "settings" in _kinds(actions)


def test_install_uses_apply_plugin_delivery(tmp_path, monkeypatch):
    home = _home(tmp_path)
    fake = _fake(home)
    calls = []

    def spy(home_arg, **kwargs):
        calls.append((home_arg, kwargs))
        return plugin_migration.MigrationResult(True, claude_plugin.PLUGIN, messages=["ok"])

    monkeypatch.setattr(plugin_migration, "apply_plugin_delivery", spy)
    actions = install.plan_install(_opts(home, fake))

    assert install.apply(actions, dry_run=False, out=lambda _line: None) == 0
    assert len(calls) == 1
    home_arg, kwargs = calls[0]
    assert home_arg == home
    assert kwargs["ld_bin"] == LD_BIN
    assert kwargs["claude_bin"] == FakeClaude.BIN
    assert kwargs["version"] == VERSION
    # `install` ran no `claude plugin …` of its own: only the version probe of the decision.
    assert fake.steps() == ["version"]


def test_failed_migration_is_a_failure(tmp_path):
    home = _home(tmp_path)
    fake = _fake(home, fail=frozenset({"install"}))

    actions = install.plan_install(_opts(home, fake))

    lines = []
    assert install.apply(actions, dry_run=False, out=lines.append) == 1
    assert install_state.load(home) is None


def test_enable_read_hook_writes_switch_state(tmp_path):
    home = _home(tmp_path)
    fake = _fake(home)

    actions = install.plan_install(_opts(home, fake, enable_read_hook=True))
    assert install.apply(actions, dry_run=False, out=lambda _line: None) == 0

    assert _switch()["active"] is True


def test_disable_read_hook_turns_active_layer_off(tmp_path):
    home = _home(tmp_path)
    fake = _fake(home)
    install.apply(
        install.plan_install(_opts(home, fake, enable_read_hook=True)),
        dry_run=False,
        out=lambda _line: None,
    )
    assert _switch()["active"] is True

    actions = install.plan_install(_opts(home, fake, disable_read_hook=True))
    assert install.apply(actions, dry_run=False, out=lambda _line: None) == 0

    assert _switch()["active"] is False


def test_install_again_without_flags_keeps_switch_on(tmp_path):
    home = _home(tmp_path)
    fake = _fake(home)
    install.apply(
        install.plan_install(_opts(home, fake, enable_read_hook=True)),
        dry_run=False,
        out=lambda _line: None,
    )

    install.apply(install.plan_install(_opts(home, fake)), dry_run=False, out=lambda _line: None)

    # Only `--disable-read-hook` and `uninstall` turn the active layer off.
    assert _switch()["active"] is True


def test_dry_run_runs_nothing(tmp_path):
    home = _home(tmp_path)
    fake = _fake(home)
    before = (home / ".claude").exists() and sorted(p.name for p in (home / ".claude").iterdir())

    actions = install.plan_install(_opts(home, fake, enable_read_hook=True))
    lines = []
    assert install.apply(actions, dry_run=True, out=lines.append) == 0

    # Only the version probe of the decision ran; the commands are shown, not run.
    assert fake.steps() == ["version"]
    text = "\n".join(lines)
    assert "claude plugin marketplace add" in text
    assert f"claude plugin install {claude_plugin.PLUGIN_ID}" in text
    assert sorted(p.name for p in (home / ".claude").iterdir()) == before
    assert install_state.load(home) is None
    assert _switch() == {}


def test_settings_requested_with_plugin_reverts(tmp_path):
    home = _home(tmp_path)
    fake = _fake(home)
    install.apply(
        install.plan_install(_opts(home, fake, enable_read_hook=True)),
        dry_run=False,
        out=lambda _line: None,
    )
    assert install_state.delivery(install_state.load(home)) == claude_plugin.PLUGIN

    actions = install.plan_install(_opts(home, fake, claude_delivery="settings"))
    assert install.apply(actions, dry_run=False, out=lambda _line: None) == 0

    assert "uninstall" in fake.steps()
    assert install_state.delivery(install_state.load(home)) == claude_plugin.SETTINGS
    claude_dir = home / ".claude"
    # The block survives the way back: the read hooks are registered again with `--enabled`.
    assert install.read_hook_registered(claude_dir)
    assert (claude_dir / "hooks" / install.HOOKS_SUBDIR).is_dir()


def test_second_install_is_idempotent(tmp_path):
    home = _home(tmp_path)
    settings_path = home / ".claude" / "settings.json"
    settings_path.write_text(json.dumps({"model": "opus"}), encoding="utf-8")
    fake = _fake(home)
    after = []
    for _ in range(2):
        actions = install.plan_install(_opts(home, fake))
        assert install.apply(actions, dry_run=False, out=lambda _line: None) == 0
        after.append(json.loads(settings_path.read_text(encoding="utf-8-sig")))

    # The second pass changes nothing the first one left.
    assert after[0] == after[1]
    assert after[1]["model"] == "opus"
    settings = after[1]
    hooks_dir = home / ".claude" / "hooks" / install.HOOKS_SUBDIR
    ours = [
        hook
        for groups in settings.get("hooks", {}).values()
        for group in groups
        for hook in group.get("hooks", [])
        if install._is_ours(hook, hooks_dir)
    ]
    assert ours == []
