"""checks_plugin.py — the `doctor` checks of the Claude Code plugin delivery.

REQ-009 and REQ-008 c (SDD claude-plugin-and-mods, batch F1-doctor). Five checks, registered in
``checks.CHECKS`` like every other one and with the same three rules: a probe never writes, what
could not be checked is ``unknown`` and never ``missing``, and it is a list, not a framework.

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

``checks`` imports this module, so this one reaches ``checks`` only inside the functions.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from . import claude_plugin, i18n, install, install_state

UPDATE_HINT = "local-delegate update"
INSTALL_HINT = "local-delegate install"


def _checks():
    from . import checks  # deferred: `checks` imports this module while it loads

    return checks


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


def _settings(ctx) -> tuple[Path, dict | None, str | None]:
    path = ctx.claude_dir / "settings.json"
    data, reason = _checks().read_json(path)
    return path, data, reason


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


def _same_path(a: str | Path, b: str | Path) -> bool:
    # No `resolve()`: on macOS the interpreter of a `uv tool` environment is a symlink to the base
    # Python, and resolving would make every environment look like the same one.
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _not_applicable(ctx):
    """``ok`` when the plugin is not the delivery here (WSL or settings), else ``None``."""
    checks = _checks()
    if in_wsl(ctx):
        return checks.Result(checks.OK, i18n.t("doctor.probe.plugin.wsl"))
    if not uses_plugin(ctx):
        return checks.Result(checks.OK, i18n.t("doctor.probe.plugin.not_used"))
    return None


def _cli_missing(ctx):
    checks = _checks()
    return checks.Result(checks.UNKNOWN, i18n.t("doctor.probe.claude_version.no_cli"))


# --- Probes ----------------------------------------------------------------------------------
def probe_delivery(ctx):
    checks = _checks()
    if absent := checks._claude_absent(ctx):
        return absent
    if in_wsl(ctx):
        return checks.Result(checks.OK, i18n.t("doctor.probe.claude_delivery.wsl"))
    current = state(ctx)
    found = install_state.delivery(current)
    path = install_state.path(ctx.home, ctx.log_dir)
    if found in (claude_plugin.PLUGIN, claude_plugin.SETTINGS):
        return checks.Result(
            checks.OK,
            i18n.t(
                "doctor.probe.claude_delivery.recorded",
                delivery=found,
                version=(current or {}).get("version") or "?",
                path=path,
            ),
        )
    return checks.Result(
        checks.UNKNOWN, i18n.t("doctor.probe.claude_delivery.no_state", path=path or "-")
    )


def probe_claude_version(ctx):
    checks = _checks()
    if in_wsl(ctx):
        return checks.Result(checks.OK, i18n.t("doctor.probe.plugin.wsl"))
    claude_bin = ctx.claude_which("claude")
    if not claude_bin or ctx.claude_runner is None:
        return _cli_missing(ctx)
    env = claude_plugin.child_env(ctx.home)
    version, _raw = claude_plugin.claude_version(claude_bin, ctx.claude_runner, env)
    minimum = claude_plugin.MIN_CLAUDE_PLUGIN_VERSION
    if version is None:
        return checks.Result(checks.UNKNOWN, i18n.t("doctor.probe.claude_version.unknown"))
    if not claude_plugin.version_at_least(version, minimum):
        return checks.Result(
            checks.WARN,
            i18n.t("doctor.probe.claude_version.below", found=version, minimum=minimum),
            i18n.t("doctor.hint.claude_update"),
        )
    return checks.Result(
        checks.OK, i18n.t("doctor.probe.claude_version.ok", found=version, minimum=minimum)
    )


def _listed(ctx):
    """``(entry, None)`` from ``claude plugin list --json``, or ``(None, an unknown Result)``."""
    checks = _checks()
    claude_bin = ctx.claude_which("claude")
    if not claude_bin or ctx.claude_runner is None:
        return None, _cli_missing(ctx)
    argv = claude_plugin.list_argv(claude_bin)
    try:
        done = ctx.claude_runner(argv, claude_plugin.child_env(ctx.home))
    except Exception as exc:  # the CLI did not start or did not finish: nothing to claim
        return None, checks.Result(
            checks.UNKNOWN, i18n.t("doctor.probe.plugin_installed.list_failed", detail=exc)
        )
    if done.returncode != 0:
        detail = ((done.stderr or done.stdout or "").strip() or str(done.returncode))[:200]
        return None, checks.Result(
            checks.UNKNOWN, i18n.t("doctor.probe.plugin_installed.list_failed", detail=detail)
        )
    return claude_plugin.listed_entry(done.stdout), None


def probe_plugin_installed(ctx):
    checks = _checks()
    if absent := checks._claude_absent(ctx):
        return absent
    if skip := _not_applicable(ctx):
        return skip
    entry, failure = _listed(ctx)
    if failure is not None:
        return failure
    if entry is None:
        return checks.Result(
            checks.MISSING,
            i18n.t("doctor.probe.plugin_installed.not_listed", plugin=claude_plugin.PLUGIN_ID),
            UPDATE_HINT,
        )
    problems: list[str] = []
    hint = ""
    if entry.get("enabled") is not True:
        problems.append(i18n.t("doctor.probe.plugin_installed.disabled"))
        hint = i18n.t("doctor.hint.plugin_enable", plugin=claude_plugin.PLUGIN_ID)
    expected = checks._installed_version()
    found = entry.get("version")
    if expected and found != expected:
        problems.append(
            i18n.t("doctor.probe.plugin_installed.version", found=found or "?", expected=expected)
        )
        hint = hint or UPDATE_HINT
    _path, settings, _reason = _settings(ctx)
    language = plugin_options(settings).get("language")
    current = i18n.lang()
    if isinstance(language, str) and language != current:
        problems.append(
            i18n.t("doctor.probe.plugin_installed.language", found=language, current=current)
        )
        hint = hint or INSTALL_HINT
    if problems:
        return checks.Result(checks.WARN, " · ".join(problems), hint)
    return checks.Result(
        checks.OK,
        i18n.t(
            "doctor.probe.plugin_installed.ok",
            plugin=claude_plugin.PLUGIN_ID,
            version=found or "?",
            language=language if isinstance(language, str) else "-",
        ),
    )


def probe_ld_bin(ctx):
    checks = _checks()
    if absent := checks._claude_absent(ctx):
        return absent
    if skip := _not_applicable(ctx):
        return skip
    path, settings, reason = _settings(ctx)
    if reason:
        return checks.Result(checks.UNKNOWN, reason)
    value = plugin_options(settings).get("ld_bin")
    if not isinstance(value, str) or not value.strip():
        return checks.Result(
            checks.MISSING, i18n.t("doctor.probe.ld_bin.not_set", path=path), INSTALL_HINT
        )
    if not Path(value).is_file():
        return checks.Result(
            checks.MISSING, i18n.t("doctor.probe.ld_bin.not_found", ld_bin=value), INSTALL_HINT
        )
    expected = ctx.expected_ld_bin()
    expected_path = getattr(expected, "path", None)
    if expected_path is None:
        return checks.Result(
            checks.OK,
            i18n.t(
                "doctor.probe.ld_bin.not_compared",
                ld_bin=value,
                reason=getattr(expected, "reason", None) or "-",
            ),
        )
    if not _same_path(value, expected_path):
        return checks.Result(
            checks.WARN,
            i18n.t("doctor.probe.ld_bin.other_env", ld_bin=value, expected=expected_path),
            INSTALL_HINT,
        )
    return checks.Result(checks.OK, i18n.t("doctor.probe.ld_bin.ok", ld_bin=value))


def probe_hook_duplicates(ctx):
    checks = _checks()
    if absent := checks._claude_absent(ctx):
        return absent
    path, settings, reason = _settings(ctx)
    if reason:
        return checks.Result(checks.UNKNOWN, reason)
    ours = our_settings_hooks(settings, ctx.hooks_dir)
    if ours and plugin_enabled(settings):
        return checks.Result(
            checks.WARN,
            i18n.t(
                "doctor.probe.hook_duplicates.found",
                n=i18n.format_number(len(ours)),
                path=path,
                plugin=claude_plugin.PLUGIN_ID,
            ),
            UPDATE_HINT,
        )
    return checks.Result(checks.OK, i18n.t("doctor.probe.hook_duplicates.none"))
