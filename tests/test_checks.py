"""Tests del registro de comprobaciones (checks.py).

Ningún test sale a la red ni lanza procesos: los tres colaboradores del `Context` se inyectan
y el HOME es siempre un `tmp_path`. Lo que más se vigila aquí no es que un check diga «ok»,
sino que **nunca diga `missing` cuando en realidad no pudo comprobar**: ese falso `missing`
es el que llevaría a un `fix` posterior a sobrescribir configuración ajena.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx2
import pytest
from conftest import (
    desktop_mcp_remote_entry,
    downgrade_to_0_34,
    make_home,
    snapshot,
    write_claude_desktop,
)

from local_delegate import checks, install, llamaswap_api, probes, recompute
from local_delegate.failures import BackendView


def make_ctx(home, **kwargs):
    """Context con los colaboradores doblados: nada de red ni de procesos.

    El daemon devuelve **la versión instalada** a propósito: si devolviera una fija, el check de
    daemon desincronizado la marcaría `warn` y los tests de «todo ok» dependerían de qué versión
    lleve el repo ese día.
    """
    defaults = {
        "daemon_status": lambda host, port: {
            "version": checks._installed_version(),
            "pid": 42,
            "mcp_url": f"http://{host}:{port}/mcp",
        },
        "backend_models": lambda: BackendView(True, "", None, "direct"),
        "version_of": lambda component, cfg: (probes.RECOMMENDED_VERSIONS[component], None),
        # Igual que el daemon: **la instalada**, no una fija. Con una fija, el check de versión
        # publicada saldría `warn` u `ok` según la versión que lleve el repo ese día.
        "latest_release": lambda: (checks._installed_version(), None),
        # Sin doblarlo, cada `run_all` de la suite leería el `clients.jsonl` REAL de la máquina
        # donde corra: verde en CI (donde no existe) y potencialmente otra cosa en la máquina de
        # quien desarrolla. El default se ejercita aparte, con `config.LOG_DIR` en un tmp_path.
        "clients_seen": checks.NO_CLIENTS,
        # Quinto colaborador de red, doblado por la misma razón que los otros cuatro: sin esto
        # cada `run_all` de la suite pediría `/models` al backend REAL de la máquina. Devuelve
        # «no exige credencial», que es el caso en el que la entrada MCP da igual.
        "backend_needs_key": lambda: (False, ""),
        # Octavo colaborador de red (T13): sin doblarlo, `backend.residency` y `backend.topology`
        # preguntarían al daemon (la fixture autouse lo corta, pero aquí se dice explícito).
        "llamaswap_daemon": checks.NO_LLAMASWAP_DAEMON,
        # Sexto colaborador de red. Lo consultan dos checks: `service.daemon` solo cuando el
        # daemon no responde y el puerto está ocupado, y `service.daemon_auth` siempre.
        #
        # Devuelve «el puerto no exige token», igual que `backend_needs_key` de arriba y por el
        # mismo motivo: es el caso en el que la entrada MCP da igual, así que un HOME completo
        # sale `ok` sin tener que fabricarle además una cabecera a cada cliente. Los tests que
        # necesitan el otro veredicto —o ninguno— lo pasan explícitamente.
        "daemon_needs_token": lambda host, port: False,
        # Séptimo colaborador de red: prueba un token concreto contra el puerto. Solo lo consulta
        # `service.desktop_auth`, y solo si hay fichero de Claude Desktop, que `make_home` no crea.
        "daemon_accepts_token": lambda host, port, token: True,
    }
    defaults.update(kwargs)
    return checks.Context(home=home, **defaults)


def result_for(check_id, ctx):
    return {check.id: result for check, result in checks.run_all(ctx)}[check_id]


# --- Estructura del registro --------------------------------------------------


def test_registry_ids_are_unique_and_groups_are_known():
    assert len({check.id for check in checks.CHECKS}) == len(checks.CHECKS)
    assert {check.group for check in checks.CHECKS} == {
        "environment",
        "scaffold",
        "service",
        "backend",
    }


def test_registry_ids_are_the_published_ones():
    """A6 (REQ-011): los 26 ids exactos, en inglés. Un id es contrato con quien lea `checks`."""
    assert len(checks.CHECKS) == 26
    assert {check.id for check in checks.CHECKS} == {
        "cli.path",
        "cli.published",
        "client.presence",
        "client.observed",
        "config.fallback",
        "config.deprecated_names",
        "config.cost",
        "metrics.test_windows",
        "scaffold.hook_files",
        "scaffold.hook_orphans",
        "scaffold.hook_settings",
        "scaffold.skill",
        "scaffold.memory",
        "scaffold.mcp_claude",
        "scaffold.mcp_codex",
        "scaffold.mcp_opencode",
        "scaffold.shell_completion",
        "service.daemon",
        "service.backend",
        "service.credential",
        "service.daemon_auth",
        "service.desktop_auth",
        "backend.llamaswap",
        "backend.llamaserver",
        "backend.residency",
        "backend.topology",
    }


def test_memory_block_from_0_34_is_outdated_and_the_packaged_one_is_ok(tmp_path):
    """D12: el bloque de la 0.34.0 nombra la skill retirada y da `warn`; el empaquetado, `ok`."""
    home = make_home(tmp_path, claude=True, codex=False, opencode=False)
    assert result_for("scaffold.memory", make_ctx(home)).status == checks.OK
    downgrade_to_0_34(home)
    result = result_for("scaffold.memory", make_ctx(home))
    assert result.status == checks.WARN
    assert "desfasado" in result.detail


def test_filtering_by_group_touches_neither_network_nor_backend(tmp_path):
    """`install` reporta el andamiaje que acaba de escribir, y solo eso.

    Correr también `service` y `backend` saldría a la red y lanzaría los binarios de llama-swap
    por haber instalado unos hooks.

    Los colaboradores **anotan** que se les llamó en vez de lanzar: `run_all` captura las
    excepciones de los probes (un check roto no debe ocultar los otros doce), así que un
    `raise` a secas se tragaría en silencio y el test pasaría con la red ya tocada.

    `latest_release` **no** entra aquí, y el motivo importa: `cli.published` vive en el grupo
    `environment`, así que el filtro no lo excluye ni debe hacerlo. A ese lo frena `SKIP_PYPI`, que
    es otro mecanismo y se prueba en su propio sitio —
    `test_install_clients.py::test_install_no_consulta_pypi_al_reportar_el_andamiaje`.
    """
    called: list[str] = []

    def _records(name):
        def _collaborator(*_a, **_kw):
            called.append(name)
            raise AssertionError(f"{name} no debe correr en el reporte del andamiaje")

        return _collaborator

    home = make_home(tmp_path, complete=False)
    ctx = make_ctx(
        home,
        daemon_status=_records("daemon_status"),
        backend_models=_records("backend_models"),
        version_of=_records("version_of"),
    )

    results = checks.run_all(ctx, groups=("environment", "scaffold"))

    assert called == [], f"el reporte del andamiaje salió a la red: {called}"
    expected = [c.id for c in checks.CHECKS if c.group in ("environment", "scaffold")]
    assert [check.id for check, _r in results] == expected
    assert len(results) < len(checks.CHECKS)


def test_context_collaborators_are_not_class_functions():
    """Un colaborador con default no puede quedar como función en la CLASE `Context`.

    Con `campo: Callable = _default_x`, el dataclass deja `_default_x` como atributo de clase y lo
    copia en cada instancia. Funciona mientras la instancia lo tenga; leído desde la clase, Python
    lo enlaza como método y le mete `self` delante. CodeQL lo marcó en el PR #204
    (`py/call/wrong-arguments`) y la salida no era descartar la alerta sino quitar el patrón.
    """
    from dataclasses import fields

    in_the_class = [
        f.name for f in fields(checks.Context) if callable(checks.Context.__dict__.get(f.name))
    ]
    assert not in_the_class, f"colaboradores guardados como función de clase: {in_the_class}"


def test_without_filter_run_all_behaves_as_always(tmp_path):
    ctx = make_ctx(make_home(tmp_path, complete=False))
    assert len(checks.run_all(ctx)) == len(checks.CHECKS)
    assert checks.run_all(ctx, groups=None) == checks.run_all(ctx)


# --- El CLI tiene que existir como comando -----------------------------------


def test_cli_missing_from_path_is_reported_with_the_command_that_fixes_it(tmp_path, monkeypatch):
    """Instalar con `uvx` deja el andamiaje puesto y el comando inexistente."""
    monkeypatch.setattr(checks.shutil, "which", lambda name: None)
    result = result_for("cli.path", make_ctx(make_home(tmp_path)))
    assert result.status == checks.MISSING
    assert result.fix_hint == checks.cli_hint()
    assert "uvx" in result.detail


def test_cli_in_path_is_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(checks.shutil, "which", lambda name: "/usr/local/bin/local-delegate")
    result = result_for("cli.path", make_ctx(make_home(tmp_path)))
    assert result.status == checks.OK
    assert "/usr/local/bin/local-delegate" in result.detail


# --- ...y estar al día ---------------------------------------------------------
# El caso que motivó este check: el 2026-07-30, con el CLI en 0.16.0 y la 0.17.0 publicada,
# `doctor` decía «todo a punto». Sabía la versión instalada y sabía preguntar por la última,
# pero nadie juntaba las dos cosas.


def _published(tmp_path, monkeypatch, installed, last, reason=None):
    """Resultado de `cli.published` con las dos versiones forzadas."""
    monkeypatch.setattr(checks, "_installed_version", lambda: installed)
    ctx = make_ctx(make_home(tmp_path), latest_release=lambda: (last, reason))
    return result_for("cli.published", ctx)


def test_outdated_install_warns_with_the_command_that_updates_it(tmp_path, monkeypatch):
    result = _published(tmp_path, monkeypatch, "0.16.0", "0.17.0")
    assert result.status == checks.WARN
    assert "0.16.0" in result.detail and "0.17.0" in result.detail
    assert result.fix_hint


def test_up_to_date_install_is_ok(tmp_path, monkeypatch):
    result = _published(tmp_path, monkeypatch, "0.17.0", "0.17.0")
    assert result.status == checks.OK
    assert not checks.is_warning(result.status)


def test_repo_ahead_of_the_published_release_is_ok(tmp_path, monkeypatch):
    """Lo normal mientras se trabaja: el repo lleva el bump y PyPI todavía no."""
    result = _published(tmp_path, monkeypatch, "0.18.0", "0.17.0")
    assert result.status == checks.OK
    assert "por delante" in result.detail


def test_versions_are_compared_as_numbers_and_not_as_text(tmp_path, monkeypatch):
    """Comparadas como texto, `"0.9.0" > "0.11.0"`. Si alguien compara strings, esto lo caza."""
    result = _published(tmp_path, monkeypatch, "0.9.0", "0.11.0")
    assert result.status == checks.WARN


@pytest.mark.parametrize(("installed", "last"), [("0.17", "0.17.0"), ("0.17.0", "0.17")])
def test_a_shorter_version_does_not_make_up_an_update(tmp_path, monkeypatch, installed, last):
    """`0.17` y `0.17.0` son la misma: sin rellenar a la misma longitud, una saldría menor."""
    assert _published(tmp_path, monkeypatch, installed, last).status == checks.OK


def test_without_network_it_cannot_compare_and_that_is_not_a_fault(tmp_path, monkeypatch):
    """`unknown`, nunca `missing`: no saber la última publicada no es que falte nada."""
    result = _published(tmp_path, monkeypatch, "0.17.0", None, "no se pudo consultar PyPI (…)")
    assert result.status == checks.UNKNOWN
    assert not checks.is_warning(result.status)
    assert "PyPI" in result.detail


def test_without_installed_version_it_does_not_compare_either(tmp_path, monkeypatch):
    result = _published(tmp_path, monkeypatch, None, "0.17.0")
    assert result.status == checks.UNKNOWN


def test_a_query_that_blows_up_does_not_bring_down_the_diagnosis(tmp_path, monkeypatch):
    """El diagnóstico se ejecuta justo cuando algo va mal; no puede caerse por un dato accesorio."""

    def _blows_up():
        raise RuntimeError("boom")

    results = checks.run_all(make_ctx(make_home(tmp_path), latest_release=_blows_up))
    assert len(results) == len(checks.CHECKS)
    by_id = {check.id: result for check, result in results}
    assert by_id["cli.published"].status == checks.UNKNOWN


# --- Hooks huérfanos de instalaciones anteriores ------------------------------
# Las versiones viejas dejaban los scripts sueltos en `~/.claude/hooks/`; la actual los pone en
# `hooks/local-delegate/` y nunca limpiaba los otros. Esta máquina los tenía: cuatro.


def _with_orphans(home, *names):
    root = home / ".claude" / "hooks"
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        (root / name).write_text("# viejo\n", encoding="utf-8")
    return root


def test_orphans_are_reported_with_their_count_and_location(tmp_path):
    home = make_home(tmp_path)
    root = _with_orphans(home, "hook_common.py", "suggest_lint_summary.py")
    result = result_for("scaffold.hook_orphans", make_ctx(home))
    assert result.status == checks.WARN
    assert "2 script(s)" in result.detail
    assert str(root) in result.detail
    assert result.fix_hint == checks.INSTALL_HINT


def test_the_good_install_is_not_reported_as_orphan(tmp_path):
    """El fallo peor posible de este check, y está a un identificador de distancia.

    `ctx.hooks_dir` **ya es** `hooks/local-delegate/`. Un probe que mirara ahí reportaría como
    huérfanos los scripts recién instalados, e `install` los borraría acto seguido: la máquina se
    quedaría sin hooks y en bucle.
    """
    home = make_home(tmp_path, complete=True)
    assert list(make_ctx(home).hooks_dir.iterdir()), "el HOME completo debe traer los hooks buenos"
    assert result_for("scaffold.hook_orphans", make_ctx(home)).status == checks.OK


def test_a_foreign_file_in_the_root_does_not_count_as_orphan(tmp_path):
    home = make_home(tmp_path)
    _with_orphans(home, "third_party_hook.py", "telemetry.jsonl")
    assert result_for("scaffold.hook_orphans", make_ctx(home)).status == checks.OK


def test_without_claude_nothing_is_asserted_about_orphans(tmp_path):
    home = make_home(tmp_path, claude=False, codex=True, complete=False)
    assert result_for("scaffold.hook_orphans", make_ctx(home)).status == checks.UNKNOWN


def test_the_hint_depends_on_how_it_is_installed(tmp_path, monkeypatch):
    """Los tres comandos no son intercambiables, y darle el que no toca es un consejo que falla.

    En una editable `uv tool upgrade` no actualiza nada —el código sale del repo— y a quien
    instaló con `pip` mandarlo a `uv tool` lo deja igual que estaba. La decisión de cuál es cuál
    vive en `update.install_kind`, en un solo sitio.
    """
    from local_delegate import update

    def hint_for(mode, folder):
        monkeypatch.setattr(update, "install_kind", lambda: mode)
        return _published(tmp_path / folder, monkeypatch, "0.16.0", "0.17.0").fix_hint

    assert hint_for(update.UV_TOOL, "a") == update.UV_TOOL_UPGRADE

    monkeypatch.setattr(update, "editable_origin", lambda: tmp_path / "repo")
    hint = hint_for(update.EDITABLE, "b")
    assert "git -C" in hint and "uv sync" in hint

    assert hint_for(update.OTHER, "c") == update.generic_upgrade()


def test_the_detail_and_hint_fit_the_windows_console(tmp_path, monkeypatch):
    """Una flecha `→` mata el doctor con UnicodeEncodeError en la consola cp1252."""
    result = _published(tmp_path, monkeypatch, "0.16.0", "0.17.0")
    (result.detail + result.fix_hint).encode("cp1252")


# --- El daemon puede estar sirviendo la versión vieja -------------------------


def test_daemon_running_an_older_version_is_warn(tmp_path, monkeypatch):
    """Un daemon es un proceso largo: tras actualizar sigue sirviendo el código viejo."""
    monkeypatch.setattr(checks, "_installed_version", lambda: "0.14.0")
    ctx = make_ctx(
        make_home(tmp_path),
        daemon_status=lambda host, port: {"version": "0.13.1", "pid": 42, "mcp_url": "u"},
    )
    result = result_for("service.daemon", ctx)
    assert result.status == checks.WARN
    assert "0.13.1" in result.detail and "0.14.0" in result.detail
    assert result.fix_hint == checks.restart_hint()


def test_daemon_newer_than_installed_says_update_not_restart(tmp_path, monkeypatch):
    """El caso al revés, encontrado en producción tras publicar la 0.18.0.

    Con el daemon corriendo del venv editable (0.18.0) y el CLI de `uv tool` en 0.17.0, el check
    decía «el daemon sirve la vieja» y mandaba **reiniciar el daemon** — un arreglo que no arregla
    nada, porque reiniciarlo lo deja igual. El atrasado es el CLI.
    """
    monkeypatch.setattr(checks, "_installed_version", lambda: "0.17.0")
    monkeypatch.setattr(checks, "_upgrade_hint", lambda: "uv tool upgrade local-delegate-mcp")
    ctx = make_ctx(
        make_home(tmp_path),
        daemon_status=lambda host, port: {"version": "0.18.0", "pid": 42, "mcp_url": "u"},
    )
    result = result_for("service.daemon", ctx)
    assert result.status == checks.WARN
    assert "la instalación está atrasada" in result.detail
    assert "el daemon sirve la vieja" not in result.detail
    assert result.fix_hint == "uv tool upgrade local-delegate-mcp"
    assert result.fix_hint != checks.restart_hint()


def test_daemon_versions_are_compared_as_numbers_not_as_text(tmp_path, monkeypatch):
    """Comparadas como texto, `"0.9.0" > "0.18.0"`. El daemon aquí es el VIEJO."""
    monkeypatch.setattr(checks, "_installed_version", lambda: "0.18.0")
    ctx = make_ctx(
        make_home(tmp_path),
        daemon_status=lambda host, port: {"version": "0.9.0", "pid": 42, "mcp_url": "u"},
    )
    result = result_for("service.daemon", ctx)
    assert result.fix_hint == checks.restart_hint()
    assert "el daemon sirve la vieja" in result.detail


def test_incomparable_daemon_versions_warn_without_offering_a_fix(tmp_path, monkeypatch):
    """Sin poder ordenarlas, cualquier arreglo que se sugiriera podría ser el equivocado."""
    monkeypatch.setattr(checks, "_installed_version", lambda: "0.18.0")
    ctx = make_ctx(
        make_home(tmp_path),
        daemon_status=lambda host, port: {"version": "who-knows", "pid": 42, "mcp_url": "u"},
    )
    result = result_for("service.daemon", ctx)
    assert result.status == checks.WARN
    assert result.fix_hint == ""
    assert "no se pudieron comparar" in result.detail


def test_daemon_on_the_installed_version_is_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(checks, "_installed_version", lambda: "0.14.0")
    ctx = make_ctx(
        make_home(tmp_path),
        daemon_status=lambda host, port: {"version": "0.14.0", "pid": 42, "mcp_url": "u"},
    )
    assert result_for("service.daemon", ctx).status == checks.OK


def test_every_status_has_a_label_and_only_warn_and_missing_count():
    assert set(checks.STATUS_LABEL) == {checks.OK, checks.WARN, checks.MISSING, checks.UNKNOWN}
    assert checks.is_warning(checks.MISSING) and checks.is_warning(checks.WARN)
    assert not checks.is_warning(checks.OK) and not checks.is_warning(checks.UNKNOWN)


def test_run_all_survives_a_broken_probe(monkeypatch, tmp_path):
    def explodes(_ctx):
        raise RuntimeError("boom")

    broken = checks.Check("test.broken", "cliente", "roto", explodes)
    monkeypatch.setattr(checks, "CHECKS", (broken,) + checks.CHECKS)
    results = dict(checks.run_all(make_ctx(make_home(tmp_path))))
    assert results[broken].status == checks.UNKNOWN
    assert "boom" in results[broken].detail


# --- HOME completo: todo ok ---------------------------------------------------


def test_complete_home_is_all_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(checks.shutil, "which", lambda name: "/usr/local/bin/local-delegate")
    # `client.observed` hay que alimentarlo aparte: su registro **no vive en el HOME** —está en
    # `LOG_DIR`—, así que un HOME completo no lo pone `ok` por sí solo. Se le da una observación en
    # vez de excluirlo del test, para que aquí también se le exija estar `ok`.
    # Claude Desktop tampoco lo escribe `install`: se le pone su entrada para exigirle `ok` también.
    home = make_home(tmp_path)
    write_claude_desktop(home, {install.SERVER_NAME: desktop_mcp_remote_entry()})
    # `config.cost` tampoco: su cotejo vive en `LOG_DIR`. Se le da uno que pasa.
    logs = tmp_path / "logs"
    recompute.write_aggregates(logs, {"version": 1, "check": {"verdict": "pass"}})
    # `backend.residency` y `backend.topology` leen la config de llama-swap (`doctor --config`):
    # se les da la de hoy, sin residente y con turno.
    ctx = make_ctx(
        home,
        clients_seen=lambda: ([CLAUDE], None),
        log_dir=logs,
        config_path=RESIDENCY_FIXTURES / "today.yaml",
    )
    for check, result in checks.run_all(ctx):
        assert result.status == checks.OK, f"{check.id}: {result.detail}"


# --- HOME vacío: missing con pista, nunca sin explicación ----------------------


def test_empty_home_reports_missing_with_fix_hint(tmp_path):
    # `scaffold.memory` queda fuera porque agrega dos clientes, y `scaffold.hook_orphans` porque
    # **nunca** puede ser `missing`: pregunta si SOBRA algo, no si falta. En un HOME vacío la
    # respuesta correcta es `ok` — no hay huérfanos que retirar.
    # `scaffold.shell_completion` tampoco: es opcional, y sin nada instalado la respuesta es `ok`
    # «no instalado (opcional)», no «falta».
    separate = {"scaffold.memory", "scaffold.hook_orphans", "scaffold.shell_completion"}
    ctx = make_ctx(make_home(tmp_path, complete=False))
    scaffold = [
        (check, result)
        for check, result in checks.run_all(ctx)
        if check.group == "scaffold" and check.id not in separate
    ]
    assert scaffold
    for check, result in scaffold:
        assert result.status == checks.MISSING, f"{check.id}: {result.detail}"
        assert result.fix_hint == checks.INSTALL_HINT


def test_memory_missing_in_both_clients(tmp_path):
    ctx = make_ctx(make_home(tmp_path, complete=False))
    result = result_for("scaffold.memory", ctx)
    assert result.status == checks.MISSING
    assert "Claude" in result.detail and "Codex" in result.detail


# --- REQ-003: cliente ausente y permisos son unknown, nunca missing ------------


def test_absent_client_is_unknown_not_missing(tmp_path):
    ctx = make_ctx(make_home(tmp_path, claude=False, codex=False, opencode=False))
    for check, result in checks.run_all(ctx):
        # El autocompletado del shell no es de ningún cliente: su estado no depende de ellos.
        if check.group == "scaffold" and check.id != "scaffold.shell_completion":
            assert result.status == checks.UNKNOWN, f"{check.id}: {result.detail}"
    assert result_for("client.presence", ctx).status == checks.UNKNOWN


def test_only_codex_installed_leaves_claude_checks_unknown(tmp_path):
    # `opencode=False` explícito y no por el default: sin esto el HOME tenía **dos** clientes y el
    # test no probaba lo que dice su nombre. Pasaba igual porque `_probe_skill` solo miraba Claude
    # Code; en cuanto el probe empezó a mirar los dos, la skill de opencode lo puso en `ok`.
    ctx = make_ctx(make_home(tmp_path, claude=False, opencode=False))
    assert result_for("scaffold.skill", ctx).status == checks.UNKNOWN
    assert result_for("scaffold.hook_files", ctx).status == checks.UNKNOWN
    assert result_for("scaffold.mcp_codex", ctx).status == checks.OK
    memory = result_for("scaffold.memory", ctx)
    assert memory.status == checks.OK  # el único cliente presente lo tiene


@pytest.mark.skipif(sys.platform == "win32", reason="chmod no quita permisos de lectura en Windows")
def test_unreadable_file_is_unknown_not_missing(tmp_path):
    home = make_home(tmp_path)
    settings = home / ".claude" / "settings.json"
    settings.chmod(0o000)
    try:
        result = result_for("scaffold.hook_settings", make_ctx(home))
    finally:
        settings.chmod(0o644)
    assert result.status == checks.UNKNOWN
    assert result.fix_hint == ""


def test_unreadable_file_is_unknown_via_read_helpers(tmp_path, monkeypatch):
    """El mismo contrato que el test anterior, verificable en cualquier plataforma."""
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")

    def denied(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("pathlib.Path.read_text", denied)
    text, reason = checks.read_text(path)
    assert text is None and reason and "no se pudo leer" in reason
    data, reason = checks.read_json(path)
    assert data is None and reason


def test_invalid_json_is_unknown(tmp_path):
    home = make_home(tmp_path)
    (home / ".claude" / "settings.json").write_text("{ roto", encoding="utf-8")
    result = result_for("scaffold.hook_settings", make_ctx(home))
    assert result.status == checks.UNKNOWN
    assert "JSON" in result.detail


# --- Hooks: distinguir los nuestros de los del usuario (REQ-005) --------------


def test_foreign_hook_is_not_counted_as_ours(tmp_path):
    home = make_home(tmp_path, complete=False)
    settings = home / ".claude" / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {"hooks": [{"type": "command", "command": "python /otro/hook.py"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    result = result_for("scaffold.hook_settings", make_ctx(home))
    assert result.status == checks.MISSING
    assert "/otro/hook.py" not in result.detail


def test_our_hook_alongside_a_foreign_one_is_ok(tmp_path):
    home = make_home(tmp_path)
    settings = home / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"].setdefault("UserPromptSubmit", []).append(
        {"hooks": [{"type": "command", "command": "python /otro/hook.py"}]}
    )
    settings.write_text(json.dumps(data), encoding="utf-8")
    result = result_for("scaffold.hook_settings", make_ctx(home))
    assert result.status == checks.OK
    assert "UserPromptSubmit" in result.detail


def test_legacy_hook_format_is_warn_not_ok(tmp_path):
    """Una instalación anterior deja entradas con `args` y los scripts en otra ruta.

    Ojo con el matiz: esas entradas **sí se ejecutan** (`args` es el exec form del schema), así
    que el detalle no puede decir que estén muertas. Es `warn` porque no es lo que instala la
    versión actual, no porque no funcionen.
    """
    home = make_home(tmp_path, complete=False)
    settings = home / ".claude" / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python",
                                    "args": [
                                        str(home / ".claude/hooks/suggest_delegate_prompt.py")
                                    ],
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    result = result_for("scaffold.hook_settings", make_ctx(home))
    assert result.status == checks.WARN
    assert "instalación anterior" in result.detail
    assert "funcionan" in result.detail
    assert result.fix_hint == checks.INSTALL_HINT


def test_missing_hook_script_is_warn_not_missing(tmp_path):
    home = make_home(tmp_path)
    script = install._HOOK_EVENTS[0][0]
    (home / ".claude" / "hooks" / install.HOOKS_SUBDIR / script).unlink()
    result = result_for("scaffold.hook_files", make_ctx(home))
    assert result.status == checks.WARN
    assert script in result.detail


def test_skill_directory_without_skill_md_is_warn(tmp_path):
    home = make_home(tmp_path)
    (home / ".claude" / "skills" / install.SKILL_NAME / "SKILL.md").unlink()
    assert result_for("scaffold.skill", make_ctx(home)).status == checks.WARN


# --- Entradas MCP -------------------------------------------------------------


def test_codex_mcp_written_by_hand_is_warn(tmp_path):
    home = make_home(tmp_path, complete=False)
    (home / ".codex" / "config.toml").write_text(
        f'[mcp_servers.{install.SERVER_NAME}]\nurl = "http://127.0.0.1:9393/mcp"\n',
        encoding="utf-8",
    )
    result = result_for("scaffold.mcp_codex", make_ctx(home))
    assert result.status == checks.WARN
    assert "a mano" in result.detail


def test_claude_mcp_entry_reports_its_type(tmp_path):
    ctx = make_ctx(make_home(tmp_path))
    result = result_for("scaffold.mcp_claude", ctx)
    assert result.status == checks.OK
    assert "http" in result.detail


def test_claude_mcp_missing_entry(tmp_path):
    home = make_home(tmp_path)
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"other": {}}}), encoding="utf-8")
    result = result_for("scaffold.mcp_claude", make_ctx(home))
    assert result.status == checks.MISSING
    assert result.fix_hint == checks.INSTALL_HINT


# --- Credencial del backend por el camino del cliente -------------------------
# El check nace de una avería que ningún otro veía: entradas MCP en `stdio`, el secreto solo en el
# lanzador del daemon y todas las tools `local_*` devolviendo 401 mientras `doctor` daba todo OK.


def _with_stdio(home):
    """Deja la entrada de Claude Code en modo stdio, como la escribe `install` por defecto."""
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {install.SERVER_NAME: {"type": "stdio", "command": "uvx"}}}),
        encoding="utf-8",
    )
    return home


def test_credential_ok_when_the_backend_does_not_require_a_key(tmp_path, monkeypatch):
    """Sin credencial de por medio, el modo de la entrada MCP no cambia nada."""
    monkeypatch.setattr(checks.config, "API_KEY", "")
    ctx = make_ctx(_with_stdio(make_home(tmp_path)), backend_needs_key=lambda: (False, ""))
    assert result_for("service.credential", ctx).status == checks.OK


def test_credential_ok_when_the_entries_go_through_the_daemon(tmp_path, monkeypatch):
    """Mismo backend que el test de abajo: lo único que cambia es el modo de la entrada.

    Los dos tests son pareja a propósito. Un probe que mirase solo el backend —y no el modo—
    pasaría este y fallaría el siguiente; uno que mirase solo el modo, al revés. Separados, ninguna
    de las dos mitades puede aprobar por la guarda de la otra.
    """
    monkeypatch.setattr(checks.config, "API_KEY", "")
    ctx = make_ctx(make_home(tmp_path), backend_needs_key=lambda: (True, ""))  # http
    assert result_for("service.credential", ctx).status == checks.OK


def test_credential_warn_when_the_client_speaks_stdio_without_key(tmp_path, monkeypatch):
    monkeypatch.setattr(checks.config, "API_KEY", "")
    ctx = make_ctx(_with_stdio(make_home(tmp_path)), backend_needs_key=lambda: (True, ""))
    result = result_for("service.credential", ctx)
    assert result.status == checks.WARN
    assert "Claude Code" in result.detail and "401" in result.detail
    assert result.fix_hint == checks.credential_hint()


def test_credential_ok_if_the_key_is_in_the_environment(tmp_path, monkeypatch):
    """Con la variable cargada, la entrada stdio la hereda y el 401 no llega a pasar."""
    monkeypatch.setattr(checks.config, "API_KEY", "fake-secret")
    ctx = make_ctx(_with_stdio(make_home(tmp_path)), backend_needs_key=lambda: (True, ""))
    assert result_for("service.credential", ctx).status == checks.OK


def test_credential_unknown_if_it_could_not_ask(tmp_path):
    """Sin respuesta del backend no hay veredicto: lo no comprobable es `unknown`, nunca `missing`."""
    ctx = make_ctx(_with_stdio(make_home(tmp_path)), backend_needs_key=checks.NO_KEY_PROBE)
    result = result_for("service.credential", ctx)
    assert result.status == checks.UNKNOWN
    assert result.fix_hint == ""


# --- Daemon y backend ---------------------------------------------------------


def test_daemon_alive_is_ok_with_version_and_pid(tmp_path):
    result = result_for("service.daemon", make_ctx(make_home(tmp_path)))
    assert result.status == checks.OK
    assert str(checks._installed_version()) in result.detail and "42" in result.detail


def test_daemon_down_is_missing_with_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(checks, "_port_taken", lambda host, port: False)
    ctx = make_ctx(make_home(tmp_path), daemon_status=lambda host, port: None)
    result = result_for("service.daemon", ctx)
    assert result.status == checks.MISSING
    assert result.fix_hint == checks.serve_hint()


def test_port_taken_by_another_process_is_warn_not_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(checks, "_port_taken", lambda host, port: True)
    ctx = make_ctx(make_home(tmp_path), daemon_status=lambda host, port: None)
    result = result_for("service.daemon", ctx)
    assert result.status == checks.WARN
    assert "no es nuestro daemon" in result.detail


def test_the_protected_port_is_not_mistaken_for_a_foreign_process(tmp_path, monkeypatch):
    """Dos causas para el mismo silencio, y arreglos opuestos.

    Sin esta distinción, poner el token hacía que `doctor` acusara al propio daemon de ser «otro
    proceso»: un mensaje que invita a matarlo cuando lo que falta es una variable de entorno. Es
    el mismo error que ya se pagó caro aquí —diagnosticar por el camino equivocado— y esta vez
    aparecía como efecto de un arreglo de seguridad, que es la peor forma de aparecer.
    """
    monkeypatch.setattr(checks, "_port_taken", lambda host, port: True)
    ctx = make_ctx(
        make_home(tmp_path),
        daemon_status=lambda host, port: None,
        daemon_needs_token=lambda host, port: True,
    )
    result = result_for("service.daemon", ctx)

    assert result.status == checks.WARN
    assert "no tiene su token" in result.detail
    assert "no es nuestro daemon" not in result.detail
    assert checks.TOKEN_VAR in (result.fix_hint or "")


def test_the_token_diagnosis_does_not_print_the_secret(tmp_path, monkeypatch):
    """El arreglo nombra la variable; su valor no sale por pantalla ni por error."""
    monkeypatch.setattr(checks, "_port_taken", lambda host, port: True)
    monkeypatch.setattr(checks.config, "WEB_TOKEN", "a-secret-that-must-not-leak")
    ctx = make_ctx(
        make_home(tmp_path),
        daemon_status=lambda host, port: None,
        daemon_needs_token=lambda host, port: True,
    )
    result = result_for("service.daemon", ctx)

    assert "a-secret-that-must-not-leak" not in result.detail
    assert "a-secret-that-must-not-leak" not in (result.fix_hint or "")


def test_without_knowing_if_it_requires_a_token_the_usual_message_stays(tmp_path, monkeypatch):
    """`None` es «no se pudo preguntar», y ahí no se inventa un diagnóstico nuevo.

    Importa porque el colaborador devuelve `None` cuando el puerto no habla HTTP — justo el caso
    en que de verdad hay otro proceso delante.
    """
    monkeypatch.setattr(checks, "_port_taken", lambda host, port: True)
    ctx = make_ctx(
        make_home(tmp_path),
        daemon_status=lambda host, port: None,
        daemon_needs_token=checks.NO_TOKEN_PROBE,
    )
    result = result_for("service.daemon", ctx)

    assert result.status == checks.WARN
    assert "no es nuestro daemon" in result.detail


def test_backend_down_is_warn(tmp_path):
    ctx = make_ctx(
        make_home(tmp_path),
        backend_models=lambda: BackendView(False, "no responde (ConnectError)", None, "direct"),
    )
    result = result_for("service.backend", ctx)
    assert result.status == checks.WARN
    assert checks.is_warning(result.status)


def test_backend_401_is_unknown_not_down(tmp_path):
    """Un 401 es «está arriba y falta la key aquí», no «caído».

    Pasó de verdad: con la key sin cargar en el entorno del agente, el doctor decía CAÍDO sobre
    un llama-swap vivo y sirviendo, y mandaba a arrancarlo.
    """
    ctx = make_ctx(
        make_home(tmp_path),
        backend_models=lambda: BackendView(
            False,
            "responde 401: está arriba pero rechaza la credencial",
            "credential",
            "direct",
        ),
    )
    result = result_for("service.backend", ctx)
    assert result.status == checks.UNKNOWN
    assert not checks.is_warning(result.status)
    assert "401" in result.detail


# --- service.backend con causa (REQ-016) ---------------------------------------------------------


def test_remote_doctor_does_not_say_to_start_llama_swap(tmp_path, monkeypatch):
    """La Mac con la VPN caída: el backend vive en otra máquina, arrancar nada aquí no lo arregla."""
    monkeypatch.setattr(checks.config, "BASE_URL", "http://pc.tailnet.ts.net:9292/v1")
    ctx = make_ctx(
        make_home(tmp_path),
        backend_models=lambda: BackendView(
            False,
            "pc.tailnet.ts.net:9292 no contesta a la conexión (ruta, cortafuegos o VPN)",
            "connect_timeout",
            "direct",
        ),
    )

    r = result_for("service.backend", ctx)

    assert "arranca llama-swap" not in (r.fix_hint or "")
    assert r.status == checks.WARN
    assert r.fix_hint == "revisa la red hacia pc.tailnet.ts.net:9292 (VPN, cortafuegos, Tailscale)"
    assert "no contesta a la conexión" in r.detail


def _ctx_with_daemon(tmp_path, monkeypatch, seen):
    """`service.backend` con el colaborador REAL, y el daemon contestando `visto`."""
    from local_delegate import daemon

    monkeypatch.setattr(daemon, "query_backend", lambda host, port, timeout=1.0: seen)
    return make_ctx(make_home(tmp_path), backend_models=checks._default_backend_models)


def test_doctor_uses_the_cause_the_daemon_gives(tmp_path, monkeypatch):
    monkeypatch.setattr(checks.config, "BASE_URL", "http://pc.lan:9292/v1")
    ctx = _ctx_with_daemon(
        tmp_path,
        monkeypatch,
        {
            "available": False,
            "cause": "dns",
            "detail": "no se resuelve el nombre pc.lan (¿VPN o DNS?)",
        },
    )

    r = result_for("service.backend", ctx)

    assert "no se resuelve el nombre pc.lan" in r.detail
    assert r.status == checks.WARN
    assert r.fix_hint == (
        "revisa el nombre en LOCAL_DELEGATE_BASE_URL o usa la IP (p. ej. la 100.x de la tailnet)"
    )


def test_doctor_daemon_401_points_to_the_launcher(tmp_path, monkeypatch):
    """El daemon SÍ tiene la clave de su lanzador: si da 401, la que no vale es la suya."""
    ctx = _ctx_with_daemon(
        tmp_path,
        monkeypatch,
        {
            "available": False,
            "cause": "credential",
            "detail": "127.0.0.1:9292 responde 401: está arriba pero rechaza la credencial",
        },
    )

    r = result_for("service.backend", ctx)

    assert "lanzador" in (r.fix_hint or "")
    assert r.status == checks.WARN


def test_doctor_understands_the_cause_from_a_0_34_daemon(tmp_path, monkeypatch):
    """Un daemon de la 0.34.0 manda `causa`/`detalle` y el valor en español (REQ-006): `doctor`
    nuevo da la misma pista que con el daemon nuevo."""
    ctx = _ctx_with_daemon(
        tmp_path,
        monkeypatch,
        {
            "available": False,
            "causa": "credencial",
            "detalle": "127.0.0.1:9292 responde 401: está arriba pero rechaza la credencial",
        },
    )

    r = result_for("service.backend", ctx)

    assert "responde 401" in r.detail
    assert "lanzador" in (r.fix_hint or "")
    assert r.status == checks.WARN


def test_doctor_with_old_daemon_uses_todays_text(tmp_path, monkeypatch):
    """Un daemon sin `causa` en `/api/backend`: el texto de siempre y la pista genérica."""
    ctx = _ctx_with_daemon(tmp_path, monkeypatch, {"available": False})

    r = result_for("service.backend", ctx)

    assert "según el daemon" in r.detail
    assert r.status == checks.WARN
    assert r.fix_hint.startswith("revisa el backend en ")


def test_doctor_waits_for_the_daemon_longer_than_its_probe(monkeypatch):
    """La causa que ve el daemon tiene que llegar también en sus fallos lentos (VPN, Windows)."""
    from local_delegate import daemon

    timeouts = []

    def _records(host, port, timeout=1.0):
        timeouts.append(timeout)

    monkeypatch.setattr(daemon, "query_backend", _records)
    monkeypatch.setattr(probes, "backend_probe", lambda: BackendView(True, "", None, "direct"))

    checks._default_backend_models()

    (t,) = timeouts
    read_timeout = t.read if isinstance(t, httpx2.Timeout) else t
    connect_timeout = t.connect if isinstance(t, httpx2.Timeout) else t
    assert read_timeout > checks.config.PROBE_CONNECT_TIMEOUT + checks.config.PROBE_READ_TIMEOUT
    # Conectar con el daemon, que está en esta máquina, no necesita más que antes.
    assert connect_timeout == 1.0


# --- Versiones: se envuelve el doctor, no se reescribe -------------------------


def test_older_version_is_warn(tmp_path):
    ctx = make_ctx(
        make_home(tmp_path),
        version_of=lambda component, cfg: ("v100" if component == "llama-swap" else "b1", None),
    )
    result = result_for("backend.llamaswap", ctx)
    assert result.status == checks.WARN
    assert "considera actualizar" in result.detail


def test_undetected_version_is_unknown_not_missing(tmp_path):
    ctx = make_ctx(make_home(tmp_path), version_of=lambda component, cfg: (None, None))
    result = result_for("backend.llamaserver", ctx)
    assert result.status == checks.UNKNOWN
    assert "no detectado" in result.detail
    assert not checks.is_warning(result.status)


def test_undetected_version_with_reason_keeps_the_reason(tmp_path):
    ctx = make_ctx(
        make_home(tmp_path),
        version_of=lambda component, cfg: (None, "config no encontrado: X"),
    )
    result = result_for("backend.llamaserver", ctx)
    assert result.status == checks.UNKNOWN
    assert "config no encontrado: X" in result.detail


# --- client.observed: los clientes MCP con los que se ha hablado --------------
#
# El registro que lee este check es HISTÓRICO y lo escriben varios procesos (cada cliente stdio
# lanza el suyo), así que los tests que más valen aquí son los de acumulación y los de dato sucio:
# el fichero viene de fuera y puede traer cualquier cosa.

CLAUDE = {
    "ts": "2026-07-31T17:15:52+00:00",
    "client": "claude-code",
    "version": "2.1.220",
    "protocol": "2025-11-25",
    "caps": ["elicitation", "roots"],
}
CODEX = {
    "ts": "2026-07-31T16:00:00+00:00",
    "client": "codex-mcp-client",
    "version": "0.146.0",
    "protocol": "2025-06-18",
    "caps": ["elicitation"],
}


def observing(tmp_path, observations, reason=None):
    return make_ctx(make_home(tmp_path), clients_seen=lambda: (observations, reason))


def test_without_seen_clients_is_unknown_and_adds_no_warning(tmp_path):
    """El caso de HOY: `clients.py` está sin publicar, así que no hay registro en ninguna máquina.

    Tiene que ser `unknown` y no `missing`: no falta nada que instalar, simplemente todavía no ha
    hablado nadie. Un `missing` mandaría a arreglar una máquina sana.
    """
    result = result_for("client.observed", observing(tmp_path, []))
    assert result.status == checks.UNKNOWN
    assert not checks.is_warning(result.status)
    assert "todavía no ha hablado ningún cliente" in result.detail


def test_unreadable_registry_is_unknown_with_the_reason(tmp_path):
    result = result_for("client.observed", observing(tmp_path, [], "no se pudo leer X: denegado"))
    assert result.status == checks.UNKNOWN
    assert "no se pudo leer X: denegado" in result.detail


def test_a_client_that_can_ask_comes_out_ok(tmp_path):
    result = result_for("client.observed", observing(tmp_path, [CLAUDE]))
    assert result.status == checks.OK
    assert "claude-code 2.1.220 [2025-11-25] elicitation" in result.detail


def test_a_client_without_elicitation_is_still_ok(tmp_path):
    """La decisión de diseño del change, y por eso tiene test propio.

    Un cliente sin `elicitation` es información, no un defecto: no hay comando del repo que lo
    arregle y marcarlo como aviso subiría el exit code de una máquina sana.
    """
    silent = {**CODEX, "client": "silent-client", "caps": []}
    result = result_for("client.observed", observing(tmp_path, [CLAUDE, silent]))
    assert result.status == checks.OK
    assert not checks.is_warning(result.status)
    assert "silent-client 0.146.0 [2025-06-18] sin elicitation" in result.detail
    assert "claude-code 2.1.220 [2025-11-25] elicitation" in result.detail


def test_the_same_repeated_client_appears_once_with_the_latest_version(tmp_path):
    """`clients.jsonl` acumula una línea por ARRANQUE de proceso: medido, no supuesto.

    La deduplicación de `clients.record` es intra-proceso, así que veinte lanzamientos de
    Claude Code dejan veinte líneas idénticas. Sin agrupar, el detail sería una lista repetida.

    La observación vieja va **la última** de la lista a propósito: si el check se quedara con la
    última que ve en vez de con la más reciente por `ts`, este test pasaría igual. Con ella al
    final, «agrupa por nombre» y «escoge la más reciente» quedan cubiertos por separado — puesta al
    principio, la segunda mitad no se probaba (comprobado introduciendo el defecto).
    """
    old = {**CLAUDE, "ts": "2026-07-01T09:00:00+00:00", "version": "2.1.219"}
    result = result_for("client.observed", observing(tmp_path, [CLAUDE] * 20 + [old]))
    assert result.detail.count("claude-code") == 1  # agrupa
    assert "2.1.220" in result.detail  # y se queda con la más reciente
    assert "2.1.219" not in result.detail


def test_an_observation_without_identity_is_not_lost(tmp_path):
    """Desde la revisión 2026-07-28 el `client_info` es opcional: hay capabilities sin nombre."""
    anonymous = {
        "ts": CODEX["ts"],
        "client": None,
        "protocol": "2026-07-28",
        "caps": ["elicitation"],
    }
    result = result_for("client.observed", observing(tmp_path, [anonymous]))
    assert result.status == checks.OK
    assert "(sin identificar) [2026-07-28] elicitation" in result.detail


def test_caps_that_is_not_a_list_does_not_count_as_elicitation(tmp_path):
    """El falso positivo por subcadena que cazó la revisión adversarial del plan.

    Con `caps` llegando como la cadena "no-elicitation", un `in` sin comprobar el tipo daría True
    y el check afirmaría justo lo contrario de la verdad.
    """
    dirty = {**CLAUDE, "caps": "no-elicitation"}
    result = result_for("client.observed", observing(tmp_path, [dirty]))
    assert "sin elicitation" in result.detail


def test_an_unreadable_ts_does_not_bring_down_the_check(tmp_path):
    """Una fecha rota debe perder la carrera de «la más reciente», no llevarse el check por delante."""
    broken = {**CLAUDE, "ts": "ayer por la tarde", "version": "0.0.1"}
    result = result_for("client.observed", observing(tmp_path, [broken, CLAUDE]))
    assert result.status == checks.OK
    assert "2.1.220" in result.detail


def test_the_detail_is_printable_in_the_windows_console(tmp_path):
    """El nombre lo pone el CLIENTE: es texto ajeno y puede traer lo que sea.

    Una flecha «→» ya mató este doctor una vez. Aquí el dato ni siquiera lo controla el repo.
    """
    exotic = {**CLAUDE, "client": "cliente-\U0001f600", "version": "1.0—beta"}
    result = result_for("client.observed", observing(tmp_path, [exotic]))
    result.detail.encode("cp1252")  # si no es codificable, esto lanza y el test falla


def test_client_observed_offers_no_fix(tmp_path):
    """Sin `fix_hint` a propósito: no existe comando de este repo que cambie con quién hablas."""
    home = make_home(tmp_path)
    for observations in ([], [CLAUDE]):
        ctx = make_ctx(home, clients_seen=lambda obs=observations: (obs, None))
        assert result_for("client.observed", ctx).fix_hint == ""


# --- El colaborador por defecto, que sí toca el disco -------------------------


def test_default_without_file_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(checks.config, "LOG_DIR", tmp_path)
    assert checks._default_clients_seen() == ([], None)


def test_default_reads_the_registry_and_skips_what_is_unusable(tmp_path, monkeypatch):
    """Una línea a medio escribir —proceso muerto durante el write— no puede perder las buenas."""
    monkeypatch.setattr(checks.config, "LOG_DIR", tmp_path)
    (tmp_path / "clients.jsonl").write_text(
        json.dumps(CLAUDE) + "\n"
        "\n"  # línea en blanco
        '{"ts": "2026-07-31T17:00:00+00:0'  # truncada
        "\n"
        "[1, 2, 3]\n"  # JSON válido, pero no un objeto
         + json.dumps(CODEX) + "\n",
        encoding="utf-8",
    )
    observations, reason = checks._default_clients_seen()
    assert reason is None
    assert [obj["client"] for obj in observations] == ["claude-code", "codex-mcp-client"]


def test_default_creates_neither_the_directory_nor_the_file(tmp_path, monkeypatch):
    """`probe` nunca escribe, y eso incluye no materializar el sitio donde iría el registro."""
    dest = tmp_path / "not-created"
    monkeypatch.setattr(checks.config, "LOG_DIR", dest)
    checks._default_clients_seen()
    assert not dest.exists()


# --- Ningún probe escribe (REQ-013 a nivel de registro) -----------------------


def test_no_probe_writes_anything(tmp_path):
    home = make_home(tmp_path)
    before = snapshot(home)
    checks.run_all(make_ctx(home))
    assert snapshot(home) == before


# --- El módulo no puede mentir sobre su propio tamaño ------------------------

_NUMBER_WORDS = {
    10: "diez",
    11: "once",
    12: "doce",
    13: "trece",
    14: "catorce",
    15: "quince",
    16: "dieciséis",
    17: "diecisiete",
    18: "dieciocho",
    19: "diecinueve",
    20: "veinte",
    # Apocopado delante de un sustantivo masculino («los veintiún elementos»); sin sustantivo
    # detrás («los otros veintiuno») va entero: ver `_NUMBER_WORDS_WITHOUT_NOUN`.
    21: "veintiún",
    22: "veintidós",
    23: "veintitrés",
    24: "veinticuatro",
    25: "veinticinco",
    26: "veintiséis",
}
_NUMBER_WORDS_WITHOUT_NOUN = {**_NUMBER_WORDS, 21: "veintiuno"}


def test_the_docstring_states_how_many_checks_there_really_are():
    """El registro dice su tamaño en cuatro sitios, y llegó a decir «once» con doce dentro.

    `cli.path` entró en el PR #61 y nadie actualizó el texto, así que durante dos sesiones el
    módulo afirmaba un número falso sobre sí mismo — y se llegó a planificar sobre ese dato.
    Un comentario no es evidencia, salvo que algo lo obligue a serlo: esto lo obliga.
    """
    from pathlib import Path

    count = _NUMBER_WORDS[len(checks.CHECKS)]
    source = Path(checks.__file__).read_text(encoding="utf-8")

    claims = (
        f"los {count} elementos del andamiaje",
        f"{count.capitalize()} checks son una tupla",
        f"{count.capitalize()} elementos, en orden de grupo",
        f"Corre los {count} probes",
        f"ver los otros {_NUMBER_WORDS_WITHOUT_NOUN[len(checks.CHECKS) - 1]}",
    )
    missing = [text for text in claims if text not in source]
    assert not missing, f"el docstring de checks.py quedó desfasado: {missing}"


# --- El token del puerto del daemon -------------------------------------------
#
# Nace de una avería del 2026-08-18: `install` sin `--web-token-env` escribe la entrada HTTP sin
# cabecera —y borra la que hubiera—, así que contra un daemon con token Claude Code cae al flujo
# OAuth y responde 401. `doctor` decía **todo a punto**, porque el check de andamiaje sólo mira
# que la entrada exista. Tercera vez que el mismo patrón muerde y las tres el diagnóstico miraba
# por un camino distinto del roto.


def _home_with_credential(tmp_path, monkeypatch):
    """HOME completo con los TRES clientes autenticados, como los deja `install --web-token-env`.

    Los tres y no solo Claude Code: el HOME de `make_home` escribe entradas HTTP sin cabecera, así
    que dejar a los otros dos como estaban haría que este helper nunca pudiera producir un `ok` —
    y el control anti-vacío mediría otra cosa. Se descubrió al escribirlo: el check avisaba de
    «Codex y opencode» y tenía razón.
    """
    home = make_home(tmp_path)
    entry = install.mcp_entry("http", None, False, None, web_token_env=True)
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {install.SERVER_NAME: entry}}), encoding="utf-8"
    )
    (home / ".codex" / "config.toml").write_text(
        install.upsert_codex_mcp("", install.codex_mcp_block(entry)), encoding="utf-8"
    )
    oc_dir = install.opencode_dir(home)
    oc_entry = install.opencode_mcp_entry("http", None, False, None, web_token_env=True)
    (oc_dir / "opencode.json").write_text(
        json.dumps({"$schema": install.OPENCODE_SCHEMA, "mcp": {install.SERVER_NAME: oc_entry}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCAL_DELEGATE_WEB_TOKEN", "any-token")
    return home


def test_an_http_entry_without_header_against_a_daemon_with_token_warns(tmp_path):
    """La avería exacta que `doctor` daba por buena."""
    ctx = make_ctx(make_home(tmp_path), daemon_needs_token=lambda host, port: True)
    result = result_for("service.daemon_auth", ctx)

    assert result.status == checks.WARN
    assert "Claude Code" in result.detail
    assert "401" in result.detail
    assert "--web-token-env" in (result.fix_hint or "")


def test_an_http_entry_without_header_is_reported_as_blind_not_as_a_missing_variable(tmp_path):
    """La entrada sin cabecera cae en la rama «ciega», no en la de «variable que no está».

    Las dos ramas dan `WARN` con «Claude Code», «401» y la misma pista, así que el test de arriba
    no las distingue (hallazgo de A8a-1). Control: mutante «`_entry_auth` devuelve
    `"sin_credencial"`» → la entrada pasa por la rama de la variable y falla el primer assert.
    """
    ctx = make_ctx(make_home(tmp_path), daemon_needs_token=lambda host, port: True)
    result = result_for("service.daemon_auth", ctx)

    assert "sin cabecera de autorización" in result.detail, result.detail
    assert "no está en el entorno" not in result.detail


def test_an_http_entry_without_credential_is_tagged_no_credential():
    """El estado interno de una entrada HTTP sin credencial es `"no_credential"`, en los tres clientes.

    Control: mutante «los tres sitios de `checks.py` vuelven a `"sin_credencial"`» → el probe
    sigue coherente consigo mismo, pero este test falla.
    """
    for client in ("Claude Code", "Codex", "opencode"):
        assert checks._entry_auth(client, "http", None) == (client, "no_credential")
        assert checks._entry_auth(client, "http", "") == (client, "no_credential")
    assert checks._entry_auth("Claude Code", "stdio", None) == ("Claude Code", "stdio")


def test_a_properly_authenticated_entry_does_not_bother(tmp_path, monkeypatch):
    """Control de todos los de este bloque, y el que impide que pasen en vacío.

    Sin él, un probe que avisara SIEMPRE dejaría en verde a los demás — que es el fallo opuesto y
    el que hace que la gente aprenda a ignorar un check.
    """
    home = _home_with_credential(tmp_path, monkeypatch)
    ctx = make_ctx(home, daemon_needs_token=lambda host, port: True)
    result = result_for("service.daemon_auth", ctx)

    assert result.status == checks.OK, result.detail


def test_codex_authenticates_with_its_own_key_and_that_also_counts(tmp_path, monkeypatch):
    """Codex no usa `headers`: escribe `bearer_token_env_var` con el nombre pelado.

    Tres clientes, tres vocabularios. Contar mal aquí daría un falso OK en el que no se contó, que
    es exactamente el defecto que este check arregla.
    """
    home = _home_with_credential(tmp_path, monkeypatch)
    block = install.codex_mcp_block(
        install.mcp_entry("http", None, False, None, web_token_env=True)
    )
    (home / ".codex" / "config.toml").write_text(
        install.upsert_codex_mcp("", block), encoding="utf-8"
    )
    ctx = make_ctx(home, daemon_needs_token=lambda host, port: True)
    result = result_for("service.daemon_auth", ctx)

    assert "Codex" not in result.detail


def test_an_open_daemon_makes_no_noise(tmp_path):
    """Sin token en el puerto, que la entrada no lleve cabecera da igual."""
    ctx = make_ctx(make_home(tmp_path), daemon_needs_token=lambda host, port: False)
    result = result_for("service.daemon_auth", ctx)

    assert result.status == checks.OK


def test_being_unable_to_ask_the_port_is_unknown_and_never_missing(tmp_path):
    """Lo no comprobable es `unknown`. Es el contrato del registro entero."""
    ctx = make_ctx(make_home(tmp_path), daemon_needs_token=checks.NO_TOKEN_PROBE)
    result = result_for("service.daemon_auth", ctx)

    assert result.status == checks.UNKNOWN


def test_header_present_but_variable_absent_warns_as_suspicion(tmp_path, monkeypatch):
    """El segundo camino al mismo 401, y de fuerza distinta.

    El entorno de `doctor` es un TESTIGO del que verá el cliente, no una prueba: alguien puede
    haber lanzado el cliente desde otra consola. Por eso el texto nombra el síntoma y no dicta que
    la máquina esté rota.
    """
    home = _home_with_credential(tmp_path, monkeypatch)
    monkeypatch.delenv("LOCAL_DELEGATE_WEB_TOKEN", raising=False)
    ctx = make_ctx(home, daemon_needs_token=lambda host, port: True)
    result = result_for("service.daemon_auth", ctx)

    assert result.status == checks.WARN
    assert "LOCAL_DELEGATE_WEB_TOKEN" in result.detail
    assert "este proceso" in result.detail


def test_a_stdio_entry_does_not_count_as_blind(tmp_path, monkeypatch):
    """No habla con el puerto del daemon, y de su problema ya avisa `service.credential`.

    Contarla aquí sería un falso positivo y además un aviso duplicado.
    """
    home = _home_with_credential(tmp_path, monkeypatch)
    (home / ".codex" / "config.toml").write_text(
        install.upsert_codex_mcp("", install.codex_mcp_block({"type": "stdio", "command": "uvx"})),
        encoding="utf-8",
    )
    ctx = make_ctx(home, daemon_needs_token=lambda host, port: True)
    result = result_for("service.daemon_auth", ctx)

    assert "Codex" not in result.detail


# --- Claude Desktop: el cliente que el instalador no toca ---------------------
#
# Su entrada está puesta a mano, va por `mcp-remote` y lleva el token LITERAL en un `--header`. El
# día que se rote el token del puerto, `install` arregla los tres clientes registrados y este se
# queda en 401 sin que nada lo diga: `service.daemon_auth` es ciego para él. Este check no escribe
# (eso sería la fase B), solo convierte el fallo mudo en un aviso.

_TOKEN_DESKTOP = "literal-desktop-token-that-must-never-leak"


def _desktop_entry(header: str | None = f"Authorization: Bearer {_TOKEN_DESKTOP}"):
    return desktop_mcp_remote_entry(header)


def _with_desktop(home, entry=None, *, raw=None):
    """Claude Desktop con un servidor ajeno al lado, que es como está el fichero real."""
    servers = {"other-server": {"command": "uvx", "args": ["algo"]}}
    if entry is not None:
        servers[install.SERVER_NAME] = entry
    write_claude_desktop(home, servers, raw=raw)
    return home


def _desktop_ctx(home, *, requires=True, accepts: bool | None = True, calls=None):
    def _accepts(host, port, token):
        if calls is not None:
            calls.append(token)
        return accepts

    return make_ctx(
        home,
        daemon_needs_token=lambda host, port: requires,
        daemon_accepts_token=_accepts,
    )


def _without_token(result):
    assert _TOKEN_DESKTOP not in result.detail
    assert _TOKEN_DESKTOP not in (result.fix_hint or "")


def test_desktop_with_a_token_the_daemon_accepts_is_ok_and_does_not_write(tmp_path):
    """Control positivo del bloque: sin él, un probe que avisara siempre dejaría verdes a los demás."""
    home = _with_desktop(make_home(tmp_path), _desktop_entry())
    before = snapshot(home)
    calls: list[str] = []
    result = result_for("service.desktop_auth", _desktop_ctx(home, calls=calls))

    assert result.status == checks.OK, result.detail
    assert calls == [_TOKEN_DESKTOP]  # el token que se prueba es el del fichero, no otro
    _without_token(result)
    assert snapshot(home) == before


def test_desktop_with_rotated_token_warns_without_printing_the_token(tmp_path):
    """La avería que motiva el check: la entrada lleva cabecera, pero el daemon ya no la acepta."""
    home = _with_desktop(make_home(tmp_path), _desktop_entry())
    result = result_for("service.desktop_auth", _desktop_ctx(home, accepts=False))

    assert result.status == checks.WARN
    assert "Claude Desktop" in result.detail
    assert "401" in result.detail
    assert result.fix_hint
    _without_token(result)


def test_desktop_without_header_against_daemon_with_token_warns(tmp_path):
    calls: list[str] = []
    home = _with_desktop(make_home(tmp_path), _desktop_entry(header=None))
    result = result_for("service.desktop_auth", _desktop_ctx(home, calls=calls))

    assert result.status == checks.WARN
    assert "401" in result.detail
    assert calls == []


def test_desktop_against_open_daemon_does_not_test_the_token(tmp_path):
    calls: list[str] = []
    home = _with_desktop(make_home(tmp_path), _desktop_entry())
    result = result_for("service.desktop_auth", _desktop_ctx(home, requires=False, calls=calls))

    assert result.status == checks.OK
    assert calls == []


def test_desktop_without_file_is_unknown_and_does_not_go_to_the_network(tmp_path):
    """Una PC sin Claude Desktop no tiene nada roto. Y no hay por qué preguntarle al puerto."""
    questions: list[str] = []

    def _records(*_args):
        questions.append("red")
        return True

    ctx = make_ctx(make_home(tmp_path), daemon_needs_token=_records, daemon_accepts_token=_records)
    # El probe a solas: `run_all` corre también `service.daemon_auth`, que sí pregunta al puerto.
    result = checks._probe_desktop_auth(ctx)

    assert result.status == checks.UNKNOWN
    assert questions == []


def test_desktop_without_our_entry_is_unknown(tmp_path):
    home = _with_desktop(make_home(tmp_path), None)
    result = result_for("service.desktop_auth", _desktop_ctx(home))

    assert result.status == checks.UNKNOWN
    assert "local-delegate" in result.detail


def test_desktop_with_broken_json_is_unknown_and_never_missing(tmp_path):
    home = _with_desktop(make_home(tmp_path), raw="{ esto no es json")
    result = result_for("service.desktop_auth", _desktop_ctx(home))

    assert result.status == checks.UNKNOWN


def test_desktop_over_stdio_does_not_go_through_the_port(tmp_path):
    entry = {"command": "uvx", "args": ["--from", "local-delegate-mcp", "local-delegate"]}
    calls: list[str] = []
    home = _with_desktop(make_home(tmp_path), entry)
    result = result_for("service.desktop_auth", _desktop_ctx(home, calls=calls))

    assert result.status == checks.UNKNOWN
    assert "stdio" in result.detail
    assert calls == []


def test_desktop_pointing_to_another_host_is_not_tested_against_the_local_daemon(tmp_path):
    """Probar su token contra NUESTRO puerto diría algo de un servidor al que no habla."""
    entry = _desktop_entry()
    entry["args"][2] = "http://100.64.0.7:9393/mcp"
    calls: list[str] = []
    home = _with_desktop(make_home(tmp_path), entry)
    result = result_for("service.desktop_auth", _desktop_ctx(home, calls=calls))

    assert result.status == checks.UNKNOWN
    assert calls == []


def test_desktop_with_referenced_variable_tests_its_value(tmp_path, monkeypatch):
    """`mcp-remote` expande `${VAR}` en las cabeceras: el valor sale de `env` de la entrada o del entorno."""
    monkeypatch.setenv("TOKEN_DESKTOP_TEST", "value-from-env")
    calls: list[str] = []
    home = _with_desktop(
        make_home(tmp_path), _desktop_entry(header="Authorization: Bearer ${TOKEN_DESKTOP_TEST}")
    )
    result = result_for("service.desktop_auth", _desktop_ctx(home, calls=calls))

    assert result.status == checks.OK, result.detail
    assert calls == ["value-from-env"]


def test_desktop_with_bearer_inside_the_variable_tests_only_the_token(tmp_path, monkeypatch):
    """La forma de la Mac: `Authorization:${AUTH_HEADER}` y `env.AUTH_HEADER = "Bearer xxx"`.

    Con el prefijo quitado solo antes de expandir, lo que se probaba era `Bearer xxx`, la
    petición salía con `Bearer Bearer xxx` y el check daba 401 con el token bueno.
    """
    monkeypatch.delenv("AUTH_HEADER", raising=False)
    entry = _desktop_entry(header="Authorization:${AUTH_HEADER}")
    entry["env"] = {"AUTH_HEADER": "Bearer good-token"}
    calls: list[str] = []
    home = _with_desktop(make_home(tmp_path), entry)
    result = result_for("service.desktop_auth", _desktop_ctx(home, calls=calls))

    assert calls == ["good-token"]
    assert result.status == checks.OK, result.detail


def test_desktop_with_missing_variable_warns_as_suspicion(tmp_path, monkeypatch):
    monkeypatch.delenv("TOKEN_DESKTOP_TEST", raising=False)
    calls: list[str] = []
    home = _with_desktop(
        make_home(tmp_path), _desktop_entry(header="Authorization: Bearer ${TOKEN_DESKTOP_TEST}")
    )
    result = result_for("service.desktop_auth", _desktop_ctx(home, calls=calls))

    assert result.status == checks.WARN
    assert "TOKEN_DESKTOP_TEST" in result.detail
    assert calls == []


def test_desktop_unable_to_test_the_token_is_unknown(tmp_path):
    home = _with_desktop(make_home(tmp_path), _desktop_entry())
    result = result_for("service.desktop_auth", _desktop_ctx(home, accepts=None))

    assert result.status == checks.UNKNOWN
    _without_token(result)


def test_the_hook_count_does_not_count_pycache(tmp_path):
    """`__pycache__` aparece en cuanto los hooks se ejecutan una vez, y no es un script.

    No es cosmético: **ese número es justo el que se mira para confirmar que un script retirado
    desapareció** —así se verificó la retirada de `output_policy.py` y compañía en la 0.27.0—, y
    con un directorio de más el check afirmaba lo contrario de lo que había pasado. Medido en la
    máquina real: decía «4 script(s)» donde había 3.
    """
    home = make_home(tmp_path)
    hooks_dir = home / ".claude" / "hooks" / install.HOOKS_SUBDIR
    scripts = sorted(p.name for p in hooks_dir.iterdir() if p.suffix == ".py")

    before = result_for("scaffold.hook_files", make_ctx(home))
    assert before.status == checks.OK
    assert f"{len(scripts)} script(s)" in before.detail, before.detail

    # Lo que hace Python en cuanto el hook corre una vez.
    pycache = hooks_dir / "__pycache__"
    pycache.mkdir()
    (pycache / "hook_common.cpython-311.pyc").write_bytes(b"\x00")

    after = result_for("scaffold.hook_files", make_ctx(home))
    assert after.status == checks.OK
    assert f"{len(scripts)} script(s)" in after.detail, (
        f"el __pycache__ se coló en el conteo: {after.detail}"
    )


def test_the_hook_count_follows_the_real_scripts(tmp_path):
    """Control del test de arriba: sin esto, un conteo clavado a mano lo dejaría en verde.

    Se añade un `.py` en vez de borrar uno porque quitarlo dispararía el `warn` de «faltan
    scripts», que es otro camino y no diría nada del conteo. Y se añade uno que **no** es del
    paquete: reescribir uno de los nuestros ahora es «script de otra versión», también otro camino.
    """
    home = make_home(tmp_path)
    hooks_dir = home / ".claude" / "hooks" / install.HOOKS_SUBDIR
    before = len([p for p in hooks_dir.iterdir() if p.suffix == ".py"])

    (hooks_dir / "my_own_hook.py").write_text("# del usuario", encoding="utf-8")

    result = result_for("scaffold.hook_files", make_ctx(home))
    assert result.status == checks.OK
    assert f"{before + 1} script(s)" in result.detail, result.detail


def test_hooks_from_another_version_are_warn(tmp_path):
    """Los nombres están todos, pero el contenido no es el del paquete instalado.

    Es lo que tuvo la Mac una semana: paquete en 0.31.1 y hooks de la 0.27, y el check en `ok`
    porque solo miraba nombres. `update` no los reponía y la telemetría de F1 nunca llegó a correr.
    """
    home = make_home(tmp_path)
    script = install._READ_HOOK[0]
    (home / ".claude" / "hooks" / install.HOOKS_SUBDIR / script).write_text(
        "# versión anterior\n", encoding="utf-8"
    )
    result = result_for("scaffold.hook_files", make_ctx(home))
    assert result.status == checks.WARN
    assert "otra versión" in result.detail
    assert script in result.detail
    assert result.fix_hint == checks.update_hooks_hint()


def test_a_packaged_script_is_missing_even_if_not_registered(tmp_path):
    """`hook_common.py` no está en `_HOOK_EVENTS`, pero sin él ningún hook arranca."""
    home = make_home(tmp_path)
    (home / ".claude" / "hooks" / install.HOOKS_SUBDIR / "hook_common.py").unlink()
    result = result_for("scaffold.hook_files", make_ctx(home))
    assert result.status == checks.WARN
    assert "hook_common.py" in result.detail


def test_codex_rewritten_by_another_program_is_not_missing(tmp_path):
    """Indentado y sin marcador de cierre, como lo dejó el plugin de JetBrains: Codex lo carga.

    Darlo por ausente no era solo un aviso falso: `update` lo «reparaba» añadiendo otra entrada.
    """
    home = make_home(tmp_path)
    (home / ".codex" / "config.toml").write_text(
        '  # local-delegate:begin\n  [mcp_servers.local-delegate]\n    url = "http://127.0.0.1:9393/mcp"\n\n'
        '  [mcp_servers.pycharm]\n    url = "http://127.0.0.1:64342/sse"\n',
        encoding="utf-8",
    )
    result = result_for("scaffold.mcp_codex", make_ctx(home))
    assert result.status == checks.OK, result.detail
    assert "http" in result.detail
    assert "cierre" in result.detail


def test_indented_codex_without_markers_still_belongs_to_someone_else(tmp_path):
    """Sin el de apertura no es nuestra, con sangría o sin ella: `warn`, y `update` no la pisa."""
    home = make_home(tmp_path)
    (home / ".codex" / "config.toml").write_text(
        '  [mcp_servers.local-delegate]\n    command = "uvx"\n', encoding="utf-8"
    )
    result = result_for("scaffold.mcp_codex", make_ctx(home))
    assert result.status == checks.WARN


# --- T12: config.fallback con `loaded` y el sinónimo obsoleto (REQ-022, REQ-023) ---------------


@pytest.mark.parametrize("obsolete_value", ["residente", "resident", "Residente"])
def test_fallback_with_resident_works_like_loaded_and_warns(
    reload_config, tmp_path, obsolete_value
):
    """`residente,long` sigue valiendo como `loaded,long`, y `doctor` pide renombrarlo."""
    from local_delegate import chains

    reload_config(LOCAL_DELEGATE_FALLBACK_CODE=f"{obsolete_value},long")
    r = checks._probe_fallback(checks.Context(home=tmp_path))

    assert "renombra" in (r.fix_hint or "")
    assert r.status == checks.WARN
    assert "LOCAL_DELEGATE_FALLBACK_CODE" in r.detail
    assert chains.resolve("code").steps == (chains.LOADED, "gemma4-26b-a4b")
    reload_config(LOCAL_DELEGATE_FALLBACK_CODE="loaded,long")
    assert chains.resolve("code").steps == (chains.LOADED, "gemma4-26b-a4b")
    assert checks._probe_fallback(checks.Context(home=tmp_path)).status == checks.OK


def test_fallback_loaded_is_not_valid_name(reload_config, tmp_path):
    """El paso se llama `loaded` (nombres que se teclean, en inglés); `cargado` no se acepta."""
    from local_delegate import chains

    reload_config(LOCAL_DELEGATE_FALLBACK_CODE="cargado,long")
    assert chains.resolve("code").ignored == ("cargado",)
    r = checks._probe_fallback(checks.Context(home=tmp_path))
    assert r.status == checks.WARN
    assert r.fix_hint == "usa roles (mechanical, long, code, loaded) o ids del catálogo de texto"


def test_fallback_with_obsolete_and_unknown_name_warns_both(reload_config, tmp_path):
    """`residente,foo`: los dos avisos en el mismo resultado; arreglar uno no esconde el otro."""
    reload_config(LOCAL_DELEGATE_FALLBACK_CODE="residente,foo")
    r = checks._probe_fallback(checks.Context(home=tmp_path))

    assert r.status == checks.WARN
    assert "foo" in r.detail and "residente" in r.detail
    assert "renombra" in r.fix_hint
    assert "usa roles (mechanical, long, code, loaded)" in r.fix_hint


# --- T13: backend.residency y backend.topology (REQ-036, REQ-002) -------------------------------
RESIDENCY_FIXTURES = Path(__file__).parent / "fixtures" / "residency"
WITH_RESIDENT = b"""models:
  a:
    cmd: llama-server -m MODELOS/a.gguf --port ${PORT}
    ttl: 0
  b:
    cmd: llama-server -m MODELOS/b.gguf --port ${PORT}
    ttl: 120
groups:
  fijo:
    persistent: true
    swap: false
    exclusive: false
    members:
    - a
  swap:
    swap: true
    exclusive: true
    members:
    - b
"""


def _check(id_: str) -> checks.Check:
    (check,) = [c for c in checks.CHECKS if c.id == id_]
    return check


def test_residency_and_topology_are_registered_after_llamaserver():
    ids = [c.id for c in checks.CHECKS]
    assert ids[-3:] == ["backend.llamaserver", "backend.residency", "backend.topology"]
    assert _check("backend.residency").group == _check("backend.topology").group == "backend"


def test_residency_ok_without_resident_with_todays_config(tmp_path):
    r = checks._probe_residency(
        checks.Context(home=tmp_path, config_path=RESIDENCY_FIXTURES / "today.yaml")
    )
    assert r.status == checks.OK
    assert "sin residente" in r.detail


def test_residency_with_a_resident_is_informative_and_says_the_vram(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_bytes(WITH_RESIDENT)
    r = checks._probe_residency(checks.Context(home=tmp_path, config_path=path))
    assert r.status == checks.OK
    assert "residente: a" in r.detail
    assert "VRAM" in r.detail


def test_residency_warns_with_persistent_and_ttl_above_zero(tmp_path):
    """La config del 2026-09-15: grupo `resident` persistent con el 4B a TTL 600."""
    cfg = RESIDENCY_FIXTURES / "pre-b10909-20260915.yaml"
    r = checks._probe_residency(checks.Context(home=tmp_path, config_path=cfg))
    assert r.status == checks.WARN
    assert "gemma3-4b" in r.detail
    assert "persistent" in r.detail
    assert "--none" in (r.fix_hint or "")


def test_residency_without_config_is_unknown(tmp_path):
    r = checks._probe_residency(checks.Context(home=tmp_path))
    assert r.status == checks.UNKNOWN
    assert "sin LLAMASWAP_CONFIG" in r.detail


def test_topology_says_active_turn_with_todays_config(tmp_path):
    r = checks._probe_topology(
        checks.Context(home=tmp_path, config_path=RESIDENCY_FIXTURES / "today.yaml")
    )
    assert r.status == checks.OK
    assert "turno activo" in r.detail


@pytest.mark.parametrize(
    ("content", "reason", "state"),
    [
        (None, "sin LLAMASWAP_CONFIG", checks.UNKNOWN),
        (
            b"models:\n  a:\n    cmd: x --port ${PORT}\nmatrix:\n  sets: {}\n",
            "matrix",
            checks.UNKNOWN,
        ),
        (b"models: [\n  a: : :\n", "ilegible", checks.WARN),
    ],
)
def test_topology_says_why_there_is_no_turn(tmp_path, content, reason, state):
    path = None
    if content is not None:
        path = tmp_path / "config.yaml"
        path.write_bytes(content)
    r = checks._probe_topology(checks.Context(home=tmp_path, config_path=path))
    assert reason in r.detail
    assert r.status == state


def test_topology_with_a_remote_backend_has_no_turn(tmp_path, monkeypatch):
    from local_delegate import config

    monkeypatch.setattr(config, "BASE_URL", "http://otra-maquina:9292/v1")
    r = checks._probe_topology(
        checks.Context(home=tmp_path, config_path=RESIDENCY_FIXTURES / "today.yaml")
    )
    assert r.status == checks.UNKNOWN
    assert "backend remoto" in r.detail


def _daemon_with_turn(config_path: Path):
    """Un daemon simulado: su llama-swap con la config de hoy y su turno activo."""
    return lambda: (
        llamaswap_api.Status(
            llamaswap_api.STATE_OK,
            config_path=str(config_path),
            turn_active=True,
            turn_detail="swap [swap, no exclusivo]: gemma3-4b, gemma4-26b-a4b",
        ),
        "",
    )


def test_topology_and_residency_follow_the_daemon_when_the_shell_has_no_config(tmp_path):
    ctx = checks.Context(
        home=tmp_path,
        config_path=None,
        llamaswap_daemon=_daemon_with_turn(RESIDENCY_FIXTURES / "today.yaml"),
    )
    topology = checks._probe_topology(ctx)
    residency = checks._probe_residency(ctx)
    assert topology.status == checks.OK
    assert "turno activo según el daemon" in topology.detail
    assert residency.status == checks.OK
    assert "la config del daemon" in residency.detail


def test_without_daemon_the_detail_says_it_is_the_shell_config(tmp_path):
    ctx = checks.Context(
        home=tmp_path,
        config_path=RESIDENCY_FIXTURES / "today.yaml",
        llamaswap_daemon=checks.NO_LLAMASWAP_DAEMON,
    )
    assert "según la config de este shell" in checks._probe_topology(ctx).detail
    assert "la config de este shell" in checks._probe_residency(ctx).detail


def test_topology_without_turn_according_to_the_daemon_says_why(tmp_path):
    status = llamaswap_api.Status(
        llamaswap_api.STATE_OK, turn_active=False, turn_reason="dos sintaxis"
    )
    ctx = checks.Context(home=tmp_path, llamaswap_daemon=lambda: (status, ""))
    r = checks._probe_topology(ctx)
    assert r.status == checks.WARN
    assert "sin turno según el daemon: dos sintaxis" in r.detail


# --- Ventanas de prueba (test-windows-out-of-metrics, REQ-019) -----------------------------------


def _probe_windows(tmp_path):
    return checks._probe_test_windows(checks.Context(home=tmp_path / "home", log_dir=tmp_path))


def test_windows_without_file_is_correct(tmp_path):
    r = _probe_windows(tmp_path)
    assert (r.status, r.detail) == (checks.OK, "sin ventanas")


def test_closed_windows_is_correct(tmp_path):
    from local_delegate import test_windows

    test_windows.add(tmp_path, "2026-10-08T01:00:00Z", "2026-10-08T02:00:00Z")
    test_windows.add(tmp_path, "2026-10-08T03:00:00Z", "2026-10-08T04:00:00Z")
    r = _probe_windows(tmp_path)
    assert (r.status, r.detail) == (checks.OK, "2 ventanas, ninguna abierta")


@pytest.mark.parametrize(("hours", "warning"), [(13, True), (1, False)])
def test_a_forgotten_window_warns_with_the_command(tmp_path, hours, warning):
    """D6: más de 12 h abierta. Control: mutante con el umbral en 24 h → falla el caso de 13 h."""
    from datetime import UTC, datetime, timedelta

    from local_delegate import test_windows

    w = test_windows.start(tmp_path, now=datetime.now(UTC) - timedelta(hours=hours))
    r = _probe_windows(tmp_path)
    if warning:
        assert r.status == checks.WARN
        assert w.id in r.detail
        assert r.fix_hint == f"local-delegate test-window stop {w.id}"
    else:
        assert (r.status, r.detail) == (checks.OK, "1 ventanas, 1 abierta(s)")


def test_a_broken_file_warns_with_the_reason(tmp_path):
    from local_delegate import test_windows

    (tmp_path / test_windows.FILE_NAME).write_text("{roto", encoding="utf-8")
    r = _probe_windows(tmp_path)
    assert r.status == checks.WARN and "JSON roto" in r.detail


def test_ignored_entries_are_counted(tmp_path):
    from local_delegate import test_windows

    (tmp_path / test_windows.FILE_NAME).write_text(
        json.dumps({"version": 1, "windows": [{"id": "x"}, {"id": "y", "start": "mal"}]}),
        encoding="utf-8",
    )
    r = _probe_windows(tmp_path)
    assert r.status == checks.WARN and "2 entrada(s) ignorada(s)" in r.detail


# --- config.deprecated_names (REQ-003): alias con sucesor e interruptores viejos ---
def _test_registry(monkeypatch, tmp_path):
    """Un alias de variable y un interruptor viejo de mentira: el registro real aún no tiene."""
    from local_delegate import config, deprecations

    entries = (
        deprecations.DeprecatedName("env_var", "LD_OLD_TEST_VAR", "LD_NEW_FOR_TEST", "0.35.0"),
        deprecations.DeprecatedName(
            "switch_file", "old-test-switch", "old-switch-for-test", "0.35.0"
        ),
    )
    monkeypatch.setattr(deprecations, "DEPRECATED_NAMES", entries)
    monkeypatch.setattr(config, "DEPRECATED_ENV_VALUES", {"LD_OLD_TEST_VAR": None})
    (tmp_path / ".claude").mkdir(exist_ok=True)
    return config


def test_deprecated_names_ok_when_nothing_is_deprecated(monkeypatch, tmp_path):
    _test_registry(monkeypatch, tmp_path)
    assert checks._probe_deprecated_names(checks.Context(home=tmp_path)).status == checks.OK


def test_deprecated_names_warns_shell_alias_with_new_name_and_removal(monkeypatch, tmp_path):
    config = _test_registry(monkeypatch, tmp_path)
    monkeypatch.setitem(config.DEPRECATED_ENV_VALUES, "LD_OLD_TEST_VAR", "1")
    r = checks._probe_deprecated_names(checks.Context(home=tmp_path))
    assert r.status == checks.WARN
    assert "LD_OLD_TEST_VAR" in r.detail and "LD_NEW_FOR_TEST" in r.detail
    assert "0.38.0" in r.detail, "el aviso no nombra la versión de retirada"
    assert "renombra LD_OLD_TEST_VAR a LD_NEW_FOR_TEST" in r.fix_hint


def test_deprecated_names_warns_alias_in_settings_json_env(monkeypatch, tmp_path):
    _test_registry(monkeypatch, tmp_path)
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"env": {"LD_OLD_TEST_VAR": "1"}}), encoding="utf-8"
    )
    r = checks._probe_deprecated_names(checks.Context(home=tmp_path))
    assert r.status == checks.WARN
    assert "settings.json" in r.detail and "LD_OLD_TEST_VAR" in r.detail


def test_deprecated_names_warns_old_switch_file_left_on_disk(monkeypatch, tmp_path):
    _test_registry(monkeypatch, tmp_path)
    (tmp_path / ".claude" / "old-test-switch").write_text("", encoding="utf-8")
    r = checks._probe_deprecated_names(checks.Context(home=tmp_path))
    assert r.status == checks.WARN
    assert "old-test-switch" in r.detail and "old-switch-for-test" in r.detail


def test_deprecated_names_survives_unreadable_settings_json(monkeypatch, tmp_path):
    _test_registry(monkeypatch, tmp_path)
    (tmp_path / ".claude" / "settings.json").write_text("{no es json", encoding="utf-8")
    assert checks._probe_deprecated_names(checks.Context(home=tmp_path)).status == checks.OK


# --- config.deprecated_names con retirados con sucesor (REQ-012, registro sintético) ---
_RETIRED_ENV = ("LD_OLD_GONE_TEST_VAR", "LD_GONE_FOR_TEST")
_RETIRED_SWITCH = ("old-gone-test-switch", "gone-switch-for-test")


def _retired_registry(monkeypatch, tmp_path, telemetry=None):
    """Un retirado con sucesor por superficie (variable e interruptor), telemetría y HOME aislados."""
    from local_delegate import config, deprecations

    entries = (
        deprecations.DeprecatedName(
            "retired", *_RETIRED_ENV, "0.38.0", "0.40.0", retired_from="env_var"
        ),
        deprecations.DeprecatedName(
            "retired", *_RETIRED_SWITCH, "0.38.0", "0.40.0", retired_from="switch_file"
        ),
    )
    monkeypatch.setattr(deprecations, "DEPRECATED_NAMES", entries)
    monkeypatch.setattr(config, "DEPRECATED_ENV_VALUES", {_RETIRED_ENV[0]: None})
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", telemetry)
    (tmp_path / ".claude").mkdir(exist_ok=True)
    return config


def _assert_retired_warning(result, old, new):
    assert result.status == checks.WARN
    assert old in result.detail and new in result.detail
    assert "ya no tiene efecto desde la 0.38.0" in result.detail
    assert f"renombra {old} a {new}" in result.fix_hint
    assert "quita" not in result.fix_hint.lower()


def test_retired_renamed_ok_when_nothing_is_set(monkeypatch, tmp_path):
    _retired_registry(monkeypatch, tmp_path)
    assert checks._probe_deprecated_names(checks.Context(home=tmp_path)).status == checks.OK


def test_retired_renamed_in_the_shell_warns_with_rename(monkeypatch, tmp_path):
    config = _retired_registry(monkeypatch, tmp_path)
    monkeypatch.setitem(config.DEPRECATED_ENV_VALUES, _RETIRED_ENV[0], "1")
    r = checks._probe_deprecated_names(checks.Context(home=tmp_path))
    _assert_retired_warning(r, *_RETIRED_ENV)


def test_retired_renamed_in_settings_json_env_warns_with_rename(monkeypatch, tmp_path):
    _retired_registry(monkeypatch, tmp_path)
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"env": {_RETIRED_ENV[0]: "1"}}), encoding="utf-8"
    )
    r = checks._probe_deprecated_names(checks.Context(home=tmp_path))
    _assert_retired_warning(r, *_RETIRED_ENV)
    assert "settings.json" in r.detail


def test_retired_switch_file_left_on_disk_warns_with_rename(monkeypatch, tmp_path):
    _retired_registry(monkeypatch, tmp_path)
    (tmp_path / ".claude" / _RETIRED_SWITCH[0]).write_text("", encoding="utf-8")
    r = checks._probe_deprecated_names(checks.Context(home=tmp_path))
    _assert_retired_warning(r, *_RETIRED_SWITCH)


def test_retired_renamed_read_by_hooks_warns_with_rename(monkeypatch, tmp_path):
    from datetime import UTC, datetime

    log = tmp_path / "telemetry.jsonl"
    event = {"ts": datetime.now(UTC).isoformat(), "deprecated_names": [_RETIRED_ENV[0]]}
    log.write_text(json.dumps(event) + "\n", encoding="utf-8")
    _retired_registry(monkeypatch, tmp_path, telemetry=log)
    r = checks._probe_deprecated_names(checks.Context(home=tmp_path))
    _assert_retired_warning(r, *_RETIRED_ENV)
