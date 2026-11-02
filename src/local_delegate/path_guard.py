"""Paths the tools never read or write, whatever `LOCAL_DELEGATE_ALLOWED_DIRS` says.

The MCP tools read `path` and write `target` on the server side, outside Claude Code's permission
prompts: the tools are usually allowed with a wildcard, so a prompt injection inside any file the
model reads could ask `local_summarize` for a credential (and get a summary of it back into the
context) or ask `local_boilerplate` to drop a script in an autostart folder. `ALLOWED_DIRS` stops
that only when it is set, and it is empty by default. This module is the floor that is always on.

Two families of rules:

- **credential** — denied for reading AND writing: files whose only content is a secret (SSH and
  cloud keys, registry tokens, the Claude Code and Claude Desktop configs that carry tokens).
- **autostart** and **executable_config** — denied for writing only: places where a written file
  runs later without anyone launching it (Startup folders, LaunchAgents, shell rc files, git hooks,
  Claude Code hooks/settings, local-delegate's own config). Reading them is harmless and useful.

Plus **user**: the paths in `LOCAL_DELEGATE_DENY_PATHS`, denied for both.

Every check runs on the absolute path as given AND on the path with symlinks/junctions resolved,
so a link that points into a protected place is caught, and so is a protected path that is itself a
link. On Windows and macOS the comparison ignores case, like their file systems.

Known limit: a hard link to a protected file has its own name and path and is not recognised.
"""

from __future__ import annotations

import fnmatch
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from . import config

READ = "read"
WRITE = "write"

KIND_CREDENTIAL = "credential"
KIND_AUTOSTART = "autostart"
KIND_EXECUTABLE_CONFIG = "executable_config"
KIND_USER = "user"

_BOTH = frozenset({READ, WRITE})
_WRITE_ONLY = frozenset({WRITE})

#: Which operations each kind blocks.
MODES: dict[str, frozenset[str]] = {
    KIND_CREDENTIAL: _BOTH,
    KIND_USER: _BOTH,
    KIND_AUTOSTART: _WRITE_ONLY,
    KIND_EXECUTABLE_CONFIG: _WRITE_ONLY,
}

_CASE_INSENSITIVE = sys.platform in ("win32", "darwin")

# --- Under the user's HOME ------------------------------------------------------------------------
#: Credential stores under HOME. A directory protects everything inside it.
HOME_CREDENTIALS: tuple[str, ...] = (
    ".ssh",  # private keys, known_hosts, config with identities
    ".aws",  # AWS access keys
    ".gnupg",  # GPG private keyring
    ".azure",  # Azure CLI tokens
    ".kube",  # kubeconfig with cluster credentials
    ".docker/config.json",  # registry auths
    ".config/gh",  # GitHub CLI OAuth token (hosts.yml)
    ".config/gcloud",  # Google Cloud credentials
    ".claude/.credentials.json",  # Claude Code OAuth credentials
    ".codex/auth.json",  # Codex CLI credentials
)

#: Autostart folders under HOME (write only).
HOME_AUTOSTART: tuple[str, ...] = (
    "Library/LaunchAgents",  # macOS per-user launchd jobs
    ".config/autostart",  # XDG desktop autostart
    ".config/systemd/user",  # systemd user units
)

#: Files and folders under HOME that run code or configure what runs (write only).
HOME_EXECUTABLE_CONFIG: tuple[str, ...] = (
    ".bashrc",
    ".bash_profile",
    ".bash_login",
    ".bash_logout",
    ".profile",
    ".zshrc",
    ".zprofile",
    ".zshenv",
    ".zlogin",
    ".zlogout",
    ".config/fish",  # fish config.fish and conf.d
    "Documents/PowerShell",  # PowerShell 7 profiles
    "Documents/WindowsPowerShell",  # Windows PowerShell 5 profiles
    ".claude/hooks",  # Claude Code hook scripts (its settings*.json are a name rule below)
    ".codex/config.toml",  # Codex: MCP servers are commands it launches
)

#: Absolute autostart folders outside HOME (write only).
SYSTEM_AUTOSTART: tuple[str, ...] = (
    "/Library/LaunchAgents",
    "/Library/LaunchDaemons",
    "/etc/xdg/autostart",
)

# --- By name, anywhere ----------------------------------------------------------------------------
#: File names that hold credentials wherever they are (read and write).
CREDENTIAL_NAMES: tuple[str, ...] = (
    ".env",  # dotenv: secrets by convention
    ".env.*",  # .env.local, .env.production... (templates are allowed below)
    ".envrc",  # direnv: exported secrets, and it runs on `cd`
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    ".npmrc",  # can carry `_authToken`, in HOME or in a project
    ".pypirc",
    ".netrc",
    "_netrc",
    ".git-credentials",
    ".claude.json",  # Claude Code: MCP entries with their tokens, account data
    ".claude.json.backup*",
    "claude_desktop_config.json",  # Claude Desktop: the daemon token, written literally
    "claude_desktop_config.json.*",  # and its backups (`.local-delegate.bak`, rotated)
)

#: Names that match a credential pattern but are shareable templates or public halves.
CREDENTIAL_NAME_EXCEPTIONS: tuple[str, ...] = (
    ".env.example",
    ".env.sample",
    ".env.template",
    "id_*.pub",  # public SSH keys
)

_POWERSHELL_DIRS = frozenset({"powershell", "windowspowershell"})


@dataclass(frozen=True)
class Denial:
    """Why a path is protected: its `kind` and the rule that matched (for tests and logs)."""

    kind: str
    rule: str


def _fold(text: str) -> str:
    return text.casefold() if _CASE_INSENSITIVE else text


def _strip_windows_prefix(text: str) -> str:
    r"""`\\?\C:\x` → `C:\x`, so the extended-length form does not dodge the prefix rules."""
    if text.startswith(("\\\\?\\", "//?/")) and not text[4:].upper().startswith("UNC"):
        return text[4:]
    return text


def _parts(path: Path) -> tuple[str, ...]:
    """The folded components of an absolute path, with an NTFS stream suffix dropped."""
    parts = list(Path(_strip_windows_prefix(str(path))).parts)
    if sys.platform == "win32" and len(parts) > 1 and ":" in parts[-1]:
        # `id_rsa::$DATA` opens `id_rsa`: the stream suffix must not hide the name.
        parts[-1] = parts[-1].split(":", 1)[0]
    return tuple(_fold(p) for p in parts)


def _forms(path: Path) -> list[tuple[str, ...]]:
    """The path as given (made absolute) and with links resolved; deduplicated."""
    forms = [Path(os.path.abspath(path))]
    try:
        forms.append(Path(os.path.realpath(path)))
    except (OSError, ValueError):
        pass
    out: list[tuple[str, ...]] = []
    for form in forms:
        parts = _parts(form)
        if parts not in out:
            out.append(parts)
    return out


def _is_under(parts: tuple[str, ...], base: tuple[str, ...]) -> bool:
    return len(parts) >= len(base) and parts[: len(base)] == base


def _windows_autostart() -> list[Path]:
    """The two Startup folders; only meaningful on Windows, harmless elsewhere."""
    startup = Path("Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    out: list[Path] = []
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    out.append(Path(appdata) / startup)
    programdata = os.environ.get("PROGRAMDATA") or os.environ.get("ALLUSERSPROFILE")
    if programdata:
        out.append(Path(programdata) / startup)
    return out


def _windows_credentials() -> list[Path]:
    """GitHub CLI keeps its token under `%APPDATA%` on Windows, not under `.config/gh`."""
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return [Path(appdata) / "GitHub CLI"]


def _own_config() -> list[Path]:
    """local-delegate's own config: the llama-swap YAML (its `cmd` runs) when it is set."""
    out: list[Path] = []
    llamaswap = config.llamaswap_config_path()
    if llamaswap:
        out.append(Path(llamaswap))
    return out


def _absolute_rules() -> Iterable[tuple[Path, str, str]]:
    """(path, kind, rule) for every rule anchored to a location."""
    home = Path.home()
    for rel in HOME_CREDENTIALS:
        yield home / rel, KIND_CREDENTIAL, f"~/{rel}"
    for rel in HOME_AUTOSTART:
        yield home / rel, KIND_AUTOSTART, f"~/{rel}"
    for rel in HOME_EXECUTABLE_CONFIG:
        yield home / rel, KIND_EXECUTABLE_CONFIG, f"~/{rel}"
    for absolute in SYSTEM_AUTOSTART:
        yield Path(absolute), KIND_AUTOSTART, absolute
    for startup in _windows_autostart():
        yield startup, KIND_AUTOSTART, "Start Menu/Programs/Startup"
    for cred in _windows_credentials():
        yield cred, KIND_CREDENTIAL, "%APPDATA%/GitHub CLI"
    for own in _own_config():
        yield own, KIND_EXECUTABLE_CONFIG, "LLAMASWAP_CONFIG"
    for extra in config.DENY_PATHS:
        yield extra, KIND_USER, "LOCAL_DELEGATE_DENY_PATHS"


def _match_name(parts: tuple[str, ...]) -> Denial | None:
    """Rules that look at the name and its parent folders, wherever the file is."""
    if len(parts) < 2:
        return None
    name, parent = parts[-1], parts[-2]
    if not any(fnmatch.fnmatchcase(name, _fold(p)) for p in CREDENTIAL_NAME_EXCEPTIONS):
        for pattern in CREDENTIAL_NAMES:
            if fnmatch.fnmatchcase(name, _fold(pattern)):
                return Denial(KIND_CREDENTIAL, pattern)
    if parent == ".claude" and name == ".credentials.json":
        return Denial(KIND_CREDENTIAL, ".claude/.credentials.json")
    return None


def _match_name_write(parts: tuple[str, ...]) -> Denial | None:
    """Write-only rules by name: git hooks/config, project Claude settings, PowerShell profiles."""
    if len(parts) < 2:
        return None
    name, parent = parts[-1], parts[-2]
    git = _fold(".git")
    for i in range(len(parts) - 1):
        if parts[i] == git and parts[i + 1] == _fold("hooks"):
            return Denial(KIND_EXECUTABLE_CONFIG, ".git/hooks/")
    if parent == git and name == _fold("config"):
        # `core.hooksPath`, `core.fsmonitor` and aliases make git run commands from here.
        return Denial(KIND_EXECUTABLE_CONFIG, ".git/config")
    if parent == _fold(".claude") and fnmatch.fnmatchcase(name, _fold("settings*.json")):
        return Denial(KIND_EXECUTABLE_CONFIG, ".claude/settings*.json")
    if _fold(parent) in _POWERSHELL_DIRS and fnmatch.fnmatchcase(name, _fold("*profile.ps1")):
        return Denial(KIND_EXECUTABLE_CONFIG, "PowerShell profile")
    log_dir = _forms(config.LOG_DIR)
    if parts[:-1] in log_dir and fnmatch.fnmatchcase(name, "*.json"):
        # daemon.json, backend-params.json, language.json, install-state.json...: the state and
        # config local-delegate reads back. The usage logs (`*.jsonl`) are not matched here.
        return Denial(KIND_EXECUTABLE_CONFIG, "LOCAL_DELEGATE_LOG_DIR/*.json")
    return None


def check(path: str | os.PathLike[str], mode: str) -> Denial | None:
    """The reason `path` cannot be used for `mode` (`READ` or `WRITE`), or `None` if it can."""
    raw = Path(os.path.expanduser(os.fspath(path)))
    forms = _forms(raw)
    rules = [(_forms(base), kind, rule) for base, kind, rule in _absolute_rules()]
    for parts in forms:
        for bases, kind, rule in rules:
            if mode in MODES[kind] and any(_is_under(parts, base) for base in bases):
                return Denial(kind, rule)
        denial = _match_name(parts)
        if denial is not None:
            return denial
        if mode == WRITE:
            denial = _match_name_write(parts)
            if denial is not None:
                return denial
    return None
