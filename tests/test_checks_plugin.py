"""Tests of the doctor checks for the Claude Code plugin delivery (REQ-009, 008 c and 012).

SDD claude-plugin-and-mods, batch F1-doctor. Nothing here launches the real `claude` (the runner
is a `FakeClaude`), reads the real registry (the bridge token is injected) or goes to the network
(the daemon collaborators are doubles from `make_ctx`). The HOME is always a `tmp_path`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from conftest import FakeClaude, desktop_mcp_remote_entry, make_home, write_claude_desktop
from test_checks import make_ctx, result_for

from local_delegate import (
    checks,
    claude_plugin,
    desktop_config,
    i18n,
    install,
    install_state,
    plugin_migration,
)

_TOKEN = "literal-token-that-must-never-leak"


def _settings_path(home: Path) -> Path:
    return home / ".claude" / "settings.json"


def _ld_bin(tmp_path: Path) -> Path:
    python = tmp_path / "uv-tools" / "local-delegate-mcp" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_bytes(b"")
    return python


def _plugin_home(
    tmp_path: Path,
    *,
    settings_hooks: bool = False,
    hook_scripts: bool = False,
    ld_bin: Path | str | None = None,
    language: str | None = None,
    enabled_in_settings: bool = True,
) -> tuple[Path, Path]:
    """A HOME as the plugin delivery leaves it: state, `enabledPlugins` and `pluginConfigs`.

    Built from the settings HOME of `make_home` and the migration's own removal, so it is the
    HOME the code produces and not an idea of it.
    """
    home = make_home(tmp_path, codex=False, opencode=False)
    claude_dir = home / ".claude"
    if not settings_hooks:
        plugin_migration.remove_settings_hooks(claude_dir)
    if hook_scripts:
        hooks_dir = claude_dir / "hooks" / install.HOOKS_SUBDIR
        hooks_dir.mkdir(parents=True, exist_ok=True)
        (hooks_dir / "record_call.py").write_text("# old\n", encoding="utf-8")
    settings = json.loads(_settings_path(home).read_text(encoding="utf-8"))
    if enabled_in_settings:
        settings["enabledPlugins"] = {claude_plugin.PLUGIN_ID: True}
    options = {"language": language or i18n.lang()}
    if ld_bin is not None:
        options["ld_bin"] = str(ld_bin)
    settings["pluginConfigs"] = {claude_plugin.PLUGIN_ID: {"options": options}}
    _settings_path(home).write_text(json.dumps(settings, indent=2), encoding="utf-8")
    data = tmp_path / "data"
    version = checks._installed_version() or "0.0.0"
    state = install_state.with_piece(
        install_state.new_state(claude_plugin.PLUGIN, version), "plugin", id=claude_plugin.PLUGIN_ID
    )
    install_state.save(home, state, data)
    return home, data


def _fake(**kwargs) -> FakeClaude:
    kwargs.setdefault("plugin_version", checks._installed_version() or "0.0.0")
    kwargs.setdefault("already_installed", True)
    return FakeClaude(**kwargs)


def _ctx(home: Path, data: Path | None, fake: FakeClaude | None = None, **kwargs):
    fake = fake or _fake()
    kwargs.setdefault("claude_runner", fake)
    kwargs.setdefault("claude_which", fake.which)
    return make_ctx(home, log_dir=data, **kwargs)


# --- REQ-008 c: hooks in settings and plugin at the same time ---------------------------------


def test_doctor_flags_hooks_in_settings_and_plugin(tmp_path):
    """After a downgrade to 0.39 without `uninstall`, every hook would run twice."""
    home, data = _plugin_home(tmp_path, settings_hooks=True, ld_bin=_ld_bin(tmp_path))
    result = result_for("hooks.duplicates", _ctx(home, data))

    assert result.status == checks.WARN, result.detail
    assert claude_plugin.PLUGIN_ID in result.detail
    assert result.fix_hint == "local-delegate update"
    # Under the plugin delivery, our hooks in settings are the wrong half, not "registered".
    assert result_for("scaffold.hook_settings", _ctx(home, data)).status == checks.WARN


# --- REQ-009: plugin installed, enabled, current and in the current language ------------------


def test_plugin_version_mismatch_warns(tmp_path):
    home, data = _plugin_home(tmp_path, ld_bin=_ld_bin(tmp_path))
    result = result_for("plugin.installed", _ctx(home, data, _fake(plugin_version="0.0.1")))

    assert result.status == checks.WARN, result.detail
    assert "0.0.1" in result.detail
    assert str(checks._installed_version()) in result.detail
    assert result.fix_hint == "local-delegate update"


def test_plugin_language_stale_warns(tmp_path):
    home, data = _plugin_home(tmp_path, ld_bin=_ld_bin(tmp_path), language="en")
    with i18n.override("es"):
        stale = result_for("plugin.installed", _ctx(home, data))
    with i18n.override("en"):
        current = result_for("plugin.installed", _ctx(home, data))

    assert stale.status == checks.WARN, stale.detail
    assert "en" in stale.detail
    assert stale.fix_hint == "local-delegate install"
    # Control: the same HOME in the language the plugin was installed with is fine.
    assert current.status == checks.OK, current.detail


def test_plugin_not_listed_is_missing_and_disabled_warns(tmp_path):
    home, data = _plugin_home(tmp_path, ld_bin=_ld_bin(tmp_path))
    missing = result_for("plugin.installed", _ctx(home, data, _fake(already_installed=False)))
    disabled = result_for("plugin.installed", _ctx(home, data, _fake(enabled=False)))

    assert missing.status == checks.MISSING
    assert disabled.status == checks.WARN
    assert "claude plugin enable" in disabled.fix_hint


# --- REQ-009: ld_bin ------------------------------------------------------------------------


def test_ld_bin_missing_fails(tmp_path):
    gone = tmp_path / "gone" / "python.exe"
    home, data = _plugin_home(tmp_path, ld_bin=gone)
    result = result_for("plugin.ld_bin", _ctx(home, data))

    assert result.status == checks.MISSING, result.detail
    assert str(gone) in result.detail
    unset_home, unset_data = _plugin_home(tmp_path / "unset")
    assert result_for("plugin.ld_bin", _ctx(unset_home, unset_data)).status == checks.MISSING


def test_ld_bin_not_the_installed_uv_tool_env_warns(tmp_path):
    """The hooks must run the environment of the installed version, not an older one."""
    configured = _ld_bin(tmp_path / "old")
    installed = _ld_bin(tmp_path / "new")
    home, data = _plugin_home(tmp_path, ld_bin=configured)

    other = result_for(
        "plugin.ld_bin",
        _ctx(home, data, expected_ld_bin=lambda: claude_plugin.LdBin(str(installed), None)),
    )
    same = result_for(
        "plugin.ld_bin",
        _ctx(home, data, expected_ld_bin=lambda: claude_plugin.LdBin(str(configured), None)),
    )

    assert other.status == checks.WARN, other.detail
    assert str(installed) in other.detail
    assert other.fix_hint == "local-delegate install"
    assert same.status == checks.OK, same.detail


# --- REQ-009: Claude Code version -------------------------------------------------------------


def test_claude_below_min_warns(tmp_path):
    home, data = _plugin_home(tmp_path, ld_bin=_ld_bin(tmp_path))
    old = result_for("claude.version", _ctx(home, data, _fake(version="2.1.200")))
    new = result_for("claude.version", _ctx(home, data, _fake(version="2.1.1000")))
    absent = result_for(
        "claude.version", _ctx(home, data, claude_which=lambda _name: None, claude_runner=None)
    )

    assert old.status == checks.WARN, old.detail
    assert "2.1.200" in old.detail
    assert claude_plugin.MIN_CLAUDE_PLUGIN_VERSION in old.detail
    assert new.status == checks.OK, new.detail  # numeric, not text: 1000 > 292
    assert absent.status == checks.UNKNOWN


# --- WSL -----------------------------------------------------------------------------------


def test_wsl_expects_no_plugin(tmp_path):
    """Inside WSL Claude Code stays on settings: no plugin is not a fault, and nobody asks for it."""
    home = make_home(tmp_path, codex=False, opencode=False)  # settings delivery, no plugin
    fake = _fake(already_installed=False)
    ctx = _ctx(home, tmp_path / "data", fake, environ={"WSL_DISTRO_NAME": "Ubuntu"})
    results = {check.id: result for check, result in checks.run_all(ctx)}

    for check_id in ("claude.delivery", "claude.version", "plugin.installed", "plugin.ld_bin"):
        assert results[check_id].status == checks.OK, (check_id, results[check_id].detail)
    assert results["hooks.duplicates"].status == checks.OK
    assert results["scaffold.hook_settings"].status == checks.OK
    assert "list" not in fake.steps()


# --- Hooks by delivery ------------------------------------------------------------------------


def test_settings_hooks_absent_is_ok_under_plugin(tmp_path):
    """With the plugin, no hooks in settings is right; leftover scripts are orphans."""
    home, data = _plugin_home(tmp_path, ld_bin=_ld_bin(tmp_path))
    results = {check.id: result for check, result in checks.run_all(_ctx(home, data))}

    for check_id in (
        "claude.delivery",
        "plugin.installed",
        "hooks.duplicates",
        "scaffold.hook_settings",
        "scaffold.hook_files",
    ):
        assert results[check_id].status == checks.OK, (check_id, results[check_id].detail)
    assert claude_plugin.PLUGIN in results["claude.delivery"].detail

    leftover, leftover_data = _plugin_home(
        tmp_path / "leftover", ld_bin=_ld_bin(tmp_path), hook_scripts=True
    )
    orphans = result_for("scaffold.hook_files", _ctx(leftover, leftover_data))
    assert orphans.status == checks.WARN, orphans.detail
    assert orphans.fix_hint == "local-delegate update"


def test_settings_delivery_without_state_keeps_the_hooks_checks(tmp_path):
    """No state (an install from 0.39): the settings checks work as before, the delivery is unknown."""
    home = make_home(tmp_path, codex=False, opencode=False)
    results = {check.id: result for check, result in checks.run_all(_ctx(home, tmp_path / "d"))}

    assert results["scaffold.hook_settings"].status == checks.OK
    assert results["scaffold.hook_files"].status == checks.OK
    assert results["claude.delivery"].status == checks.UNKNOWN
    assert results["plugin.installed"].status == checks.OK  # not used


# --- REQ-012: Claude Desktop ------------------------------------------------------------------


def _desktop(home: Path, entry: dict) -> Path:
    return write_claude_desktop(home, {"other": {"command": "uvx"}, install.SERVER_NAME: entry})


def _desktop_ctx(home, *, accepts=True, token=_TOKEN, calls=None):
    def _accepts(host, port, value):
        if calls is not None:
            calls.append(value)
        return accepts

    return make_ctx(
        home,
        daemon_needs_token=lambda host, port: True,
        daemon_accepts_token=_accepts,
        bridge_token=lambda: token,
    )


def _no_token(result) -> None:
    assert _TOKEN not in result.detail
    assert _TOKEN not in (result.fix_hint or "")


def test_desktop_literal_token_not_shown(tmp_path):
    """Desktop neither passes its environment nor expands `${VAR}`: both forms are warnings."""
    home = make_home(tmp_path, codex=False, opencode=False)

    _desktop(home, desktop_mcp_remote_entry(f"Authorization: Bearer {_TOKEN}"))
    literal = result_for("service.desktop_auth", _desktop_ctx(home))
    assert literal.status == checks.WARN, literal.detail
    _no_token(literal)

    _desktop(home, desktop_mcp_remote_entry("Authorization: Bearer ${LOCAL_DELEGATE_WEB_TOKEN}"))
    unexpanded = result_for("service.desktop_auth", _desktop_ctx(home))
    assert unexpanded.status == checks.WARN, unexpanded.detail
    assert "${" in unexpanded.detail
    _no_token(unexpanded)

    # Control: the bridge entry that `install --desktop` writes, with a token the daemon accepts.
    exe = tmp_path / "bin" / "local-delegate.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    _desktop(home, desktop_config.bridge_entry(exe))
    calls: list[str] = []
    bridge = result_for("service.desktop_auth", _desktop_ctx(home, calls=calls))
    assert bridge.status == checks.OK, bridge.detail
    assert calls == [_TOKEN]
    _no_token(bridge)

    rejected = result_for("service.desktop_auth", _desktop_ctx(home, accepts=False))
    assert rejected.status == checks.WARN, rejected.detail
    _no_token(rejected)
    no_token = result_for("service.desktop_auth", _desktop_ctx(home, token=""))
    assert no_token.status == checks.WARN, no_token.detail
    assert "LOCAL_DELEGATE_WEB_TOKEN" in no_token.detail


# --- mod.loaded (F2-mod-core, REQ-009): the heartbeat the mod writes ---------------------------
_PIECES = {"pinned-tools": "on", "commands": "on", "status": "absent", "read": "absent"}


def _heartbeat(home: Path, session: str = "sess-1", **fields) -> Path:
    """What `mod/common.js` writes at session start (`heartbeat`), with its field names."""
    folder = (
        home
        / ".claude"
        / "plugins"
        / "data"
        / f"{claude_plugin.PLUGIN_NAME}-{claude_plugin.MARKETPLACE_NAME}"
        / "heartbeats"
    )
    folder.mkdir(parents=True, exist_ok=True)
    beat = {
        "session_id": session,
        "version": checks._installed_version() or "0.0.0",
        "entrypoint": "cli",
        "process_run": True,
        "dialog": True,
        "read_mod_enabled": False,
        "pieces": dict(_PIECES),
        "at": "2026-10-22T10:00:00.000Z",
    }
    beat.update(fields)
    path = folder / f"{session}.json"
    path.write_text(json.dumps(beat), encoding="utf-8")
    return path


def test_mod_loaded_from_heartbeat(tmp_path):
    home, data = _plugin_home(tmp_path, ld_bin=_ld_bin(tmp_path))
    old = _heartbeat(home, "older", pieces={**_PIECES, "commands": "failed"})
    os.utime(old, (old.stat().st_mtime - 3600, old.stat().st_mtime - 3600))
    _heartbeat(home, "newest")
    result = result_for("mod.loaded", _ctx(home, data))
    # The newest session's heartbeat speaks: the older one's failed piece is history.
    assert result.status == checks.OK, result.detail
    assert "pinned-tools" in result.detail and "commands" in result.detail
    assert "2026-10-22" in result.detail


def test_no_heartbeat_warns(tmp_path):
    home, data = _plugin_home(tmp_path, ld_bin=_ld_bin(tmp_path))
    result = result_for("mod.loaded", _ctx(home, data))
    assert result.status == checks.WARN, result.detail
    assert "heartbeats" in result.detail
    assert result.fix_hint
    # Control: the same HOME with a heartbeat is ok, so the warn came from its absence.
    _heartbeat(home)
    assert result_for("mod.loaded", _ctx(home, data)).status == checks.OK


def test_mod_failed_piece_or_stale_heartbeat_warns(tmp_path):
    home, data = _plugin_home(tmp_path, ld_bin=_ld_bin(tmp_path))
    _heartbeat(home, pieces={**_PIECES, "commands": "failed"})
    failed = result_for("mod.loaded", _ctx(home, data))
    assert failed.status == checks.WARN, failed.detail
    assert "commands" in failed.detail

    stale = _heartbeat(home)
    eight_days = 8 * 24 * 3600
    os.utime(stale, (stale.stat().st_mtime - eight_days, stale.stat().st_mtime - eight_days))
    old = result_for("mod.loaded", _ctx(home, data))
    assert old.status == checks.WARN, old.detail

    broken = _heartbeat(home, "broken")
    broken.write_text("{not json", encoding="utf-8")
    assert result_for("mod.loaded", _ctx(home, data)).status == checks.WARN


def test_mod_not_expected_without_plugin(tmp_path):
    home = make_home(tmp_path, codex=False, opencode=False)
    result = result_for("mod.loaded", make_ctx(home))
    assert result.status == checks.OK, result.detail


# --- mod.read_overlap (F4-hooks-swap, REQ-023): the read mod and the read hooks ----------------


def _read_mod(home: Path, data: Path, *, enabled: bool, layer: bool | None) -> None:
    """The `read_mod_enabled` option in `pluginConfigs` and the read hook's active layer
    (`read-hook.json`, as `install --enable-read-hook` writes it; `None` leaves no file)."""
    settings = json.loads(_settings_path(home).read_text(encoding="utf-8"))
    settings["pluginConfigs"][claude_plugin.PLUGIN_ID]["options"]["read_mod_enabled"] = enabled
    _settings_path(home).write_text(json.dumps(settings, indent=2), encoding="utf-8")
    switch = plugin_migration.read_switch_path(home, data)
    assert switch is not None
    if layer is None:
        switch.unlink(missing_ok=True)
    else:
        switch.parent.mkdir(parents=True, exist_ok=True)
        payload = {"active": layer, "since": "2026-10-22T10:00:00+00:00"}
        switch.write_text(json.dumps(payload), encoding="utf-8")


def _settings_read_hooks(home: Path) -> None:
    """The read hooks in `settings.json` as `install --enable-read-hook` registers them there."""
    hooks_dir = home / ".claude" / "hooks" / install.HOOKS_SUBDIR
    entries = [
        (
            event,
            matcher,
            install.hook_command(hooks_dir, script, "python", (install.READ_HOOK_FLAG,)),
        )
        for script, event, matcher in (
            install._READ_HOOK,
            install._MCP_READ_HOOK,
            install._SHELL_HOOK,
        )
    ]
    settings = json.loads(_settings_path(home).read_text(encoding="utf-8"))
    settings, _removed = install.merge_hook_settings(settings, entries, hooks_dir)
    _settings_path(home).write_text(json.dumps(settings, indent=2), encoding="utf-8")


def test_read_mod_and_read_hook_overlap_warns(tmp_path):
    # Both act: the read hook still in settings.json (it never sees the plugin option, so it never
    # steps aside) while the read mod is on.
    home, data = _plugin_home(tmp_path / "both", ld_bin=_ld_bin(tmp_path))
    _settings_read_hooks(home)
    _read_mod(home, data, enabled=True, layer=True)
    both = result_for("mod.read_overlap", _ctx(home, data))
    assert both.status == checks.WARN, both.detail
    assert "settings.json" in both.detail
    assert both.fix_hint == "local-delegate update"

    # Neither acts: the option is on but the read layer is off, so the mod passes every read
    # (`read_switch` is not `on`) and the hook does not run.
    home, data = _plugin_home(tmp_path / "none", ld_bin=_ld_bin(tmp_path))
    _read_mod(home, data, enabled=True, layer=False)
    none = result_for("mod.read_overlap", _ctx(home, data))
    assert none.status == checks.WARN, none.detail
    assert "read_mod_enabled" in none.detail
    assert none.fix_hint == "local-delegate install --enable-read-hook"
    _read_mod(home, data, enabled=True, layer=None)
    assert result_for("mod.read_overlap", _ctx(home, data)).status == checks.WARN

    # Controls: the same HOME with the layer on is coordinated, and with the option off the hooks
    # act alone; so the warns came from the overlap and the gap, not from the HOME.
    _read_mod(home, data, enabled=True, layer=True)
    ok = result_for("mod.read_overlap", _ctx(home, data))
    assert ok.status == checks.OK, ok.detail
    _read_mod(home, data, enabled=False, layer=False)
    assert result_for("mod.read_overlap", _ctx(home, data)).status == checks.OK
    home, data = _plugin_home(tmp_path / "off", ld_bin=_ld_bin(tmp_path))
    _settings_read_hooks(home)
    _read_mod(home, data, enabled=False, layer=True)
    assert result_for("mod.read_overlap", _ctx(home, data)).status == checks.OK
    # Without the plugin there is no read mod to overlap with.
    plain = make_home(tmp_path / "plain", codex=False, opencode=False)
    assert result_for("mod.read_overlap", make_ctx(plain)).status == checks.OK
