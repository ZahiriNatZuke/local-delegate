"""shell_profiles.py — where each shell keeps its profile and which policy PowerShell has.

It is the part of ``install --shell-completion`` that does not depend on the generated script (SDD
``cli-completion``, batch L3a):

- which shells resolve on this machine (REQ-024);
- the profile path of each one and the PowerShell execution policy (REQ-025, REQ-044);
- the directory and the names of the completion files (REQ-026);
- the text of the load block that goes into the profile (REQ-027).

The PowerShell ASCII escaping of the block (REQ-018) is ``completion.ps_literal``, the same one the
generated script uses: there is a single copy, and ``completion`` does not import this module, so
there is no cycle.

Nothing here writes to disk. The only ways out to the system are the PowerShell query
(``query_powershell``), which always goes through ``_default_run``, and the fallback through the
*Documents* known folder (``_documents_folder``). The suite replaces both with doubles that fail
(fixture ``real_profiles_untouchable`` in ``tests/conftest.py``), so no test can reach the user's
real profile, not even with ``Path.home`` patched.
"""

from __future__ import annotations

import base64
import binascii
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

from . import config
from .completion import ps_literal
from .i18n import t
from .simulated_home import is_simulated_home

#: Shells with completion, in the fixed order in which they are resolved.
SHELLS = ("powershell", "zsh", "bash")
#: PowerShell editions: pwsh 7 and Windows PowerShell 5.1. They share one completion file.
POWERSHELL_EDITIONS = ("pwsh", "powershell")

#: Markers of the load block (REQ-027): ASCII, valid as a comment in the three shells.
BLOCK_BEGIN = "# >>> local-delegate completion >>>"
BLOCK_END = "# <<< local-delegate completion <<<"

#: Name of the completion file of each shell (REQ-026). The zsh one also works for `fpath`.
COMPLETION_FILES = {
    "powershell": "local-delegate.ps1",
    "bash": "local-delegate.bash",
    "zsh": "_local-delegate",
}

#: Policies under which PowerShell does not run the completion file (REQ-044). `Undefined`
#: resolves to `Restricted` on a desktop Windows.
BLOCKING_POLICIES = frozenset({"restricted", "allsigned", "undefined"})
#: Policy assumed with a simulated HOME, where the shell is never asked (REQ-025).
SIMULATED_POLICY = "RemoteSigned"
#: Policy value when the query failed (REQ-044: the file is written with a warning).
UNKNOWN_POLICY = "Unknown"

#: Timeout of the PowerShell query (REQ-025): pwsh takes ~250 ms, but a broken machine profile
#: or an antivirus can hang it.
QUERY_TIMEOUT = 20
#: The query of REQ-025: profile path and effective policy in a single call, in Base64 of
#: UTF-16 LE so that accents and a `Documents` redirected by OneDrive survive whatever the console
#: code page is.
PROFILE_QUERY = (
    "[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes("
    "$PROFILE.CurrentUserAllHosts + [char]10 + (Get-ExecutionPolicy)))"
)
#: Variables removed from the environment of the query. `PSExecutionPolicyPreference` holds the
#: `Process` scope policy of the parent (a PowerShell opened with `-ExecutionPolicy Bypass`) and
#: would falsify the queried one; it applies to both editions.
_DROPPED_ALWAYS = frozenset({"PSEXECUTIONPOLICYPREFERENCE"})
#: `powershell.exe` launched from pwsh inherits its `PSModulePath` and does not load
#: `Microsoft.PowerShell.Security`: `Get-ExecutionPolicy` fails (research-shells §1).
_DROPPED_WINDOWS_POWERSHELL = frozenset({"PSMODULEPATH"})

#: `FOLDERID_Documents`, for `SHGetKnownFolderPath`.
_FOLDERID_DOCUMENTS = "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"

#: Signature of the query runner: it receives the command, the environment and the timeout.
Runner = Callable[..., subprocess.CompletedProcess]
#: Signature of the PowerShell query: executable → (profile path, policy).
Query = Callable[[str], "tuple[Path | None, str | None]"]


@dataclass(frozen=True)
class ShellTarget:
    """A shell resolved on this machine. ``edition`` only exists for PowerShell."""

    shell: str
    edition: str | None
    executable: str


@dataclass(frozen=True)
class ShellResolution:
    """What ``resolve_shells`` gave: the resolved shells and the requested ones that are absent."""

    targets: list[ShellTarget] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def warnings(self) -> list[str]:
        """The catalog warning of each requested shell that is not there (REQ-024)."""
        return [t("install.completion.shell_missing", shell=name) for name in self.missing]


@dataclass(frozen=True)
class ProfileLocation:
    """Where the profile of a shell is and, for PowerShell, its execution policy.

    ``policy`` is ``None`` for zsh and bash (they have none), and ``UNKNOWN_POLICY`` if the query
    failed. ``assumed`` is true when nobody asked the shell (simulated HOME): the policy is then
    ``SIMULATED_POLICY``, not the effective one (SDD backlog-minor-leftovers, REQ-007).
    """

    path: Path
    policy: str | None = None
    assumed: bool = False


# --- Which shells (REQ-024) ------------------------------------------------------------------
def git_bash(which: Callable[[str], str | None]) -> str | None:
    """The ``bash.exe`` of Git for Windows, derived from where ``git`` is (REQ-024, REQ-037).

    ``System32\\bash.exe`` is the WSL one: it opens another machine, with another HOME and another
    profile, so it never counts as «bash exists». Git installs ``cmd\\git.exe``, ``bin\\git.exe``
    or ``mingw64\\bin\\git.exe`` under its root, and bash is always ``<root>\\bin\\bash.exe``.
    """
    found = which("git")
    if not found:
        return None
    git = Path(found)
    for root in (git.parent.parent, git.parent.parent.parent):
        candidate = root / "bin" / "bash.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def _auto_shells(platform: str, shell_env: str | None) -> list[str]:
    """The shells of ``auto`` for the platform (REQ-024)."""
    if platform == "win32":
        return ["powershell"]
    if platform == "darwin":
        return ["zsh"]
    shells = ["bash"]
    if shell_env and PurePath(shell_env).name == "zsh":
        shells.append("zsh")
    return shells


def resolve_shells(
    requested: Sequence[str],
    *,
    platform: str | None = None,
    which: Callable[[str], str | None] | None = None,
    shell_env: str | None = None,
) -> ShellResolution:
    """The shells completion is installed for, in the fixed order of ``SHELLS``.

    ``requested`` are the values of ``--shell-completion`` (``auto``, ``powershell``, ``zsh``,
    ``bash``). A requested shell without an executable goes to ``missing``, with its warning, and
    nothing is written for it (REQ-024). The PowerShell policy is not checked here: the writer
    skips it (REQ-044), with the path already queried.
    """
    platform = sys.platform if platform is None else platform
    which = shutil.which if which is None else which
    wanted: list[str] = []
    for name in requested:
        for shell in _auto_shells(platform, shell_env) if name == "auto" else [name]:
            if shell not in wanted:
                wanted.append(shell)

    resolution = ShellResolution()
    for shell in (s for s in SHELLS if s in wanted):
        found = _executables(shell, platform, which)
        if found:
            resolution.targets.extend(found)
        else:
            resolution.missing.append(shell)
    return resolution


def _executables(
    shell: str, platform: str, which: Callable[[str], str | None]
) -> list[ShellTarget]:
    if shell == "powershell":
        editions = POWERSHELL_EDITIONS if platform == "win32" else ("pwsh",)
        targets = []
        for edition in editions:
            exe = which(edition)
            if exe:
                targets.append(ShellTarget("powershell", edition, exe))
        return targets
    exe = git_bash(which) if shell == "bash" and platform == "win32" else which(shell)
    return [ShellTarget(shell, None, exe)] if exe else []


# --- PowerShell query (REQ-025) -----------------------------------------------------------
def _default_run(cmd: list[str], *, env: Mapping[str, str], timeout: float):
    """The real runner of the query. The suite replaces it with a double that fails."""
    return subprocess.run(
        cmd,
        env=dict(env),
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )


def _is_windows_powershell(executable: str) -> bool:
    return PurePath(executable.replace("\\", "/")).stem.lower() == "powershell"


def query_environment(executable: str, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment of the query: the current one minus the variables that would falsify it
    (REQ-025)."""
    environ = os.environ if environ is None else environ
    dropped = set(_DROPPED_ALWAYS)
    if _is_windows_powershell(executable):
        dropped |= _DROPPED_WINDOWS_POWERSHELL
    return {key: value for key, value in environ.items() if key.upper() not in dropped}


def decode_query_output(stdout: bytes | str) -> tuple[Path | None, str | None]:
    """Path and policy from the Base64 output of the query; ``(None, None)`` if unreadable."""
    text = stdout.decode("ascii", "replace") if isinstance(stdout, bytes) else stdout
    try:
        decoded = base64.b64decode(text.strip(), validate=True).decode("utf-16-le")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None, None
    path_text, _, policy = decoded.partition("\n")
    path_text = path_text.strip()
    # Absolute in either system: decoding does not depend on where it runs.
    absolute = PureWindowsPath(path_text).is_absolute() or PurePosixPath(path_text).is_absolute()
    if not path_text or not absolute:
        return None, None
    return Path(path_text), (policy.strip() or None)


def query_powershell(
    executable: str, *, run: Runner | None = None, environ: Mapping[str, str] | None = None
) -> tuple[Path | None, str | None]:
    """Asks a PowerShell edition for the path of ``$PROFILE.CurrentUserAllHosts`` and the
    effective policy, in a single call (REQ-025).

    Returns ``(None, None)`` if the query fails, times out or returns something unreadable: the
    caller then uses the fallback path and the unknown policy.
    """
    runner = _default_run if run is None else run
    cmd = [executable, "-NoProfile", "-NonInteractive", "-Command", PROFILE_QUERY]
    try:
        done = runner(cmd, env=query_environment(executable, environ), timeout=QUERY_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None, None
    if done.returncode != 0:
        return None, None
    return decode_query_output(done.stdout or b"")


def _documents_folder() -> Path | None:
    """The Windows *Documents* known folder (it follows OneDrive), or ``None``.

    The suite replaces it with a double that fails: it is the other way, besides the query, by
    which a test would reach the user's real folder.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes.wintypes  # also binds `ctypes`

        class _Guid(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.wintypes.DWORD),
                ("Data2", ctypes.wintypes.WORD),
                ("Data3", ctypes.wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        raw = bytes.fromhex(_FOLDERID_DOCUMENTS.strip("{}").replace("-", ""))
        guid = _Guid(
            int.from_bytes(raw[0:4], "big"),
            int.from_bytes(raw[4:6], "big"),
            int.from_bytes(raw[6:8], "big"),
            (ctypes.c_ubyte * 8)(*raw[8:]),
        )
        buffer = ctypes.c_void_p()
        windll = ctypes.windll  # type: ignore[attr-defined]
        result = windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(buffer)
        )
        try:
            if result != 0 or not buffer.value:
                return None
            return Path(ctypes.wstring_at(buffer.value))
        finally:
            windll.ole32.CoTaskMemFree(buffer)
    except Exception:  # it is a fallback: any failure leaves the last resort
        return None


# --- Profile paths (REQ-025) ------------------------------------------------------------------
def _powershell_subdir(edition: str | None) -> str:
    return "WindowsPowerShell" if edition == "powershell" else "PowerShell"


def simulated_profile(target: ShellTarget, home: Path, *, platform: str | None = None) -> Path:
    """The profile path with a simulated HOME: it always comes from ``home`` (REQ-025)."""
    platform = sys.platform if platform is None else platform
    if target.shell == "powershell":
        if platform == "win32":
            return home / "Documents" / _powershell_subdir(target.edition) / "profile.ps1"
        return home / ".config" / "powershell" / "profile.ps1"
    if target.shell == "zsh":
        return home / ".zshrc"
    return home / (".bash_profile" if platform == "darwin" else ".bashrc")


def profile_path(
    target: ShellTarget,
    home: Path,
    *,
    simulated: bool,
    query: Query | None = None,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
    known_folder: Callable[[], Path | None] | None = None,
    simulated_policy: str = SIMULATED_POLICY,
) -> ProfileLocation:
    """The profile path of ``target`` and, for PowerShell, its policy (REQ-025).

    With a simulated HOME the shell is never asked and ``ZDOTDIR`` is not read: the path comes
    from ``home`` and the policy is ``simulated_policy``, marked as assumed. With the real HOME,
    PowerShell answers the query; if it fails, the path comes from the *Documents* known folder
    (on Windows) and the policy is unknown.
    """
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ
    if simulated:
        powershell = target.shell == "powershell"
        return ProfileLocation(
            simulated_profile(target, home, platform=platform),
            simulated_policy if powershell else None,
            assumed=powershell,
        )

    if target.shell == "powershell":
        ask = query_powershell if query is None else query
        path, policy = ask(target.executable)
        if path is not None:
            return ProfileLocation(path, policy or UNKNOWN_POLICY)
        return ProfileLocation(
            _fallback_powershell_profile(target, home, platform, known_folder), UNKNOWN_POLICY
        )
    if target.shell == "zsh":
        zdotdir = (environ.get("ZDOTDIR") or "").strip()
        return ProfileLocation((Path(zdotdir).expanduser() if zdotdir else home) / ".zshrc")
    return ProfileLocation(simulated_profile(target, home, platform=platform))


def _fallback_powershell_profile(
    target: ShellTarget,
    home: Path,
    platform: str,
    known_folder: Callable[[], Path | None] | None,
) -> Path:
    if platform != "win32":
        return home / ".config" / "powershell" / "profile.ps1"
    lookup = _documents_folder if known_folder is None else known_folder
    documents = lookup() or home / "Documents"
    return documents / _powershell_subdir(target.edition) / "profile.ps1"


def policy_blocks(policy: str | None) -> bool:
    """Does this policy prevent running the completion file? (REQ-044).

    An unknown policy does not block: the file is written with a warning that it could not be
    checked.
    """
    return bool(policy) and policy.strip().lower() in BLOCKING_POLICIES


def policy_warning(target: ShellTarget, policy: str | None) -> str | None:
    """The REQ-044 warning for a PowerShell edition, or ``None`` if there is nothing to say."""
    if target.shell != "powershell" or policy is None:
        return None
    edition = target.edition or "pwsh"
    if policy == UNKNOWN_POLICY:
        return t("install.completion.policy_unknown", edition=edition)
    if policy_blocks(policy):
        return t("install.completion.policy_blocks", edition=edition, policy=policy)
    return None


def policy_note(target: ShellTarget, location: ProfileLocation) -> str | None:
    """The REQ-040 line for a PowerShell edition: profile path and effective policy.

    It is always shown, whether the policy lets the file run or blocks it; ``None`` for zsh and
    bash. With a simulated HOME the line says the policy is the assumed one (REQ-007).
    """
    if target.shell != "powershell" or location.policy is None:
        return None
    policy = location.policy
    if policy == UNKNOWN_POLICY:
        policy = t("install.completion.policy_unknown_value")
    key = "policy_note_assumed" if location.assumed else "policy_note"
    return t(
        f"install.completion.{key}",
        edition=target.edition or "pwsh",
        path=location.path,
        policy=policy,
    )


def candidate_profiles(
    home: Path,
    *,
    simulated: bool,
    platform: str | None = None,
    which: Callable[[str], str | None] | None = None,
    query: Query | None = None,
    environ: Mapping[str, str] | None = None,
    known_folder: Callable[[], Path | None] | None = None,
    shells: Sequence[str] = SHELLS,
) -> list[Path]:
    """The REQ-025 profiles that exist, so that ``uninstall`` cleans up even without the
    manifest (REQ-032): both PowerShell editions, ``.zshrc``, ``.bashrc`` and ``.bash_profile``.
    ``shells`` limits them to those shells (a partial ``uninstall``).

    With the real HOME only the installed PowerShell editions are asked; for the others the
    fallback path is used.
    """
    platform = sys.platform if platform is None else platform
    which = shutil.which if which is None else which
    editions = POWERSHELL_EDITIONS if platform == "win32" else ("pwsh",)
    if "powershell" not in shells:
        editions = ()
    paths: list[Path] = []
    for edition in editions:
        exe = None if simulated else which(edition)
        target = ShellTarget("powershell", edition, exe or edition)
        if simulated or exe:
            location = profile_path(
                target,
                home,
                simulated=simulated,
                query=query,
                platform=platform,
                environ=environ,
                known_folder=known_folder,
            )
            paths.append(location.path)
        else:
            paths.append(_fallback_powershell_profile(target, home, platform, known_folder))
    if "zsh" in shells:
        zsh = ShellTarget("zsh", None, "zsh")
        paths.append(profile_path(zsh, home, simulated=simulated, environ=environ).path)
    if "bash" in shells:
        paths.extend([home / ".bashrc", home / ".bash_profile"])
    unique: list[Path] = []
    for path in paths:
        if path not in unique and path.is_file():
            unique.append(path)
    return unique


# --- Completion files and load block (REQ-026, REQ-027) ---------------------------------------
def completion_dir(home: Path, data_dir: Path | None = None) -> Path:
    """The directory of the completion files: ``<data>/completion`` (REQ-026).

    It is the **only** derivation, the one ``install``, ``uninstall``, ``update`` and the check
    use. ``<data>`` is ``data_dir`` if given; otherwise ``config.LOG_DIR`` with the real HOME or
    with ``LOCAL_DELEGATE_LOG_DIR`` set; and with a simulated HOME without that variable,
    ``<home>/.local/share/local-delegate``, so that the sandbox does not write outside its HOME
    (deviation 2).
    """
    if data_dir is not None:
        base = Path(data_dir)
    else:
        explicit = (os.environ.get("LOCAL_DELEGATE_LOG_DIR") or "").strip()
        if explicit or not is_simulated_home(home):
            base = Path(config.LOG_DIR)
        else:
            base = home / ".local" / "share" / "local-delegate"
    return base / "completion"


def completion_file(directory: Path, shell: str) -> Path:
    """The completion file of ``shell`` inside ``directory`` (REQ-026)."""
    return directory / COMPLETION_FILES[shell]


def posix_single_quoted(text: str) -> str:
    """``text`` in sh single quotes, with ``'`` written as ``'\\''`` (REQ-027)."""
    return "'" + text.replace("'", "'\\''") + "'"


def load_block(shell: str, file_path: Path | PurePath) -> str:
    """The REQ-027 load block, with its markers and no final newline.

    It only loads the file if it exists. The path uses ``/`` (on Windows too): PowerShell, Git
    Bash and zsh understand it, so the block does not depend on escaping ``\\``.
    """
    # `as_posix` of the object itself: `PurePath(file_path)` would turn it into the system flavour,
    # and on POSIX a Windows path would keep its `\`.
    posix = file_path.as_posix()
    if shell == "powershell":
        quoted = ps_literal(posix)
        body = f"if (Test-Path -LiteralPath {quoted}) {{ . {quoted} }}"
    elif shell == "bash":
        quoted = posix_single_quoted(posix)
        body = f"[ -f {quoted} ] && . {quoted}"
    elif shell == "zsh":
        quoted = posix_single_quoted(posix)
        body = f"[[ -f {quoted} ]] && source {quoted}"
    else:
        raise ValueError(shell)
    return f"{BLOCK_BEGIN}\n{body}\n{BLOCK_END}"
