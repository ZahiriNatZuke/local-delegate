"""Paths the tools never read or write, whatever `LOCAL_DELEGATE_ALLOWED_DIRS` says.

The MCP tools read `path` and write `target` on the server side, outside Claude Code's permission
prompts: the tools are usually allowed with a wildcard, so a prompt injection inside any file the
model reads could ask `local_summarize` for a credential (and get a summary of it back into the
context) or ask `local_boilerplate` to drop a script in an autostart folder. `ALLOWED_DIRS` stops
that only when it is set, and it is empty by default. This module is the floor that is always on.

It lives next to the hooks, with the standard library only, because the read hook needs the same
answer: a protected file must not be blocked for `Read` and sent to `local_summarize`, which would
refuse it. The hooks run with a bare `python` that cannot import the package; the server imports it
through `local_delegate.path_guard`, which passes in the values of `config`.

Families of rules:

- **credential** — denied for reading AND writing: files whose content is a secret (SSH and cloud
  keys, registry tokens, the Claude Code and Claude Desktop configs that carry tokens).
- **autostart** and **executable_config** — denied for writing only: places where a written file
  runs later without anyone launching it (Startup folders, LaunchAgents, shell rc files, git hooks
  and config, Claude Code hooks/settings/agents, local-delegate's own config). Reading them is
  harmless and useful.
- **network** — Windows UNC and device paths (`\\\\server\\share`, `\\\\?\\UNC\\…`, `\\\\.\\…`), for
  both: `\\\\localhost\\C$\\…` reaches any local file under a name no other rule recognises, and
  touching a remote host leaks the user's NTLM hash. Allowed only inside `ALLOWED_DIRS`.
- **user** — the paths in `LOCAL_DELEGATE_DENY_PATHS`, for both.

Every check runs on the absolute path as given AND on the path with symlinks/junctions resolved,
so a link that points into a protected place is caught, and so is a protected path that is itself a
link. On Windows and macOS the comparison ignores case, like their file systems.

Known limits (documented in the wiki): a hard link to a protected file has its own name and path;
and a link swapped by another process between this check and the read or write is not seen.
"""

from __future__ import annotations

import fnmatch
import os
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

READ = "read"
WRITE = "write"

KIND_CREDENTIAL = "credential"
KIND_AUTOSTART = "autostart"
KIND_EXECUTABLE_CONFIG = "executable_config"
KIND_NETWORK = "network"
KIND_USER = "user"

_BOTH = frozenset({READ, WRITE})
_WRITE_ONLY = frozenset({WRITE})

#: Which operations each kind blocks.
MODES: dict[str, frozenset[str]] = {
    KIND_CREDENTIAL: _BOTH,
    KIND_NETWORK: _BOTH,
    KIND_USER: _BOTH,
    KIND_AUTOSTART: _WRITE_ONLY,
    KIND_EXECUTABLE_CONFIG: _WRITE_ONLY,
}

DENY_PATHS_VARIABLE = "LOCAL_DELEGATE_DENY_PATHS"
ALLOWED_DIRS_VARIABLE = "LOCAL_DELEGATE_ALLOWED_DIRS"
LLAMASWAP_CONFIG_VARIABLE = "LLAMASWAP_CONFIG"

_CASE_INSENSITIVE = sys.platform in ("win32", "darwin")
_WINDOWS = os.name == "nt"

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
    ".config/hub",  # hub, the older GitHub CLI
    ".config/gcloud",  # Google Cloud credentials
    ".config/git/credentials",  # git's credential-store file in its XDG place
    ".cargo/credentials.toml",  # crates.io token
    ".cargo/credentials",  # same, older name
    ".terraform.d/credentials.tfrc.json",  # Terraform Cloud tokens
    ".pgpass",  # PostgreSQL passwords
    ".vault-token",  # HashiCorp Vault token
    ".m2/settings.xml",  # Maven repository passwords
    ".gem/credentials",  # RubyGems API key
    ".claude/.credentials.json",  # Claude Code OAuth credentials
    ".codex/auth.json",  # Codex CLI credentials
)

#: Credential stores under `%APPDATA%` (Windows keeps them there instead of under `.config`).
APPDATA_CREDENTIALS: tuple[str, ...] = (
    "GitHub CLI",
    "gcloud",
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
    ".gitconfig",  # core.hooksPath, core.fsmonitor, aliases with `!` run commands
    ".config/git/config",  # same file in its XDG place
    ".claude/hooks",  # Claude Code hook scripts (its settings*.json are a name rule below)
    ".claude/CLAUDE.md",  # instructions every session obeys
    ".claude/agents",
    ".claude/commands",
    ".claude/plugins",
    ".codex/config.toml",  # Codex: MCP servers are commands it launches
)

#: Absolute autostart folders outside HOME (write only).
SYSTEM_AUTOSTART: tuple[str, ...] = (
    "/Library/LaunchAgents",
    "/Library/LaunchDaemons",
    "/etc/xdg/autostart",
)

# --- By name, anywhere ----------------------------------------------------------------------------
_KEY_TYPES = ("rsa", "dsa", "ecdsa", "ed25519")

#: File names that hold credentials wherever they are (read and write).
CREDENTIAL_NAMES: tuple[str, ...] = (
    ".env",  # dotenv: secrets by convention
    ".env.*",  # .env.local, .env.production... (templates are allowed below)
    ".envrc",  # direnv: exported secrets, and it runs on `cd`
    # SSH private keys by their exact default names: `id_rsa_parser.py` is not a key.
    *(f"id_{kind}" for kind in _KEY_TYPES),
    *(f"id_{kind}.*" for kind in _KEY_TYPES),
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
    "*.example",
    "*.sample",
    "*.template",
    ".env.dist",
    "id_*.pub",  # public SSH keys
)

#: File names that run code or configure what runs, wherever they are (write only).
EXECUTABLE_NAMES: tuple[str, ...] = (
    ".mcp.json",  # project MCP servers: commands Claude Code launches
    ".yarnrc.yml",  # yarnPath runs a script on every yarn command
    "*.pth",  # import lines in site-packages run at every Python start
    "sitecustomize.py",
    "usercustomize.py",
)

_POWERSHELL_DIRS = frozenset({"powershell", "windowspowershell"})
#: `%APPDATA%` under HOME when the variable is missing (folder names, not text for people).
_DEFAULT_APPDATA = ("AppData", "Roaming")
_DRIVE_DEVICE = re.compile(r"^\\\\[?.]\\([A-Za-z]:)(\\|$)")


@dataclass(frozen=True)
class Denial:
    """Why a path is protected: its `kind` and the rule that matched (for tests and logs)."""

    kind: str
    rule: str


def parse_path_list(raw: str | None) -> list[Path]:
    """`a;b;` → resolved paths, the parse of `ALLOWED_DIRS` and `DENY_PATHS`."""
    return [Path(p.strip()).expanduser().resolve() for p in (raw or "").split(";") if p.strip()]


def _fold(text: str) -> str:
    return text.casefold() if _CASE_INSENSITIVE else text


def _windows_text(text: str) -> str:
    r"""Backslashes, and `\\?\C:\x` or `\\.\C:\x` → `C:\x`: a local drive in any spelling."""
    text = text.replace("/", "\\")
    match = _DRIVE_DEVICE.match(text)
    if match:
        return match.group(1) + "\\" + text[match.end() :]
    return text


def _is_unc(text: str) -> bool:
    r"""A UNC or device path that is not a plain drive: `\\host\share`, `\\?\UNC\…`, `\\.\pipe`."""
    return _WINDOWS and _windows_text(text).startswith("\\\\")


def _parts(path: Path | str) -> tuple[str, ...]:
    """The folded components of an absolute path, with an NTFS stream suffix dropped."""
    text = _windows_text(str(path)) if _WINDOWS else str(path)
    parts = list(Path(text).parts)
    if _WINDOWS and len(parts) > 1 and ":" in parts[-1]:
        # `id_rsa::$DATA` opens `id_rsa`: the stream suffix must not hide the name.
        parts[-1] = parts[-1].split(":", 1)[0]
    return tuple(_fold(p) for p in parts)


def _forms(path: Path | str) -> list[tuple[str, ...]]:
    """The path as given (made absolute) and with links resolved; deduplicated."""
    absolute = os.path.abspath(path)
    texts = [absolute]
    try:
        texts.append(os.path.realpath(path))
    except (OSError, ValueError):
        # The full path cannot be resolved (a name the OS rejects, a broken link loop): resolve
        # its folder instead, so a link in the folder is still followed. Only if that also fails
        # does the absolute form stand alone; the name rules still apply to it.
        try:
            texts.append(
                os.path.join(os.path.realpath(os.path.dirname(absolute)), Path(absolute).name)
            )
        except (OSError, ValueError):
            texts.append(absolute)
    out: list[tuple[str, ...]] = []
    for text in texts:
        parts = _parts(text)
        if parts not in out:
            out.append(parts)
    return out


def _is_under(parts: tuple[str, ...], base: tuple[str, ...]) -> bool:
    return len(parts) >= len(base) and parts[: len(base)] == base


def _home(env: Mapping[str, str]) -> Path:
    raw = (env.get("USERPROFILE" if _WINDOWS else "HOME") or "").strip()
    return Path(raw) if raw else Path.home()


def _appdata(env: Mapping[str, str], home: Path) -> Path:
    raw = (env.get("APPDATA") or "").strip()
    return Path(raw) if raw else home.joinpath(*_DEFAULT_APPDATA)


@dataclass(frozen=True)
class _Context:
    home: Path
    appdata: Path
    programdata: Path | None
    deny_paths: tuple[Path, ...]
    allowed_dirs: tuple[Path, ...]
    log_dir: Path | None
    llamaswap_config: str


def _absolute_rules(ctx: _Context) -> Iterable[tuple[Path, str, str]]:
    """(path, kind, rule) for every rule anchored to a location."""
    for rel in HOME_CREDENTIALS:
        yield ctx.home / rel, KIND_CREDENTIAL, f"~/{rel}"
    for rel in APPDATA_CREDENTIALS:
        yield ctx.appdata / rel, KIND_CREDENTIAL, f"%APPDATA%/{rel}"
    for rel in HOME_AUTOSTART:
        yield ctx.home / rel, KIND_AUTOSTART, f"~/{rel}"
    for rel in HOME_EXECUTABLE_CONFIG:
        yield ctx.home / rel, KIND_EXECUTABLE_CONFIG, f"~/{rel}"
    for absolute in SYSTEM_AUTOSTART:
        yield Path(absolute), KIND_AUTOSTART, absolute
    startup = Path("Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    yield ctx.appdata / startup, KIND_AUTOSTART, "Start Menu/Programs/Startup"
    if ctx.programdata is not None:
        yield ctx.programdata / startup, KIND_AUTOSTART, "Start Menu/Programs/Startup"
    if ctx.llamaswap_config:
        # Its `cmd` entries are commands llama-swap runs.
        yield Path(ctx.llamaswap_config), KIND_EXECUTABLE_CONFIG, LLAMASWAP_CONFIG_VARIABLE
    for extra in ctx.deny_paths:
        yield extra, KIND_USER, DENY_PATHS_VARIABLE


def _match_name(parts: tuple[str, ...]) -> Denial | None:
    """Credential rules that look at the name and its parent folder, wherever the file is."""
    if len(parts) < 2:
        return None
    name, parent = parts[-1], parts[-2]
    if not any(fnmatch.fnmatchcase(name, _fold(p)) for p in CREDENTIAL_NAME_EXCEPTIONS):
        for pattern in CREDENTIAL_NAMES:
            if fnmatch.fnmatchcase(name, _fold(pattern)):
                return Denial(KIND_CREDENTIAL, pattern)
    if parent == _fold(".claude") and name == _fold(".credentials.json"):
        return Denial(KIND_CREDENTIAL, ".claude/.credentials.json")
    return None


def _match_name_write(parts: tuple[str, ...], ctx: _Context) -> Denial | None:
    """Write-only rules by name: git hooks/config, Claude/VS Code settings, startup files."""
    if len(parts) < 2:
        return None
    name, parent = parts[-1], parts[-2]
    git = _fold(".git")
    if git in parts[:-1]:
        below = parts[parts.index(git) + 1 :]
        # `.git/hooks/x`, `.git/modules/<sub>/hooks/x`: every hooks folder git may run from.
        if _fold("hooks") in below[:-1]:
            return Denial(KIND_EXECUTABLE_CONFIG, ".git/**/hooks/")
        # `core.hooksPath`, `core.fsmonitor` and aliases make git run commands; submodules and
        # worktrees have their own (`.git/modules/<sub>/config`, `.git/worktrees/<w>/config.worktree`).
        if name in (_fold("config"), _fold("config.worktree")):
            return Denial(KIND_EXECUTABLE_CONFIG, ".git/**/config")
    if parent == _fold(".claude") and fnmatch.fnmatchcase(name, _fold("settings*.json")):
        return Denial(KIND_EXECUTABLE_CONFIG, ".claude/settings*.json")
    if parent == _fold(".vscode") and name == _fold("tasks.json"):
        return Denial(KIND_EXECUTABLE_CONFIG, ".vscode/tasks.json")
    for pattern in EXECUTABLE_NAMES:
        if fnmatch.fnmatchcase(name, _fold(pattern)):
            return Denial(KIND_EXECUTABLE_CONFIG, pattern)
    # Folded always, even on Linux: pwsh spells the folder `PowerShell` or `powershell`, and a
    # profile under either runs at every start.
    if parent.casefold() in _POWERSHELL_DIRS and fnmatch.fnmatch(name.casefold(), "*profile.ps1"):
        return Denial(KIND_EXECUTABLE_CONFIG, "PowerShell profile")
    # daemon.json, backend-params.json, language.json, install-state.json...: the state and config
    # local-delegate reads back. The usage logs (`*.jsonl`) are not matched.
    in_log_dir = ctx.log_dir is not None and parts[:-1] in _forms(ctx.log_dir)
    if in_log_dir and fnmatch.fnmatchcase(name, "*.json"):
        return Denial(KIND_EXECUTABLE_CONFIG, "LOCAL_DELEGATE_LOG_DIR/*.json")
    return None


def _inside_allowed(absolute: str, allowed: Sequence[Path]) -> bool:
    parts = _parts(absolute)
    return any(_is_under(parts, _parts(root)) for root in allowed)


def check(
    path: str | os.PathLike[str],
    mode: str,
    *,
    environ: Mapping[str, str] | None = None,
    deny_paths: Sequence[Path] | None = None,
    allowed_dirs: Sequence[Path] | None = None,
    log_dir: Path | None = None,
    llamaswap_config: str | None = None,
) -> Denial | None:
    """The reason `path` cannot be used for `mode` (`READ` or `WRITE`), or `None` if it can.

    `environ` locates HOME and `%APPDATA%` (the client's, when the daemon asks for a hook) and
    supplies whatever is not passed: `LOCAL_DELEGATE_DENY_PATHS`, `LOCAL_DELEGATE_ALLOWED_DIRS`
    and `LLAMASWAP_CONFIG`. The server passes the values already parsed by `config`.
    """
    env = os.environ if environ is None else environ
    raw = os.path.expanduser(os.fspath(path))
    absolute = os.path.abspath(raw)
    if _is_unc(absolute) or _is_unc(raw):
        # Before any resolution: resolving a UNC path already opens a connection to its host.
        allowed = (
            parse_path_list(env.get(ALLOWED_DIRS_VARIABLE))
            if allowed_dirs is None
            else allowed_dirs
        )
        if _inside_allowed(absolute, allowed):
            return None
        return Denial(KIND_NETWORK, "UNC")
    home = _home(env)
    programdata = (env.get("PROGRAMDATA") or env.get("ALLUSERSPROFILE") or "").strip()
    ctx = _Context(
        home=home,
        appdata=_appdata(env, home),
        programdata=Path(programdata) if programdata else None,
        deny_paths=tuple(
            parse_path_list(env.get(DENY_PATHS_VARIABLE)) if deny_paths is None else deny_paths
        ),
        allowed_dirs=tuple(allowed_dirs or ()),
        log_dir=log_dir,
        llamaswap_config=(
            (env.get(LLAMASWAP_CONFIG_VARIABLE) or "")
            if llamaswap_config is None
            else llamaswap_config
        ).strip(),
    )
    forms = _forms(raw)
    rules = [(_forms(base), kind, rule) for base, kind, rule in _absolute_rules(ctx)]
    for parts in forms:
        for bases, kind, rule in rules:
            if mode in MODES[kind] and any(_is_under(parts, base) for base in bases):
                return Denial(kind, rule)
        denial = _match_name(parts)
        if denial is not None:
            return denial
        if mode == WRITE:
            denial = _match_name_write(parts, ctx)
            if denial is not None:
                return denial
    return None
