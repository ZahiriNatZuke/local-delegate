"""`update` regenera el autocompletado instalado (SDD cli-completion, L4).

REQ-034 (refresco en el idioma configurado, paso propio fuera de `REPAIRS`, también sin
clientes) y REQ-043 (lectura del manifiesto). Todo en un HOME simulado **sin ningún cliente**
(`tmp_path/home` vacío) con el directorio de datos de la suite (`conftest.isolate_runtime_logs`):
si el refresco dependiera de un cliente presente, estos tests no verían ninguna acción.

Cada test anota su **control positivo**: la mutación que lo pone en rojo (las marcadas con
«comprobado» se aplicaron a mano y el test falló por el assert que dice).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import snapshot

from local_delegate import checks, completion, install, shell_profiles, update
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


def opts_for(home: Path, **kwargs) -> update.Options:
    """Options sin red, sin procesos y sin esperas reales."""
    defaults = {
        "runner": lambda argv: subprocess.CompletedProcess(argv, 0, "", ""),
        "daemon_status": lambda host, port: None,
        "sleep": lambda seconds: None,
        "spawn": lambda argv: None,
    }
    defaults.update(kwargs)
    return update.Options(home=home, **defaults)


def install_completion(home: Path, shells=("bash", "zsh"), lang: str = SUITE_LANG) -> None:
    plan = install.plan_completion_install(home, list(shells), lang=lang)
    assert install.apply(plan.actions, dry_run=False, out=lambda _line: None) == 0


def comp_dir(home: Path) -> Path:
    return shell_profiles.completion_dir(home)


def comp_file(home: Path, shell: str) -> Path:
    return shell_profiles.completion_file(comp_dir(home), shell)


def read_manifest(home: Path) -> dict:
    return json.loads(completion.manifest_path(comp_dir(home)).read_text(encoding="utf-8"))


def age(home: Path, shell: str = "bash") -> None:
    """Deja el fichero y el manifiesto como los habría dejado la 0.0.1."""
    file = comp_file(home, shell)
    text = file.read_text(encoding="utf-8")
    first, rest = text.split("\n", 1)
    file.write_bytes((first.replace(get_version(), "0.0.1") + "\n" + rest).encode("utf-8"))
    data = read_manifest(home)
    data["generator"] = "0.0.1"
    completion.manifest_path(comp_dir(home)).write_bytes(completion.manifest_bytes(data))


def apply(actions) -> None:
    assert install.apply(actions, dry_run=False, out=lambda _line: None) == 0


def test_without_clients_an_old_file_is_rewritten_once(home):
    """REQ-034: sin ningún cliente y con el fichero de la 0.0.1 → una acción de fichero (más la
    del manifiesto, que dice la versión nueva); después el fichero es `render` y la segunda
    pasada no planifica nada. Los perfiles no se tocan. Control positivo (comprobado): con el
    refresco dentro de `REPAIRS` (que solo actúa con clientes presentes), no hay acciones."""
    install_completion(home)
    age(home)
    assert install.present_targets(home) == set()
    profiles = {p: p.read_bytes() for p in (home / ".bashrc", home / ".zshrc")}
    actions = update.plan_completion_refresh(opts_for(home))
    assert [a.kind for a in actions] == ["completion", "manifest"], actions
    assert actions[0].target == comp_file(home, "bash")
    apply(actions)
    assert comp_file(home, "bash").read_bytes() == completion.render(
        "bash", lang=SUITE_LANG
    ).encode("utf-8")
    assert read_manifest(home)["generator"] == get_version()
    assert {p: p.read_bytes() for p in profiles} == profiles
    assert update.plan_completion_refresh(opts_for(home)) == []
    # y el check de `doctor` queda en `ok`
    assert checks._probe_shell_completion(checks.Context(home=home)).status == checks.OK


def test_configured_language_change_rewrites_in_that_language(home, monkeypatch):
    """REQ-034: ficheros en `es` con el idioma configurado en `en` → se reescriben en `en` y el
    manifiesto dice `en`; segunda pasada, nada. Control positivo (comprobado): con
    `lang=manifest["lang"]` en vez del configurado, no hay acciones."""
    install_completion(home, shells=("bash",), lang="es")
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    actions = update.plan_completion_refresh(opts_for(home))
    assert [a.kind for a in actions] == ["completion", "manifest"], actions
    apply(actions)
    assert comp_file(home, "bash").read_bytes() == completion.render("bash", lang="en").encode(
        "utf-8"
    )
    assert read_manifest(home)["lang"] == "en"
    assert update.plan_completion_refresh(opts_for(home)) == []


def test_without_manifest_nothing_is_planned(home):
    """REQ-034: sin manifiesto no hay acciones, ni siquiera con ficheros sueltos (no se crean ni
    se adoptan ficheros no listados). Control positivo: recorriendo `SHELLS` en vez del
    manifiesto, el fichero suelto da una acción."""
    assert update.plan_completion_refresh(opts_for(home)) == []
    loose = comp_file(home, "bash")
    loose.parent.mkdir(parents=True)
    loose.write_bytes(b"# suelto\n")
    assert update.plan_completion_refresh(opts_for(home)) == []


def test_unreadable_manifest_plans_nothing(home):
    """REQ-043: un manifiesto roto no hace lanzar a `update`. Control positivo: dejando escapar
    `ManifestUnreadableError`, el test ve la excepción."""
    install_completion(home, shells=("bash",))
    completion.manifest_path(comp_dir(home)).write_bytes(b"{roto")
    assert update.plan_completion_refresh(opts_for(home)) == []


def test_a_missing_listed_file_is_not_created(home):
    """REQ-034: «no crea ficheros»: un fichero listado que falta lo repone `install
    --shell-completion` (lo dice el check), no `update`. Control positivo: sin el `continue` del
    `OSError`, `read_bytes` lanza."""
    install_completion(home, shells=("bash",))
    comp_file(home, "bash").unlink()
    assert update.plan_completion_refresh(opts_for(home)) == []


def test_run_update_rewrites_and_does_not_tell_to_run_update(home, monkeypatch, tmp_path):
    """REQ-034: `run_update` llama al refresco (sin clientes) y no imprime el aviso «ejecuta
    `local-delegate update`» del check, que sería decírselo desde el propio `update`. Control
    positivo (comprobado): sin la llamada en `run_update`, el fichero queda viejo; sin el filtro
    de `notes`, aparece el aviso."""
    monkeypatch.setattr(update, "latest_version", lambda timeout=0: (None, "sin red"))
    install_completion(home, shells=("bash",))
    age(home)
    lines: list[str] = []
    code = update.run_update(opts_for(home, no_restart=True), out=lines.append)
    output = "\n".join(lines)
    assert code == 0, output
    assert comp_file(home, "bash").read_bytes() == completion.render(
        "bash", lang=SUITE_LANG
    ).encode("utf-8")
    title = next(c.title for c in checks.CHECKS if c.id == "scaffold.shell_completion")
    assert title not in output, output
    # La segunda pasada ya no toca nada del autocompletado.
    before = snapshot(tmp_path)
    update.run_update(opts_for(home, no_restart=True), out=lambda _line: None)
    after = snapshot(tmp_path)
    changed = [k for k in after if after.get(k) != before.get(k)]
    assert not [k for k in changed if "completion" in k], changed


def test_dry_run_writes_nothing(home, monkeypatch, tmp_path):
    """REQ-034: con `--dry-run`, el refresco se dice pero no se escribe. Control positivo: con
    `dry_run=False` en el `apply`, cambia el snapshot."""
    monkeypatch.setattr(update, "latest_version", lambda timeout=0: (None, "sin red"))
    install_completion(home, shells=("bash",))
    age(home)
    before = snapshot(tmp_path)
    update.run_update(opts_for(home, dry_run=True), out=lambda _line: None)
    assert snapshot(tmp_path) == before
