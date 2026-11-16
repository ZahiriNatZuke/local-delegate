"""codex_plugin.py — what Codex CLI accepts in a plugin's ``hooks/hooks.json``, and our plugin in it.

Issue #668. Codex imports Claude Code marketplaces (it reads ``.claude-plugin/marketplace.json``
and ``.claude-plugin/plugin.json``), so the Claude plugin of local-delegate can end up enabled in
Codex by hand. Its ``hooks/hooks.json`` is not in the format Codex reads, and Codex says so only
as a startup warning while the process still exits 0.

The rules below are the Codex CLI 0.169.0 parser (``openai/codex``, tag ``rust-v0.169.0``):

- ``codex-rs/config/src/hook_config.rs``: ``HooksFile`` is ``deny_unknown_fields`` with only
  ``description`` and ``hooks``. Any other top-level key (``modules``, the Claude mod) rejects the
  **whole file**: ``unknown field `modules`, expected `description` or `hooks```.
- ``codex-rs/protocol/src/hooks.rs``: ``HookEventsToml`` lists the events; an unknown event is
  ignored without a warning. ``MatcherGroup`` holds ``matcher`` and ``hooks``. A handler is tagged
  by ``type`` (``command``, ``mcp_tool``, ``prompt``, ``agent``): an unknown ``type`` rejects the
  file, an unknown field (``args``) is dropped without a warning.
- ``codex-rs/hooks/src/engine/discovery.rs``: the command runs with ``PLUGIN_ROOT``,
  ``CLAUDE_PLUGIN_ROOT``, ``PLUGIN_DATA`` and ``CLAUDE_PLUGIN_DATA`` in its environment. Nothing
  expands Claude's ``${user_config.…}``: it reaches the shell as written.
- ``codex-rs/core-plugins/src/loader.rs``: with no ``hooks`` entry in the manifest the file read is
  ``hooks/hooks.json``; the cache is ``<CODEX_HOME>/plugins/cache/<marketplace>/<plugin>/<version>``
  and ``config.toml`` keeps ``[plugins."<plugin>@<marketplace>"] enabled = …``.

Measured on Codex 0.169.0 with a temporary ``CODEX_HOME`` (app-server ``hooks/list``): the
packaged Claude ``hooks.json`` gives that warning and zero hooks; without ``modules`` Codex lists
the hooks, but with ``command = "${user_config.ld_bin}"`` and no arguments.

Not checked: the value types (a ``command`` handler without ``command``, a number where Codex
wants text). Codex rejects those files too, so a clean result is not proof of loading.

Only reads: it never writes Codex files, never builds a ``Result`` and never imports ``checks``.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

PLUGIN_NAME = "local-delegate"

#: The Codex CLI version whose parser these rules copy.
CODEX_VERSION_CHECKED = "0.169.0"

#: Default hooks file of a plugin (`DEFAULT_HOOKS_CONFIG_FILE` in `loader.rs`).
HOOKS_FILE = Path("hooks") / "hooks.json"

#: `HooksFile` (`deny_unknown_fields`): any other top-level key rejects the file.
HOOKS_FILE_KEYS = frozenset({"description", "hooks"})

#: `HookEventsToml`: the events Codex dispatches. Another name is ignored without a warning.
HOOK_EVENTS = frozenset(
    {
        "PreModelRequest",
        "PostModelRequest",
        "PreToolUse",
        "PermissionRequest",
        "PostToolUse",
        "PreCompact",
        "PostCompact",
        "SessionStart",
        "SessionEnd",
        "UserPromptSubmit",
        "SubagentStart",
        "SubagentStop",
        "Stop",
        "Interrupt",
    }
)

#: `MatcherGroup`: other keys are ignored.
MATCHER_GROUP_KEYS = frozenset({"matcher", "hooks"})

#: `HookHandlerConfig`, by its `type` tag: the fields each variant reads. An unknown `type` rejects
#: the file; an unknown field is dropped.
HANDLER_FIELDS = {
    "command": frozenset(
        {
            "type",
            "command",
            "commandWindows",
            "command_windows",
            "timeout",
            "async",
            "statusMessage",
            "additionalContextLimit",
        }
    ),
    "mcp_tool": frozenset({"type", "server", "tool", "input", "timeout", "statusMessage"}),
    "prompt": frozenset({"type"}),
    "agent": frozenset({"type"}),
}

#: Claude Code's plugin option syntax: Codex does not expand it.
CLAUDE_USER_CONFIG = "${user_config."

#: What a finding does to the file in Codex.
REJECTED = "rejected"  # Codex refuses the whole file: no hook of it loads
DROPPED = "dropped"  # Codex loads the file but this piece is lost or runs differently


@dataclass(frozen=True)
class Finding:
    """One thing of a ``hooks.json`` that Codex does not read as written."""

    effect: str  # REJECTED or DROPPED
    where: str  # JSON path, e.g. `modules` or `hooks.PreToolUse[0].hooks[0].args`
    reason: str  # stable code: unknown_top_key, unknown_event, unknown_type, unknown_field, …


def check_hooks_file(data: object) -> list[Finding]:
    """What Codex would reject or drop of an already parsed ``hooks.json``. ``[]``: it reads it all."""
    if not isinstance(data, dict):
        return [Finding(REJECTED, "$", "not_an_object")]
    findings = [
        Finding(REJECTED, key, "unknown_top_key") for key in data if key not in HOOKS_FILE_KEYS
    ]
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        return [*findings, Finding(REJECTED, "hooks", "not_an_object")]
    for event, groups in hooks.items():
        where = f"hooks.{event}"
        if event not in HOOK_EVENTS:
            findings.append(Finding(DROPPED, where, "unknown_event"))
            continue
        if not isinstance(groups, list):
            findings.append(Finding(REJECTED, where, "not_a_list"))
            continue
        for g, group in enumerate(groups):
            findings.extend(_check_group(group, f"{where}[{g}]"))
    return findings


def _check_group(group: object, where: str) -> list[Finding]:
    if not isinstance(group, dict):
        return [Finding(REJECTED, where, "not_an_object")]
    findings = [
        Finding(DROPPED, f"{where}.{key}", "unknown_field")
        for key in group
        if key not in MATCHER_GROUP_KEYS
    ]
    handlers = group.get("hooks", [])
    if not isinstance(handlers, list):
        return [*findings, Finding(REJECTED, f"{where}.hooks", "not_a_list")]
    for h, handler in enumerate(handlers):
        findings.extend(_check_handler(handler, f"{where}.hooks[{h}]"))
    return findings


def _check_handler(handler: object, where: str) -> list[Finding]:
    if not isinstance(handler, dict):
        return [Finding(REJECTED, where, "not_an_object")]
    kind = handler.get("type")
    fields = HANDLER_FIELDS.get(kind) if isinstance(kind, str) else None
    if fields is None:
        return [Finding(REJECTED, f"{where}.type", "unknown_type")]
    findings = [
        Finding(DROPPED, f"{where}.{key}", "unknown_field") for key in handler if key not in fields
    ]
    for key in ("command", "commandWindows", "command_windows"):
        value = handler.get(key)
        if isinstance(value, str) and CLAUDE_USER_CONFIG in value:
            findings.append(Finding(DROPPED, f"{where}.{key}", "claude_user_config"))
    return findings


def rejected(findings: list[Finding]) -> bool:
    return any(finding.effect == REJECTED for finding in findings)


@dataclass(frozen=True)
class CachedPlugin:
    """One cached version of our plugin under ``<codex_dir>/plugins/cache``."""

    marketplace: str
    version: str
    root: Path
    enabled: bool | None  # what Codex does with `[plugins."…"]`; None: no entry or unreadable
    findings: tuple[Finding, ...] | None  # None: no hooks file, or it could not be read
    read_error: str | None = None  # why the hooks file could not be read or parsed

    @property
    def plugin_id(self) -> str:
        return f"{PLUGIN_NAME}@{self.marketplace}"


def _enabled_plugins(codex_dir: Path) -> dict[str, bool]:
    """Whether Codex loads each ``[plugins."<id>"]`` of ``config.toml``; ``{}`` if unreadable.

    Codex loads only the plugins configured there, and an entry without ``enabled`` counts as
    enabled (``plugin.enabled.unwrap_or(true)`` in ``loader.rs``). A plugin that is only in the
    cache, with no entry, is not loaded. A non-boolean ``enabled`` is left out: Codex would not
    parse that ``config.toml``.
    """
    try:
        config = tomllib.loads((codex_dir / "config.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, RecursionError, tomllib.TOMLDecodeError):
        return {}
    plugins = config.get("plugins")
    if not isinstance(plugins, dict):
        return {}
    found = {}
    for key, value in plugins.items():
        if not isinstance(value, dict):
            continue
        flag = value.get("enabled", True)
        if isinstance(flag, bool):
            found[key] = flag
    return found


def _subdirs(path: Path) -> list[Path]:
    """The folders inside ``path``, sorted; an unreadable one is skipped, not fatal."""
    try:
        entries = list(path.iterdir())
    except OSError:
        return []
    found = []
    for entry in entries:
        try:
            if entry.is_dir():
                found.append(entry)
        except OSError:
            continue
    return sorted(found)


def cached_plugins(codex_dir: Path) -> list[CachedPlugin]:
    """Every cached version of ``local-delegate`` in Codex, from any marketplace, sorted."""
    marketplaces = _subdirs(codex_dir / "plugins" / "cache")
    if not marketplaces:
        return []
    enabled = _enabled_plugins(codex_dir)
    found: list[CachedPlugin] = []
    for marketplace in marketplaces:
        versions = _subdirs(marketplace / PLUGIN_NAME)
        plugin_id = f"{PLUGIN_NAME}@{marketplace.name}"
        for root in versions:
            findings, error = _read_findings(root / HOOKS_FILE)
            found.append(
                CachedPlugin(
                    marketplace=marketplace.name,
                    version=root.name,
                    root=root,
                    enabled=enabled.get(plugin_id),
                    findings=findings,
                    read_error=error,
                )
            )
    return found


def _read_findings(path: Path) -> tuple[tuple[Finding, ...] | None, str | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, None
    except UnicodeDecodeError as exc:
        # Codex reads it as UTF-8 too (`read_to_string`): it cannot read it either.
        return (Finding(REJECTED, "$", "invalid_utf8"),), str(exc)
    except OSError as exc:
        return None, str(exc.strerror or exc)
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        # Codex rejects it too (`failed to parse plugin hooks config`).
        return (Finding(REJECTED, "$", "invalid_json"),), str(exc)
    try:
        return tuple(check_hooks_file(data)), None
    except RecursionError as exc:
        return (Finding(REJECTED, "$", "invalid_json"),), str(exc)
