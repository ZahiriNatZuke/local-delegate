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

Inside WSL Claude Code stays on settings (REQ-005): there no plugin is expected, and its absence
is not a fault. The helpers ``uses_plugin`` and ``our_settings_hooks`` are also what the hooks
checks of ``checks`` use to read their state by delivery.

Only reads, without ``Result``: the probes live in ``checks``, which imports this module.
This one never imports ``checks`` (CodeQL ``py/cyclic-import``, PR #400).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from . import claude_plugin, install, install_state

UPDATE_HINT = "local-delegate update"
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


def same_path(a: str | Path, b: str | Path) -> bool:
    # No `resolve()`: on macOS the interpreter of a `uv tool` environment is a symlink to the base
    # Python, and resolving would make every environment look like the same one.
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
