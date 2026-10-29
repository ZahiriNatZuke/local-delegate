"""Tests de `local-delegate update`.

Ningún test sale a la red, escribe fuera de `tmp_path` ni lanza un proceso: el ejecutor de
comandos, el estado del daemon, el reloj y el `spawn` se inyectan por `Options`. Lo que más se
vigila aquí no es que una reparación funcione, sino **que no ocurra cuando no debe**: `unknown`
nunca repara, `warn` solo repara donde significa «es nuestro y está viejo», y un pid que no
confirmó `/api/daemon` no recibe ninguna señal.
"""

from __future__ import annotations

import subprocess

import pytest
from conftest import OLD_SKILL_NAME, downgrade_to_0_34, live_memory_files, make_home, snapshot

from local_delegate import agents, checks, install, update
from local_delegate.failures import BackendView


@pytest.fixture(autouse=True)
def _without_real_signals(monkeypatch):
    """Ningún test de este fichero manda una señal de verdad.

    Varios dan un pid inventado a `restart_daemon` (999, 7) sin doblar `os.kill`, y la señal
    salía de verdad contra lo que tuviera ese pid en la máquina. En el PR #242 el runner de macOS
    recibió dos veces seguidas «The runner has received a shutdown signal» justo al llegar a estos
    tests, con la suite entera en verde. Los tests que miran qué se mata lo vuelven a
    doblar con su propia lista, y ese doble gana porque se pone después.
    """
    monkeypatch.setattr(update.os, "kill", lambda pid, sig: None)


def fake_run(returncode=0, stdout="", stderr=""):
    """Runner doble que registra lo que se le pidió ejecutar."""
    calls: list[list[str]] = []

    def runner(argv):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def opts_for(home, **kwargs):
    """Options con todo doblado: sin red, sin procesos y sin esperas reales."""
    defaults = {
        "runner": fake_run(),
        "daemon_status": lambda host, port: None,
        "sleep": lambda seconds: None,
        "clock": _fake_clock(),
        "spawn": lambda argv: None,
    }
    defaults.update(kwargs)
    return update.Options(home=home, **defaults)


def _fake_clock():
    """Reloj que avanza solo: sin esto, `wait_until_up` esperaría de verdad en los tests."""
    ticks = iter(range(10_000))

    def clock():
        return float(next(ticks))

    return clock


def results_from(**statuses):
    """Lista (Check, Result) con el estado que se pida por id; el resto en `ok`."""
    return [
        (check, checks.Result(statuses.get(check.id, checks.OK), f"detalle de {check.id}"))
        for check in checks.CHECKS
    ]


# --- La regla que ordena toda la tabla: `unknown` no repara -------------------


def test_unknown_repairs_none_of_the_twelve_checks(tmp_path):
    """La regla que hereda de `checks`: lo que no se pudo comprobar no se toca.

    Se recorren los doce, no solo los reparables: si mañana entra un check nuevo a la tabla
    con `unknown` entre sus estados, este test lo caza.
    """
    home = make_home(tmp_path, complete=False)
    all_unknown = {check.id: checks.UNKNOWN for check in checks.CHECKS}
    actions, _notes = update.plan_repairs(results_from(**all_unknown), opts_for(home))
    assert actions == []


def test_client_observed_is_never_repaired(tmp_path):
    """Con quién se ha hablado no se «arregla»: es una observación, no una configuración.

    El check no tiene `fix_hint` ni entrada en `REPAIRS`, y este test lo ata para que nadie le
    añada una reparación por simetría con el resto de la tabla.
    """
    assert [r for r in update.REPAIRS if r.check_id == "client.observed"] == []
    home = make_home(tmp_path, complete=False)
    for state in (checks.OK, checks.WARN, checks.MISSING, checks.UNKNOWN):
        results = results_from(**{"client.observed": state})
        actions, _notes = update.plan_repairs(results, opts_for(home))
        assert all(getattr(a, "check_id", None) != "client.observed" for a in actions)


def test_service_credential_is_never_repaired(tmp_path):
    """El transporte de la entrada MCP lo elige el usuario; `update` no se lo cambia.

    Este check **sí** se sabría reparar —reinstalar en modo `http`, que `_infer_mcp_mode` ya sabe
    elegir—, y justo por eso hace falta atarlo: la reparación es tan fácil de añadir «por simetría»
    con el resto de la tabla que alguien la pondría sin ver que pisa una decisión del usuario. Mismo
    criterio que el `warn` de `scaffold.mcp_codex`.
    """
    assert [r for r in update.REPAIRS if r.check_id == "service.credential"] == []
    home = make_home(tmp_path, complete=False)
    for state in (checks.OK, checks.WARN, checks.MISSING, checks.UNKNOWN):
        results = results_from(**{"service.credential": state})
        actions, _notes = update.plan_repairs(results, opts_for(home))
        assert all(getattr(a, "check_id", None) != "service.credential" for a in actions)


def test_mcp_codex_warn_produces_no_action(tmp_path):
    """Ese `warn` dice «entrada puesta a mano»: es configuración del usuario, no basura nuestra."""
    home = make_home(tmp_path, complete=False)
    results = results_from(**{"scaffold.mcp_codex": checks.WARN})
    actions, _notes = update.plan_repairs(results, opts_for(home))
    assert [a for a in actions if a.kind == "toml"] == []


def test_hook_settings_warn_does_repair(tmp_path):
    """Aquí `warn` significa «hooks nuestros en formato viejo», y reinstalarlos es lo correcto."""
    home = make_home(tmp_path, complete=False)
    results = results_from(**{"scaffold.hook_settings": checks.WARN})
    actions, _notes = update.plan_repairs(results, opts_for(home))
    assert any(a.kind == "settings" for a in actions)


def test_skill_warn_does_repair(tmp_path):
    home = make_home(tmp_path, complete=False)
    results = results_from(**{"scaffold.skill": checks.WARN})
    actions, _notes = update.plan_repairs(results, opts_for(home))
    assert any(a.kind == "copy" and "skills" in str(a.target) for a in actions)


def test_orphan_hooks_warn_plans_the_removal(tmp_path):
    """Aquí `warn` significa «scripts nuestros de una instalación anterior»: sobran, y se van."""
    home = make_home(tmp_path, complete=False)
    root = home / ".claude" / "hooks"
    root.mkdir(parents=True, exist_ok=True)
    (root / "hook_common.py").write_text("# viejo\n", encoding="utf-8")

    results = results_from(**{"scaffold.hook_orphans": checks.WARN})
    actions, _notes = update.plan_repairs(results, opts_for(home))
    assert any(a.kind == "prune" for a in actions)


def test_orphans_and_missing_hooks_do_not_plan_the_same_thing_twice(tmp_path):
    """Los dos checks reparan con `components={"hooks"}`, que emite la copia **y** el retirado.

    Sin la deduplicación por `(kind, target)` habría dos copias del árbol —y la copia hace
    `rmtree` del destino, así que la segunda borraría lo que escribió la primera— y dos prunes.
    """
    home = make_home(tmp_path, complete=False)
    root = home / ".claude" / "hooks"
    root.mkdir(parents=True, exist_ok=True)
    (root / "hook_common.py").write_text("# viejo\n", encoding="utf-8")

    results = results_from(
        **{"scaffold.hook_orphans": checks.WARN, "scaffold.hook_files": checks.MISSING}
    )
    actions, _notes = update.plan_repairs(results, opts_for(home))
    assert len([a for a in actions if a.kind == "copy" and "hooks" in str(a.target)]) == 1
    assert len([a for a in actions if a.kind == "prune"]) == 1


def test_a_client_that_does_not_exist_is_not_repaired(tmp_path):
    """Con Codex ausente, un `missing` suyo no crea `~/.codex` de la nada."""
    home = make_home(tmp_path, claude=True, codex=False, complete=False)
    results = results_from(**{"scaffold.mcp_codex": checks.MISSING})
    actions, _notes = update.plan_repairs(results, opts_for(home))
    assert [a for a in actions if "codex" in str(a.target).lower()] == []


# --- Deduplicación: dos borrados del mismo directorio serían un desastre ------


def test_incomplete_hooks_do_not_plan_two_deletions_of_the_same_directory(tmp_path):
    """`plan_install` emite copia + registro, y la copia hace `rmtree` antes de copiar.

    Con `hook_files` y `hook_settings` los dos en `missing` se invoca dos veces, así que sin
    deduplicar habría **dos** acciones `copy` sobre el mismo destino: la segunda borraría lo
    que acababa de escribir la primera.
    """
    home = make_home(tmp_path, complete=False)
    results = results_from(
        **{"scaffold.hook_files": checks.MISSING, "scaffold.hook_settings": checks.MISSING}
    )
    actions, _notes = update.plan_repairs(results, opts_for(home))
    copies = [a for a in actions if a.kind == "copy" and "hooks" in str(a.target)]
    assert len(copies) == 1


# --- Idempotencia: sale del diseño, se comprueba contando acciones ------------


def test_a_complete_home_plans_nothing(tmp_path):
    home = make_home(tmp_path, complete=True)
    actions, _notes = update.plan_repairs(results_from(), opts_for(home))
    assert actions == []


def test_second_pass_over_the_same_home_plans_nothing(tmp_path):
    """La prueba de la idempotencia de verdad: se repara y se vuelve a diagnosticar."""
    home = make_home(tmp_path, complete=False)
    ctx = _ctx(home)
    actions, _notes = update.plan_repairs(checks.run_all(ctx), opts_for(home))
    assert actions, "la primera pasada debía tener algo que reparar"
    install.apply(actions, dry_run=False, out=lambda *a: None)

    second, _notes = update.plan_repairs(checks.run_all(_ctx(home)), opts_for(home))
    assert second == []


def _ctx(home):
    return checks.Context(
        home=home,
        daemon_status=lambda host, port: None,
        backend_models=lambda: BackendView(True, "", None, "direct"),
        version_of=lambda component, cfg: ("v238", None),
        latest_release=checks.SKIP_PYPI,
    )


# --- `--dry-run` no escribe ni reinicia --------------------------------------


def test_dry_run_leaves_the_tree_byte_for_byte_identical(tmp_path):
    home = make_home(tmp_path, complete=False)
    before = snapshot(home)
    opts = opts_for(home, dry_run=True)
    update.run_update(opts, out=lambda *a: None)
    assert snapshot(home) == before


def test_dry_run_does_not_restart_the_daemon(tmp_path):
    runner = fake_run()
    opts = opts_for(make_home(tmp_path, complete=False), dry_run=True, runner=runner)
    update.run_update(opts, out=lambda *a: None)
    assert runner.calls == []


# --- Cómo está instalado esto -------------------------------------------------
# `update` actualiza el pin, el andamiaje y el daemon, pero NO el ejecutable de `uv tool`. Y no
# puede hacerlo: probado en Windows, reinstalar el entorno desde el que corre el proceso falla al
# borrar `Scripts/` y deja la instalación destruida (ya había borrado el paquete).


def _fake_prefix(monkeypatch, tmp_path, receipt: str | None):
    """Un `sys.prefix` de mentira, con o sin `uv-receipt.toml` dentro."""
    monkeypatch.setattr(update, "editable_origin", lambda: None)
    monkeypatch.setattr(update.sys, "prefix", str(tmp_path))
    tmp_path.mkdir(parents=True, exist_ok=True)
    if receipt is not None:
        (tmp_path / "uv-receipt.toml").write_text(receipt, encoding="utf-8")
    return tmp_path


def test_recognizes_a_uv_tool_install(monkeypatch, tmp_path):
    _fake_prefix(monkeypatch, tmp_path, f'[tool]\nrequirements = [{{ name = "{update.PACKAGE}" }}]')
    assert update.install_kind() == update.UV_TOOL
    assert update.upgrade_command() == update.UV_TOOL_UPGRADE


def test_without_a_receipt_nothing_is_claimed(monkeypatch, tmp_path):
    """`pip`, `pipx`, conda… no se adivina: comando genérico, no uno que podría fallar."""
    _fake_prefix(monkeypatch, tmp_path, None)
    assert update.install_kind() == update.OTHER
    assert update.upgrade_command() == update.generic_upgrade()


def test_a_receipt_from_another_package_is_not_ours(monkeypatch, tmp_path):
    _fake_prefix(monkeypatch, tmp_path, '[tool]\nrequirements = [{ name = "otra-cosa" }]')
    assert update.install_kind() == update.OTHER


def test_the_editable_wins_over_the_receipt(monkeypatch, tmp_path):
    """Si se dieran los dos, manda la editable: es lo que gobierna de dónde sale el código."""
    _fake_prefix(monkeypatch, tmp_path, f'[tool]\nname = "{update.PACKAGE}"')
    monkeypatch.setattr(update, "editable_origin", lambda: tmp_path / "repo")
    assert update.install_kind() == update.EDITABLE
    assert "git -C" in update.upgrade_command()


def test_an_unreadable_prefix_does_not_break_detection(monkeypatch):
    monkeypatch.setattr(update, "editable_origin", lambda: None)
    monkeypatch.setattr(update.sys, "prefix", "\x00 ruta imposible \x00")
    assert update.install_kind() == update.OTHER


# --- Instalación de `uv tool` fijada con `==` (issue #488) ------------------------
# `uv tool upgrade` no mueve una instalación fijada: «Nothing to upgrade», código 0. La forma del
# receipt es la real de esta PC tras `uv tool install "local-delegate-mcp[llamaswap]==0.45.0"`.
_PINNED_WITH_EXTRAS = (
    "[tool]\n"
    'requirements = [{ name = "local-delegate-mcp", extras = ["llamaswap"], '
    'specifier = "==0.45.0" }]\n'
    "entrypoints = [\n"
    '    { name = "local-delegate", install-path = "C:/x/local-delegate.exe", '
    'from = "local-delegate-mcp" },\n'
    "]\n"
)


def test_a_pinned_install_with_extras_gets_install_latest_with_its_extras(monkeypatch, tmp_path):
    _fake_prefix(monkeypatch, tmp_path, _PINNED_WITH_EXTRAS)
    assert update.install_kind() == update.UV_TOOL
    assert update.upgrade_command() == 'uv tool install "local-delegate-mcp[llamaswap]@latest"'


def test_a_pinned_install_without_extras_gets_install_latest(monkeypatch, tmp_path):
    _fake_prefix(
        monkeypatch,
        tmp_path,
        '[tool]\nrequirements = [{ name = "local-delegate-mcp", specifier = "==0.44.2" }]\n',
    )
    assert update.upgrade_command() == "uv tool install local-delegate-mcp@latest"


@pytest.mark.parametrize(
    "entry",
    [
        '{ name = "local-delegate-mcp" }',  # tras `@latest`: sin especificador
        '{ name = "local-delegate-mcp", extras = ["llamaswap"] }',
        '{ name = "local-delegate-mcp", specifier = ">=0.40" }',  # rango: upgrade sí lo mueve
        '{ name = "local-delegate-mcp", specifier = "==0.45.*" }',
        '{ name = "local-delegate-mcp", specifier = "==0.45.0; rm -rf /" }',
        '{ name = "local-delegate-mcp", specifier = "==0.45.0", extras = ["a b"] }',
    ],
)
def test_without_an_exact_pin_the_usual_upgrade_stays(monkeypatch, tmp_path, entry):
    _fake_prefix(monkeypatch, tmp_path, f"[tool]\nrequirements = [{entry}]\n")
    assert update.upgrade_command() == update.UV_TOOL_UPGRADE


@pytest.mark.parametrize(
    "receipt",
    [
        f'[tool\nrequirements = "{update.PACKAGE}==0.45.0"',  # TOML roto que nombra el paquete
        f'[tool]\nrequirements = "{update.PACKAGE}==0.45.0"\n',  # forma desconocida
        f'[tool]\nname = "{update.PACKAGE}"\n',  # sin requirements
    ],
)
def test_an_unreadable_receipt_keeps_the_usual_command(monkeypatch, tmp_path, receipt):
    _fake_prefix(monkeypatch, tmp_path, receipt)
    assert update.install_kind() == update.UV_TOOL
    assert update.upgrade_command() == update.UV_TOOL_UPGRADE


def test_a_missing_receipt_does_not_raise(monkeypatch, tmp_path):
    _fake_prefix(monkeypatch, tmp_path, None)
    assert update.install_origin.uv_tool_pin() is None
    monkeypatch.setattr(update.sys, "prefix", "\x00 ruta imposible \x00")
    assert update.install_origin.uv_tool_pin() is None


def test_the_pin_keeps_version_and_extras(monkeypatch, tmp_path):
    _fake_prefix(monkeypatch, tmp_path, _PINNED_WITH_EXTRAS)
    pin = update.install_origin.uv_tool_pin()
    assert pin == update.install_origin.UvToolPin("0.45.0", ("llamaswap",))


def test_the_uv_tool_warning_of_a_pinned_install_says_why_and_how(monkeypatch, tmp_path):
    _fake_prefix(monkeypatch, tmp_path, _PINNED_WITH_EXTRAS)
    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.45.0")
    lines = update.uv_tool_lines("0.46.0")
    text = "\n".join(lines)
    assert update.UV_TOOL_UPGRADE not in text, "ese consejo no mueve una instalación fijada"
    assert lines[-1].strip() == 'uv tool install "local-delegate-mcp[llamaswap]@latest"'
    assert update.t("install.update.uv_tool.pinned", version="0.45.0") in lines
    text.encode("cp1252")


def test_the_uv_tool_warning_gives_the_version_and_the_command(monkeypatch, tmp_path):
    _fake_prefix(monkeypatch, tmp_path, f'[tool]\nname = "{update.PACKAGE}"')
    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    text = "\n".join(update.uv_tool_lines("0.18.0"))
    assert "0.17.0" in text
    assert update.UV_TOOL_UPGRADE in text
    assert "reinstalaría el entorno" in text, "tiene que decir POR QUÉ no lo hace él"


@pytest.mark.parametrize("published", ["0.17.0", "0.16.0", None])
def test_with_nothing_to_warn_the_block_does_not_appear(monkeypatch, tmp_path, published):
    """Al día, por delante, o sin red: un aviso que sale siempre deja de leerse."""
    _fake_prefix(monkeypatch, tmp_path, f'[tool]\nname = "{update.PACKAGE}"')
    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    assert update.uv_tool_lines(published) == []


def test_an_editable_does_not_get_the_uv_tool_warning(monkeypatch, tmp_path):
    """Ya tiene el suyo, con `git pull` + `uv sync`. Dos avisos serían uno de más."""
    monkeypatch.setattr(update, "editable_origin", lambda: tmp_path)
    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    assert update.uv_tool_lines("0.18.0") == []


def test_the_uv_tool_warning_fits_in_the_windows_console(monkeypatch, tmp_path):
    _fake_prefix(monkeypatch, tmp_path, f'[tool]\nname = "{update.PACKAGE}"')
    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    "\n".join(update.uv_tool_lines("0.18.0")).encode("cp1252")
    update.generic_upgrade().encode("cp1252")


def test_the_uv_tool_warning_changes_neither_the_plan_nor_the_exit_code(tmp_path, monkeypatch):
    monkeypatch.setattr(update, "latest_version", lambda timeout=0: ("0.18.0", None))
    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    home = make_home(tmp_path, complete=False)

    _fake_prefix(monkeypatch, tmp_path / "pref", f'[tool]\nname = "{update.PACKAGE}"')
    out_with: list[str] = []
    code_with = update.run_update(opts_for(home, dry_run=True), out=out_with.append)
    extra = update.uv_tool_lines("0.18.0")

    monkeypatch.setattr(update, "install_kind", lambda: update.OTHER)
    out_without: list[str] = []
    code_without = update.run_update(opts_for(home, dry_run=True), out=out_without.append)

    assert code_with == code_without
    assert extra, "el caso de uv tool debería aportar líneas"

    # Se ignoran las vacías: son maquetación, y el aviso añade una de separación. Lo que se
    # compara es el contenido — si el plan de acciones cambiara, aquí se vería.
    def without_warning(output):
        return [x for x in output if x.strip() and x not in extra]

    assert without_warning(out_with) == without_warning(out_without)


# --- De dónde salió la versión, y el desfase tras publicar --------------------
# Justo después de publicar, `update` anuncia como «última» la anterior. Desde el comando no se
# puede distinguir «PyPI sirve caché» de «la publicación no ha terminado» —eso pediría medir
# durante una publicación real—, pero sí se puede detectar la firma del caso y decirla.


def test_the_version_requested_by_hand_is_not_shown_as_the_latest_published():
    """`--version 0.17.0` no comprueba nada de PyPI; decir que es «la última» era mentira."""
    lines = update.version_lines("0.17.0", None, from_user=True)
    assert lines == ["Versión pedida con --version: 0.17.0"]
    assert not any("publicada" in line for line in lines)


def test_the_queried_version_says_where_it_came_from(monkeypatch):
    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    (line,) = update.version_lines("0.17.0", None, from_user=False)
    assert "0.17.0" in line
    assert update.pypi_source() in line


def test_installed_newer_than_published_warns_and_reminds_the_flag(monkeypatch):
    """La firma exacta de una release recién publicada que PyPI todavía no anuncia."""
    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    text = "\n".join(update.version_lines("0.16.0", None, from_user=False))
    assert "0.16.0" in text and "0.17.0" in text
    # La versión ya sustituida, no un placeholder: quien lee esto acaba de publicar y algo no le
    # cuadra; traducir `X.Y.Z` mentalmente es justo lo que no debe tener que hacer.
    assert "--version 0.17.0" in text


def test_without_drift_there_is_no_warning(monkeypatch):
    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    assert len(update.version_lines("0.17.0", None, from_user=False)) == 1
    assert len(update.version_lines("0.18.0", None, from_user=False)) == 1


@pytest.mark.parametrize("installed", [None, "no-numbers"])
def test_with_nothing_to_compare_it_stays_quiet(monkeypatch, installed):
    """`unknown` no inventa: sin versión instalada utilizable, no hay aviso que dar."""
    monkeypatch.setattr(update.checks, "_installed_version", lambda: installed)
    assert len(update.version_lines("0.16.0", None, from_user=False)) == 1


def test_without_network_the_usual_warning_is_kept():
    (line,) = update.version_lines(None, "no se pudo consultar PyPI (URLError)", from_user=False)
    assert "no se pudo consultar PyPI" in line
    assert "sin tocar los pines" in line


def test_the_lines_fit_in_the_windows_console(monkeypatch):
    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    for args in [("0.16.0", None, True), ("0.16.0", None, False), (None, "motivo", False)]:
        version, reason, from_user = args
        "\n".join(update.version_lines(version, reason, from_user=from_user)).encode("cp1252")


def test_the_drift_warning_changes_neither_the_plan_nor_the_exit_code(tmp_path, monkeypatch):
    """Es información, no un cambio de comportamiento: `update` hace exactamente lo mismo."""
    monkeypatch.setattr(update, "latest_version", lambda timeout=0: ("0.16.0", None))
    home = make_home(tmp_path, complete=False)

    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    output_with: list[str] = []
    code_with = update.run_update(opts_for(home, dry_run=True), out=output_with.append)
    # Las líneas que aporta el aviso, tomadas **con la instalada todavía en 0.17.0**.
    extra = update.version_lines("0.16.0", None, from_user=False)[1:]

    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.16.0")
    output_without: list[str] = []
    code_without = update.run_update(opts_for(home, dry_run=True), out=output_without.append)

    assert code_with == code_without
    assert any("MÁS NUEVA" in line for line in output_with), "no salió el aviso"
    assert not any("MÁS NUEVA" in line for line in output_without)

    # Y lo único que cambia es ese bloque: quitadas sus líneas exactas —las que `version_lines`
    # añade de más, no las que casen con un substring— las dos salidas son idénticas.
    assert extra, "el caso de desfase debería aportar líneas"
    assert [line for line in output_with if line not in extra] == output_without


def test_pypi_is_queried_only_once_in_the_whole_command(tmp_path, monkeypatch):
    """`update` ya pregunta por la última versión; el check del registro no debe repetirlo.

    Se cuentan las consultas en vez de prohibirlas: la de `run_update` es legítima y necesaria,
    y lo que se vigila es que no aparezca una **segunda** por correr el diagnóstico.
    """
    queries: list[float] = []

    def _spy(timeout=0.0):
        queries.append(timeout)
        return "9.9.9", None

    monkeypatch.setattr(update, "latest_version", _spy)
    opts = opts_for(make_home(tmp_path, complete=False), dry_run=True)

    update.run_update(opts, out=lambda *a: None)

    assert len(queries) == 1, f"PyPI se consultó {len(queries)} veces en un solo comando"


# --- Los mecanismos de arranque ----------------------------------------------


@pytest.mark.parametrize(
    ("platform", "expected", "command"),
    [
        ("win32", update.SCHTASKS, "schtasks"),
        ("darwin", update.LAUNCHCTL, "launchctl"),
        ("linux", update.SYSTEMD, "systemctl"),
    ],
)
def test_detects_the_registered_mechanism_of_each_system(
    tmp_path, monkeypatch, platform, expected, command
):
    monkeypatch.setattr(update.sys, "platform", platform)
    runner = fake_run(returncode=0)
    assert update.detect_mechanism(opts_for(tmp_path, runner=runner)) == expected
    assert runner.calls[0][0] == command


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_without_a_registered_service_it_falls_back(tmp_path, monkeypatch, platform):
    """Estar en Windows no implica que la tarea exista: se pregunta de verdad."""
    monkeypatch.setattr(update.sys, "platform", platform)
    runner = fake_run(returncode=1)
    assert update.detect_mechanism(opts_for(tmp_path, runner=runner)) == update.FALLBACK


def test_the_failing_mechanism_falls_back_and_relaunches(tmp_path, monkeypatch):
    monkeypatch.setattr(update.sys, "platform", "linux")
    launched: list[list[str]] = []
    # `systemctl cat` responde (existe la unidad) pero `restart` falla.
    responses = iter([0, 1])

    def runner(argv):
        return subprocess.CompletedProcess(argv, next(responses), "", "unit failed")

    opts = opts_for(
        tmp_path,
        runner=runner,
        spawn=launched.append,
        daemon_status=lambda host, port: {"pid": 999, "version": "0.16.0"},
    )
    update.restart_daemon(opts, out=lambda *a: None)
    assert launched, "tras fallar el mecanismo registrado hay que relanzar por el fallback"


def test_the_pid_that_survives_the_service_stop_gets_the_signal(tmp_path, monkeypatch):
    """Parar el SERVICIO no siempre para el PROCESO, y se descubrió ejecutándolo en Windows.

    La tarea programada lanza `conhost -> powershell -> launcher`, y el launcher crea el daemon
    con `Start-Process`, o sea desacoplado. `schtasks /End` termina la cadena de la tarea y el
    nieto sobrevive con el puerto tomado: el `/Run` siguiente arranca una instancia que no puede
    escuchar y el reinicio se da por fallido con el daemon viejo todavía sirviendo.
    """
    monkeypatch.setattr(update.sys, "platform", "win32")
    killed: list[int] = []
    monkeypatch.setattr(update.os, "kill", lambda pid, sig: killed.append(pid))
    opts = opts_for(
        tmp_path,
        runner=fake_run(returncode=0),
        # Siempre el mismo pid: el `/End` no lo mató.
        daemon_status=lambda host, port: {"pid": 41176, "version": "0.16.0"},
        spawn=lambda argv: None,
    )
    update.restart_daemon(opts, out=lambda *a: None)
    assert 41176 in killed


def test_the_mechanism_that_does_stop_the_process_gets_no_extra_signal(tmp_path, monkeypatch):
    """`systemctl restart` para y arranca en un solo comando: ahí no hay nada que rematar."""
    monkeypatch.setattr(update.sys, "platform", "linux")
    killed: list[int] = []
    monkeypatch.setattr(update.os, "kill", lambda pid, sig: killed.append(pid))
    pids = iter([{"pid": 7, "version": "v"}, {"pid": 8, "version": "v"}])
    last = {}

    def daemon_status(host, port):
        last["v"] = next(pids, last.get("v"))
        return last["v"]

    opts = opts_for(tmp_path, runner=fake_run(0), daemon_status=daemon_status, spawn=lambda a: None)
    assert update.restart_daemon(opts, out=lambda *a: None) == 0
    assert killed == []


# --- REQ-008: el pid solo sale de /api/daemon --------------------------------


def test_without_a_live_daemon_no_signal_is_sent(tmp_path, monkeypatch):
    """El caso del pid reciclado: `daemon.json` puede tener un pid ajeno, y nunca se lee.

    Si `/api/daemon` no responde, no hay pid que señalar: se trata como caído y se levanta.
    """
    killed: list[int] = []
    monkeypatch.setattr(update.os, "kill", lambda pid, sig: killed.append(pid))
    monkeypatch.setattr(update.sys, "platform", "linux")
    opts = opts_for(
        tmp_path,
        runner=fake_run(returncode=1),  # sin servicio registrado -> fallback
        daemon_status=lambda host, port: None,
        spawn=lambda argv: None,
    )
    update.restart_daemon(opts, out=lambda *a: None)
    assert killed == []


def test_the_daemon_that_does_not_come_back_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(update.sys, "platform", "linux")
    opts = opts_for(
        tmp_path,
        runner=fake_run(returncode=0),
        daemon_status=lambda host, port: None,
        spawn=lambda argv: None,
    )
    assert update.restart_daemon(opts, out=lambda *a: None) == 1


def test_the_pid_must_change_after_restarting(tmp_path, monkeypatch):
    """REQ-005: si vuelve el MISMO pid, el servicio no reinició y no vale darlo por bueno."""
    monkeypatch.setattr(update.sys, "platform", "linux")
    opts = opts_for(
        tmp_path,
        runner=fake_run(returncode=0),
        daemon_status=lambda host, port: {"pid": 7, "version": "0.16.0"},
        spawn=lambda argv: None,
    )
    assert update.restart_daemon(opts, out=lambda *a: None) == 1


def test_the_correct_restart_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(update.sys, "platform", "linux")
    pids = iter([{"pid": 7, "version": "0.16.0"}, {"pid": 8, "version": "0.16.0"}])
    last = {}

    def daemon_status(host, port):
        last["v"] = next(pids, last.get("v"))
        return last["v"]

    opts = opts_for(
        tmp_path, runner=fake_run(returncode=0), daemon_status=daemon_status, spawn=lambda a: None
    )
    assert update.restart_daemon(opts, out=lambda *a: None) == 0


# --- El pin: paridad con el bash ---------------------------------------------


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_the_pin_keeps_the_line_terminator(tmp_path, newline):
    """Escribir con el terminador de la plataforma marcaría el fichero entero como modificado."""
    path = tmp_path / ".claude.json"
    raw = '{{"mcpServers": {{"local-delegate": {{"args": ["--from", "local-delegate-mcp==0.13.0"]}}}}}}'
    path.write_bytes(raw.format().replace("\n", newline).encode("utf-8"))
    original = path.read_bytes()

    actions = update.plan_pin(update.Options(home=tmp_path), "0.16.0")
    assert len(actions) == 1
    install.apply(actions, dry_run=False, out=lambda *a: None)

    written = path.read_bytes()
    assert b"local-delegate-mcp==0.16.0" in written
    assert (b"\r\n" in written) == (b"\r\n" in original)
    assert (tmp_path / ".claude.json.bak").is_file()


def test_without_a_pin_there_is_nothing_to_change(tmp_path):
    """Sin `==X.Y.Z`, uvx ya resuelve la última en cada arranque."""
    (tmp_path / ".claude.json").write_text(
        '{"mcpServers": {"local-delegate": {"args": ["--from", "local-delegate-mcp"]}}}',
        encoding="utf-8",
    )
    assert update.plan_pin(update.Options(home=tmp_path), "0.16.0") == []


def test_an_up_to_date_pin_is_not_touched(tmp_path):
    (tmp_path / ".claude.json").write_text("local-delegate-mcp==0.16.0", encoding="utf-8")
    assert update.plan_pin(update.Options(home=tmp_path), "0.16.0") == []


def test_without_the_package_entry_nothing_is_touched(tmp_path):
    (tmp_path / ".claude.json").write_text('{"mcpServers": {}}', encoding="utf-8")
    assert update.plan_pin(update.Options(home=tmp_path), "0.16.0") == []


def test_without_network_it_warns_and_continues_successfully(tmp_path, monkeypatch):
    """Edge case de la spec: PyPI caído no impide completar el andamiaje ni reiniciar."""
    monkeypatch.setattr(update, "latest_version", lambda *a, **k: (None, "sin red"))
    output: list[str] = []
    opts = opts_for(make_home(tmp_path, complete=True), no_restart=True)
    assert update.run_update(opts, out=output.append) == 0
    assert any("sin red" in line for line in output)


# --- El backend no se toca salvo que se pida ---------------------------------


def test_without_the_flag_there_is_not_a_single_backend_call(tmp_path, monkeypatch):
    """REQ-012: reiniciar el daemon no puede descargar los modelos de la VRAM."""
    called = []
    monkeypatch.setattr(update, "restart_backend", lambda *a, **k: called.append(1) or 0)
    opts = opts_for(make_home(tmp_path, complete=True), no_restart=True)
    update.run_update(opts, out=lambda *a: None)
    assert called == []


def test_with_remote_backend_nothing_is_attempted(tmp_path, monkeypatch):
    """El caso de la Mac apuntando a la PC: no hay backend local que reiniciar, y no es error."""
    monkeypatch.setattr(update.config, "backend_origin", lambda *a: "remote")
    runner = fake_run()
    output: list[str] = []
    assert update.restart_backend(opts_for(tmp_path, runner=runner), out=output.append) == 0
    assert runner.calls == []
    assert any("remoto" in line for line in output)


def test_a_port_taken_by_another_process_gets_no_signal(tmp_path, monkeypatch):
    """Dos confirmaciones antes de señalar: el host dice «local», pero el proceso manda."""
    monkeypatch.setattr(update.config, "backend_origin", lambda *a: "local")
    monkeypatch.setattr(update, "_port_owner", lambda opts, port: 1234)
    monkeypatch.setattr(update, "_process_name", lambda opts, pid: "nginx.exe")
    killed: list[int] = []
    monkeypatch.setattr(update.os, "kill", lambda pid, sig: killed.append(pid))
    assert update.restart_backend(opts_for(tmp_path), out=lambda *a: None) == 1
    assert killed == []


# --- Instalación editable (PEP 610) ------------------------------------------


class _FakeDistribution:
    def __init__(self, payload):
        self.payload = payload

    def read_text(self, name):
        return self.payload


@pytest.mark.parametrize(
    ("payload", "expects_path"),
    [
        ('{"url": "file:///repo", "dir_info": {"editable": true}}', True),
        ('{"url": "file:///repo", "dir_info": {"editable": false}}', False),
        ('{"url": "https://pypi.org/x.whl"}', False),
        (None, False),
        ("no es json", False),
    ],
)
def test_editable_install_detection(monkeypatch, payload, expects_path):
    monkeypatch.setattr(
        update.metadata.Distribution,
        "from_name",
        staticmethod(lambda name: _FakeDistribution(payload)),
    )
    assert (update.editable_origin() is not None) is expects_path


def test_without_metadata_editable_is_not_assumed(monkeypatch):
    def boom(name):
        raise update.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(update.metadata.Distribution, "from_name", staticmethod(boom))
    assert update.editable_origin() is None


# --- El HOME simulado no toca servicios --------------------------------------


def test_simulated_home_does_not_restart_the_real_daemon(tmp_path):
    """B-3: el daemon no se deriva de `ctx.home`, así que sin esta regla `--home /tmp` reiniciaría
    el servicio de verdad de la máquina."""
    runner = fake_run()
    opts = opts_for(make_home(tmp_path, complete=True), runner=runner)
    assert opts.simulated_home is True
    update.run_update(opts, out=lambda *a: None)
    assert runner.calls == []


def test_simulated_home_does_not_register_the_mcp_through_the_client_cli(tmp_path):
    """`claude mcp add-json --scope user` escribe en el `~/.claude.json` REAL, ignorando `home`.

    Se descubrió ejecutando `update --home <tmp>` dos veces: la segunda volvía a planificar la
    misma acción —el probe seguía viendo vacío el árbol simulado— mientras la configuración de
    verdad sí se había reescrito. Con HOME simulado hay que escribir el fichero a mano.
    """
    home = make_home(tmp_path, complete=False)
    results = results_from(**{"scaffold.mcp_claude": checks.MISSING})
    actions, _notes = update.plan_repairs(results, opts_for(home))
    mcp = [a for a in actions if a.kind == "mcp"]
    assert len(mcp) == 1
    install.apply(mcp, dry_run=False, out=lambda *a: None)
    # La prueba de que no salió del árbol: la entrada quedó en el .claude.json simulado.
    assert (home / ".claude.json").is_file()
    assert install.SERVER_NAME in (home / ".claude.json").read_text(encoding="utf-8")


# --- Los nombres canónicos viven en un solo sitio ----------------------------


def test_the_service_names_match_the_wiki():
    """Si el módulo y la receta se separan, `update` busca un servicio que nadie registró."""
    from pathlib import Path as _Path

    wiki = _Path(__file__).resolve().parents[1] / "docs" / "wiki" / "Daemon.md"
    text = wiki.read_text(encoding="utf-8")
    for name in (update.TASK_NAME, update.LAUNCH_LABEL, update.SYSTEMD_UNIT):
        assert name in text, f"{name} no aparece en docs/wiki/Daemon.md"


# --- Hooks de otra versión: el caso de la Mac ---------------------------------


def test_hooks_from_another_version_are_restored_without_turning_off_the_read_hook(tmp_path):
    """Paquete nuevo, hooks viejos y el de lectura encendido: `update` los repone y lo respeta.

    Tres cosas, y cada una falló o habría fallado: el check daba `ok` con hooks de otra versión,
    la reparación solo actuaba si faltaba el directorio entero, y al reponer los hooks se
    reescribía su registro sin el de lectura —con el arreglo de los dos primeros, eso habría
    apagado el bloqueo en cada actualización—.
    """
    home = make_home(tmp_path, complete=False)
    install.apply(
        install.plan_install(
            install.Options(
                home=home,
                components={"hooks"},
                targets={"claude"},
                python_exe="python",
                enable_read_hook=True,
            )
        ),
        dry_run=False,
        out=lambda *a: None,
    )
    hooks_dir = home / ".claude" / "hooks" / install.HOOKS_SUBDIR
    old = hooks_dir / install._READ_HOOK[0]
    old.write_text("# versión anterior\n", encoding="utf-8")
    assert install.read_hook_registered(home / ".claude")

    actions, _notes = update.plan_repairs(checks.run_all(_ctx(home)), opts_for(home))
    assert any(a.kind == "copy" and a.target == hooks_dir for a in actions), actions
    install.apply(actions, dry_run=False, out=lambda *a: None)

    packaged = install.resources_dir() / "hooks" / install._READ_HOOK[0]
    assert old.read_bytes() == packaged.read_bytes()
    assert install.read_hook_registered(home / ".claude"), "update apagó el hook de lectura"
    second, _notes = update.plan_repairs(checks.run_all(_ctx(home)), opts_for(home))
    assert [a for a in second if "hooks" in str(a.target)] == []


def test_without_a_registered_read_hook_update_does_not_turn_it_on(tmp_path):
    """El otro lado: respetar la elección es también no activarlo si no estaba."""
    home = make_home(tmp_path)
    assert not install.read_hook_registered(home / ".claude")
    hooks_dir = home / ".claude" / "hooks" / install.HOOKS_SUBDIR
    (hooks_dir / install._HOOK_EVENTS[0][0]).write_text("# versión anterior\n", encoding="utf-8")

    actions, _notes = update.plan_repairs(checks.run_all(_ctx(home)), opts_for(home))
    assert actions
    install.apply(actions, dry_run=False, out=lambda *a: None)
    assert not install.read_hook_registered(home / ".claude")


# --- D12: `update` sobre una 0.34.0 deja todo nombrando la skill nueva --------------------------


def _agent_with_catalog(home, rule_skill: str) -> tuple:
    """Un subagente con nuestro bloque de catálogo (con la regla de la versión que se pida) y otro
    que delega pero sin marcadores. Devuelve las dos rutas."""
    agents_dir = home / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    skill_md = install.resources_dir() / "skills" / install.SKILL_NAME / "SKILL.md"
    block = agents.catalog_block(agents.tool_catalog(skill_md))
    block = block.replace(install.SKILL_NAME, rule_skill)
    tools = f"tools: Read, {agents.ANCHOR}\n"
    marked = agents_dir / "with-catalog.md"
    marked.write_text(
        f"---\nname: with-catalog\n{tools}---\n\n## Delegación a modelos locales\n\n{block}\n## Otra\n",
        encoding="utf-8",
    )
    unmarked = agents_dir / "without-markers.md"
    unmarked.write_text(
        f"---\nname: without-markers\n{tools}---\n\n## Delegación a modelos locales\n\nTexto mío.\n",
        encoding="utf-8",
    )
    return marked, unmarked


def _live_files(home) -> list:
    """Los ficheros vivos de D12: memoria, subagentes y skills instaladas (sin los `.bak`)."""
    skill_roots = [
        home / ".claude" / "skills",
        install.opencode_dir(home) / install.OPENCODE_SKILL_SUBDIR,
    ]
    files = [p for p in live_memory_files(home) if p.is_file()]
    files += sorted((home / ".claude" / "agents").glob("*.md"))
    for root in skill_roots:
        files += [p for p in root.rglob("*") if p.is_file()]
    return files


def _update_once(home) -> list:
    actions, _notes = update.plan_repairs(checks.run_all(_ctx(home)), opts_for(home))
    install.apply(actions, dry_run=False, out=lambda *a: None)
    return actions


def test_update_over_0_34_leaves_no_trace_of_the_retired_skill(tmp_path):
    home = make_home(tmp_path, complete=True)
    downgrade_to_0_34(home)
    marked, unmarked = _agent_with_catalog(home, OLD_SKILL_NAME)
    unmarked_before = unmarked.read_bytes()
    assert OLD_SKILL_NAME in (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")

    _update_once(home)

    claude_md = (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "delegacion-local" not in claude_md
    assert "delegacion-local" not in marked.read_text(encoding="utf-8")
    for path in _live_files(home):
        assert OLD_SKILL_NAME not in path.read_text(encoding="utf-8"), path
    assert install.SKILL_NAME in marked.read_text(encoding="utf-8")
    assert unmarked.read_bytes() == unmarked_before, "un subagente sin marcadores no se toca"
    assert (home / ".claude" / "skills" / install.SKILL_NAME / "SKILL.md").is_file()
    assert not (home / ".claude" / "skills" / OLD_SKILL_NAME).exists()


def test_a_crlf_memory_file_that_is_up_to_date_is_not_rewritten(tmp_path):
    """Un `CLAUDE.md` en CRLF con el bloque al día da `ok` y `update` no lo toca."""
    home = make_home(tmp_path, complete=True)
    claude_md = home / ".claude" / "CLAUDE.md"
    claude_md.write_bytes(claude_md.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    before, mtime = claude_md.read_bytes(), claude_md.stat().st_mtime_ns

    by_id = {c.id: r for c, r in checks.run_all(_ctx(home))}
    assert by_id["scaffold.memory"].status == checks.OK, by_id["scaffold.memory"].detail
    _update_once(home)

    assert claude_md.read_bytes() == before
    assert claude_md.stat().st_mtime_ns == mtime
    assert not claude_md.with_suffix(".md.bak").exists()


def test_second_update_pass_changes_nothing(tmp_path):
    """Tras reparar una 0.34.0, otra pasada no informa reparaciones ni deja `.bak` nuevos."""
    home = make_home(tmp_path, complete=True)
    downgrade_to_0_34(home)
    _agent_with_catalog(home, OLD_SKILL_NAME)
    assert _update_once(home), "la primera pasada debía reparar algo"
    before = snapshot(home)

    second = _update_once(home)

    assert second == []
    assert snapshot(home) == before


# --- Migración de nombres retirados: migrar → checks → notas (REQ-014, REQ-016, REQ-017) ---------
# Registro sintético: con nombres de mentira, la prueba no depende del registro real.
_GONE_ENV = ("LD_OLD_GONE_VAR", "LD_GONE_VAR_NEW")
_GONE_SWITCH = ("old-gone-switch", "gone-switch-new")


def _retired_registry(monkeypatch, *, in_shell: str | None = None):
    from local_delegate import config, deprecations

    def retired(names, surface):
        return deprecations.DeprecatedName(
            "retired", *names, "0.38.0", "0.40.0", retired_from=surface
        )

    monkeypatch.setattr(
        deprecations,
        "DEPRECATED_NAMES",
        (retired(_GONE_ENV, "env_var"), retired(_GONE_SWITCH, "switch_file")),
    )
    monkeypatch.setattr(config, "DEPRECATED_ENV_VALUES", {_GONE_ENV[0]: in_shell})
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", None)
    # Sin red: la versión publicada no hace falta para migrar.
    monkeypatch.setattr(update, "latest_version", lambda: (None, "sin red en la suite"))


def _home_with_env(tmp_path, env: dict, *, complete=True):
    import json

    home = make_home(tmp_path, complete=complete)
    path = home / ".claude" / "settings.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data["env"] = env
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return home


def _run(home, **kwargs) -> tuple[int, str]:
    lines: list[str] = []
    code = update.run_update(opts_for(home, **kwargs), out=lambda *a: lines.append(" ".join(a)))
    return code, "\n".join(lines)


def _rename_hint() -> str:
    return install.t("doctor.probe.deprecated_names.rename", old=_GONE_ENV[0], new=_GONE_ENV[1])


def _env(home) -> dict:
    import json

    return json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))["env"]


@pytest.mark.parametrize("dry_run", [False, True])
def test_update_migrates_before_reporting(monkeypatch, tmp_path, dry_run):
    """Las notas no piden «renombra» lo que la migración cubre (aplicada o planificada)."""
    _retired_registry(monkeypatch)
    home = _home_with_env(tmp_path, {_GONE_ENV[0]: "1"})
    code, text = _run(home, dry_run=dry_run)
    assert code == 0, text
    assert f"{_GONE_ENV[0]} -> {_GONE_ENV[1]}" in text
    assert install.t("install.update.migration") in text
    assert _rename_hint() not in text
    expected = {_GONE_ENV[0]: "1"} if dry_run else {_GONE_ENV[1]: "1"}
    assert _env(home) == expected


def test_update_keeps_the_hint_of_a_name_also_in_the_shell(monkeypatch, tmp_path):
    """La shell no se migra: su pista sigue en las notas (control del filtro de arriba)."""
    _retired_registry(monkeypatch, in_shell="1")
    home = _home_with_env(tmp_path, {_GONE_ENV[0]: "1"})
    code, text = _run(home)
    assert code == 0, text
    assert _env(home) == {_GONE_ENV[1]: "1"}
    assert _rename_hint() in text


def test_update_reports_the_rename_when_nothing_is_migrated(monkeypatch, tmp_path):
    """Control del orden: sin migración que lo cubra, el check sí pide «renombra»."""
    _retired_registry(monkeypatch)
    home = _home_with_env(tmp_path, {"OTHER": "x"})
    (home / ".claude" / _GONE_SWITCH[0]).mkdir()  # un directorio no se migra
    _code, text = _run(home)
    hint = install.t(
        "doctor.probe.deprecated_names.rename", old=_GONE_SWITCH[0], new=_GONE_SWITCH[1]
    )
    assert hint in text


def test_update_runs_the_migration_before_the_checks(monkeypatch, tmp_path):
    """El orden fijo: cuando corren los checks, `settings.json` ya está migrado."""
    _retired_registry(monkeypatch)
    home = _home_with_env(tmp_path, {_GONE_ENV[0]: "1"})
    seen: list[dict] = []
    real_run_all = checks.run_all

    def spy(ctx):
        seen.append(_env(home))
        return real_run_all(ctx)

    monkeypatch.setattr(checks, "run_all", spy)
    code, text = _run(home)
    assert code == 0, text
    assert seen == [{_GONE_ENV[1]: "1"}]


def test_update_exits_one_when_the_migration_fails(monkeypatch, tmp_path):
    _retired_registry(monkeypatch)
    home = _home_with_env(tmp_path, {_GONE_ENV[0]: "1"})

    def refuse(*args, **kwargs):
        raise PermissionError(13, "denied")

    monkeypatch.setattr(install, "_write_migrated_settings", refuse)
    code, text = _run(home)
    assert code == 1, text
    assert _env(home) == {_GONE_ENV[0]: "1"}


def test_migration_and_hook_repair_both_survive(monkeypatch, tmp_path):
    """`env` viejo y hooks de otra versión a la vez: ninguna de las dos escrituras se pierde."""
    _retired_registry(monkeypatch)
    home = make_home(tmp_path, complete=False)
    install.apply(
        install.plan_install(
            install.Options(
                home=home, components={"hooks"}, targets={"claude"}, python_exe="python"
            )
        ),
        dry_run=False,
        out=lambda *a: None,
    )
    hooks_dir = home / ".claude" / "hooks" / install.HOOKS_SUBDIR
    stale = hooks_dir / install._HOOK_EVENTS[0][0]
    stale.write_text("# versión anterior\n", encoding="utf-8")
    import json

    path = home / ".claude" / "settings.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["env"] = {_GONE_ENV[0]: "1"}
    # Hooks registrados con otra ruta de Python: el registro está desactualizado.
    data["hooks"] = {}
    path.write_text(json.dumps(data), encoding="utf-8")

    code, text = _run(home)
    assert code == 0, text
    assert _env(home) == {_GONE_ENV[1]: "1"}
    packaged = install.resources_dir() / "hooks" / stale.name
    assert stale.read_bytes() == packaged.read_bytes()
    after = json.loads(path.read_text(encoding="utf-8"))
    commands = json.dumps(after.get("hooks"))
    assert stale.name in commands, "la reparación de hooks no quedó en settings.json"


def test_retired_name_migration_dry_run_writes_nothing(monkeypatch, tmp_path):
    """`--dry-run`: ni settings.json, ni el interruptor, ni registro, ni copia; sí la acción."""
    _retired_registry(monkeypatch)
    home = _home_with_env(tmp_path, {_GONE_ENV[0]: "s3cr3t-value", "OTHER": "x"})
    (home / ".claude" / _GONE_SWITCH[0]).write_text("", encoding="utf-8")
    before = snapshot(tmp_path)
    code, text = _run(home, dry_run=True)
    assert code == 0, text
    assert snapshot(tmp_path) == before
    assert "[dry-run] [migrate]" in text
    assert "s3cr3t-value" not in text
    assert not list(tmp_path.rglob(install.RETIRED_NAMES_MIGRATION_FILE))
    assert not list(tmp_path.rglob("settings.json.retired-names*.bak"))


def test_retired_name_migration_is_idempotent_in_update(monkeypatch, tmp_path):
    _retired_registry(monkeypatch)
    home = _home_with_env(tmp_path, {_GONE_ENV[0]: "s3cr3t-value", "OTHER": "x"})
    (home / ".claude" / _GONE_SWITCH[0]).write_text("", encoding="utf-8")
    code, first = _run(home)
    assert code == 0, first
    assert install.t("install.update.migration") in first
    assert _env(home) == {_GONE_ENV[1]: "s3cr3t-value", "OTHER": "x"}
    assert (home / ".claude" / _GONE_SWITCH[1]).is_file()
    assert "s3cr3t-value" not in first
    code, second = _run(home)
    assert code == 0, second
    assert install.t("install.update.migration") not in second
    assert "[migrate]" not in second


def test_unreadable_settings_is_left_alone(monkeypatch, tmp_path):
    """Aislando la migración (sin reparación de hooks): bytes idénticos y el motivo en la salida."""
    _retired_registry(monkeypatch)
    home = make_home(tmp_path, complete=True)
    path = home / ".claude" / "settings.json"
    path.write_bytes(b'{"env": {"' + _GONE_ENV[0].encode() + b'": "1"')
    before = path.read_bytes()
    monkeypatch.setattr(update, "plan_repairs", lambda results, opts, **kw: ([], []))
    code, text = _run(home)
    assert code == 0, text
    assert path.read_bytes() == before
    assert install.t("install.migrate.reason.not_json") in text


def test_the_migration_line_in_english(monkeypatch, tmp_path):
    """REQ-018: con la CLI en inglés, la línea de la migración sale en inglés."""
    from local_delegate import i18n

    _retired_registry(monkeypatch)
    home = _home_with_env(tmp_path, {_GONE_ENV[0]: "1"})
    with i18n.override("en"):
        code, text = _run(home, dry_run=True)
        english = i18n.t("install.migrate.settings_plan", names=f"{_GONE_ENV[0]} -> {_GONE_ENV[1]}")
    assert code == 0, text
    assert english in text
    assert english != i18n.t_lang(
        "es", "install.migrate.settings_plan", names=f"{_GONE_ENV[0]} -> {_GONE_ENV[1]}"
    )


def test_the_repairs_do_not_plan_the_migration_twice(monkeypatch, tmp_path):
    """Con reparaciones de Claude en el plan, `--dry-run` muestra la migración una sola vez."""
    _retired_registry(monkeypatch)
    home = _home_with_env(tmp_path, {_GONE_ENV[0]: "1"}, complete=False)
    code, text = _run(home, dry_run=True)
    assert code == 0, text
    assert "[dry-run] [settings]" in text, "la prueba necesita una reparación de settings.json"
    assert text.count("[dry-run] [migrate]") == 1, text


# --- Issue #443: el bloque con las reglas de subagentes llega a quien ya tenía el de la 0.41.1 ----


def _without_subagent_rules(block: str) -> str:
    """El bloque de la 0.41.1: el empaquetado sin el párrafo de subagentes (es o en)."""
    for heading, tail in (
        ("**Subagentes:**", "Detalle completo"),
        ("**Subagents:**", "Full details"),
    ):
        if heading in block:
            start, end = block.index(heading), block.index(tail)
            return block[:start] + block[end:]
    raise AssertionError("el bloque empaquetado no trae el párrafo de subagentes")


def test_update_rewrites_an_old_block_with_the_subagent_rules(tmp_path):
    home = make_home(tmp_path, complete=True)
    files = [p for p in live_memory_files(home) if p.is_file()]
    assert len(files) >= 2, "la prueba necesita CLAUDE.md y un AGENTS.md"
    for path in files:
        text = path.read_text(encoding="utf-8")
        inner = install.managed_block(text, install.MD_BEGIN, install.MD_END)
        assert inner is not None, path
        path.write_text(text.replace(inner, _without_subagent_rules(inner)), encoding="utf-8")
        assert install.memory_block_is_current(path.read_text(encoding="utf-8")) is False, path

    by_id = {c.id: r for c, r in checks.run_all(_ctx(home))}
    assert by_id["scaffold.memory"].status == checks.WARN, by_id["scaffold.memory"].detail
    _update_once(home)

    for path in files:
        text = path.read_text(encoding="utf-8")
        assert install.memory_block_is_current(text) is True, path
        assert "mcp__local-delegate__local_extract" in text, path
        assert "offset`/`limit`" in text, path
