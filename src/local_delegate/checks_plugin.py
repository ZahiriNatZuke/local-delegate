"""checks_plugin.py — what the `doctor` checks of the Claude Code plugin delivery read.

REQ-009 and REQ-008 c (SDD claude-plugin-and-mods, batch F1-doctor). The five checks are probes in
``checks`` (``_probe_delivery`` and the rest), registered in ``checks.CHECKS`` like every other
one; this module holds what they read, and never builds a ``Result``:

- ``claude.delivery``: the delivery ``install-state.json`` records (``install_state``). No state
  means an install from before 0.40: ``unknown``, not a guess.
- ``claude.version``: ``claude --version`` against ``MIN_CLAUDE_PLUGIN_VERSION``.
- ``plugin.installed``: ``claude plugin list --json`` lists it enabled, at the package version and
  with the ``language`` option of the current language.
- ``plugin.ld_bin``: the ``ld_bin`` option points to an interpreter that exists and that is the one
  of the installed ``uv tool`` environment.
- ``hooks.duplicates``: our hooks in ``settings.json`` while the plugin is enabled, so every event
  runs twice (a downgrade to 0.39 without ``uninstall``).
- ``mod.loaded`` (F2-mod-core): the newest heartbeat the mod wrote at a session's start
  (``heartbeats/<session_id>.json`` in the plugin's data folder), with the state of each piece.
- ``mod.read_overlap`` (F4-hooks-swap, REQ-023): the ``read_mod_enabled`` option, the read hook's
  active layer (``read-hook.json``) and our read hooks in ``settings.json``.

Inside WSL Claude Code stays on settings (REQ-005): there no plugin is expected, and its absence
is not a fault. The helpers ``uses_plugin`` and ``our_settings_hooks`` are also what the hooks
checks of ``checks`` use to read their state by delivery.

Only reads, without ``Result``: the probes live in ``checks``, which imports this module.
This one never imports ``checks`` (CodeQL ``py/cyclic-import``, PR #400).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from pathlib import Path

from . import claude_plugin, install, install_state, plugin_migration

UPDATE_HINT = "local-delegate update"
READ_LAYER_HINT = "local-delegate install --enable-read-hook"
INSTALL_HINT = "local-delegate install"


# --- Shared reads ----------------------------------------------------------------------------
def environ(ctx) -> Mapping[str, str]:
    return os.environ if ctx.environ is None else ctx.environ


def in_wsl(ctx) -> bool:
    return claude_plugin.is_wsl(environ(ctx))


def state(ctx) -> dict | None:
    """``install-state.json`` by the rule of ``language.json`` (``ctx.log_dir`` or ``LOG_DIR``)."""
    return install_state.load(ctx.home, ctx.log_dir)


def delivery(ctx) -> str | None:
    """The Claude Code delivery: settings inside WSL, else the state's; ``None`` if unknown."""
    if in_wsl(ctx):
        return claude_plugin.SETTINGS
    return install_state.delivery(state(ctx))


def uses_plugin(ctx) -> bool:
    return delivery(ctx) == claude_plugin.PLUGIN


def plugin_enabled(settings: dict | None) -> bool:
    """``enabledPlugins`` of ``settings.json``: what Claude Code itself reads to load it."""
    enabled = (settings or {}).get("enabledPlugins")
    return isinstance(enabled, dict) and enabled.get(claude_plugin.PLUGIN_ID) is True


def plugin_options(settings: dict | None) -> dict:
    """The plugin's non-secret ``userConfig`` values: ``pluginConfigs.<id>.options`` (research r1)."""
    configs = (settings or {}).get("pluginConfigs")
    entry = configs.get(claude_plugin.PLUGIN_ID) if isinstance(configs, dict) else None
    options = entry.get("options") if isinstance(entry, dict) else None
    return options if isinstance(options, dict) else {}


def our_settings_hooks(settings: dict | None, hooks_dir: Path) -> list[str]:
    """``event/matcher`` of every hook of ours in ``settings.json`` (``install._is_ours``)."""
    hooks = (settings or {}).get("hooks")
    if not isinstance(hooks, dict):
        return []
    found: list[str] = []
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            for hook in group.get("hooks", []):
                if isinstance(hook, dict) and install._is_ours(hook, hooks_dir):
                    matcher = group.get("matcher")
                    found.append(f"{event}{'/' + matcher if matcher else ''}")
    return found


# --- The mod's heartbeat (F2-mod-core, decision 9) -------------------------------------------
#: A heartbeat older than this is not evidence that the mod loads today: the horizon decision 9
#: gives the heartbeats.
HEARTBEAT_MAX_AGE_DAYS = 7


def heartbeat_dir(ctx) -> Path:
    """Where the mod writes ``<session_id>.json``: the plugin's ``CLAUDE_PLUGIN_DATA`` (T0)."""
    data = f"{claude_plugin.PLUGIN_NAME}-{claude_plugin.MARKETPLACE_NAME}"
    return ctx.claude_dir / "plugins" / "data" / data / "heartbeats"


def latest_heartbeat(ctx) -> tuple[Path, dict | None, str | None, float] | None:
    """The newest heartbeat: its path, its content (or ``None`` and why) and its age in days.

    ``None`` when no session has written one. By modification time: each session writes its own
    file at its start, so the newest file is the last session that loaded the mod.
    """
    folder = heartbeat_dir(ctx)
    try:
        files = [p for p in folder.glob("*.json") if p.is_file()]
    except OSError:
        return None
    if not files:
        return None
    newest = max(files, key=lambda p: p.stat().st_mtime)
    age_days = max(0.0, (time.time() - newest.stat().st_mtime) / 86400)
    try:
        data = json.loads(newest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return newest, None, str(exc), age_days
    if not isinstance(data, dict):
        return newest, None, type(data).__name__, age_days
    return newest, data, None, age_days


def same_path(a: str | Path, b: str | Path) -> bool:
    # No `resolve()`: on macOS the interpreter of a `uv tool` environment is a symlink to the base
    # Python, and resolving would make every environment look like the same one.
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


# --- The read mod and the read hooks (F4-hooks-swap, REQ-023, decision 10) -------------------
#: The matchers of our read hooks (`Read`, other MCPs' read tools, `Bash|PowerShell`).
READ_HOOK_MATCHERS = frozenset(
    matcher
    for _script, _event, matcher in (
        install._READ_HOOK,
        install._MCP_READ_HOOK,
        install._SHELL_HOOK,
    )
)


def read_mod_enabled(settings: dict | None) -> bool:
    """The plugin's ``read_mod_enabled`` option (off by default)."""
    return plugin_options(settings).get("read_mod_enabled") is True


def read_layer_active(ctx) -> bool:
    """The read hook's active layer: ``read-hook.json`` in the data folder, or
    ``LD_HOOK_READ_ENABLED`` in the environment doctor runs in (``read_switch.enabled``)."""
    if str(environ(ctx).get("LD_HOOK_READ_ENABLED", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True
    target = plugin_migration.read_switch_path(ctx.home, ctx.log_dir)
    if target is None:
        return False
    try:
        data = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("active") is True


def settings_read_hooks(settings: dict | None, hooks_dir: Path) -> list[str]:
    """``event/matcher`` of our read hooks in ``settings.json``: they never see the plugin's option,
    so they never step aside for the read mod."""
    return [
        found
        for found in our_settings_hooks(settings, hooks_dir)
        if found.partition("/")[2] in READ_HOOK_MATCHERS
    ]
