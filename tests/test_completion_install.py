"""`install` y `uninstall` con `--shell-completion` (SDD cli-completion, L3b).

REQ-023 (opción), REQ-026 (fichero), REQ-028 (escritura del perfil), REQ-029 (idempotencia),
REQ-030 (orden e independencia de los clientes), REQ-031 (`--dry-run`), REQ-032 (`uninstall`),
REQ-043 (manifiesto) y REQ-044 (salto por política).

Todo va en un HOME simulado (`tmp_path/home`) y con el directorio de datos de la suite
(`config.LOG_DIR = tmp_path`, `conftest.isolate_runtime_logs`). Las sondas de la máquina (qué
shells hay, plataforma, `$SHELL`, consulta a PowerShell) son dobles inyectados con
`install.shell_probes`; por defecto, un Linux con bash, zsh y pwsh, y `$SHELL=zsh`, para que el
resultado no dependa del sistema que corre la suite. Los dos últimos tests cargan el perfil en
pwsh 7 y en Windows PowerShell 5.1 de verdad.

Cada test anota su **control positivo**: la mutación del código que lo pone en rojo (las marcadas
con «comprobado» se aplicaron a mano y el test falló por el assert que dice).
"""

from __future__ import annotations

import codecs
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from completion_shells import SHELL_TIMEOUT, powershell_command, powershell_env, require_or_skip
from conftest import make_home, snapshot

from local_delegate import cli, completion, config, i18n, install, shell_profiles
from local_delegate.install import ShellProbes

BEGIN = shell_profiles.BLOCK_BEGIN
WINDOWS = sys.platform == "win32"
SUITE_LANG = "es"


def _which(*present: str):
    table = {name: f"/usr/bin/{name}" for name in present}
    return table.get


LINUX_PROBES = ShellProbes(
    platform="linux", which=_which("bash", "zsh", "pwsh"), shell_env="/usr/bin/zsh"
)


@pytest.fixture(autouse=True)
def linux_probes(monkeypatch):
    """Sondas de un Linux con bash, zsh y pwsh. Un test que necesite otras lo vuelve a parchear."""
    monkeypatch.setattr(install, "shell_probes", lambda: LINUX_PROBES)


def use_probes(monkeypatch, probes: ShellProbes) -> None:
    monkeypatch.setattr(install, "shell_probes", lambda: probes)


@pytest.fixture
def home(tmp_path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


def comp_dir(home: Path) -> Path:
    return shell_profiles.completion_dir(home)


def manifest(home: Path) -> dict:
    return json.loads((comp_dir(home) / completion.MANIFEST_NAME).read_text(encoding="utf-8"))


def run(argv: list[str], capsys) -> tuple[int, str]:
    try:
        code = cli.run(argv)
    except SystemExit as exc:  # argparse
        code = exc.code
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def install_cmd(home: Path, *extra: str) -> list[str]:
    return ["install", "--home", str(home), *extra]


def uninstall_cmd(home: Path, *extra: str) -> list[str]:
    return ["uninstall", "--home", str(home), *extra]


# --- REQ-023: la opción ---------------------------------------------------------------------------
@pytest.mark.parametrize("command", ["install", "uninstall"])
def test_option_parses_like_clients(command):
    """REQ-023: sin valor → `["auto"]`; repetida → las dos; ausente → `None`. Control positivo
    (comprobado): sin `const="auto"`, el primer assert ve `[None]`."""
    parser = cli.build_parser()
    assert parser.parse_args([command, "--shell-completion"]).shell_completion == ["auto"]
    both = [command, "--shell-completion", "powershell", "--shell-completion", "bash"]
    assert parser.parse_args(both).shell_completion == ["powershell", "bash"]
    assert parser.parse_args([command]).shell_completion is None


@pytest.mark.parametrize(
    "argv",
    [
        ["install", "--shell-completion", "fish"],
        ["uninstall", "--shell-completion", "powershell,bash"],
        ["update", "--shell-completion"],
    ],
    ids=["fish", "comma-list", "update"],
)
def test_bad_values_and_update_exit_2(argv, capsys):
    """REQ-023: valor fuera de `choices`, lista con comas y `update --shell-completion` → 2.
    Control positivo: con la opción añadida también a `update`, el tercer caso sale con 0."""
    code, _ = run(argv, capsys)
    assert code == 2


def test_install_without_the_option_touches_nothing(home, tmp_path, capsys):
    """REQ-023: sin la opción, ni perfiles ni directorio de completado. Control positivo
    (comprobado): con `_shell_completion_request` devolviendo `["auto"]` siempre, aparecen
    `.bashrc` y `completion/`."""
    before = snapshot(tmp_path)
    code, _ = run(install_cmd(home), capsys)
    assert code == 0
    assert snapshot(tmp_path) == before


# --- REQ-026 y REQ-027: fichero y bloque ----------------------------------------------------------
def test_files_are_the_render_in_the_configured_language(home, capsys):
    """REQ-026: cada fichero es byte a byte `render(shell, lang=L)`, sin `.bak`, y cada perfil
    lleva el bloque que carga ese fichero (REQ-027). Control positivo: con `render(shell)` sin
    `lang`, el test de `en` de abajo falla; con `.bak` en `_owned_file_action`, falla el último
    assert."""
    code, out = run(install_cmd(home, "--shell-completion"), capsys)
    assert code == 0, out
    directory = comp_dir(home)
    for shell, profile in (("bash", home / ".bashrc"), ("zsh", home / ".zshrc")):
        file = shell_profiles.completion_file(directory, shell)
        assert file.read_bytes() == completion.render(shell, lang=SUITE_LANG).encode("utf-8")
        expected = (shell_profiles.load_block(shell, file) + "\n").encode("utf-8")
        assert profile.read_bytes() == expected
    # `auto` en Linux sin pwsh pedido: no hay fichero de PowerShell.
    assert not shell_profiles.completion_file(directory, "powershell").exists()
    assert sorted(p.name for p in directory.iterdir()) == sorted(
        ["_local-delegate", "local-delegate.bash", completion.MANIFEST_NAME]
    )


def test_language_variable_wins_over_the_suite_language(home, monkeypatch, capsys):
    """REQ-026: con `LOCAL_DELEGATE_LANG=en` y la suite en `es`, el fichero sale en `en`, el
    idioma **configurado** (`plan_language`), aunque el proceso ya tenga resuelto (y cacheado)
    el de la suite. Control positivo (comprobado): pasando `i18n.lang()` en vez de
    `plan_language(...).lang`, la cabecera dice `lang=es`."""
    assert i18n.lang() == SUITE_LANG  # el idioma del proceso queda resuelto antes del cambio
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    code, out = run(install_cmd(home, "--shell-completion", "bash"), capsys)
    assert code == 0, out
    data = shell_profiles.completion_file(comp_dir(home), "bash").read_bytes()
    assert data == completion.render("bash", lang="en").encode("utf-8")
    assert b"lang=en" in data.splitlines()[0]
    assert manifest(home)["lang"] == "en"


def test_explicit_data_dir(home, tmp_path):
    """REQ-026: con `data_dir` explícito, todo va a `<data_dir>/completion`. Control positivo
    (comprobado): ignorando `data_dir` en `completion_dir`, el fichero aparece bajo `tmp_path/completion`."""
    data_dir = tmp_path / "datos con espacio"
    plan = install.plan_completion_install(home, ["bash"], lang="es", data_dir=data_dir)
    assert install.apply(plan.actions, dry_run=False, out=lambda _line: None) == 0
    assert (data_dir / "completion" / "local-delegate.bash").is_file()
    assert (data_dir / "completion" / completion.MANIFEST_NAME).is_file()
    assert not (tmp_path / "completion").exists()


# --- REQ-029: idempotencia ------------------------------------------------------------------------
def test_second_install_changes_no_byte_and_says_up_to_date(home, tmp_path, capsys):
    """REQ-029: la segunda pasada deja el snapshot igual (manifiesto incluido) y dice «ya al día».
    Control positivo (comprobado): con un campo de fecha en el manifiesto, el snapshot cambia."""
    argv = install_cmd(home, "--shell-completion")
    assert run(argv, capsys)[0] == 0
    first = snapshot(tmp_path)
    code, out = run(argv, capsys)
    assert code == 0
    assert snapshot(tmp_path) == first
    up_to_date = install.t("install.completion.up_to_date")
    # dos ficheros, dos perfiles y el manifiesto
    assert out.count(up_to_date) == 5, out


# --- REQ-030: orden fijo e independencia de los clientes ------------------------------------------
def test_empty_home_writes_completion_and_says_so(home, capsys):
    """REQ-030: sin clientes, escribe el autocompletado, lo dice (no solo «no se escribió nada»)
    y sale con 0. Control positivo (comprobado): sin el cambio de la rama «ningún cliente», sale
    `cli.install.no_client.nothing_written`."""
    code, out = run(install_cmd(home, "--shell-completion"), capsys)
    assert code == 0
    assert install.t("cli.install.no_client.completion_written", home=home) in out
    assert install.t("cli.install.no_client.nothing_written", home=home) not in out
    assert (home / ".bashrc").is_file()


@pytest.mark.skipif(
    not WINDOWS and hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root escribe en ficheros de solo lectura",
)
def test_read_only_profile_exits_1_and_the_other_shells_are_written(home, capsys):
    """REQ-028 y REQ-030: un perfil de solo lectura da aviso de no escrito y salida 1; zsh sí se
    escribe. Control positivo (comprobado): devolviendo el texto en vez de lanzar
    `CompletionWriteError`, sale con 0."""
    bashrc = home / ".bashrc"
    bashrc.write_bytes(b"x\n")
    os.chmod(bashrc, stat.S_IREAD)
    try:
        code, out = run(install_cmd(home, "--shell-completion"), capsys)
    finally:
        os.chmod(bashrc, stat.S_IREAD | stat.S_IWRITE)
    assert code == 1
    assert bashrc.read_bytes() == b"x\n"
    assert install.t("install.completion.not_written", names="").strip() in out
    assert (home / ".zshrc").read_bytes().startswith(BEGIN.encode())


def test_no_components_with_completion_is_not_exit_2(tmp_path, capsys):
    """REQ-030: `--no-hooks --no-skill --no-memory --no-mcp --shell-completion` con clientes
    presentes escribe el autocompletado, no toca los clientes y no sale con 2. Control positivo
    (comprobado): sin el `if shells` antes de `cli.install.no_component`, sale con 2."""
    home = make_home(tmp_path, complete=False)
    clients = {name: snapshot(home / name) for name in (".claude", ".codex")}
    off = ["--no-hooks", "--no-skill", "--no-memory", "--no-mcp"]
    code, out = run(install_cmd(home, *off, "--shell-completion", "bash"), capsys)
    assert code == 0, out
    assert (home / ".bashrc").is_file()
    assert {name: snapshot(home / name) for name in clients} == clients


def test_completion_only_dry_run_ends_with_the_dry_run_line(tmp_path, capsys):
    """REQ-008 (SDD backlog-minor-leftovers): with clients present, the «completion only»
    `--dry-run` (every component off) ends with the same final line as the other dry runs and
    writes nothing. Positive control (checked): without printing `cli.install.dry_run` in that
    branch, the last line is the last planned action and the second assert fails."""
    home = make_home(tmp_path, complete=False)
    before = snapshot(tmp_path)
    off = ["--no-hooks", "--no-skill", "--no-memory", "--no-mcp"]
    code, out = run(install_cmd(home, *off, "--shell-completion", "bash", "--dry-run"), capsys)
    assert code == 0, out
    assert out.strip().splitlines()[-1] == install.t("cli.install.dry_run")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize(
    "extra",
    [["--clients", "nope"], ["--clients", "claude", "--target", "codex"]],
    ids=["bad-choice", "clients-and-target"],
)
def test_invalid_clients_exit_2_before_writing_anything(home, tmp_path, capsys, extra):
    """REQ-030 paso 1: un `--clients` inválido sale con 2 sin crear nada. Control positivo
    (comprobado): con el autocompletado antes de `_resolve_clients`, el segundo caso deja
    `.bashrc`."""
    before = snapshot(tmp_path)
    code, _ = run(install_cmd(home, *extra, "--shell-completion"), capsys)
    assert code == 2
    assert snapshot(tmp_path) == before


def test_install_with_clients_and_completion_does_both(tmp_path, capsys):
    """REQ-030: con clientes, el autocompletado va primero y el flujo de clientes sigue igual."""
    home = make_home(tmp_path, complete=False)
    code, out = run(install_cmd(home, "--clients", "codex", "--shell-completion", "bash"), capsys)
    assert code == 0, out
    assert (home / ".bashrc").is_file()
    assert install.MD_BEGIN in (home / ".codex" / "AGENTS.md").read_text(encoding="utf-8")
    assert out.index(install.t("cli.install.completion.heading")) < out.index("AGENTS.md")


# --- REQ-031: --dry-run ---------------------------------------------------------------------------
def test_install_dry_run_writes_nothing_and_prints_the_block(home, tmp_path, capsys):
    """REQ-031: `install --dry-run` no escribe nada e imprime el bloque literal. Control positivo
    (comprobado): sin `literal=block`, falta el marcador en la salida."""
    before = snapshot(tmp_path)
    code, out = run(install_cmd(home, "--shell-completion", "--dry-run"), capsys)
    assert code == 0
    assert snapshot(tmp_path) == before
    assert BEGIN in out
    assert "[dry-run] [manifest]" in out


@pytest.mark.parametrize("extra", [[], ["--shell-completion"]], ids=["unrestricted", "explicit"])
def test_uninstall_dry_run_writes_nothing(home, tmp_path, capsys, extra):
    """REQ-031: `uninstall --dry-run` tras una instalación real no cambia nada."""
    assert run(install_cmd(home, "--shell-completion"), capsys)[0] == 0
    before = snapshot(tmp_path)
    code, out = run(uninstall_cmd(home, "--dry-run", *extra), capsys)
    assert code == 0
    assert snapshot(tmp_path) == before
    assert "[dry-run] [profile]" in out


# --- REQ-032 y REQ-046: ida y vuelta --------------------------------------------------------------
SEEDS = {
    "missing": None,
    "empty": b"",
    "final-newline": b"export A=1\nalias ll='ls -l'\n",
    "no-final-newline": b"export A=1\nalias ll='ls -l'",
    "crlf": b"export A=1\r\nexport B=2\r\n",
    "ansi-cp1252": "# configuración de José\r\nalias ñ=ls\r\n".encode("cp1252"),
    "utf16le-bom": codecs.BOM_UTF16_LE + "# ó\r\nexport A=1\r\n".encode("utf-16-le"),
}


@pytest.mark.parametrize("seed", list(SEEDS), ids=list(SEEDS))
def test_round_trip_leaves_the_profile_byte_for_byte(home, tmp_path, capsys, seed):
    """REQ-032 y REQ-046: `install` y `uninstall` devuelven el perfil byte a byte; uno que no
    existía no existe, y no queda `.local-delegate.bak`, ni `completion/`, ni manifiesto.
    Control positivo (comprobado): borrando el perfil vacío sin mirar si `install` lo creó, el
    caso «empty» desaparece."""
    profile = home / ".bashrc"
    if SEEDS[seed] is not None:
        profile.write_bytes(SEEDS[seed])
    before = snapshot(tmp_path)
    assert run(install_cmd(home, "--shell-completion", "bash"), capsys)[0] == 0
    assert BEGIN.encode() in profile.read_bytes() or seed == "utf16le-bom"
    code, out = run(uninstall_cmd(home), capsys)
    assert code == 0, out
    assert snapshot(tmp_path) == before
    assert not install.profile_backup_path(profile).exists()


def test_users_bak_is_untouched_and_an_edited_profile_keeps_the_copy(home, capsys):
    """REQ-046: el `.bashrc.bak` del usuario queda intacto; si el usuario edita el perfil entre
    `install` y `uninstall`, la copia propia se queda. Control positivo (comprobado): borrando la
    copia sin comparar, el último assert falla."""
    profile, users_bak = home / ".bashrc", home / ".bashrc.bak"
    profile.write_bytes(b"a\n")
    users_bak.write_bytes(b"de otro\n")
    assert run(install_cmd(home, "--shell-completion", "bash"), capsys)[0] == 0
    with profile.open("ab") as handle:
        handle.write(b"b\n")
    assert run(uninstall_cmd(home, "--shell-completion"), capsys)[0] == 0
    assert users_bak.read_bytes() == b"de otro\n"
    assert BEGIN.encode() not in profile.read_bytes()
    assert install.profile_backup_path(profile).read_bytes() == b"a\n"


def test_created_profile_edited_by_the_user_is_kept_without_a_copy(home, capsys):
    """REQ-032 y REQ-046: si `install` creó el perfil y el usuario le añadió algo, `uninstall`
    quita el bloque, no lo borra y no hace copia (el estado previo era «no existe»). Control
    positivo (comprobado): con `backup=True` siempre en `uninstall`, aparece la copia."""
    profile = home / ".bashrc"
    assert run(install_cmd(home, "--shell-completion", "bash"), capsys)[0] == 0
    with profile.open("ab") as handle:
        handle.write(b"export MIO=1\n")
    assert run(uninstall_cmd(home), capsys)[0] == 0
    assert profile.read_bytes() == b"export MIO=1\n"
    assert not install.profile_backup_path(profile).exists()


def test_stale_completion_file_is_replaced_without_bak(home, capsys):
    """REQ-026: un fichero de completado desfasado se reescribe entero y sin `.bak` (es nuestro).
    Control positivo (comprobado): con `_backup` antes de la escritura atómica, aparece
    `local-delegate.bash.bak`."""
    file = shell_profiles.completion_file(comp_dir(home), "bash")
    file.parent.mkdir(parents=True)
    file.write_bytes(b"# viejo\n")
    assert run(install_cmd(home, "--shell-completion", "bash"), capsys)[0] == 0
    assert file.read_bytes() == completion.render("bash", lang=SUITE_LANG).encode("utf-8")
    assert sorted(p.name for p in file.parent.iterdir()) == sorted(
        [file.name, completion.MANIFEST_NAME]
    )


def test_created_profile_parent_is_removed_only_if_install_created_it(tmp_path, capsys):
    """REQ-032: con pwsh en Linux, `install` crea `.config/powershell/` y su perfil; `uninstall`
    borra los dos, pero no `.config`, que ya existía. Control positivo (comprobado): sin `created_parent`, la
    carpeta `powershell` queda."""
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    before = snapshot(home)
    assert run(install_cmd(home, "--shell-completion", "powershell"), capsys)[0] == 0
    profile = home / ".config" / "powershell" / "profile.ps1"
    assert profile.is_file()
    assert manifest(home)["shells"][0]["profiles"][0] == {
        "path": str(profile),
        "created": True,
        "created_parent": True,
    }
    assert run(uninstall_cmd(home), capsys)[0] == 0
    assert snapshot(home) == before


SANDBOX_PROBES = {
    "windows": ShellProbes(
        platform="win32", which=_which("pwsh", "powershell"), simulated_policy="RemoteSigned"
    ),
    "linux": LINUX_PROBES,
}
#: On Linux `auto` is bash and zsh only; pwsh is named so that `.config/powershell/` appears.
SANDBOX_ALL_SHELLS = [f"--shell-completion={shell}" for shell in shell_profiles.SHELLS]


@pytest.mark.parametrize("system", list(SANDBOX_PROBES))
def test_round_trip_in_an_empty_sandbox_leaves_no_folder(home, monkeypatch, capsys, system):
    """REQ-005 (SDD backlog-minor-leftovers): with an empty simulated HOME and no data directory
    of its own, `install --shell-completion` creates `Documents/` (Windows) or `.config/`
    (Linux) and `.local/share/local-delegate/`; `uninstall` leaves the HOME as empty as it was.
    Positive control (checked): without the `created_ancestors` cleanup, `Documents` and `.local`
    are left behind and the last assert fails."""
    monkeypatch.delenv("LOCAL_DELEGATE_LOG_DIR", raising=False)
    use_probes(monkeypatch, SANDBOX_PROBES[system])
    shells = ["--shell-completion"] if system == "windows" else SANDBOX_ALL_SHELLS
    code, out = run(install_cmd(home, *shells), capsys)
    assert code == 0, out
    assert comp_dir(home) == home / ".local" / "share" / "local-delegate" / "completion"
    assert (home / ".local").is_dir()
    parent = "Documents" if system == "windows" else ".config"
    assert (home / parent).is_dir()
    code, out = run(uninstall_cmd(home), capsys)
    assert code == 0, out
    assert snapshot(home) == {}


def test_round_trip_keeps_folders_that_existed_or_got_foreign_content(home, monkeypatch, capsys):
    """REQ-005: a folder that existed before `install` stays even if it is empty, and one that
    `install` created but now holds something else stays with its content. Positive control
    (checked): removing every listed folder with `shutil.rmtree`, `foreign.txt` disappears; and
    recording folders that already existed, the empty `Documents/` disappears."""
    monkeypatch.delenv("LOCAL_DELEGATE_LOG_DIR", raising=False)
    use_probes(monkeypatch, SANDBOX_PROBES["windows"])
    (home / "Documents").mkdir()
    share = home / ".local" / "share"
    share.mkdir(parents=True)
    assert run(install_cmd(home, "--shell-completion"), capsys)[0] == 0
    foreign = home / ".local" / "share" / "local-delegate" / "foreign.txt"
    foreign.write_text("not ours", encoding="utf-8")
    assert run(uninstall_cmd(home), capsys)[0] == 0
    assert snapshot(home) == {
        "Documents": None,
        ".local": None,
        str(Path(".local", "share")): None,
        str(Path(".local", "share", "local-delegate")): None,
        str(Path(".local", "share", "local-delegate", "foreign.txt")): b"not ours",
    }


def test_uninstall_no_client_cli_still_removes_it(home, capsys):
    """REQ-032: `--no-client-cli` no es una restricción. Control positivo (comprobado): contando
    `no_client_cli` como restricción, el bloque se queda."""
    assert run(install_cmd(home, "--shell-completion", "bash"), capsys)[0] == 0
    assert run(uninstall_cmd(home, "--no-client-cli"), capsys)[0] == 0
    assert not (home / ".bashrc").exists()


@pytest.mark.parametrize(
    "extra",
    [["--clients", "codex"], ["--no-hooks"], ["--target", "claude"]],
    ids=["clients-codex", "no-hooks", "target"],
)
def test_restricted_uninstall_leaves_it(home, tmp_path, capsys, extra):
    """REQ-032: un `uninstall` restringido a clientes o componentes no toca el autocompletado.
    Es el control positivo del caso «sin restricciones» de arriba."""
    assert run(install_cmd(home, "--shell-completion", "bash"), capsys)[0] == 0
    files = snapshot(comp_dir(home))
    profile = (home / ".bashrc").read_bytes()
    run(uninstall_cmd(home, *extra), capsys)
    assert (home / ".bashrc").read_bytes() == profile
    assert snapshot(comp_dir(home)) == files


def test_uninstall_shell_completion_leaves_the_clients(tmp_path, capsys):
    """REQ-032: `uninstall --shell-completion` quita el autocompletado y deja hooks, skill,
    memoria y MCP. Control positivo (comprobado): sin la salida temprana de `completion_only`,
    desaparecen los hooks."""
    home = make_home(tmp_path)
    assert run(install_cmd(home, "--shell-completion", "bash"), capsys)[0] == 0
    clients = {name: snapshot(home / name) for name in (".claude", ".codex", ".config")}
    code, out = run(uninstall_cmd(home, "--shell-completion"), capsys)
    assert code == 0, out
    assert not (home / ".bashrc").exists()
    assert {name: snapshot(home / name) for name in clients} == clients


def test_partial_uninstall_by_shell_keeps_the_other_entry(home, capsys):
    """REQ-032: `uninstall --shell-completion zsh` quita zsh y deja bash, su fichero y su entrada.
    Control positivo (comprobado): borrando el manifiesto entero en un `uninstall` parcial, el
    último assert no encuentra el fichero."""
    assert run(install_cmd(home, "--shell-completion"), capsys)[0] == 0
    assert run(uninstall_cmd(home, "--shell-completion", "zsh"), capsys)[0] == 0
    assert not (home / ".zshrc").exists()
    assert (home / ".bashrc").is_file()
    assert [entry["shell"] for entry in manifest(home)["shells"]] == ["bash"]
    assert shell_profiles.completion_file(comp_dir(home), "bash").is_file()
    assert not shell_profiles.completion_file(comp_dir(home), "zsh").exists()


def test_uninstall_shell_completion_with_clients_removes_both(tmp_path, capsys):
    """REQ-032: `uninstall --shell-completion --clients codex` quita el autocompletado y Codex,
    y deja Claude. Control positivo (comprobado): con la salida temprana también con clientes explícitos,
    Codex se queda."""
    home = make_home(tmp_path)
    assert run(install_cmd(home, "--shell-completion", "bash"), capsys)[0] == 0
    claude = snapshot(home / ".claude")
    code, out = run(uninstall_cmd(home, "--shell-completion", "--clients", "codex"), capsys)
    assert code == 0, out
    assert not (home / ".bashrc").exists()
    assert install.MD_BEGIN not in (home / ".codex" / "AGENTS.md").read_text(encoding="utf-8")
    assert snapshot(home / ".claude") == claude


@pytest.mark.parametrize("extra", [[], ["--shell-completion"]], ids=["unrestricted", "explicit"])
def test_uninstall_with_nothing_installed(home, tmp_path, capsys, extra):
    """REQ-032: sin nada instalado, sale con 0 y no crea nada."""
    before = snapshot(tmp_path)
    code, out = run(uninstall_cmd(home, *extra), capsys)
    assert code == 0
    assert snapshot(tmp_path) == before
    if extra:
        assert install.t("install.completion.nothing_to_uninstall") in out


def test_uninstall_cleans_candidates_without_a_manifest(home, capsys):
    """REQ-032: sin manifiesto, el bloque se quita igual de los candidatos que existan."""
    assert run(install_cmd(home, "--shell-completion", "bash"), capsys)[0] == 0
    (comp_dir(home) / completion.MANIFEST_NAME).unlink()
    assert run(uninstall_cmd(home), capsys)[0] == 0
    # Sin manifiesto no se sabe que `install` lo creó: queda, vacío, y la copia propia (con el
    # bloque) se queda, como pide REQ-046 cuando no existía antes de `uninstall`.
    assert (home / ".bashrc").read_bytes() == b""
    assert BEGIN.encode() in install.profile_backup_path(home / ".bashrc").read_bytes()
    assert not comp_dir(home).exists()


# --- REQ-043: manifiesto --------------------------------------------------------------------------
def test_manifest_merges_a_second_shell_and_keeps_created(home, capsys):
    """REQ-043: una segunda instalación con otro shell fusiona; un perfil ya listado conserva su
    `created` original aunque ahora exista. Control positivo (comprobado): con `merge_manifest`
    dando prioridad a los perfiles nuevos y `created` recalculado con `edit.existed` (las dos
    capas que lo conservan), el perfil de bash pasa a `False`."""
    assert run(install_cmd(home, "--shell-completion", "bash"), capsys)[0] == 0
    assert run(install_cmd(home, "--shell-completion", "zsh"), capsys)[0] == 0
    assert run(install_cmd(home, "--shell-completion", "bash"), capsys)[0] == 0
    data = manifest(home)
    assert data["version"] == 1 and data["lang"] == SUITE_LANG
    assert [entry["shell"] for entry in data["shells"]] == ["zsh", "bash"]
    bash = next(entry for entry in data["shells"] if entry["shell"] == "bash")
    assert bash["profiles"] == [
        {"path": str(home / ".bashrc"), "created": True, "created_parent": False}
    ]
    assert bash["file"] == str(shell_profiles.completion_file(comp_dir(home), "bash"))


@pytest.mark.parametrize("raw", [b"{nope", b'{"version": 9}', b"\xff\xfe"])
def test_broken_manifest_does_not_raise(home, capsys, raw):
    """REQ-043: un manifiesto roto no hace lanzar: `install` avisa y lo reescribe; `uninstall`
    sigue con los candidatos y lo borra. Control positivo (comprobado): sin el `except` de
    `_read_manifest_or_warn`, `install` termina con la excepción."""
    directory = comp_dir(home)
    directory.mkdir(parents=True)
    (directory / completion.MANIFEST_NAME).write_bytes(raw)
    code, out = run(install_cmd(home, "--shell-completion", "bash"), capsys)
    assert code == 0, out
    assert "installed.json" in out
    assert manifest(home)["shells"][0]["shell"] == "bash"
    (directory / completion.MANIFEST_NAME).write_bytes(raw)
    code, out = run(uninstall_cmd(home), capsys)
    assert code == 0, out
    assert BEGIN.encode() not in (home / ".bashrc").read_bytes()
    assert not directory.exists()


def test_read_manifest_contract(tmp_path):
    """REQ-043: `None` sin fichero, el dato si es válido, `ManifestUnreadableError` si no."""
    assert completion.read_manifest(tmp_path) is None
    good = completion.merge_manifest(None, generator="1.0", lang="es", written={"zsh": ("/f", [])})
    (tmp_path / completion.MANIFEST_NAME).write_bytes(completion.manifest_bytes(good))
    assert completion.read_manifest(tmp_path) == good
    bad = {**good, "shells": [{"shell": "fish", "file": "/f", "profiles": []}]}
    (tmp_path / completion.MANIFEST_NAME).write_bytes(completion.manifest_bytes(bad))
    with pytest.raises(completion.ManifestUnreadableError):
        completion.read_manifest(tmp_path)


@pytest.mark.parametrize("lang", ["fr", "", "ES", 7])
def test_manifest_with_an_unknown_language_is_unreadable(tmp_path, lang):
    """REQ-010 (SDD backlog-minor-leftovers): `lang` must be a language of the catalog. `"fr"`
    made `render` raise inside the doctor probe, and `""` made the verdict depend on the session
    language. Positive control (checked): with `_valid_manifest` accepting any string, the first
    three cases DID NOT RAISE."""
    for known in i18n.LANGUAGES:
        good = completion.merge_manifest(None, generator="1.0", lang=known, written={})
        (tmp_path / completion.MANIFEST_NAME).write_bytes(completion.manifest_bytes(good))
        assert completion.read_manifest(tmp_path) == good
    bad = completion.merge_manifest(None, generator="1.0", lang="es", written={})
    bad["lang"] = lang
    (tmp_path / completion.MANIFEST_NAME).write_bytes(completion.manifest_bytes(bad))
    with pytest.raises(completion.ManifestUnreadableError):
        completion.read_manifest(tmp_path)


def test_manifest_created_ancestors_must_be_a_list_of_strings(tmp_path):
    """REQ-005: the optional `created_ancestors` lists (top level and per profile) are validated; a
    manifest without them (written by 0.38.0) is still valid."""
    profile = {"path": "/p", "created": True, "created_parent": True}
    base = completion.merge_manifest(
        None, generator="1.0", lang="es", written={"bash": ("/f", [profile])}
    )
    (tmp_path / completion.MANIFEST_NAME).write_bytes(completion.manifest_bytes(base))
    assert completion.read_manifest(tmp_path) == base
    for broken in (
        {**base, "created_ancestors": "/d"},
        {**base, "created_ancestors": [1]},
        {
            **base,
            "shells": [
                {**base["shells"][0], "profiles": [{**profile, "created_ancestors": [None]}]}
            ],
        },
    ):
        (tmp_path / completion.MANIFEST_NAME).write_bytes(completion.manifest_bytes(broken))
        with pytest.raises(completion.ManifestUnreadableError):
            completion.read_manifest(tmp_path)


# --- REQ-024 y REQ-044: shells ausentes y política ------------------------------------------------
def test_missing_shell_warns_and_writes_nothing(home, tmp_path, monkeypatch, capsys):
    """REQ-024: un shell pedido sin ejecutable se salta con aviso, sin escribir y con salida 0."""
    use_probes(monkeypatch, ShellProbes(platform="linux", which=_which("bash")))
    before = snapshot(tmp_path)
    code, out = run(install_cmd(home, "--shell-completion", "zsh"), capsys)
    assert code == 0
    assert install.t("install.completion.shell_missing", shell="zsh") in out
    assert snapshot(tmp_path) == before


def _windows(policy: str) -> ShellProbes:
    return ShellProbes(
        platform="win32", which=_which("pwsh", "powershell"), simulated_policy=policy
    )


@pytest.mark.parametrize("requested", [[], ["powershell"]], ids=["auto", "explicit"])
@pytest.mark.parametrize("policy", ["Restricted", "AllSigned", "Undefined"])
def test_blocking_policy_skips_with_a_warning(
    home, tmp_path, monkeypatch, capsys, policy, requested
):
    """REQ-044: con una política que bloquea, se salta con aviso, también con `powershell`
    explícito; las dos ediciones bloqueadas → ni `.ps1` ni manifiesto, y salida 0. Control
    positivo (comprobado): sin el `continue` tras `policy_blocks`, aparece el perfil."""
    use_probes(monkeypatch, _windows(policy))
    before = snapshot(tmp_path)
    code, out = run(install_cmd(home, "--shell-completion", *requested), capsys)
    assert code == 0
    assert install.t("install.completion.policy_blocks", edition="pwsh", policy=policy) in out
    assert snapshot(tmp_path) == before


def test_remote_signed_writes_both_editions_sharing_one_file(home, monkeypatch, capsys):
    """REQ-044 y REQ-026: con `RemoteSigned` se escriben las dos ediciones, que comparten
    `local-delegate.ps1`."""
    use_probes(monkeypatch, _windows("RemoteSigned"))
    code, out = run(install_cmd(home, "--shell-completion"), capsys)
    assert code == 0, out
    profiles = manifest(home)["shells"][0]["profiles"]
    assert [Path(p["path"]).parent.name for p in profiles] == ["PowerShell", "WindowsPowerShell"]
    file = shell_profiles.completion_file(comp_dir(home), "powershell")
    block = shell_profiles.load_block("powershell", file)
    for profile in profiles:
        assert Path(profile["path"]).read_text(encoding="utf-8") == block + "\n"


def test_real_home_policy_per_edition_and_unknown(tmp_path, monkeypatch, capsys):
    """REQ-044 con HOME «real» (consulta inyectada): pwsh `Restricted` se salta; 5.1 con la
    consulta fallida se escribe en la carpeta conocida y avisa de que no se pudo comprobar.
    Control positivo: con una política desconocida tratada como bloqueante, falta el perfil
    de 5.1."""
    home = tmp_path / "home"
    documents = home / "Docs"
    documents.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    answers = {
        "pwsh": (home / "pw" / "profile.ps1", "Restricted"),
        "powershell": (None, None),
    }
    probes = ShellProbes(
        platform="win32",
        which=_which("pwsh", "powershell"),
        query=lambda exe: answers[Path(exe).name],
        known_folder=lambda: documents,
    )
    plan = install.plan_completion_install(home, ["auto"], lang="es", probes=probes)
    assert install.t("install.completion.policy_blocks", edition="pwsh", policy="Restricted") in (
        plan.warnings
    )
    assert install.t("install.completion.policy_unknown", edition="powershell") in plan.warnings
    assert install.apply(plan.actions, dry_run=False, out=lambda _line: None) == 0
    assert (documents / "WindowsPowerShell" / "profile.ps1").is_file()
    assert not (home / "pw").exists()


@pytest.mark.parametrize(
    ("language", "policy_words", "unknown_word"),
    [("es", "política de ejecución", "desconocida"), ("en", "execution policy", "unknown")],
)
def test_policy_note_per_edition(tmp_path, monkeypatch, language, policy_words, unknown_word):
    """REQ-040: una línea por edición con la ruta del perfil y la política efectiva, deje pasar,
    bloquee o sea desconocida, en es y en. Control positivo (comprobado): sin añadir la nota en
    `plan_completion_install`, `plan.notes` sale vacío y falla el primer assert."""
    home = tmp_path / "home"
    documents = home / "Docs"
    documents.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    pwsh_profile = home / "pw" / "profile.ps1"
    for answers, expected in [
        (
            {"pwsh": (pwsh_profile, "RemoteSigned"), "powershell": (None, None)},
            [
                ("pwsh", pwsh_profile, "RemoteSigned"),
                ("powershell", documents / "WindowsPowerShell" / "profile.ps1", unknown_word),
            ],
        ),
        (
            {"pwsh": (pwsh_profile, "Restricted"), "powershell": (None, None)},
            [
                ("pwsh", pwsh_profile, "Restricted"),
                ("powershell", documents / "WindowsPowerShell" / "profile.ps1", unknown_word),
            ],
        ),
    ]:
        probes = ShellProbes(
            platform="win32",
            which=_which("pwsh", "powershell"),
            query=lambda exe, answers=answers: answers[Path(exe).name],
            known_folder=lambda: documents,
        )
        with i18n.override(language):
            plan = install.plan_completion_install(home, ["auto"], lang=language, probes=probes)
            lines = [
                install.t("install.completion.policy_note", edition=name, path=where, policy=value)
                for name, where, value in expected
            ]
        assert plan.notes == lines
        assert all(
            policy_words in line and str(path) in line
            for line, (_, path, _) in zip(plan.notes, expected, strict=True)
        )
        assert unknown_word in plan.notes[1]
        assert "Unknown" not in plan.notes[1]


@pytest.mark.parametrize("dry_run", [True, False], ids=["dry-run", "real"])
@pytest.mark.parametrize("policy", ["RemoteSigned", "Restricted"])
def test_install_output_shows_policy_per_edition(home, monkeypatch, capsys, dry_run, policy):
    """REQ-040: `install --shell-completion` enseña ruta y política de pwsh y de 5.1, con y sin
    `--dry-run`, también cuando la política bloquea. Control positivo (comprobado): sin imprimir
    `plan.notes` en `cli.py`, faltan las dos líneas."""
    use_probes(monkeypatch, _windows(policy))
    extra = ["--dry-run"] if dry_run else []
    code, out = run(install_cmd(home, "--shell-completion", *extra), capsys)
    assert code == 0, out
    for edition in ("pwsh", "powershell"):
        target = shell_profiles.ShellTarget("powershell", edition, edition)
        path = shell_profiles.simulated_profile(target, home, platform="win32")
        # The HOME is simulated, so the line says the policy is assumed (REQ-007).
        line = install.t(
            "install.completion.policy_note_assumed", edition=edition, path=path, policy=policy
        )
        assert line in out


@pytest.mark.parametrize(
    ("language", "assumed_words"),
    [("es", "supuesta: HOME simulado"), ("en", "assumed: simulated HOME")],
)
def test_simulated_home_policy_note_says_it_is_assumed(home, language, assumed_words):
    """REQ-007 (SDD backlog-minor-leftovers): with a simulated HOME nobody asks PowerShell, so the
    policy line says the policy is the assumed one, in es and en; with a real HOME it does not
    (`test_policy_note_per_edition`). Positive control (checked): with `policy_note` ignoring
    `location.assumed`, the line lacks the words and the first assert fails."""
    with i18n.override(language):
        plan = install.plan_completion_install(
            home, ["powershell"], lang=language, probes=_windows("RemoteSigned")
        )
    assert len(plan.notes) == 2
    assert all(assumed_words in note and "RemoteSigned" in note for note in plan.notes)


def test_untouchable_profile_is_reported_and_left_alone(home, capsys):
    """REQ-028: un perfil con un marcador sin pareja no se toca y se avisa; el otro shell sí."""
    bashrc = home / ".bashrc"
    bashrc.write_bytes(f"{BEGIN}\nhuérfano\n".encode())
    before = bashrc.read_bytes()
    code, out = run(install_cmd(home, "--shell-completion"), capsys)
    assert code == 0
    assert bashrc.read_bytes() == before
    assert install.t("install.completion.reason.marker_mismatch") in out
    assert (home / ".zshrc").is_file()


@pytest.mark.skipif(WINDOWS, reason="enlaces simbólicos sin privilegio en Windows")
def test_symlinked_profile_round_trip(home, tmp_path, capsys):
    """REQ-045: `.zshrc` como enlace a `dotfiles/zshrc`; tras `install` y `uninstall` sigue
    siendo un enlace y el destino vuelve byte a byte."""
    target = tmp_path / "dotfiles" / "zshrc"
    target.parent.mkdir()
    target.write_bytes(b"setopt x\n")
    (home / ".zshrc").symlink_to(target)
    assert run(install_cmd(home, "--shell-completion", "zsh"), capsys)[0] == 0
    assert (home / ".zshrc").is_symlink() and BEGIN.encode() in target.read_bytes()
    assert run(uninstall_cmd(home), capsys)[0] == 0
    assert (home / ".zshrc").is_symlink()
    assert target.read_bytes() == b"setopt x\n"


# --- Ida y vuelta real en PowerShell (pwsh 7 y Windows PowerShell 5.1) ----------------------------
#: ASCII: 5.1 lee sin BOM en la página ANSI. Carga el perfil como lo haría el shell (dot-source)
#: y completa dos líneas con `TabExpansion2`.
PROFILE_RUNNER = r"""
param([string]$Profile1, [string]$OutPath, [string]$Empty)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $Empty
$rows = @{}
foreach ($phase in @('before', 'after')) {
    if ($phase -eq 'after' -and (Test-Path -LiteralPath $Profile1)) { . $Profile1 }
    $found = @{}
    foreach ($line in @('local-delegate ins', 'local-delegate install --shell-completion ')) {
        $result = TabExpansion2 -inputScript $line -cursorColumn $line.Length
        $found[$line] = @($result.CompletionMatches | ForEach-Object { $_.CompletionText })
    }
    $rows[$phase] = $found
}
[System.IO.File]::WriteAllText($OutPath, ($rows | ConvertTo-Json -Depth 5 -Compress), (New-Object System.Text.UTF8Encoding $false))
"""

EDITIONS = (
    pytest.param("pwsh", marks=pytest.mark.shell("pwsh"), id="pwsh"),
    pytest.param("powershell", marks=pytest.mark.shell("powershell"), id="powershell"),
)


@pytest.mark.xdist_group("completion_powershell")
@pytest.mark.parametrize("edition", EDITIONS)
def test_real_powershell_round_trip(tmp_path, monkeypatch, capsys, edition):
    """Ida y vuelta real: `install --shell-completion powershell` en un HOME temporal con `ó` y
    espacio, el perfil cargado en el shell completa; `uninstall` deja el perfil (sembrado, en
    ANSI) byte a byte como estaba. Control positivo: la fase `before` no completa (sin el
    perfil no hay completer), y con el fichero de completado borrado tampoco. Comprobado:
    sin el dot-source del perfil en el runner, falla el assert de `install`."""
    executable = require_or_skip(edition)
    if not WINDOWS:
        pytest.skip("la ruta de perfil de cada edición solo existe en Windows")
    home = tmp_path / "hóme x"
    data = tmp_path / "dátos x"
    monkeypatch.setattr(config, "LOG_DIR", data)
    subdir = "PowerShell" if edition == "pwsh" else "WindowsPowerShell"
    profile = home / "Documents" / subdir / "profile.ps1"
    profile.parent.mkdir(parents=True)
    seed = "# configuración\r\n$x = 1\r\n".encode("cp1252")
    profile.write_bytes(seed)
    use_probes(
        monkeypatch,
        ShellProbes(platform="win32", which=lambda name: name if name == edition else None),
    )

    code, out = run(install_cmd(home, "--shell-completion", "powershell"), capsys)
    assert code == 0, out
    assert profile.read_bytes() != seed

    runner = tmp_path / "runner.ps1"
    runner.write_text(PROFILE_RUNNER, encoding="ascii")
    empty = tmp_path / "empty"
    empty.mkdir()

    def complete() -> dict:
        report = tmp_path / "report.json"
        done = subprocess.run(
            powershell_command(executable, runner, str(profile), str(report), str(empty)),
            env=powershell_env(edition),
            cwd=empty,
            capture_output=True,
            timeout=SHELL_TIMEOUT,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        assert done.returncode == 0, done.stderr.decode(errors="replace")
        return json.loads(report.read_text(encoding="utf-8"))

    rows = complete()
    assert rows["before"]["local-delegate ins"] in ([], None)
    assert "install" in rows["after"]["local-delegate ins"]
    values = rows["after"]["local-delegate install --shell-completion "]
    assert set(values) >= {"auto", "powershell", "zsh", "bash"}

    # Control de REQ-027: sin el fichero, el perfil carga sin error y no completa.
    file = shell_profiles.completion_file(comp_dir(home), "powershell")
    saved = file.read_bytes()
    file.unlink()
    assert complete()["after"]["local-delegate ins"] in ([], None)
    file.write_bytes(saved)

    code, out = run(uninstall_cmd(home), capsys)
    assert code == 0, out
    assert profile.read_bytes() == seed
    assert not install.profile_backup_path(profile).exists()
    assert not comp_dir(home).exists()
