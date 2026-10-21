"""Shells, rutas de perfil, política y bloque de carga (SDD cli-completion, L3a).

REQ-024 (qué shells), REQ-025 (ruta y política), REQ-026 (directorio), REQ-027 (texto del bloque)
y REQ-044 (detección de la política). Todo con dobles: la consulta real a PowerShell solo la hace
el último test, marcado `real_profile_query` (y de solo lectura). Los controles positivos van
anotados en cada test.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from local_delegate import config, shell_profiles
from local_delegate.shell_profiles import (
    UNKNOWN_POLICY,
    ShellTarget,
    completion_dir,
    completion_file,
    load_block,
    policy_blocks,
    policy_warning,
    profile_path,
    query_powershell,
    resolve_shells,
)

#: El ejecutor real, guardado al importar (antes de que la fixture de conftest lo sustituya).
ORIGINAL_RUN = shell_profiles._default_run

PWSH = ShellTarget("powershell", "pwsh", r"C:\Program Files\PowerShell\7\pwsh.exe")
WINDOWS_PS = ShellTarget(
    "powershell", "powershell", r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
)
ZSH = ShellTarget("zsh", None, "/bin/zsh")
BASH = ShellTarget("bash", None, "/bin/bash")


def _which(available: dict[str, str]):
    return lambda name: available.get(name)


def _git_install(tmp_path: Path) -> str:
    """Un Git for Windows de mentira: `cmd/git.exe` y `bin/bash.exe` bajo una raíz."""
    root = tmp_path / "Git"
    (root / "cmd").mkdir(parents=True)
    (root / "bin").mkdir()
    (root / "cmd" / "git.exe").write_bytes(b"")
    (root / "bin" / "bash.exe").write_bytes(b"")
    return str(root / "cmd" / "git.exe")


# --- REQ-024 ------------------------------------------------------------------------------------
def test_windows_auto_resolves_both_powershell_editions():
    found = resolve_shells(
        ["auto"],
        platform="win32",
        which=_which({"pwsh": "pwsh.exe", "powershell": "powershell.exe", "bash": "x"}),
    )
    assert [(t.shell, t.edition) for t in found.targets] == [
        ("powershell", "pwsh"),
        ("powershell", "powershell"),
    ]
    assert found.missing == []


def test_windows_without_pwsh_resolves_only_5_1():
    found = resolve_shells(["auto"], platform="win32", which=_which({"powershell": "ps.exe"}))
    assert [(t.edition, t.executable) for t in found.targets] == [("powershell", "ps.exe")]


def test_powershell_requested_without_any_edition_warns_and_writes_nothing():
    """Control positivo de la lista `missing`: con una edición presente, ya no hay aviso."""
    found = resolve_shells(["powershell"], platform="win32", which=_which({}))
    assert found.targets == [] and found.missing == ["powershell"]
    assert found.warnings() == [
        "autocompletado: no se encontró powershell; no se escribe nada para él"
    ]
    present = resolve_shells(["powershell"], platform="win32", which=_which({"pwsh": "p"}))
    assert present.missing == []


def test_windows_bash_ignores_wsl_and_uses_git_bash(tmp_path):
    """REQ-024: `System32\\bash.exe` (WSL) no cuenta; el bash es el de Git.

    Control positivo: con Git presente, el mismo `which` sí da bash, y es el de Git.
    """
    wsl = {"bash": r"C:\Windows\System32\bash.exe"}
    alone = resolve_shells(["bash"], platform="win32", which=_which(wsl))
    assert alone.targets == [] and alone.missing == ["bash"]

    git = _git_install(tmp_path)
    with_git = resolve_shells(["bash"], platform="win32", which=_which({**wsl, "git": git}))
    assert [t.executable for t in with_git.targets] == [str(tmp_path / "Git" / "bin" / "bash.exe")]


def test_git_bash_from_a_mingw64_git(tmp_path):
    root = tmp_path / "Git"
    (root / "mingw64" / "bin").mkdir(parents=True)
    (root / "bin").mkdir()
    (root / "bin" / "bash.exe").write_bytes(b"")
    git = root / "mingw64" / "bin" / "git.exe"
    git.write_bytes(b"")
    assert shell_profiles.git_bash(_which({"git": str(git)})) == str(root / "bin" / "bash.exe")


@pytest.mark.parametrize(
    ("platform", "shell_env", "expected"),
    [
        ("darwin", "/bin/zsh", ["zsh"]),
        ("darwin", "/bin/bash", ["zsh"]),
        ("linux", "/usr/bin/zsh", ["zsh", "bash"]),  # orden fijo de SHELLS
        ("linux", "/bin/bash", ["bash"]),
        ("linux", None, ["bash"]),
    ],
)
def test_auto_per_platform(platform, shell_env, expected):
    which = _which({"zsh": "/bin/zsh", "bash": "/bin/bash", "pwsh": "/usr/bin/pwsh"})
    found = resolve_shells(["auto"], platform=platform, which=which, shell_env=shell_env)
    assert [t.shell for t in found.targets] == expected


def test_powershell_outside_windows_is_only_pwsh():
    which = _which({"pwsh": "/usr/bin/pwsh", "powershell": "/x"})
    found = resolve_shells(["powershell"], platform="darwin", which=which)
    assert [(t.shell, t.edition) for t in found.targets] == [("powershell", "pwsh")]


def test_order_is_fixed_and_duplicates_collapse():
    which = _which({"pwsh": "p", "zsh": "z", "bash": "b"})
    found = resolve_shells(["bash", "auto", "zsh", "auto"], platform="linux", which=which)
    assert [t.shell for t in found.targets] == ["zsh", "bash"]


# --- REQ-025: la consulta -----------------------------------------------------------------------
def _encoded(text: str) -> bytes:
    return base64.b64encode(text.encode("utf-16-le"))


class _Recorder:
    def __init__(self, result=None, exc: BaseException | None = None):
        self.calls: list[tuple[list[str], dict, float]] = []
        self.result, self.exc = result, exc

    def __call__(self, cmd, *, env, timeout):
        self.calls.append((cmd, dict(env), timeout))
        if self.exc is not None:
            raise self.exc
        return self.result


ONEDRIVE = r"C:\Users\José Pérez\OneDrive\Documentos\PowerShell\profile.ps1"


def test_query_decodes_path_with_tildes_and_policy():
    """REQ-025: la ruta (OneDrive, tildes, espacios) y la política salen de la salida Base64.

    Control positivo: decodificando la salida como UTF-8 en vez de UTF-16 LE, este test falla.
    """
    done = subprocess.CompletedProcess([], 0, _encoded(ONEDRIVE + "\nRemoteSigned") + b"\r\n", b"")
    run = _Recorder(done)
    path, policy = query_powershell(PWSH.executable, run=run, environ={})
    assert str(path) == str(Path(ONEDRIVE))
    assert policy == "RemoteSigned"
    cmd, _, timeout = run.calls[0]
    assert cmd[:4] == [PWSH.executable, "-NoProfile", "-NonInteractive", "-Command"]
    assert cmd[4] == shell_profiles.PROFILE_QUERY
    assert timeout == 20


def test_query_environment_drops_the_variables_that_would_lie():
    """REQ-025: `PSModulePath` fuera para `powershell.exe` (y solo para él);
    `PSExecutionPolicyPreference` fuera en las dos ediciones.

    Control positivo: pwsh conserva `PSModulePath`, así que el filtro distingue la edición.
    """
    environ = {"PSModulePath": "C:/m", "PSExecutionPolicyPreference": "Bypass", "KEEP": "1"}
    done = subprocess.CompletedProcess([], 0, _encoded("C:/p.ps1\nRestricted"), b"")
    for target, keeps_module_path in ((WINDOWS_PS, False), (PWSH, True)):
        run = _Recorder(done)
        query_powershell(target.executable, run=run, environ=environ)
        env = run.calls[0][1]
        assert "PSExecutionPolicyPreference" not in env
        assert ("PSModulePath" in env) is keeps_module_path
        assert env["KEEP"] == "1"


def test_default_runner_closes_stdin_and_applies_the_timeout(monkeypatch):
    """El ejecutor real lanza con `stdin` cerrado, el tope y el entorno dados (sin lanzar nada:
    se sustituye `subprocess.run`)."""
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs, cmd=cmd)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(shell_profiles.subprocess, "run", fake_run)
    ORIGINAL_RUN(["pwsh"], env={"A": "1"}, timeout=20)
    assert seen["stdin"] is subprocess.DEVNULL
    assert seen["timeout"] == 20
    assert seen["env"] == {"A": "1"}
    assert seen["capture_output"] is True


@pytest.mark.parametrize(
    "runner",
    [
        _Recorder(exc=subprocess.TimeoutExpired(["pwsh"], 20)),
        _Recorder(exc=FileNotFoundError("pwsh")),
        _Recorder(subprocess.CompletedProcess([], 1, _encoded("C:/p.ps1\nBypass"), b"")),
        _Recorder(subprocess.CompletedProcess([], 0, b"esto no es base64!", b"")),
        _Recorder(subprocess.CompletedProcess([], 0, _encoded("relativa\\p.ps1\nBypass"), b"")),
        _Recorder(subprocess.CompletedProcess([], 0, b"", b"")),
    ],
    ids=["timeout", "missing-exe", "exit-1", "garbage", "relative-path", "empty"],
)
def test_query_failures_give_nothing(runner):
    assert query_powershell("pwsh", run=runner, environ={}) == (None, None)


def test_posix_pwsh_path_is_accepted():
    done = subprocess.CompletedProcess(
        [], 0, _encoded("/home/u/.config/powershell/profile.ps1\nUnrestricted"), b""
    )
    path, policy = query_powershell("pwsh", run=_Recorder(done), environ={})
    assert path == Path("/home/u/.config/powershell/profile.ps1") and policy == "Unrestricted"


# --- REQ-025: rutas -----------------------------------------------------------------------------
def _never(*_a, **_k):
    raise AssertionError("con HOME simulado no se pregunta al shell")


@pytest.mark.parametrize(
    ("target", "platform", "relative", "policy"),
    [
        (PWSH, "win32", "Documents/PowerShell/profile.ps1", "RemoteSigned"),
        (WINDOWS_PS, "win32", "Documents/WindowsPowerShell/profile.ps1", "RemoteSigned"),
        (PWSH, "linux", ".config/powershell/profile.ps1", "RemoteSigned"),
        (PWSH, "darwin", ".config/powershell/profile.ps1", "RemoteSigned"),
        (ZSH, "darwin", ".zshrc", None),
        (BASH, "darwin", ".bash_profile", None),
        (BASH, "linux", ".bashrc", None),
        (BASH, "win32", ".bashrc", None),
    ],
)
def test_simulated_home_paths_never_ask_the_shell(tmp_path, target, platform, relative, policy):
    """REQ-025: con HOME simulado la ruta sale de `home` y no se pregunta (`query` y
    `known_folder` revientan si se llaman). Control positivo: el mismo PWSH con
    `simulated=False` sí llama a la consulta (siguiente test)."""
    location = profile_path(
        target,
        tmp_path,
        simulated=True,
        query=_never,
        known_folder=_never,
        platform=platform,
        environ={"ZDOTDIR": "/zdot"},
    )
    assert location.path == tmp_path / relative
    assert location.policy == policy


def test_simulated_policy_is_injectable(tmp_path):
    location = profile_path(PWSH, tmp_path, simulated=True, simulated_policy="Restricted")
    assert location.policy == "Restricted"


def test_real_home_powershell_uses_the_query(tmp_path):
    asked = []

    def query(executable):
        asked.append(executable)
        return Path(ONEDRIVE), "AllSigned"

    location = profile_path(PWSH, tmp_path, simulated=False, query=query, platform="win32")
    assert asked == [PWSH.executable]
    assert location.path == Path(ONEDRIVE) and location.policy == "AllSigned"


def test_real_home_query_without_policy_is_unknown(tmp_path):
    location = profile_path(
        PWSH, tmp_path, simulated=False, query=lambda _e: (Path("C:/p.ps1"), None)
    )
    assert location.policy == UNKNOWN_POLICY


def test_failed_query_falls_back_to_the_known_documents_folder(tmp_path):
    """REQ-025: consulta fallida → carpeta conocida *Documents* + subcarpeta de la edición, con la
    política desconocida; sin carpeta conocida, `home/Documents`; fuera de Windows,
    `~/.config/powershell`."""
    failed = lambda _e: (None, None)
    documents = tmp_path / "OneDrive" / "Documentos"
    for target, subdir in ((PWSH, "PowerShell"), (WINDOWS_PS, "WindowsPowerShell")):
        location = profile_path(
            target,
            tmp_path,
            simulated=False,
            query=failed,
            platform="win32",
            known_folder=lambda: documents,
        )
        assert location.path == documents / subdir / "profile.ps1"
        assert location.policy == UNKNOWN_POLICY
    last_resort = profile_path(
        PWSH, tmp_path, simulated=False, query=failed, platform="win32", known_folder=lambda: None
    )
    assert last_resort.path == tmp_path / "Documents" / "PowerShell" / "profile.ps1"
    posix = profile_path(PWSH, tmp_path, simulated=False, query=failed, platform="linux")
    assert posix.path == tmp_path / ".config" / "powershell" / "profile.ps1"


def test_zdotdir_is_honoured_with_real_home_and_ignored_with_simulated(tmp_path):
    """Control positivo cruzado: el mismo `environ` da dos rutas según el HOME."""
    environ = {"ZDOTDIR": str(tmp_path / "zdot")}
    real = profile_path(ZSH, tmp_path, simulated=False, environ=environ)
    simulated = profile_path(ZSH, tmp_path, simulated=True, environ=environ)
    assert real.path == tmp_path / "zdot" / ".zshrc"
    assert simulated.path == tmp_path / ".zshrc"
    assert profile_path(ZSH, tmp_path, simulated=False, environ={}).path == tmp_path / ".zshrc"


def test_candidate_profiles_lists_the_existing_ones(tmp_path):
    (tmp_path / "Documents" / "WindowsPowerShell").mkdir(parents=True)
    (tmp_path / "Documents" / "WindowsPowerShell" / "profile.ps1").write_bytes(b"")
    (tmp_path / ".bash_profile").write_bytes(b"")
    (tmp_path / ".zshrc").write_bytes(b"")
    found = shell_profiles.candidate_profiles(
        tmp_path, simulated=True, platform="win32", which=_never, query=_never
    )
    assert found == [
        tmp_path / "Documents" / "WindowsPowerShell" / "profile.ps1",
        tmp_path / ".zshrc",
        tmp_path / ".bash_profile",
    ]


# --- REQ-044 ------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("policy", "blocks"),
    [
        ("Restricted", True),
        ("AllSigned", True),
        ("Undefined", True),
        (" restricted ", True),
        ("RemoteSigned", False),
        ("Unrestricted", False),
        ("Bypass", False),
        (UNKNOWN_POLICY, False),
        (None, False),
        ("", False),
    ],
)
def test_policy_blocks(policy, blocks):
    assert policy_blocks(policy) is blocks


def test_policy_warnings():
    blocked = policy_warning(WINDOWS_PS, "Restricted")
    assert "Set-ExecutionPolicy -Scope CurrentUser RemoteSigned" in blocked
    assert "powershell" in blocked and "Restricted" in blocked
    assert "no se pudo comprobar" in policy_warning(PWSH, UNKNOWN_POLICY)
    assert policy_warning(PWSH, "RemoteSigned") is None
    assert policy_warning(ZSH, None) is None


# --- REQ-026 ------------------------------------------------------------------------------------
def test_completion_dir_rules(tmp_path, monkeypatch):
    """REQ-026: `data_dir` manda; HOME simulado sin variable → `<home>/.local/share/...`; con la
    variable o con HOME real → `config.LOG_DIR`. Control positivo: quitando la variable cambia
    el resultado con el mismo HOME simulado."""
    home = tmp_path / "home"
    assert completion_dir(home, tmp_path / "data") == tmp_path / "data" / "completion"
    # La suite fija `LOCAL_DELEGATE_LOG_DIR` (conftest): con ella, `config.LOG_DIR`.
    assert completion_dir(home) == Path(config.LOG_DIR) / "completion"
    monkeypatch.delenv("LOCAL_DELEGATE_LOG_DIR")
    assert completion_dir(home) == home / ".local" / "share" / "local-delegate" / "completion"
    monkeypatch.setattr(Path, "home", lambda: home)
    assert completion_dir(home) == Path(config.LOG_DIR) / "completion"


def test_completion_file_names(tmp_path):
    names = {shell: completion_file(tmp_path, shell).name for shell in shell_profiles.SHELLS}
    assert names == {
        "powershell": "local-delegate.ps1",
        "zsh": "_local-delegate",
        "bash": "local-delegate.bash",
    }


# --- REQ-027 ------------------------------------------------------------------------------------
def test_bash_and_zsh_blocks_quote_the_path():
    """REQ-027: comillas simples con `'` como `'\\''`; la ruta en UTF-8 tal cual."""
    path = PurePosixPath("/home/jo sé/it's/local-delegate.bash")
    quoted = "'/home/jo sé/it'\\''s/local-delegate.bash'"
    assert load_block("bash", path).splitlines() == [
        shell_profiles.BLOCK_BEGIN,
        f"[ -f {quoted} ] && . {quoted}",
        shell_profiles.BLOCK_END,
    ]
    assert load_block("zsh", path).splitlines()[1] == f"[[ -f {quoted} ]] && source {quoted}"


def test_powershell_block_is_ascii_with_forward_slashes():
    """REQ-027 y REQ-018: el bloque de PowerShell es ASCII aunque la ruta lleve `ó`, va con `/`, y
    `'` no necesita escape dentro de comillas dobles. Control positivo: sin el escape, el bloque
    tendría un byte ≥ 0x80."""
    path = PureWindowsPath(r"C:\Users\Ramón O'Neil\AppData\Local\local-delegate\completion\x.ps1")
    block = load_block("powershell", path)
    assert max(block.encode("utf-8")) < 0x80
    quoted = '"C:/Users/Ram$([char]0x00F3)n O\'Neil/AppData/Local/local-delegate/completion/x.ps1"'
    assert block.splitlines()[1] == f"if (Test-Path -LiteralPath {quoted}) {{ . {quoted} }}"


def test_block_uses_the_single_powershell_escape():
    """El bloque y el script generado comparten el escape ASCII (REQ-018): una sola copia, la de
    `completion`. Control positivo: con una segunda copia en `shell_profiles` (la de L3a), la
    identidad falla."""
    from local_delegate import completion

    assert shell_profiles.ps_literal is completion.ps_literal
    assert not hasattr(shell_profiles, "powershell_string")
    assert completion.ps_literal('a$b`c"d') == '"a`$b``c`"d"'
    assert completion.ps_literal("\U0001d11e") == '"$([char]0xD834)$([char]0xDD1E)"'
    assert completion.ps_literal("\t") == '"$([char]0x0009)"'


def test_unknown_shell_has_no_block():
    with pytest.raises(ValueError):
        load_block("fish", PurePosixPath("/x"))


# --- Consulta real (solo lectura) ---------------------------------------------------------------
def _real_profile(executable: str, environ: dict[str, str]) -> str:
    done = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-Command", "$PROFILE.CurrentUserAllHosts"],
        env=environ,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return done.stdout.strip()


@pytest.mark.real_profile_query
@pytest.mark.skipif(sys.platform != "win32", reason="la consulta real se prueba en Windows")
@pytest.mark.parametrize("edition", ["pwsh", "powershell"])
def test_real_query_matches_what_powershell_reports(edition):
    """REQ-025: la consulta real da la misma ruta que `$PROFILE.CurrentUserAllHosts` y una política
    con nombre. Solo **lee**: no abre ni escribe el perfil. Desactiva la fixture que protege el
    perfil real con el marcador `real_profile_query`."""
    executable = shutil.which(edition)
    if executable is None:
        pytest.skip(f"{edition} no está instalado")
    path, policy = query_powershell(executable)
    expected = _real_profile(executable, shell_profiles.query_environment(executable, os.environ))
    assert path is not None and str(path) == expected
    assert policy in {
        "Restricted",
        "AllSigned",
        "RemoteSigned",
        "Unrestricted",
        "Bypass",
        "Undefined",
        "Default",
    }


# --- REQ-006 (SDD backlog-minor-leftovers): the guard covers the POSIX profiles too ------------
def test_the_guard_lists_the_real_posix_profiles():
    """`real_profiles_untouchable` watches `.bashrc`, `.bash_profile` and `.zshrc` of the real
    HOME, read before any test could patch `Path.home`. Positive control (checked): with the
    list limited to PowerShell, the set below is empty and the assert fails."""
    import conftest

    names = {path.name for path in conftest.REAL_SHELL_PROFILES}
    assert {".bashrc", ".bash_profile", ".zshrc"} <= names
    assert all(path.parent == conftest.REAL_HOME for path in conftest.REAL_SHELL_PROFILES[:3])


@pytest.mark.parametrize("writer", ["profile_edit", "atomic_write", "cli_install"])
def test_writing_a_guarded_profile_fails_before_touching_it(tmp_path, monkeypatch, writer):
    """A write aimed at a guarded profile fails the test (an exception that `except OSError` cannot
    swallow) and the file is not created. The guarded list points at a temporary `.bashrc` here,
    so the check runs without going near the real one. Positive control (checked): without the
    wrappers in the fixture, `pytest.raises` reports DID NOT RAISE and `.bashrc` appears."""
    import conftest

    from local_delegate import cli, install

    home = tmp_path / "home"
    home.mkdir()
    bashrc = home / ".bashrc"
    monkeypatch.setattr(conftest, "REAL_SHELL_PROFILES", (bashrc,))
    with pytest.raises(pytest.fail.Exception):
        if writer == "profile_edit":
            install.write_profile_edit(install.upsert_profile_block(bashrc, "block"))
        elif writer == "atomic_write":
            install._atomic_write(bashrc, b"block\n")
        else:
            probes = install.ShellProbes(
                platform="linux", which={"bash": "/usr/bin/bash"}.get, shell_env="/usr/bin/bash"
            )
            monkeypatch.setattr(install, "shell_probes", lambda: probes)
            cli.run(["install", "--home", str(home), "--shell-completion", "bash"])
    assert not bashrc.exists()
