"""`update` and the Claude Code plugin delivery (SDD claude-plugin-and-mods, F1-update).

REQ-008 a, REQ-010 and REQ-012. With the plugin, `update` refreshes the marketplace and then the
plugin, repairs the plugin when it is missing or carries another language, and takes our hooks
**out** of `settings.json` when they duplicate the plugin's: it never puts them back. A settings
install that meets REQ-005 is migrated with the same orchestration `install` uses. Every test runs
in a simulated HOME with an injected `claude` (the suite forbids the real one).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import FakeClaude, make_home

from local_delegate import (
    checks,
    checks_plugin,
    claude_plugin,
    desktop_config,
    install,
    install_state,
    plugin_migration,
    update,
)
from local_delegate.i18n import t
from local_delegate.version import get_version

VERSION = get_version()
PLUGIN_ID = claude_plugin.PLUGIN_ID


@pytest.fixture(autouse=True)
def _without_real_signals(monkeypatch):
    monkeypatch.setattr(update.os, "kill", lambda pid, sig: None)


class Claude(FakeClaude):
    """`FakeClaude` that also knows `plugin marketplace update` and `plugin update`."""

    @staticmethod
    def step_of(argv: list[str]) -> str:
        rest = list(argv)[1:]
        if rest[:3] == ["plugin", "marketplace", "update"]:
            return "marketplace_update"
        if rest[:2] == ["plugin", "update"]:
            return "update"
        return FakeClaude.step_of(argv)

    def __call__(self, argv, env=None) -> subprocess.CompletedProcess:
        done = super().__call__(argv, env)
        if self.step_of(list(argv)) == "update" and done.returncode == 0:
            self.plugin_version = VERSION
        return done


def _ld_bin(tmp_path: Path) -> Path:
    path = tmp_path / "uv" / "tools" / "local-delegate-mcp" / "Scripts" / "python.exe"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def _settings_path(home: Path) -> Path:
    return home / ".claude" / "settings.json"


def _read_settings(home: Path) -> dict:
    return json.loads(_settings_path(home).read_text(encoding="utf-8-sig"))


def _write_settings(home: Path, data: dict) -> None:
    _settings_path(home).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _hooks_dir(home: Path) -> Path:
    return home / ".claude" / "hooks" / install.HOOKS_SUBDIR


def _our_hooks(home: Path) -> list[str]:
    return checks_plugin.our_settings_hooks(_read_settings(home), _hooks_dir(home))


def _settings_home(tmp_path: Path, *, read_hook: bool = False) -> Path:
    """A 0.39 install: hooks in `settings.json` (and the read trio if asked), no state file."""
    home = make_home(tmp_path, codex=False, opencode=False)
    if read_hook:
        entries = install._settings_hook_entries(_hooks_dir(home), "python", True)
        data, _removed = install.merge_hook_settings(
            _read_settings(home), entries, _hooks_dir(home)
        )
        _write_settings(home, data)
    return home


def _plugin_home(
    tmp_path: Path, ld_bin: Path, *, language: str = "es", settings_hooks: bool = False
) -> Path:
    """An install by plugin: state `plugin`, the plugin enabled with its options, no hooks folder."""
    home = make_home(tmp_path, codex=False, opencode=False)
    data = _read_settings(home)
    if not settings_hooks:
        data.pop("hooks", None)
        install.shutil.rmtree(_hooks_dir(home))
    data["enabledPlugins"] = {PLUGIN_ID: True}
    data["pluginConfigs"] = {PLUGIN_ID: {"options": {"ld_bin": str(ld_bin), "language": language}}}
    _write_settings(home, data)
    state = install_state.new_state(claude_plugin.PLUGIN, VERSION)
    state = install_state.with_piece(state, "plugin", id=PLUGIN_ID)
    state = install_state.with_piece(state, "marketplace", name=claude_plugin.MARKETPLACE_NAME)
    install_state.save(home, state)
    return home


def _claude(home: Path, **kwargs) -> Claude:
    kwargs.setdefault("plugin_version", VERSION)
    return Claude(settings_path=_settings_path(home), **kwargs)


def _clock():
    ticks = iter(range(10_000))
    return lambda: float(next(ticks))


def _opts(home: Path, fake: Claude, ld_bin: Path, **kwargs) -> update.Options:
    defaults = {
        "version": VERSION,
        "runner": lambda argv: subprocess.CompletedProcess(argv, 0, "", ""),
        "daemon_status": lambda host, port: None,
        "sleep": lambda seconds: None,
        "clock": _clock(),
        "spawn": lambda argv: None,
        "claude_runner": fake,
        "claude_which": fake.which,
        "claude_ld_bin": claude_plugin.LdBin(str(ld_bin), None),
    }
    defaults.update(kwargs)
    return update.Options(home=home, **defaults)


def _run(opts: update.Options) -> tuple[int, str]:
    lines: list[str] = []
    code = update.run_update(opts, out=lambda *a: lines.append(" ".join(str(x) for x in a)))
    return code, "\n".join(lines)


def _argv(fake: Claude, step: str) -> list[str]:
    found = [argv for argv, _env in fake.calls if fake.step_of(argv) == step]
    assert found, (step, fake.steps())
    return found[-1]


# --- REQ-010: marketplace first, then the plugin -------------------------------------------
def test_marketplace_update_before_plugin_update(tmp_path):
    ld = _ld_bin(tmp_path)
    home = _plugin_home(tmp_path, ld)
    fake = _claude(home, already_installed=True, plugin_version="0.0.1")

    code, text = _run(_opts(home, fake, ld))

    assert code == 0, text
    steps = fake.steps()
    assert "marketplace_update" in steps and "update" in steps, steps
    assert steps.index("marketplace_update") < steps.index("update"), steps
    assert _argv(fake, "marketplace_update")[1:] == [
        "plugin",
        "marketplace",
        "update",
        claude_plugin.MARKETPLACE_NAME,
    ]
    assert _argv(fake, "update")[1:] == ["plugin", "update", PLUGIN_ID]
    # The simulated HOME reaches every `claude …` child (REQ-005).
    for _argv_, env in fake.calls:
        assert env == {"CLAUDE_CONFIG_DIR": str(home / ".claude")}
    assert t("plugin_update.restart_sessions") in text
    # Nothing came back to settings.json.
    assert _our_hooks(home) == []


def test_current_plugin_is_left_alone(tmp_path):
    """Control of the test above: plugin current, same language, nothing of the CLI runs."""
    ld = _ld_bin(tmp_path)
    home = _plugin_home(tmp_path, ld)
    fake = _claude(home, already_installed=True)

    code, text = _run(_opts(home, fake, ld))

    assert code == 0, text
    assert set(fake.steps()) <= {"version", "list"}, fake.steps()


# --- Repairs by check id --------------------------------------------------------------------
def test_repairs_missing_plugin(tmp_path):
    ld = _ld_bin(tmp_path)
    home = _plugin_home(tmp_path, ld)
    fake = _claude(home, already_installed=False)

    code, text = _run(_opts(home, fake, ld))

    assert code == 0, text
    argv = _argv(fake, "install")
    assert f"ld_bin={ld}" in argv
    assert "language=es" in argv
    assert fake.installed is True
    assert install_state.delivery(install_state.load(home)) == claude_plugin.PLUGIN
    assert _our_hooks(home) == []


def test_duplicates_are_removed_not_restored(tmp_path):
    ld = _ld_bin(tmp_path)
    home = _plugin_home(tmp_path, ld, settings_hooks=True)
    fake = _claude(home, already_installed=True)
    assert _our_hooks(home), "precondition: our hooks are in settings.json"

    code, text = _run(_opts(home, fake, ld))

    assert code == 0, text
    assert _our_hooks(home) == []
    assert not _hooks_dir(home).exists()
    # Retired with `plugin_migration`, not reinstalled: the plugin was fine.
    assert "install" not in fake.steps()
    assert _read_settings(home)["enabledPlugins"] == {PLUGIN_ID: True}


def _plugin_enabled_without_state(tmp_path: Path) -> Path:
    """The downgrade case: plugin enabled in settings.json, no state, no hooks of ours."""
    home = make_home(tmp_path, codex=False, opencode=False)
    data = _read_settings(home)
    data.pop("hooks", None)
    data["enabledPlugins"] = {PLUGIN_ID: True}
    _write_settings(home, data)
    install.shutil.rmtree(_hooks_dir(home))
    return home


@pytest.mark.parametrize("case", ["state", "enabled_only"])
def test_update_never_restores_settings_hooks_under_plugin(tmp_path, case):
    ld = _ld_bin(tmp_path)
    if case == "state":
        home = _plugin_home(tmp_path, ld)
    else:
        home = _plugin_enabled_without_state(tmp_path)
    # A `claude` too old for the plugin: `decide` falls back to settings, the trap of REQ-006.
    fake = _claude(home, version="2.1.200", already_installed=True)
    opts = _opts(home, fake, ld)
    results = [
        (
            check,
            checks.Result(
                checks.MISSING if check.id.startswith("scaffold.hook") else checks.OK, "x"
            ),
        )
        for check in checks.CHECKS
    ]

    actions, _notes = update.plan_repairs(results, opts)

    assert [a for a in actions if a.kind in ("settings", "copy") and "hooks" in str(a.target)] == []
    assert not [a for a in actions if str(a.target).endswith("settings.json")], [
        a.describe() for a in actions
    ]
    code, text = _run(opts)
    assert code == 0, text
    assert _our_hooks(home) == []
    assert not _hooks_dir(home).exists()


# --- REQ-008 a: a settings install moves to the plugin ---------------------------------------
def test_settings_install_migrates_carries_switch_and_warns_restart(tmp_path):
    ld = _ld_bin(tmp_path)
    home = _settings_home(tmp_path, read_hook=True)
    assert install.read_hook_registered(home / ".claude")
    fake = _claude(home)

    code, text = _run(_opts(home, fake, ld))

    assert code == 0, text
    steps = fake.steps()
    assert "marketplace_add" in steps and "install" in steps, steps
    assert _our_hooks(home) == []
    assert not _hooks_dir(home).exists()
    switch = plugin_migration.read_switch_path(home)
    assert switch is not None
    assert json.loads(switch.read_text(encoding="utf-8"))["active"] is True
    assert install_state.delivery(install_state.load(home)) == claude_plugin.PLUGIN
    assert t("plugin_update.restart_sessions") in text


def test_settings_install_stays_when_plugin_not_possible(tmp_path):
    """Control: with an old `claude` the 0.39 install is left as it is (settings as today)."""
    ld = _ld_bin(tmp_path)
    home = _settings_home(tmp_path)
    before = _our_hooks(home)
    fake = _claude(home, version="2.1.200")

    code, text = _run(_opts(home, fake, ld))

    assert code == 0, text
    assert "install" not in fake.steps()
    assert _our_hooks(home) == before
    assert t("plugin_update.restart_sessions") not in text


def test_install_and_update_share_one_orchestration(tmp_path, monkeypatch):
    calls: list[str] = []

    def spy(home_arg, **kwargs):
        calls.append(kwargs["claude_bin"])
        return plugin_migration.MigrationResult(True, claude_plugin.PLUGIN, messages=["ok"])

    monkeypatch.setattr(plugin_migration, "apply_plugin_delivery", spy)
    ld = _ld_bin(tmp_path)

    install_home = _settings_home(tmp_path / "a")
    install_fake = _claude(install_home)
    actions = install.plan_install(
        install.Options(
            home=install_home,
            components={"hooks"},
            targets={"claude"},
            python_exe="python",
            use_cli=False,
            claude_runner=install_fake,
            claude_which=install_fake.which,
            claude_ld_bin=claude_plugin.LdBin(str(ld), None),
        )
    )
    assert install.apply(actions, dry_run=False, out=lambda _line: None) == 0

    update_home = _settings_home(tmp_path / "b")
    update_fake = _claude(update_home)
    code, text = _run(_opts(update_home, update_fake, ld))

    assert code == 0, text
    # One migration each, both through the same function.
    assert calls == [FakeClaude.BIN, FakeClaude.BIN]
    # `update` ran no install step of its own: the spy did not run the CLI.
    assert not {"marketplace_add", "install"} & set(update_fake.steps()), update_fake.steps()
    # And the module holds no copy of the steps.
    source = Path(update.__file__).read_text(encoding="utf-8")
    for name in ("marketplace_add_argv", "install_argv", "apply_plugin_delivery("):
        assert name not in source, name


def test_language_change_reapplied(tmp_path):
    ld = _ld_bin(tmp_path)
    home = _plugin_home(tmp_path, ld, language="en")
    fake = _claude(home, already_installed=True)

    code, text = _run(_opts(home, fake, ld))

    assert code == 0, text
    argv = _argv(fake, "install")
    assert "language=es" in argv
    assert "language=en" not in argv


# --- REQ-012: the Desktop bridge follows the executable --------------------------------------
def _desktop_home(tmp_path: Path, ld: Path, old_exe: Path) -> tuple[Path, Path]:
    home = _plugin_home(tmp_path, ld)
    desktop_dir = tmp_path / "AppData"
    path = desktop_config.config_path(desktop_dir)
    path.parent.mkdir(parents=True)
    other = {"command": "npx", "args": ["other"]}
    path.write_text(
        json.dumps(
            {"mcpServers": {"other": other, "local-delegate": desktop_config.bridge_entry(old_exe)}}
        ),
        encoding="utf-8",
    )
    state = install_state.load(home)
    install_state.save(
        home, install_state.with_piece(state, "desktop_entry", path=str(path), backup=None)
    )
    return home, desktop_dir


def _exe(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name / "Scripts" / "local-delegate.exe"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")
    return path


def test_desktop_bridge_path_rewritten(tmp_path):
    ld = _ld_bin(tmp_path)
    old_exe, new_exe = _exe(tmp_path, "old"), _exe(tmp_path, "new")
    home, desktop_dir = _desktop_home(tmp_path, ld, old_exe)
    fake = _claude(home, already_installed=True)

    code, text = _run(_opts(home, fake, ld, desktop_dir=desktop_dir, desktop_executable=new_exe))

    assert code == 0, text
    data = json.loads(desktop_config.config_path(desktop_dir).read_text(encoding="utf-8"))
    assert data["mcpServers"]["local-delegate"] == desktop_config.bridge_entry(new_exe)
    assert data["mcpServers"]["other"] == {"command": "npx", "args": ["other"]}


def test_desktop_bridge_same_path_untouched(tmp_path):
    """Control: same executable, the file is not rewritten (no backup appears)."""
    ld = _ld_bin(tmp_path)
    exe = _exe(tmp_path, "same")
    home, desktop_dir = _desktop_home(tmp_path, ld, exe)
    fake = _claude(home, already_installed=True)

    code, text = _run(_opts(home, fake, ld, desktop_dir=desktop_dir, desktop_executable=exe))

    assert code == 0, text
    assert desktop_config.backups(desktop_config.config_path(desktop_dir)) == []


# --- What does not change -------------------------------------------------------------------
def test_plan_pin_unchanged(tmp_path):
    ld = _ld_bin(tmp_path)
    home = _plugin_home(tmp_path, ld)
    claude_json = home / ".claude.json"
    entry = {"command": "uvx", "args": ["--from", f"{update.PACKAGE}==0.0.1", "local-delegate"]}
    claude_json.write_text(json.dumps({"mcpServers": {"local-delegate": entry}}), encoding="utf-8")
    fake = _claude(home, already_installed=True)
    opts = _opts(home, fake, ld)

    pin = update.plan_pin(opts, VERSION)

    assert [a.target for a in pin] == [claude_json]
    code, text = _run(opts)
    assert code == 0, text
    assert f"{update.PACKAGE}=={VERSION}" in claude_json.read_text(encoding="utf-8")
    # The MCP entry stays in `~/.claude.json`, never in the plugin (REQ-010).
    assert "local-delegate" in json.loads(claude_json.read_text(encoding="utf-8"))["mcpServers"]


# --- The settings delivery chosen by hand stays (F1-settings-choice) --------------------------
#: The optional field of `install-state.json` that says `--claude-delivery settings` was explicit.
EXPLICIT = "claude_delivery_explicit"


def _install(home: Path, fake: Claude, ld: Path, delivery: str | None) -> None:
    """`install` of the hooks for Claude Code, with ``--claude-delivery`` = ``delivery``."""
    actions = install.plan_install(
        install.Options(
            home=home,
            components={"hooks"},
            targets={"claude"},
            python_exe="python",
            use_cli=False,
            claude_runner=fake,
            claude_which=fake.which,
            claude_ld_bin=claude_plugin.LdBin(str(ld), None),
            claude_delivery=delivery,
        )
    )
    assert install.apply(actions, dry_run=False, out=lambda _line: None) == 0


def _drop_settings_hooks(home: Path) -> None:
    """Our entries out of `settings.json`: the `scaffold.hook_settings` repair has to run."""
    data = _read_settings(home)
    data.pop("hooks", None)
    _write_settings(home, data)


@pytest.mark.parametrize("case", ["intact", "broken"])
def test_update_respects_explicit_settings_choice(tmp_path, case):
    ld = _ld_bin(tmp_path)
    home = _settings_home(tmp_path)
    fake = _claude(home)  # a `claude` that can take the plugin: only the choice holds it back
    _install(home, fake, ld, claude_plugin.SETTINGS)
    if case == "broken":
        _drop_settings_hooks(home)

    code, text = _run(_opts(home, fake, ld))

    assert code == 0, text
    assert "install" not in fake.steps(), fake.steps()
    assert install_state.delivery(install_state.load(home)) == claude_plugin.SETTINGS
    # The settings delivery is still (or again) the one in place.
    assert _our_hooks(home), "our hooks should be in settings.json"
    assert _read_settings(home).get("enabledPlugins", {}).get(PLUGIN_ID) is None


@pytest.mark.parametrize("delivery", [None, claude_plugin.PLUGIN])
def test_install_without_explicit_settings_removes_the_choice(tmp_path, delivery):
    ld = _ld_bin(tmp_path)
    home = _settings_home(tmp_path)
    state = {**install_state.new_state(claude_plugin.SETTINGS, VERSION), EXPLICIT: True}
    install_state.save(home, state)
    # Without the flag and an old `claude`, `install` stays on settings; with `plugin`, it moves.
    fake = _claude(home, **({"version": "2.1.200"} if delivery is None else {}))

    _install(home, fake, ld, delivery)

    stored = install_state.load(home)
    assert stored is not None
    assert EXPLICIT not in stored, stored


def test_old_settings_install_without_mark_still_migrates(tmp_path):
    """Control of the two above: a state of today (no mark) keeps migrating (REQ-008 a)."""
    ld = _ld_bin(tmp_path)
    home = _settings_home(tmp_path)
    install_state.save(home, install_state.new_state(claude_plugin.SETTINGS, "0.39.0"))
    fake = _claude(home)

    code, text = _run(_opts(home, fake, ld))

    assert code == 0, text
    assert "install" in fake.steps(), fake.steps()
    assert install_state.delivery(install_state.load(home)) == claude_plugin.PLUGIN
    assert EXPLICIT not in (install_state.load(home) or {})
