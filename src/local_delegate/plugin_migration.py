"""plugin_migration.py — the one orchestration that moves Claude Code from settings to the plugin.

REQ-004, REQ-006 and REQ-008 a/b (SDD claude-plugin-and-mods). ``install`` and ``update`` only
call ``apply_plugin_delivery`` and ``revert_to_settings``; neither repeats a step of its own.

The order of ``apply_plugin_delivery`` is the safety of the migration, so it is fixed here:

1. Copy ``settings.json`` (``settings.json.local-delegate-plugin.bak``, only the first time)
   **before any** ``claude plugin …``: the CLI rewrites that file when it adds the marketplace.
2. Carry the read hook: read ``install.read_hook_registered()`` and write ``read-hook.json`` with
   that value **before removing anything**. If the file exists the migration never turns it off;
   that belongs to ``install --disable-read-hook`` and ``uninstall``. If the value cannot be
   written (simulated HOME without a data directory) and the hook was on, nothing is migrated:
   removing the settings entries would switch the block off in silence (plan, B-2).
3. Marketplace and install, with ``--config ld_bin=…`` and ``--config language=…``.
4. ``claude plugin list --json``: our plugin is there, enabled and at the package version.
5. **Only then** remove our settings entries (``install._is_ours`` and
   ``install.strip_hook_settings``, imported, never copied) and ``~/.claude/hooks/local-delegate/``.
6. Write the installation state (``install_state``).

If a step from 3 to 5 fails, ``settings.json`` is left as it was and the result says why. The
contract of ``read-hook.json`` (``{"active", "since"}``) belongs to ``read_switch``, which lives in
another batch: this module writes **the file** with that exact shape and does not import it.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from . import claude_plugin, install, install_state
from .i18n import t

BACKUP_NAME = "settings.json.local-delegate-plugin.bak"
READ_SWITCH_FILE = "read-hook.json"


@dataclass
class MigrationResult:
    """What happened. ``failed_step`` names the step that stopped it, if any."""

    ok: bool
    delivery: str | None
    removed: int = 0
    backup: Path | None = None
    failed_step: str | None = None
    messages: list[str] = field(default_factory=list)


# --- Step 1: the copy -----------------------------------------------------------------------
def backup_settings(claude_dir: Path) -> Path | None:
    """Copies ``settings.json`` byte for byte, once. Returns the copy, or ``None`` if no file."""
    source = claude_dir / "settings.json"
    target = claude_dir / BACKUP_NAME
    if target.exists():
        return target
    if not source.is_file():
        return None
    target.write_bytes(source.read_bytes())
    return target


# --- Step 2: the read switch ----------------------------------------------------------------
def read_switch_path(home: Path, data_dir: Path | None = None) -> Path | None:
    directory = install.data_dir_for(home, data_dir)
    return directory / READ_SWITCH_FILE if directory is not None else None


def _switch_active(target: Path) -> bool | None:
    try:
        data = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    value = data.get("active") if isinstance(data, dict) else None
    return value if isinstance(value, bool) else None


def carry_read_switch(
    home: Path, claude_dir: Path, *, data_dir: Path | None, now: str
) -> tuple[bool, str | None]:
    """Writes the read-hook state from the settings registration. ``(ok, message)``.

    Never lowers it: an existing ``{"active": true}`` stays. A registered hook raises an existing
    ``false`` to ``true``, because the registration is the 0.39 user's decision to have it on.
    """
    registered = install.read_hook_registered(claude_dir)
    target = read_switch_path(home, data_dir)
    if target is None:
        if registered:
            return False, t("plugin.migration.switch_without_data_dir")
        return True, None
    current = _switch_active(target) if target.exists() else None
    if target.exists() and current is not None and (current or not registered):
        return True, None
    install_state.write_json_atomic(target, {"active": registered, "since": now})
    return True, None


# --- Steps 3 and 4: the CLI ------------------------------------------------------------------
def _run(
    runner: claude_plugin.Runner, argv: list[str], env: Mapping[str, str] | None
) -> tuple[bool, str]:
    try:
        done = runner(argv, env)
    except (OSError, ValueError) as exc:
        return False, str(exc)
    except Exception as exc:  # a timeout or anything the CLI throws: the migration stops cleanly
        return False, f"{type(exc).__name__}: {exc}"
    detail = (done.stderr or done.stdout or "").strip()
    return done.returncode == 0, detail if done.returncode != 0 else (done.stdout or "")


def _listed(
    runner: claude_plugin.Runner, claude_bin: str, env: Mapping[str, str] | None
) -> tuple[bool, dict | None, str]:
    ok, output = _run(runner, claude_plugin.list_argv(claude_bin), env)
    return ok, (claude_plugin.listed_entry(output) if ok else None), output


# --- Step 5: the removal ---------------------------------------------------------------------
def remove_settings_hooks(claude_dir: Path) -> int:
    """Removes our hook entries from ``settings.json`` and our hooks folder. Returns the count."""
    hooks_dir = claude_dir / "hooks" / install.HOOKS_SUBDIR
    path = claude_dir / "settings.json"
    removed = 0
    if path.is_file():
        removed = install.update_config_json(
            path, lambda settings: install.strip_hook_settings(settings, hooks_dir)
        )
    if hooks_dir.is_dir():
        shutil.rmtree(hooks_dir)
    return removed


# --- The orchestration -----------------------------------------------------------------------
def apply_plugin_delivery(
    home: Path,
    *,
    claude_bin: str,
    ld_bin: str,
    language: str,
    version: str,
    runner: claude_plugin.Runner = claude_plugin.run_subprocess,
    env: Mapping[str, str] | None = None,
    data_dir: Path | None = None,
    claude_dir: Path | None = None,
    now: str | None = None,
) -> MigrationResult:
    """Installs the plugin and retires the settings delivery, in the order of the module doc."""
    claude_dir = claude_dir or home / ".claude"
    now = now or install_state.now_iso()

    # 1. The copy, before anything can rewrite the file.
    try:
        backup = backup_settings(claude_dir)
    except OSError as exc:
        return _failed("backup", t("plugin.migration.backup_failed", detail=exc))

    # 2. The read switch, before anything is removed.
    try:
        switch_ok, message = carry_read_switch(home, claude_dir, data_dir=data_dir, now=now)
    except OSError as exc:
        switch_ok, message = False, t("plugin.migration.switch_failed", detail=exc)
    if not switch_ok:
        return _failed("read_switch", message or "", backup=backup)

    state = install_state.load(home, data_dir)
    owned = install_state.piece(state, "plugin") is not None
    ok, before, _output = _listed(runner, claude_bin, env)
    foreign_plugin = ok and before is not None and not owned

    # 3. Marketplace and install.
    steps = (
        ("marketplace_add", claude_plugin.marketplace_add_argv(claude_bin)),
        ("install", claude_plugin.install_argv(claude_bin, ld_bin, language)),
    )
    for step, argv in steps:
        ok, detail = _run(runner, argv, env)
        if not ok:
            return _failed(
                step, t("plugin.migration.step_failed", step=step, detail=detail), backup
            )

    # 4. It is there, enabled and current.
    ok, entry, output = _listed(runner, claude_bin, env)
    if not ok:
        return _failed(
            "list", t("plugin.migration.step_failed", step="list", detail=output), backup
        )
    if not claude_plugin.entry_is_current(entry, version):
        found = json.dumps(entry, ensure_ascii=False) if entry else "-"
        return _failed(
            "list", t("plugin.migration.not_current", version=version, found=found), backup
        )

    # 5. Only now, the settings delivery goes.
    try:
        removed = remove_settings_hooks(claude_dir)
    except (OSError, install.UnreadableConfigError) as exc:
        return _failed("remove", t("plugin.migration.remove_failed", detail=exc), backup)

    # 6. The state.
    new_state = dict(state) if state else install_state.new_state(claude_plugin.PLUGIN, version)
    new_state.update(
        {"claude_delivery": claude_plugin.PLUGIN, "version": version, "updated_at": now}
    )
    if not foreign_plugin:
        if install_state.piece(new_state, "plugin") is None:
            new_state = install_state.with_piece(
                new_state, "plugin", now=now, id=claude_plugin.PLUGIN_ID
            )
        if install_state.piece(new_state, "marketplace") is None:
            new_state = install_state.with_piece(
                new_state, "marketplace", now=now, name=claude_plugin.MARKETPLACE_NAME
            )
    install_state.save(home, new_state, data_dir)

    messages = [t("plugin.migration.done", plugin=claude_plugin.PLUGIN_ID, version=version)]
    if removed:
        messages.append(t("plugin.migration.removed", count=removed))
    if backup is not None:
        messages.append(t("plugin.migration.backup", path=backup))
    return MigrationResult(True, claude_plugin.PLUGIN, removed, backup, None, messages)


def revert_to_settings(
    home: Path,
    *,
    claude_bin: str,
    restore_settings: Callable[[bool], None],
    runner: claude_plugin.Runner = claude_plugin.run_subprocess,
    env: Mapping[str, str] | None = None,
    data_dir: Path | None = None,
    now: str | None = None,
) -> MigrationResult:
    """REQ-008 b: uninstalls the plugin and restores the settings delivery in the same step.

    ``restore_settings(read_hook_enabled)`` is the settings delivery of ``install``; it gets the
    read switch so the block survives the way back too. The plugin goes first: if its uninstall
    fails, settings are not restored on top of it (that would duplicate every hook).
    """
    now = now or install_state.now_iso()
    ok, detail = _run(runner, claude_plugin.uninstall_argv(claude_bin), env)
    if not ok:
        return _failed(
            "uninstall", t("plugin.migration.step_failed", step="uninstall", detail=detail)
        )
    state = install_state.load(home, data_dir)
    messages = []
    if state is None or install_state.piece(state, "marketplace") is not None:
        removed_ok, detail = _run(runner, claude_plugin.marketplace_remove_argv(claude_bin), env)
        if not removed_ok:
            messages.append(
                t("plugin.migration.step_failed", step="marketplace_remove", detail=detail)
            )

    switch = read_switch_path(home, data_dir)
    read_hook_enabled = bool(switch and _switch_active(switch))
    try:
        restore_settings(read_hook_enabled)
    except Exception as exc:  # the caller's writer: report it, the plugin is already gone
        return _failed("restore", t("plugin.revert.restore_failed", detail=exc))

    new_state = dict(state) if state else install_state.new_state(claude_plugin.SETTINGS, "")
    new_state.update({"claude_delivery": claude_plugin.SETTINGS, "updated_at": now})
    new_state = install_state.without_piece(new_state, "plugin")
    new_state = install_state.without_piece(new_state, "marketplace")
    install_state.save(home, new_state, data_dir)
    messages.append(t("plugin.revert.done"))
    return MigrationResult(True, claude_plugin.SETTINGS, messages=messages)


def _failed(step: str, message: str, backup: Path | None = None) -> MigrationResult:
    return MigrationResult(
        False, None, backup=backup, failed_step=step, messages=[message] if message else []
    )
