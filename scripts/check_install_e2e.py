#!/usr/bin/env python3
"""Ejercita `install`/`uninstall` de punta a punta contra un HOME temporal.

**Por qué existe.** La suite prueba las funciones del instalador; esto prueba el **comando**, con
su parser, su plan y su escritura real. La diferencia importa porque `install` decide rutas, monta
comandos de shell y elige intérprete **según la plataforma**, y de sus tres caminos el de macOS no
se había ejecutado nunca: el backlog lo daba por «no auditable sin un Mac». No hacía falta un Mac,
hacía falta un runner — y `test (macos-latest)` ya estaba en la matriz del CI desde hace tiempo.

**Por qué en Python y no en shell.** El paso corre en los tres sistemas, y un script de shell
tendría que sobrevivir a Git Bash en Windows, donde una ruta `/tmp/...` llega al binario nativo
traducida o sin traducir según el caso. Aquí las rutas las construye y las comprueba el mismo
Python que va a recibirlas.

Se instala **dos veces** a propósito: la idempotencia es la propiedad que más fácil se rompe en un
instalador, y una sola pasada no la vería.

**Fase del autocompletado (SDD cli-completion, REQ-039).** Tras la fase de los clientes, con el mismo
HOME temporal: siembra los perfiles del «usuario», instala `--shell-completion` dos veces, abre cada
shell **real** cargando el perfil temporal y completa `local-delegate backend-params set `, hace el
control positivo del bloque de carga (REQ-027: sin el fichero, el perfil carga sin error y ya no
completa), desinstala y compara los perfiles byte a byte con los sembrados. En Linux, además,
readline de verdad en un pseudoterminal (REQ-016). Cada shell lleva tope de tiempo.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from local_delegate import install

ROOT = Path(__file__).resolve().parents[1]

# Cuántas entradas de hook debe haber tras instalar. Se deriva de `_HOOK_EVENTS` en vez de llevar
# el número a mano: escrito a mano decía 2, y al retirar `suggest_lint_summary.py` este smoke se
# puso en rojo en las tres plataformas por un cambio que era correcto. Un número duplicado a mano
# es una segunda fuente para el mismo dato, que es el defecto recurrente de este repo.
#
# El de `Read` no cuenta porque es opt-in (`--enable-read-hook`). Reinstalar no puede cambiar este
# número — si sube, se están duplicando; si baja, se están perdiendo.
EXPECTED_HOOKS = len(install._HOOK_EVENTS)

#: Segundos para cada `local-delegate` y para cada shell que se abre. El paso del CI tiene 6 min.
COMMAND_TIMEOUT = 120
SHELL_TIMEOUT = 60


def _child_env() -> dict[str, str]:
    """El entorno de los hijos, sin lo que movería el directorio de datos fuera del HOME temporal."""
    env = dict(os.environ)
    env.pop("LOCAL_DELEGATE_LOG_DIR", None)
    return env


def _run(*args: str) -> str:
    print(f"$ local-delegate {' '.join(args)}", flush=True)
    process = subprocess.run(
        [sys.executable, "-m", "local_delegate", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=_child_env(),
        stdin=subprocess.DEVNULL,
        timeout=COMMAND_TIMEOUT,
    )
    if process.returncode != 0:
        print(process.stdout)
        print(process.stderr, file=sys.stderr)
        raise SystemExit(f"falló `local-delegate {' '.join(args)}` con {process.returncode}")
    return process.stdout


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FALLO: {message}")


def _registered_hooks(home: Path) -> int:
    data = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    return sum(len(g["hooks"]) for groups in data.get("hooks", {}).values() for g in groups)


def _opencode_entry(directory: Path) -> dict | None:
    """La entrada `local-delegate` en la config de opencode, mirando **los dos** ficheros.

    opencode lee `opencode.json` y `opencode.jsonc` y los fusiona, y `install` elige uno u otro
    según cuál exista: comprobar solo uno daría por ausente lo que está en el otro.
    """
    for name in ("opencode.json", "opencode.jsonc"):
        path = directory / name
        if not path.is_file():
            continue
        # Sin comentarios: los escribe `install` con un serializador de JSON, no una persona.
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = (data.get("mcp") or {}).get("local-delegate")
        if isinstance(entry, dict):
            return entry
    return None


# --- Fase del autocompletado (SDD cli-completion, REQ-039) ---------------------------------------
#
# Las rutas van escritas a mano, como las de opencode arriba: es una prueba de caja negra del
# comando, y derivarlas de `shell_profiles` no probaría que las documentadas son las que se usan.
SET_LINE = "local-delegate backend-params set "
EXPECTED_VALUE = "mechanical"
COMPLETION_NAMES = {
    "powershell": "local-delegate.ps1",
    "bash": "local-delegate.bash",
    "zsh": "_local-delegate",
}
OWN_BACKUP_SUFFIX = ".local-delegate.bak"
BLOCK_BEGIN = "# >>> local-delegate completion >>>"

# ASCII a propósito: Windows PowerShell 5.1 lee en la página ANSI un script sin BOM.
PS_RUNNER = r"""
param([string]$ProfilePath, [string]$Line, [string]$OutPath)
$ErrorActionPreference = 'Stop'
. $ProfilePath
$result = TabExpansion2 -inputScript $Line -cursorColumn $Line.Length
$texts = @($result.CompletionMatches | ForEach-Object { $_.CompletionText })
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($OutPath, ($texts -join "`n"), $utf8)
"""

# Válido en bash 3.2. Llama a la función que `complete -p` registró para el comando, como hace
# readline, e imprime COMPREPLY separado por US (0x1f). Copia mínima del de
# `tests/test_completion_posix.py`: `scripts/` no importa de `tests/`.
BASH_RUNNER = r"""
run_case() {
    local spec func reply
    COMP_WORDS=("$@")
    COMP_CWORD=$(( ${#COMP_WORDS[@]} - 1 ))
    COMP_LINE="$*"
    COMP_POINT=${#COMP_LINE}
    COMPREPLY=()
    spec=$(complete -p "${COMP_WORDS[0]##*/}" 2>/dev/null)
    if [ -n "$spec" ]; then
        func=${spec##*-F }
        func=${func%% *}
        "$func" "${COMP_WORDS[0]}" "${COMP_WORDS[COMP_CWORD]}" "${COMP_WORDS[COMP_CWORD-1]}"
    fi
    printf 'case'
    for reply in "${COMPREPLY[@]}"; do printf '\037%s' "$reply"; done
    printf '\n'
}
run_case local-delegate backend-params set ''
"""

# zsh interactivo de verdad (`zsh -i`, que lee `$ZDOTDIR/.zshrc`) en un pseudoterminal de `zpty`.
# Los marcadores van partidos por comillas para que el eco de lo tecleado no case con el patrón.
ZSH_RUNNER = r"""
zmodload zsh/zpty
zpty -b ld 'TERM=dumb zsh -i'
zpty -w ld 'PS1="@P@ "; setopt nolistbeep; unsetopt menucomplete automenu; print RE""ADY'
zpty -r -m ld start '*READY*@P@ *'
print -r -- "start"$'\t'"${${(f)${start//$'\r'/}}[*]}"
zpty -n -w ld "local-delegate backend-params set "$'\t\t'
zpty -w ld $'\x15'"print -r -- @@E''ND@@"
zpty -r -m ld buf '*@@END@@*@P@ *'
buf=${buf//$'\r'/}
buf=${buf%%print -r -- @@E*}
print -r -- "completed"$'\t'"${${(f)buf}[*]}"
zpty -d ld
"""


def _shell_env(home: Path, *, windows_powershell: bool = False) -> dict[str, str]:
    env = _child_env()
    env["HOME"] = str(home)
    env["ZDOTDIR"] = str(home)
    for name in ("BASH_ENV", "ENV"):
        env.pop(name, None)
    if windows_powershell:
        # Lanzado desde pwsh o Git Bash, `powershell.exe` hereda el `PSModulePath` de pwsh 7 y no
        # carga su propio `Microsoft.PowerShell.Security` (research-shells §1).
        env.pop("PSModulePath", None)
    return env


def _empty_dir(home: Path) -> Path:
    """Directorio de trabajo vacío: así el completado de rutas del shell no aporta candidatos."""
    empty = home.parent / "empty"
    empty.mkdir(exist_ok=True)
    return empty


def _launch(command: list[str], env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess:
    """Un shell con tope de tiempo y sin entrada; en POSIX, en su propio grupo de procesos.

    El grupo propio es para que el tope mate también a los hijos (el `zsh -i` de `zpty`): matar
    solo al padre los dejaría huérfanos.
    """
    print(f"  $ {' '.join(command)}", flush=True)
    posix = sys.platform != "win32"
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=posix,
    )
    try:
        out, err = proc.communicate(timeout=SHELL_TIMEOUT)
    except subprocess.TimeoutExpired:
        if posix:
            os.killpg(proc.pid, 9)
        else:
            proc.kill()
        proc.communicate()
        raise SystemExit(f"FALLO: `{command[0]}` superó {SHELL_TIMEOUT} s") from None
    return subprocess.CompletedProcess(command, proc.returncode, out, err)


def _check_launch(proc: subprocess.CompletedProcess, file_name: str) -> str:
    """La salida de un shell que terminó bien y sin quejarse del fichero de completado."""
    stdout = proc.stdout.decode("utf-8", "replace")
    stderr = proc.stderr.decode("utf-8", "replace")
    _require(proc.returncode == 0, f"`{proc.args[0]}` salió con {proc.returncode}\n{stderr}")
    _require(
        file_name not in stderr and file_name not in stdout,
        f"`{proc.args[0]}` se quejó del fichero de completado:\n{stdout}\n{stderr}",
    )
    return stdout


def _complete_powershell(executable: str, edition: str, profile: Path, home: Path) -> str:
    work = home.parent / "ps-run"
    work.mkdir(exist_ok=True)
    runner = work / "runner.ps1"
    runner.write_bytes(PS_RUNNER.encode("ascii"))
    out = work / f"{edition}.txt"
    out.unlink(missing_ok=True)
    proc = _launch(
        [
            executable,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(runner),
            str(profile),
            SET_LINE,
            str(out),
        ],
        _shell_env(home, windows_powershell=edition == "powershell"),
        _empty_dir(home),
    )
    _check_launch(proc, COMPLETION_NAMES["powershell"])
    return out.read_bytes().decode("utf-8")


def _complete_bash(executable: str, home: Path, *, startup: bool) -> str:
    """`startup`: shell de inicio de sesión (`-l`), el único que lee `.bash_profile`."""
    runner = home.parent / "runner.bash"
    runner.write_bytes(BASH_RUNNER.encode("utf-8"))
    flags = ["-l", "-i"] if startup else ["-i"]
    proc = _launch(
        [executable, *flags, "-c", f". '{runner.as_posix()}'"], _shell_env(home), _empty_dir(home)
    )
    stdout = _check_launch(proc, COMPLETION_NAMES["bash"])
    lines = [line for line in stdout.splitlines() if line.startswith("case")]
    _require(len(lines) == 1, f"bash no imprimió el caso:\n{stdout}")
    return "\n".join(lines[0].split("\x1f")[1:])


def _complete_zsh(executable: str, home: Path) -> str:
    runner = home.parent / "runner.zsh"
    runner.write_bytes(ZSH_RUNNER.encode("utf-8"))
    proc = _launch([executable, "-f", str(runner)], _shell_env(home), _empty_dir(home))
    stdout = _check_launch(proc, COMPLETION_NAMES["zsh"])
    found = dict(line.split("\t", 1) for line in stdout.splitlines() if "\t" in line)
    _require("completed" in found, f"zsh no imprimió la línea completada:\n{stdout}")
    return found["completed"]


def _complete(kind: str, executable: str, profile: Path, home: Path) -> str:
    """Lo que ofrece el shell real tras `SET_LINE` y Tab, cargando el perfil temporal."""
    if kind in ("pwsh", "powershell"):
        return _complete_powershell(executable, kind, profile, home)
    if kind == "zsh":
        return _complete_zsh(executable, home)
    return _complete_bash(executable, home, startup=kind == "bash-startup")


def _readline_free_value(executable: str, home: Path) -> bytes:
    """REQ-016 con readline de verdad: Tab tras `--home ./d/` completa `con espacio.txt` entero.

    `bash -i` en un pseudoterminal de la biblioteca estándar, con el perfil del HOME temporal. Lo
    que se teclea no contiene «espacio»: si aparece en la pantalla, lo puso el completado.
    """
    import select

    work = home.parent / "readline"
    (work / "d").mkdir(parents=True, exist_ok=True)
    (work / "d" / "con espacio.txt").write_bytes(b"x")
    env = _shell_env(home)
    env["TERM"] = "dumb"

    # El hijo abre su propia sesión (`start_new_session`) y toma el pty como terminal de control
    # antes de pasar a bash: sin terminal de control, `bash -i` no tiene control de trabajos.
    take_terminal = (
        "import fcntl, os, sys, termios; fcntl.ioctl(0, termios.TIOCSCTTY, 0); "
        "os.execv(sys.argv[1], sys.argv[1:])"
    )
    parent_fd, child_fd = os.openpty()
    print(f"  $ (pty) {executable} -i", flush=True)
    proc = subprocess.Popen(
        [sys.executable, "-c", take_terminal, executable, "-i"],
        stdin=child_fd,
        stdout=child_fd,
        stderr=child_fd,
        cwd=work,
        env=env,
        start_new_session=True,
    )
    os.close(child_fd)
    captured = b""

    def _read_until(pattern: re.Pattern[bytes], seconds: float) -> bool:
        nonlocal captured
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not pattern.search(captured):
            ready, _, _ = select.select([parent_fd], [], [], 0.2)
            if not ready:
                continue
            try:
                chunk = os.read(parent_fd, 4096)
            except OSError:  # EIO: el hijo cerró el terminal
                break
            if not chunk:
                break
            captured += chunk
        return bool(pattern.search(captured))

    try:
        os.write(parent_fd, b"PS1='@P@ '; echo RE''ADY\n")
        _require(
            _read_until(re.compile(rb"READY\r?\n.*@P@ ", re.DOTALL), SHELL_TIMEOUT),
            f"bash -i no llegó al prompt en el pty:\n{captured!r}",
        )
        os.write(parent_fd, b"local-delegate install --home ./d/\t")
        _read_until(re.compile(rb"espacio\.txt"), 15)
        return captured
    finally:
        try:
            os.write(parent_fd, b"\x15exit\n")
            proc.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            os.killpg(proc.pid, 9)
            proc.wait()
        os.close(parent_fd)


def _seed_profiles(home: Path) -> dict[Path, bytes]:
    """Los perfiles del «usuario» antes de instalar, con lo que deben volver a ser (REQ-039, 1)."""
    if sys.platform == "win32":
        seeds = {
            # 5.1 sin BOM se lee en ANSI: cp1252 con tildes y CRLF, como el de una PC española.
            home / "Documents" / "WindowsPowerShell" / "profile.ps1": (
                "# perfil del usuario: configuración\r\n$saludo = 'año'\r\n".encode("cp1252")
            ),
            home / "Documents" / "PowerShell" / "profile.ps1": (
                "﻿# perfil de pwsh: canción\n$x = 1\n".encode()
            ),
        }
    else:
        name = ".zshrc" if sys.platform == "darwin" else ".bashrc"
        seeds = {
            home / name: f"# {name} del usuario: canción\nexport LD_E2E_USER=1\n".encode(),
            # Una copia del usuario con el nombre de siempre: `install` no puede pisarla (REQ-046).
            home / ".bashrc.bak": b"# copia del usuario, no tocar\n",
        }
    for path, data in seeds.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return seeds


def _targets(home: Path) -> tuple[list[str], list[tuple[str, str, Path]]]:
    """Los `--shell-completion` que se piden y los shells que se abren: (tipo, ejecutable, perfil).

    Windows: `auto` = las dos ediciones de PowerShell. Linux: `auto` = bash. macOS: `auto` = zsh,
    y además bash, abierto con `/bin/bash` 3.2 y su `.bash_profile` (REQ-039, 2). En Linux y macOS
    se pide también `powershell` si está pwsh: su perfil y su carpeta **no existen**, así que la
    vuelta atrás tiene que borrar los dos (REQ-032).
    """
    requested = ["--shell-completion"]
    targets: list[tuple[str, str, Path]] = []
    if sys.platform == "win32":
        for edition, folder in (("pwsh", "PowerShell"), ("powershell", "WindowsPowerShell")):
            exe = shutil.which(edition)
            _require(exe is not None, f"no se encontró `{edition}`")
            targets.append((edition, str(exe), home / "Documents" / folder / "profile.ps1"))
        return requested, targets
    if sys.platform == "darwin":
        requested.append("--shell-completion=bash")
        zsh = shutil.which("zsh")
        _require(zsh is not None, "no se encontró `zsh`")
        targets.append(("zsh", str(zsh), home / ".zshrc"))
        _require(Path("/bin/bash").is_file(), "no está /bin/bash")
        targets.append(("bash-startup", "/bin/bash", home / ".bash_profile"))
    else:
        bash = shutil.which("bash")
        _require(bash is not None, "no se encontró `bash`")
        targets.append(("bash", str(bash), home / ".bashrc"))
    pwsh = shutil.which("pwsh")
    if pwsh:
        requested.append("--shell-completion=powershell")
        targets.append(("pwsh", pwsh, home / ".config" / "powershell" / "profile.ps1"))
    else:
        print("  (sin pwsh: no se prueba el perfil que crea `install`)", flush=True)
    return requested, targets


def _shell_of(kind: str) -> str:
    return {"pwsh": "powershell", "powershell": "powershell", "zsh": "zsh"}.get(kind, "bash")


def _snapshot(paths: list[Path]) -> dict[Path, bytes | None]:
    return {p: (p.read_bytes() if p.is_file() else None) for p in paths}


def _completion_phase(home: Path, common: list[str]) -> None:
    print("\n== autocompletado del shell ==", flush=True)
    seeds = _seed_profiles(home)
    requested, targets = _targets(home)
    data_dir = home / ".local" / "share" / "local-delegate" / "completion"
    created = [profile for _, _, profile in targets if profile not in seeds]
    created_dirs = [p.parent for p in created if not p.parent.exists()]

    _run("install", *common, *requested)
    for kind, _, profile in targets:
        name = COMPLETION_NAMES[_shell_of(kind)]
        _require((data_dir / name).is_file(), f"`install` no escribió {name}")
        text = profile.read_bytes().decode("utf-8", "replace")
        _require(BLOCK_BEGIN in text, f"`install` no escribió el bloque de carga en {profile}")
    files = sorted(data_dir.iterdir())
    own_copies = [p.with_name(p.name + OWN_BACKUP_SUFFIX) for p in seeds]
    watched = [*seeds, *created, *files, *own_copies]
    first = _snapshot(watched)
    _run("install", *common, *requested)  # idempotencia (REQ-029)
    _require(
        _snapshot(watched) == first,
        "la segunda instalación cambió bytes de perfiles, copias, ficheros o manifiesto",
    )

    for kind, exe, profile in targets:
        offered = _complete(kind, exe, profile, home)
        _require(
            EXPECTED_VALUE in offered,
            f"{kind}: `{SET_LINE}` + Tab no ofreció `{EXPECTED_VALUE}`, ofreció: {offered!r}",
        )
        print(f"  {kind}: `{SET_LINE}` + Tab ofrece `{EXPECTED_VALUE}`", flush=True)

    if sys.platform.startswith("linux"):
        bash = next(exe for kind, exe, _ in targets if kind == "bash")
        captured = _readline_free_value(bash, home)
        _require(
            re.search(rb"con(\\ | )espacio\.txt", captured) is not None,
            f"readline no completó `con espacio.txt` tras `--home ./d/`:\n{captured!r}",
        )
        print("  bash + readline: completa `con espacio.txt` entero (REQ-016)", flush=True)

    # Control positivo de REQ-027: sin el fichero de completado el perfil carga sin error y ya no
    # completa. Sin esto, «completa» podría venir de otro sitio que no fuera el bloque.
    saved = {p: p.read_bytes() for p in files}
    for name in {COMPLETION_NAMES[_shell_of(kind)] for kind, _, _ in targets}:
        (data_dir / name).unlink()
    for kind, exe, profile in targets:
        offered = _complete(kind, exe, profile, home)
        _require(
            EXPECTED_VALUE not in offered,
            f"{kind}: sin el fichero de completado aún ofrece `{EXPECTED_VALUE}`: {offered!r}",
        )
        print(f"  {kind}: sin el fichero, carga sin error y no completa (control)", flush=True)
    _run("install", *common, *requested)
    _require(_snapshot(files) == saved, "`install` no repuso los ficheros de completado tal cual")

    # Sin `--shell-completion`: un `uninstall` sin restricciones (`--no-client-cli` no lo es)
    # también quita el autocompletado (REQ-032).
    _run("uninstall", *common)
    for path, data in seeds.items():
        _require(path.is_file(), f"`uninstall` borró {path}, que ya existía")
        _require(path.read_bytes() == data, f"{path} no volvió byte a byte a como estaba")
    for profile in created:
        _require(not profile.exists(), f"`uninstall` dejó {profile}, que creó `install`")
    for folder in created_dirs:
        _require(not folder.exists(), f"`uninstall` dejó la carpeta {folder}, que creó `install`")
    leftovers = sorted(str(p) for p in home.rglob(f"*{OWN_BACKUP_SUFFIX}"))
    _require(not leftovers, f"quedaron copias propias: {leftovers}")
    remaining = sorted(data_dir.iterdir()) if data_dir.is_dir() else []
    _require(not remaining, f"quedaron ficheros de completado: {remaining}")
    print("  vuelta atrás exacta: perfiles como antes, sin copias ni ficheros", flush=True)


def main() -> int:
    # La consola de Windows en el CI no es UTF-8: un mensaje con tildes no puede tumbar el paso.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="backslashreplace")
    home = Path(tempfile.mkdtemp(prefix="ld-e2e-")) / "home"
    # Los tres directorios de cliente se crean a mano: `install` configura los que **existen**, y
    # sin esto el paso probaría el camino de «no hay ningún cliente», que no es el que interesa.
    #
    # El de opencode se escribe como ruta literal a propósito, y no derivándolo de
    # `install.opencode_dir`: esto es una prueba de caja negra del **comando**, y comprobarlo con
    # la misma función que lo calcula no probaría que la ruta documentada es la que se usa. Con un
    # HOME simulado la variable `XDG_CONFIG_HOME` se ignora, así que es determinista.
    (home / ".claude").mkdir(parents=True)
    (home / ".codex").mkdir(parents=True)
    opencode = home / ".config" / "opencode"
    opencode.mkdir(parents=True)
    print(f"HOME temporal: {home}", flush=True)

    common = ["--home", str(home), "--no-client-cli"]

    _run("install", *common, "--dry-run")
    _require(
        not (home / ".claude" / "hooks").exists(),
        "`--dry-run` escribió en disco; tiene que describir sin tocar nada",
    )

    _run("install", *common)
    _run("install", *common)  # idempotencia

    claude = home / ".claude"
    _require(
        (claude / "hooks" / "local-delegate" / "suggest_delegate_prompt.py").is_file(),
        "no se copiaron los scripts de hooks",
    )
    _require(
        (claude / "hooks" / "local-delegate" / "hook_common.py").is_file(),
        "falta hook_common.py, que los hooks importan por sys.path[0]",
    )
    _require(
        (claude / "skills" / "local-delegation" / "SKILL.md").is_file(), "no se instaló la skill"
    )
    _require(
        "local-delegate:begin" in (claude / "CLAUDE.md").read_text(encoding="utf-8"),
        "no se escribió el bloque de memoria de Claude Code",
    )
    _require(
        "local-delegate:begin" in (home / ".codex" / "AGENTS.md").read_text(encoding="utf-8"),
        "no se escribió el bloque de memoria de Codex",
    )
    _require(
        "local-delegate:begin" in (opencode / "AGENTS.md").read_text(encoding="utf-8"),
        "no se escribió el bloque de memoria de opencode",
    )
    _require(
        (opencode / "skill" / "local-delegation" / "SKILL.md").is_file(),
        "no se instaló la skill en el directorio de opencode",
    )
    _require(
        _opencode_entry(opencode) is not None,
        "no se escribió la entrada MCP de opencode",
    )

    registered = _registered_hooks(home)
    _require(
        registered == EXPECTED_HOOKS,
        f"tras dos instalaciones hay {registered} hooks y deberían ser {EXPECTED_HOOKS}",
    )

    _run("uninstall", *common)
    _require(
        not (claude / "hooks" / "local-delegate").exists(),
        "`uninstall` dejó los scripts de hooks: el módulo promete ser reversible",
    )
    _require(not (claude / "skills" / "local-delegation").exists(), "`uninstall` dejó la skill")
    _require(
        not (opencode / "skill" / "local-delegation").exists(),
        "`uninstall` dejó la skill de opencode",
    )
    _require(
        _opencode_entry(opencode) is None,
        "`uninstall` dejó la entrada MCP en la configuración de opencode",
    )
    _require(
        _registered_hooks(home) == 0,
        "`uninstall` dejó hooks nuestros registrados en settings.json",
    )

    _completion_phase(home, common)

    print(f"instalador OK en {sys.platform}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
