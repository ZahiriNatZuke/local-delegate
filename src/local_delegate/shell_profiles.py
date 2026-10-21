"""shell_profiles.py — dónde vive el perfil de cada shell y qué política tiene PowerShell.

Es la parte de ``install --shell-completion`` que no depende del script generado (SDD
``cli-completion``, lote L3a):

- qué shells se resuelven en esta máquina (REQ-024);
- la ruta del perfil de cada uno y la política de ejecución de PowerShell (REQ-025, REQ-044);
- el directorio y los nombres de los ficheros de completado (REQ-026);
- el texto del bloque de carga que va en el perfil (REQ-027).

El escape ASCII de PowerShell del bloque (REQ-018) es ``completion.ps_literal``, el mismo del
script generado: hay una sola copia, y ``completion`` no importa este módulo, así que no hay ciclo.

Nada de aquí escribe en disco. La única salida al sistema es la consulta a PowerShell
(``query_powershell``), que pasa siempre por ``_default_run``, y el respaldo por la carpeta
conocida *Documents* (``_documents_folder``). Las dos las sustituye la suite por dobles que fallan
(fixture ``real_profiles_untouchable`` de ``tests/conftest.py``): así ningún test puede llegar al
perfil real del usuario, ni siquiera con ``Path.home`` parcheado.
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

#: Shells con autocompletado, en el orden fijo en que se resuelven.
SHELLS = ("powershell", "zsh", "bash")
#: Ediciones de PowerShell: pwsh 7 y Windows PowerShell 5.1. Comparten fichero de completado.
POWERSHELL_EDITIONS = ("pwsh", "powershell")

#: Marcadores del bloque de carga (REQ-027): ASCII, válidos como comentario en los tres shells.
BLOCK_BEGIN = "# >>> local-delegate completion >>>"
BLOCK_END = "# <<< local-delegate completion <<<"

#: Nombre del fichero de completado de cada shell (REQ-026). El de zsh vale también para `fpath`.
COMPLETION_FILES = {
    "powershell": "local-delegate.ps1",
    "bash": "local-delegate.bash",
    "zsh": "_local-delegate",
}

#: Políticas con las que PowerShell no ejecuta el fichero de completado (REQ-044). `Undefined`
#: resuelve a `Restricted` en un Windows de escritorio.
BLOCKING_POLICIES = frozenset({"restricted", "allsigned", "undefined"})
#: Política que se supone con HOME simulado, donde nunca se pregunta al shell (REQ-025).
SIMULATED_POLICY = "RemoteSigned"
#: Valor de la política cuando la consulta falló (REQ-044: se escribe y se avisa).
UNKNOWN_POLICY = "Unknown"

#: Tope de la consulta a PowerShell (REQ-025): pwsh tarda ~250 ms, pero un perfil de máquina
#: roto o un antivirus pueden colgarla.
QUERY_TIMEOUT = 20
#: La consulta de REQ-025: ruta del perfil y política efectiva en una sola llamada, en Base64 de
#: UTF-16 LE para que sobrevivan las tildes y `Documents` redirigido por OneDrive sea cual sea la
#: página de códigos de la consola.
PROFILE_QUERY = (
    "[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes("
    "$PROFILE.CurrentUserAllHosts + [char]10 + (Get-ExecutionPolicy)))"
)
#: Variables que se quitan del entorno de la consulta. `PSExecutionPolicyPreference` guarda la
#: política de ámbito `Process` del padre (un PowerShell abierto con `-ExecutionPolicy Bypass`) y
#: falsearía la consultada; vale para las dos ediciones.
_DROPPED_ALWAYS = frozenset({"PSEXECUTIONPOLICYPREFERENCE"})
#: `powershell.exe` lanzado desde pwsh hereda su `PSModulePath` y no carga
#: `Microsoft.PowerShell.Security`: `Get-ExecutionPolicy` falla (research-shells §1).
_DROPPED_WINDOWS_POWERSHELL = frozenset({"PSMODULEPATH"})

#: `FOLDERID_Documents`, para `SHGetKnownFolderPath`.
_FOLDERID_DOCUMENTS = "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"

#: Firma del ejecutor de la consulta: recibe la orden, el entorno y el tope.
Runner = Callable[..., subprocess.CompletedProcess]
#: Firma de la consulta a PowerShell: ejecutable → (ruta del perfil, política).
Query = Callable[[str], "tuple[Path | None, str | None]"]


@dataclass(frozen=True)
class ShellTarget:
    """Un shell resuelto en esta máquina. ``edition`` solo existe en PowerShell."""

    shell: str
    edition: str | None
    executable: str


@dataclass(frozen=True)
class ShellResolution:
    """Lo que dio ``resolve_shells``: los shells resueltos y los pedidos que no existen."""

    targets: list[ShellTarget] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def warnings(self) -> list[str]:
        """El aviso del catálogo de cada shell pedido que no está (REQ-024)."""
        return [t("install.completion.shell_missing", shell=name) for name in self.missing]


@dataclass(frozen=True)
class ProfileLocation:
    """Dónde está el perfil de un shell y, en PowerShell, su política de ejecución.

    ``policy`` es ``None`` en zsh y bash (no tienen), y ``UNKNOWN_POLICY`` si la consulta falló.
    """

    path: Path
    policy: str | None = None


# --- Qué shells (REQ-024) ---------------------------------------------------------------------
def git_bash(which: Callable[[str], str | None]) -> str | None:
    """El ``bash.exe`` de Git for Windows, derivado de dónde está ``git`` (REQ-024, REQ-037).

    ``System32\\bash.exe`` es el de WSL: abre otra máquina, con otro HOME y otro perfil, así que
    nunca cuenta como «bash existe». Git se instala con ``cmd\\git.exe``, ``bin\\git.exe`` o
    ``mingw64\\bin\\git.exe`` bajo su raíz, y el bash va siempre en ``<raíz>\\bin\\bash.exe``.
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
    """Los shells de ``auto`` según la plataforma (REQ-024)."""
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
    """Los shells a los que se instala el autocompletado, en el orden fijo de ``SHELLS``.

    ``requested`` son los valores de ``--shell-completion`` (``auto``, ``powershell``, ``zsh``,
    ``bash``). Un shell pedido sin ejecutable va a ``missing``, con su aviso, y no se escribe nada
    para él (REQ-024). La política de PowerShell no se mira aquí: la salta quien escribe
    (REQ-044), con la ruta ya consultada.
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


# --- Consulta a PowerShell (REQ-025) ----------------------------------------------------------
def _default_run(cmd: list[str], *, env: Mapping[str, str], timeout: float):
    """El ejecutor real de la consulta. La suite lo sustituye por un doble que falla."""
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
    """El entorno de la consulta: el actual sin las variables que la falsearían (REQ-025)."""
    environ = os.environ if environ is None else environ
    dropped = set(_DROPPED_ALWAYS)
    if _is_windows_powershell(executable):
        dropped |= _DROPPED_WINDOWS_POWERSHELL
    return {key: value for key, value in environ.items() if key.upper() not in dropped}


def decode_query_output(stdout: bytes | str) -> tuple[Path | None, str | None]:
    """Ruta y política de la salida en Base64 de la consulta; ``(None, None)`` si no se entiende."""
    text = stdout.decode("ascii", "replace") if isinstance(stdout, bytes) else stdout
    try:
        decoded = base64.b64decode(text.strip(), validate=True).decode("utf-16-le")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None, None
    path_text, _, policy = decoded.partition("\n")
    path_text = path_text.strip()
    # Absoluta en cualquiera de los dos sistemas: la decodificación no depende de dónde corre.
    absolute = PureWindowsPath(path_text).is_absolute() or PurePosixPath(path_text).is_absolute()
    if not path_text or not absolute:
        return None, None
    return Path(path_text), (policy.strip() or None)


def query_powershell(
    executable: str, *, run: Runner | None = None, environ: Mapping[str, str] | None = None
) -> tuple[Path | None, str | None]:
    """Pregunta a una edición de PowerShell la ruta de ``$PROFILE.CurrentUserAllHosts`` y la
    política efectiva, en una sola llamada (REQ-025).

    Devuelve ``(None, None)`` si la consulta falla, vence el tope o devuelve algo ilegible: quien
    llama usa entonces la ruta de respaldo y la política desconocida.
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
    """La carpeta conocida *Documents* de Windows (sigue a OneDrive), o ``None``.

    La suite lo sustituye por un doble que falla: es la otra vía, además de la consulta, por la
    que un test llegaría a la carpeta real del usuario.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes.wintypes  # enlaza también `ctypes`

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
    except Exception:  # es un respaldo: cualquier fallo deja el último recurso
        return None


# --- Rutas de perfil (REQ-025) ----------------------------------------------------------------
def _powershell_subdir(edition: str | None) -> str:
    return "WindowsPowerShell" if edition == "powershell" else "PowerShell"


def simulated_profile(target: ShellTarget, home: Path, *, platform: str | None = None) -> Path:
    """La ruta del perfil con HOME simulado: sale siempre de ``home`` (REQ-025)."""
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
    """La ruta del perfil de ``target`` y, en PowerShell, su política (REQ-025).

    Con HOME simulado nunca se pregunta al shell ni se mira ``ZDOTDIR``: la ruta sale de ``home``
    y la política es ``simulated_policy``. Con HOME real, PowerShell responde a la consulta; si
    falla, la ruta sale de la carpeta conocida *Documents* (en Windows) y la política queda
    desconocida.
    """
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ
    if simulated:
        policy = simulated_policy if target.shell == "powershell" else None
        return ProfileLocation(simulated_profile(target, home, platform=platform), policy)

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
    """¿Esta política impide ejecutar el fichero de completado? (REQ-044).

    Una política desconocida no bloquea: se escribe y se avisa de que no se pudo comprobar.
    """
    return bool(policy) and policy.strip().lower() in BLOCKING_POLICIES


def policy_warning(target: ShellTarget, policy: str | None) -> str | None:
    """El aviso de REQ-044 para una edición de PowerShell, o ``None`` si no hay nada que decir."""
    if target.shell != "powershell" or policy is None:
        return None
    edition = target.edition or "pwsh"
    if policy == UNKNOWN_POLICY:
        return t("install.completion.policy_unknown", edition=edition)
    if policy_blocks(policy):
        return t("install.completion.policy_blocks", edition=edition, policy=policy)
    return None


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
    """Los perfiles de REQ-025 que existen, para que ``uninstall`` limpie aunque falte el
    manifiesto (REQ-032): las dos ediciones de PowerShell, ``.zshrc``, ``.bashrc`` y
    ``.bash_profile``. ``shells`` los limita a esos shells (un ``uninstall`` parcial).

    Con HOME real solo se pregunta a las ediciones de PowerShell instaladas; para las demás vale
    la ruta de respaldo.
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


# --- Ficheros de completado y bloque de carga (REQ-026, REQ-027) ------------------------------
def completion_dir(home: Path, data_dir: Path | None = None) -> Path:
    """El directorio de los ficheros de completado: ``<datos>/completion`` (REQ-026).

    Es la **única** derivación, la que usan ``install``, ``uninstall``, ``update`` y el check.
    ``<datos>`` es ``data_dir`` si se da; si no, ``config.LOG_DIR`` con HOME real o con
    ``LOCAL_DELEGATE_LOG_DIR`` fijada; y con HOME simulado sin esa variable,
    ``<home>/.local/share/local-delegate``, para que el sandbox no escriba fuera de su HOME
    (desviación 2).
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
    """El fichero de completado de ``shell`` dentro de ``directory`` (REQ-026)."""
    return directory / COMPLETION_FILES[shell]


def posix_single_quoted(text: str) -> str:
    """``text`` entre comillas simples de sh, con ``'`` escrita como ``'\\''`` (REQ-027)."""
    return "'" + text.replace("'", "'\\''") + "'"


def load_block(shell: str, file_path: Path | PurePath) -> str:
    """El bloque de carga de REQ-027, con sus marcadores y sin salto final.

    Solo carga el fichero si existe. La ruta va con barras ``/`` (en Windows, también): PowerShell,
    Git Bash y zsh las entienden, y así el bloque no depende de escapar ``\\``.
    """
    # `as_posix` del propio objeto: `PurePath(file_path)` lo pasaría al sabor del sistema, y en
    # POSIX una ruta de Windows conservaría sus `\`.
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
