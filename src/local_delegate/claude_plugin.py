"""claude_plugin.py — when Claude Code gets local-delegate as a plugin, and the commands for it.

REQ-005 (SDD claude-plugin-and-mods). This module decides the delivery (plugin or settings),
finds ``ld_bin`` and builds the argv of every ``claude plugin …`` call. It runs nothing on its own:
the runner is injected (``Runner``), so the tests never reach the real CLI and ``--dry-run`` can
print the same commands it would run.

Facts from the T0 measurement (``.sdd/changes/claude-plugin-and-mods/evidence/T0.md``):

- ``MIN_CLAUDE_PLUGIN_VERSION`` is 2.1.292: the first version with every plugin feature we use.
- ``claude plugin`` honours ``CLAUDE_CONFIG_DIR`` (measured on Windows), so a simulated HOME gets
  ``CLAUDE_CONFIG_DIR=<home>/.claude`` in the child environment and never touches the real config.
- The hooks run ``<ld_bin> -I -m local_delegate.hook <name>``, with ``ld_bin`` the **interpreter of
  the ``uv tool`` environment** (fail-open path B). A ``userConfig`` default does not fill
  ``${user_config.ld_bin}``, so ``install`` always passes ``--config ld_bin=…``.
"""

from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import install
from .i18n import t
from .simulated_home import is_simulated_home

#: Lowest Claude Code version for the plugin delivery (T0: path B, `install --marketplace`).
MIN_CLAUDE_PLUGIN_VERSION = "2.1.292"

PLUGIN_NAME = "local-delegate"
MARKETPLACE_NAME = "local-delegate"
PLUGIN_ID = f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"

PLUGIN = "plugin"
SETTINGS = "settings"

#: Platforms where T0 or the CI `plugin` job verified that `claude plugin` honours
#: `CLAUDE_CONFIG_DIR`. Elsewhere a simulated HOME falls back to settings (REQ-005).
CLAUDE_CONFIG_DIR_VERIFIED = frozenset({"win32"})

#: Seconds a `claude plugin …` call may take. `install` copies the plugin into the cache.
TIMEOUT = 180.0

#: `runner(argv, env)`: runs a command. `env` holds only the variables to add, or `None`.
Runner = Callable[[Sequence[str], Mapping[str, str] | None], subprocess.CompletedProcess]


def run_subprocess(
    argv: Sequence[str], env: Mapping[str, str] | None
) -> subprocess.CompletedProcess:
    """The real runner: never interactive (stdin closed), UTF-8 output, bounded in time."""
    merged = {**os.environ, **env} if env else None
    return subprocess.run(
        list(argv),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT,
        env=merged,
    )


def marketplace_dir() -> Path:
    """The local marketplace shipped inside the package (plan, decision 1)."""
    return install.resources_dir() / "claude-plugin"


# --- Version --------------------------------------------------------------------------------
def parse_version(text: str | None) -> tuple[int, ...] | None:
    """``(2, 1, 307)`` from ``"2.1.307 (Claude Code)"``; ``None`` if there is no version."""
    for token in (text or "").split():
        parts = token.split(".")
        if len(parts) >= 2 and all(part.isdigit() for part in parts):
            return tuple(int(part) for part in parts)
    return None


def version_at_least(found: str, minimum: str = MIN_CLAUDE_PLUGIN_VERSION) -> bool:
    """Numeric comparison: 2.1.1000 is newer than 2.1.292."""
    have, need = parse_version(found), parse_version(minimum)
    return have is not None and need is not None and have >= need


def claude_version(
    claude_bin: str, runner: Runner, env: Mapping[str, str] | None
) -> tuple[str | None, str | None]:
    """``(version, None)`` or ``(None, raw output)`` when ``claude --version`` gives none."""
    try:
        done = runner([claude_bin, "--version"], env)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    raw = (done.stdout or "") + (done.stderr or "")
    version = parse_version(done.stdout) if done.returncode == 0 else None
    return (".".join(str(n) for n in version), None) if version else (None, raw.strip())


# --- ld_bin ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class LdBin:
    """The interpreter the plugin hooks will run, or why there is none (``reason``)."""

    path: str | None
    reason: str | None


def _env_python(prefix: Path) -> Path:
    """The interpreter of the environment at ``prefix``, by the platform's own install scheme."""
    folder = sysconfig.get_path("scripts", vars={"base": str(prefix)})
    return Path(folder) / ("python.exe" if sys.platform == "win32" else "python")


def _in_uv_cache(prefix: Path) -> bool:
    """True for an environment inside uv's cache, which is where ``uvx`` runs from."""
    parts = [part.lower() for part in prefix.parts]
    return any(a == "uv" and b == "cache" for a, b in itertools.pairwise(parts))


def resolve_ld_bin(prefix: Path | None = None) -> LdBin:
    """The interpreter of the ``uv tool`` environment that is running, or a reason to refuse.

    Only a ``uv tool`` install qualifies (plan, N-2). ``uvx`` runs from uv's cache, an editable
    install from a checkout and a ``.venv`` from a repo or worktree: any of them can disappear,
    and then every hook would stop acting without a word. Those go to settings, with a warning.
    """
    from . import update  # lazy: update imports install, which will import this module

    prefix = Path(prefix if prefix is not None else sys.prefix)
    if _in_uv_cache(prefix):
        return LdBin(None, "uvx_cache")
    kind = update.install_kind()
    if kind == update.EDITABLE:
        return LdBin(None, "editable")
    if kind != update.UV_TOOL:
        return LdBin(None, "not_uv_tool")
    python = _env_python(prefix)
    if not python.is_file():
        return LdBin(None, "no_python")
    return LdBin(str(python), None)


# --- Decision -------------------------------------------------------------------------------
@dataclass(frozen=True)
class Decision:
    """Which delivery Claude Code gets, and everything needed to carry it out or print it."""

    delivery: str
    reason: str | None = None
    warning: str | None = None
    claude_bin: str | None = None
    version: str | None = None
    ld_bin: str | None = None
    env: dict[str, str] | None = None


def child_env(home: Path) -> dict[str, str] | None:
    """Variables for every ``claude …`` child: the simulated config folder, or nothing."""
    if is_simulated_home(home):
        return {"CLAUDE_CONFIG_DIR": str(home / ".claude")}
    return None


def is_wsl(environ: Mapping[str, str]) -> bool:
    return bool(environ.get("WSL_DISTRO_NAME", "").strip())


def _fallback(reason: str, **values: object) -> Decision:
    keys = {
        "no_cli": "plugin.fallback.no_cli",
        "version_unknown": "plugin.fallback.version_unknown",
        "old_version": "plugin.fallback.old_version",
        "wsl": "plugin.fallback.wsl",
        "simulated_home": "plugin.fallback.simulated_home",
        "ld_bin_uvx_cache": "plugin.fallback.ld_bin_uvx_cache",
        "ld_bin_editable": "plugin.fallback.ld_bin_editable",
        "ld_bin_not_uv_tool": "plugin.fallback.ld_bin_not_uv_tool",
        "ld_bin_no_python": "plugin.fallback.ld_bin_no_python",
    }
    warning = t("plugin.fallback.lead", detail=t(keys[reason], **values))
    return Decision(SETTINGS, reason=reason, warning=warning)


def decide(
    home: Path,
    *,
    requested: str | None = None,
    runner: Runner = run_subprocess,
    which: Callable[[str], str | None] = shutil.which,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
    ld_bin: LdBin | None = None,
) -> Decision:
    """REQ-005: plugin with ``claude`` ≥ the minimum, outside WSL and with a known config folder.

    ``requested`` is ``--claude-delivery``: ``settings`` is honoured silently; ``plugin`` (or
    nothing) still falls back to settings when a condition fails, with a warning that says why.
    """
    if requested == SETTINGS:
        return Decision(SETTINGS)
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    if is_wsl(environ):
        return _fallback("wsl")
    if is_simulated_home(home) and platform not in CLAUDE_CONFIG_DIR_VERIFIED:
        return _fallback("simulated_home", platform=platform)
    claude_bin = which("claude")
    if not claude_bin:
        return _fallback("no_cli")
    env = child_env(home)
    version, raw = claude_version(claude_bin, runner, env)
    if version is None:
        return _fallback("version_unknown", output=(raw or "")[:120])
    if not version_at_least(version):
        return _fallback("old_version", found=version, minimum=MIN_CLAUDE_PLUGIN_VERSION)
    ld = ld_bin if ld_bin is not None else resolve_ld_bin()
    if ld.path is None:
        return _fallback(f"ld_bin_{ld.reason}", prefix=sys.prefix)
    return Decision(PLUGIN, claude_bin=claude_bin, version=version, ld_bin=ld.path, env=env)


# --- argv -----------------------------------------------------------------------------------
def marketplace_add_argv(claude_bin: str) -> list[str]:
    return [claude_bin, "plugin", "marketplace", "add", str(marketplace_dir())]


def marketplace_remove_argv(claude_bin: str) -> list[str]:
    return [claude_bin, "plugin", "marketplace", "remove", MARKETPLACE_NAME]


def install_argv(claude_bin: str, ld_bin: str, language: str) -> list[str]:
    """Non-interactive install: scope, both options and JSON output on the command line."""
    return [
        claude_bin,
        "plugin",
        "install",
        PLUGIN_ID,
        "--scope",
        "user",
        "--config",
        f"ld_bin={ld_bin}",
        "--config",
        f"language={language}",
        "--json",
    ]


def uninstall_argv(claude_bin: str) -> list[str]:
    return [claude_bin, "plugin", "uninstall", PLUGIN_ID, "--scope", "user"]


def list_argv(claude_bin: str) -> list[str]:
    return [claude_bin, "plugin", "list", "--json"]


def _display(argv: Sequence[str]) -> str:
    """A command as the user would type it: `claude` by name, arguments with spaces quoted."""
    shown = ["claude", *argv[1:]]
    return " ".join(f'"{part}"' if " " in part else part for part in shown)


def dry_run_lines(decision: Decision, *, language: str) -> list[str]:
    """The ``claude plugin …`` commands ``install`` would run; none for the settings delivery."""
    if decision.delivery != PLUGIN or not decision.claude_bin or not decision.ld_bin:
        return []
    claude_bin = decision.claude_bin
    commands = [
        marketplace_add_argv(claude_bin),
        install_argv(claude_bin, decision.ld_bin, language),
        list_argv(claude_bin),
    ]
    lines = [_display(argv) for argv in commands]
    if decision.env:
        prefix = " ".join(f"{name}={value}" for name, value in decision.env.items())
        lines = [f"{prefix} {line}" for line in lines]
    return lines


# --- `plugin list --json` -------------------------------------------------------------------
def listed_entry(stdout: str) -> dict | None:
    """Our entry in ``claude plugin list --json`` (a list of ``{"id", "version", "enabled"}``)."""
    try:
        data = json.loads(stdout or "")
    except ValueError:
        return None
    if isinstance(data, dict):
        entries = list(data.values())
    elif isinstance(data, list):
        entries = data
    else:
        return None
    for entry in entries:
        if isinstance(entry, dict) and entry.get("id") == PLUGIN_ID:
            return entry
    return None


def entry_is_current(entry: dict | None, version: str) -> bool:
    """Installed, enabled and at the package version."""
    return bool(entry) and entry.get("enabled") is True and entry.get("version") == version
