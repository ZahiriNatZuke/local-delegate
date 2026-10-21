"""Check `scaffold.shell_completion` de `doctor` (SDD cli-completion, L4).

REQ-033 (estados del check, sin lanzar shells y con el mismo veredicto en los dos idiomas) y
REQ-043 (lectura del manifiesto). Todo en un HOME simulado (`tmp_path/home`) con el directorio de
datos de la suite (`config.LOG_DIR = tmp_path`, `conftest.isolate_runtime_logs`). La instalación
se hace con `install.plan_completion_install` y las sondas de un Linux con bash, zsh y pwsh, para
que el resultado no dependa del sistema que corre la suite.

Cada test anota su **control positivo**: la mutación del probe que lo pone en rojo (las marcadas
con «comprobado» se aplicaron a mano y el test falló por el assert que dice).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import snapshot

from local_delegate import checks, completion, i18n, install, shell_profiles
from local_delegate.install import ShellProbes
from local_delegate.version import get_version

SUITE_LANG = "es"
LINUX_PROBES = ShellProbes(
    platform="linux",
    which={name: f"/usr/bin/{name}" for name in ("bash", "zsh", "pwsh")}.get,
    shell_env="/usr/bin/zsh",
)


@pytest.fixture(autouse=True)
def linux_probes(monkeypatch):
    monkeypatch.setattr(install, "shell_probes", lambda: LINUX_PROBES)


@pytest.fixture
def home(tmp_path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


def install_completion(home: Path, shells=("bash", "zsh"), lang: str = SUITE_LANG) -> None:
    plan = install.plan_completion_install(home, list(shells), lang=lang)
    assert install.apply(plan.actions, dry_run=False, out=lambda _line: None) == 0


def comp_file(home: Path, shell: str) -> Path:
    return shell_profiles.completion_file(shell_profiles.completion_dir(home), shell)


def probe(home: Path) -> checks.Result:
    return checks._probe_shell_completion(checks.Context(home=home))


def t(key: str, **kwargs) -> str:
    return i18n.t(key, **kwargs)


def test_registered_in_scaffold_after_the_mcp_entries():
    """REQ-033: el check existe con su id, en `scaffold` (lo ve el reporte de `install`) y con
    título en los dos idiomas. Control positivo: sin la entrada en `CHECKS`, falla el `next`."""
    check = next(c for c in checks.CHECKS if c.id == "scaffold.shell_completion")
    assert check.group == "scaffold"
    assert i18n.t_lang("es", check.title_key) == "autocompletado del shell"
    assert i18n.t_lang("en", check.title_key) == "shell completion"


def test_nothing_installed_is_ok_and_renders_nothing(home, monkeypatch):
    """REQ-033: sin manifiesto ni ficheros, `ok` «no instalado (opcional)», sin construir el
    parser. Control positivo (comprobado): renderizando antes de mirar el manifiesto, el doble
    de `render` lanza y el probe no devuelve."""

    def _no_render(*_args, **_kwargs):
        raise AssertionError("render llamado sin nada instalado")

    monkeypatch.setattr(completion, "render", _no_render)
    result = probe(home)
    assert result == checks.Result(checks.OK, t("doctor.probe.shell_completion.not_installed"), "")


def test_installed_is_ok_with_language_and_profiles(home, tmp_path):
    """REQ-033: instalado y al día → `ok`, con el idioma y los perfiles en el detalle, y sin
    escribir nada (el probe es de solo lectura). Control positivo: comparando con
    `render(shell, lang="en")`, sale `warn`."""
    install_completion(home)
    before = snapshot(tmp_path)
    result = probe(home)
    assert result.status == checks.OK, result.detail
    assert result.fix_hint == ""
    expected = t(
        "doctor.probe.shell_completion.current",
        shell="bash",
        lang=SUITE_LANG,
        profiles=str(home / ".bashrc"),
    )
    assert expected in result.detail
    assert str(home / ".zshrc") in result.detail
    assert snapshot(tmp_path) == before


def test_same_verdict_with_the_session_in_english(home, monkeypatch):
    """REQ-033: fichero en `es` y `doctor` con `LOCAL_DELEGATE_LANG=en` → `ok` en los dos idiomas,
    el mismo veredicto (solo cambia el idioma del detalle). Control positivo (comprobado): con
    `render(shell)` sin `lang`, la pasada en `en` da `warn`."""
    install_completion(home, lang="es")
    spanish = probe(home)
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    i18n.reset()
    assert i18n.lang() == "en"
    english = probe(home)
    assert spanish.status == english.status == checks.OK, (spanish, english)
    assert "up to date in language es" in english.detail
    assert "al día en el idioma es" in spanish.detail


def test_older_version_header_warns_with_update(home):
    """REQ-033: un fichero con la cabecera de la 0.0.1 → `warn` con `local-delegate update`, y el
    detalle dice las dos versiones. Control positivo: sin comparar contra `render`, sale `ok`."""
    install_completion(home, shells=("bash",))
    file = comp_file(home, "bash")
    text = file.read_text(encoding="utf-8")
    first, rest = text.split("\n", 1)
    file.write_bytes((first.replace(get_version(), "0.0.1") + "\n" + rest).encode("utf-8"))
    assert completion.header_version(file.read_text(encoding="utf-8")) == "0.0.1"
    result = probe(home)
    assert result.status == checks.WARN
    assert result.fix_hint == "local-delegate update"
    assert (
        t(
            "doctor.probe.shell_completion.stale_version",
            path=file,
            found="0.0.1",
            installed=get_version(),
        )
        in result.detail
    )


def test_same_version_different_content_warns_with_update(home):
    """REQ-033: misma cabecera y otro contenido → `warn`, «contenido distinto». Control positivo:
    con la rama de versión sin la condición `found != installed`, el detalle habla de versiones."""
    install_completion(home, shells=("bash",))
    file = comp_file(home, "bash")
    file.write_bytes(file.read_bytes() + b"# editado a mano\n")
    result = probe(home)
    assert result.status == checks.WARN
    assert result.fix_hint == "local-delegate update"
    assert t("doctor.probe.shell_completion.content_differs", path=file) in result.detail


def test_deleted_block_warns_with_install(home):
    """REQ-033, control positivo del falso OK: el fichero sigue al día, pero el usuario borró el
    bloque de `.bashrc` → `warn` con `install --shell-completion`. Control positivo
    (comprobado): sin el recorrido de los perfiles, sale `ok` (el falso OK que el check evita)."""
    install_completion(home)
    bashrc = home / ".bashrc"
    bashrc.write_bytes(b"alias ll='ls -l'\n")
    result = probe(home)
    assert result.status == checks.WARN, result.detail
    assert result.fix_hint == "local-delegate install --shell-completion"
    assert t("doctor.probe.shell_completion.no_block", path=bashrc) in result.detail
    # el otro shell sigue al día y se dice
    assert "zsh: " in result.detail


def test_block_pointing_elsewhere_warns(home):
    """REQ-033: el bloque debe apuntar a SU fichero; uno que carga otra ruta no cuenta. Control
    positivo: mirando solo los marcadores (`_has_block`), sale `ok`."""
    install_completion(home, shells=("bash",))
    other = shell_profiles.load_block("bash", home / "other.bash")
    (home / ".bashrc").write_bytes((other + "\n").encode("utf-8"))
    assert probe(home).status == checks.WARN


def test_deleted_profile_warns_with_install(home):
    """REQ-033: un perfil listado que ya no existe no tiene el bloque → `warn`. Control positivo:
    tratando «no existe» como `ok`, falla el estado."""
    install_completion(home, shells=("bash",))
    (home / ".bashrc").unlink()
    result = probe(home)
    assert result.status == checks.WARN
    assert result.fix_hint == "local-delegate install --shell-completion"


def test_missing_file_warns_with_install(home):
    """REQ-033: falta un fichero listado → `warn` con `install --shell-completion` (no `update`,
    que no crea ficheros). Control positivo: con `FileNotFoundError` como `unknown`, falla el
    estado."""
    install_completion(home, shells=("bash",))
    file = comp_file(home, "bash")
    file.unlink()
    result = probe(home)
    assert result.status == checks.WARN
    assert result.fix_hint == "local-delegate install --shell-completion"
    assert t("doctor.probe.shell_completion.file_missing", path=file) in result.detail


def test_files_without_manifest_warn_with_install(home):
    """REQ-033: ficheros de completado sin manifiesto → `warn` con `install --shell-completion`.
    Control positivo (comprobado): sin la búsqueda de ficheros no listados, sale `ok` «no
    instalado»."""
    install_completion(home, shells=("bash",))
    directory = shell_profiles.completion_dir(home)
    completion.manifest_path(directory).unlink()
    result = probe(home)
    assert result.status == checks.WARN
    assert result.fix_hint == "local-delegate install --shell-completion"
    assert str(comp_file(home, "bash")) in result.detail


def test_file_not_in_the_manifest_warns(home):
    """REQ-033: con manifiesto, un fichero de otro shell que no figura en él también cuenta.
    Control positivo: buscando no listados solo sin manifiesto, sale `ok`."""
    install_completion(home, shells=("bash",))
    comp_file(home, "zsh").write_bytes(b"# suelto\n")
    result = probe(home)
    assert result.status == checks.WARN
    assert result.fix_hint == "local-delegate install --shell-completion"


@pytest.mark.parametrize("raw", [b"{no es json", b'{"version": 99}'])
def test_unreadable_manifest_is_unknown(home, raw):
    """REQ-033/REQ-043: manifiesto ilegible o de otro esquema → `unknown`, sin lanzar. Control
    positivo: dejando escapar `ManifestUnreadableError`, el test ve la excepción."""
    install_completion(home, shells=("bash",))
    completion.manifest_path(shell_profiles.completion_dir(home)).write_bytes(raw)
    result = probe(home)
    assert result.status == checks.UNKNOWN
    assert result.fix_hint == ""


def test_unreadable_profile_is_unknown(home):
    """REQ-033: un perfil listado que no se puede leer (aquí, un directorio) → `unknown`, nunca
    `warn` con «reinstala». Control positivo: tratando todo `reason` como bloque ausente, sale
    `warn`."""
    install_completion(home, shells=("bash",))
    bashrc = home / ".bashrc"
    bashrc.unlink()
    bashrc.mkdir()
    result = probe(home)
    assert result.status == checks.UNKNOWN, result.detail
    assert result.fix_hint == ""


def test_unreadable_file_is_unknown(home):
    """REQ-033: un fichero listado ilegible (un directorio en su sitio) → `unknown`. Control
    positivo: capturando solo `FileNotFoundError`, el probe lanza."""
    install_completion(home, shells=("bash",))
    file = comp_file(home, "bash")
    file.unlink()
    file.mkdir()
    result = probe(home)
    assert result.status == checks.UNKNOWN, result.detail


def test_doctor_runs_it_without_a_process(home, monkeypatch):
    """REQ-033: el probe no lanza procesos. Control positivo: con una consulta a PowerShell en el
    probe, el doble de `subprocess.run` lanza."""
    import subprocess

    install_completion(home, shells=("bash", "powershell"))

    def _no_process(*_args, **_kwargs):
        raise AssertionError("el check lanzó un proceso")

    monkeypatch.setattr(subprocess, "run", _no_process)
    monkeypatch.setattr(subprocess, "Popen", _no_process)
    assert probe(home).status == checks.OK
