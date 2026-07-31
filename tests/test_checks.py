"""Tests del registro de comprobaciones (checks.py).

Ningún test sale a la red ni lanza procesos: los tres colaboradores del `Context` se inyectan
y el HOME es siempre un `tmp_path`. Lo que más se vigila aquí no es que un check diga «ok»,
sino que **nunca diga `missing` cuando en realidad no pudo comprobar**: ese falso `missing`
es el que llevaría a un `fix` posterior a sobrescribir configuración ajena.
"""

from __future__ import annotations

import json
import sys

import pytest
from conftest import make_home, snapshot

from local_delegate import checks, doctor, install


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
        "backend_models": lambda: (True, ""),
        "version_of": lambda component, cfg: (doctor.RECOMMENDED_VERSIONS[component], None),
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
    }
    defaults.update(kwargs)
    return checks.Context(home=home, **defaults)


def result_for(check_id, ctx):
    return {check.id: result for check, result in checks.run_all(ctx)}[check_id]


# --- Estructura del registro --------------------------------------------------


def test_registry_ids_are_unique_and_groups_are_known():
    assert len({check.id for check in checks.CHECKS}) == len(checks.CHECKS)
    assert {check.group for check in checks.CHECKS} == {
        "entorno",
        "andamiaje",
        "servicio",
        "backend",
    }


def test_filtrar_por_grupo_no_toca_la_red_ni_el_backend(tmp_path):
    """`install` reporta el andamiaje que acaba de escribir, y solo eso.

    Correr también `servicio` y `backend` saldría a la red y lanzaría los binarios de llama-swap
    por haber instalado unos hooks.

    Los colaboradores **anotan** que se les llamó en vez de lanzar: `run_all` captura las
    excepciones de los probes (un check roto no debe ocultar los otros doce), así que un
    `raise` a secas se tragaría en silencio y el test pasaría con la red ya tocada.

    `latest_release` **no** entra aquí, y el motivo importa: `cli.published` vive en el grupo
    `entorno`, así que el filtro no lo excluye ni debe hacerlo. A ese lo frena `SKIP_PYPI`, que
    es otro mecanismo y se prueba en su propio sitio —
    `test_install_clients.py::test_install_no_consulta_pypi_al_reportar_el_andamiaje`.
    """
    llamados: list[str] = []

    def _anota(nombre):
        def _colaborador(*_a, **_kw):
            llamados.append(nombre)
            raise AssertionError(f"{nombre} no debe correr en el reporte del andamiaje")

        return _colaborador

    home = make_home(tmp_path, complete=False)
    ctx = make_ctx(
        home,
        daemon_status=_anota("daemon_status"),
        backend_models=_anota("backend_models"),
        version_of=_anota("version_of"),
    )

    results = checks.run_all(ctx, groups=("entorno", "andamiaje"))

    assert llamados == [], f"el reporte del andamiaje salió a la red: {llamados}"
    esperados = [c.id for c in checks.CHECKS if c.group in ("entorno", "andamiaje")]
    assert [check.id for check, _r in results] == esperados
    assert len(results) < len(checks.CHECKS)


def test_sin_filtro_run_all_se_comporta_igual_que_siempre(tmp_path):
    ctx = make_ctx(make_home(tmp_path, complete=False))
    assert len(checks.run_all(ctx)) == len(checks.CHECKS)
    assert checks.run_all(ctx, groups=None) == checks.run_all(ctx)


# --- El CLI tiene que existir como comando -----------------------------------


def test_cli_missing_from_path_is_reported_with_the_command_that_fixes_it(tmp_path, monkeypatch):
    """Instalar con `uvx` deja el andamiaje puesto y el comando inexistente."""
    monkeypatch.setattr(checks.shutil, "which", lambda name: None)
    result = result_for("cli.path", make_ctx(make_home(tmp_path)))
    assert result.status == checks.MISSING
    assert result.fix_hint == checks.CLI_HINT
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


def _publicada(tmp_path, monkeypatch, instalada, ultima, motivo=None):
    """Resultado de `cli.published` con las dos versiones forzadas."""
    monkeypatch.setattr(checks, "_installed_version", lambda: instalada)
    ctx = make_ctx(make_home(tmp_path), latest_release=lambda: (ultima, motivo))
    return result_for("cli.published", ctx)


def test_instalacion_atrasada_avisa_con_el_comando_que_la_actualiza(tmp_path, monkeypatch):
    result = _publicada(tmp_path, monkeypatch, "0.16.0", "0.17.0")
    assert result.status == checks.WARN
    assert "0.16.0" in result.detail and "0.17.0" in result.detail
    assert result.fix_hint


def test_instalacion_al_dia_es_ok(tmp_path, monkeypatch):
    result = _publicada(tmp_path, monkeypatch, "0.17.0", "0.17.0")
    assert result.status == checks.OK
    assert not checks.is_warning(result.status)


def test_repo_por_delante_de_lo_publicado_es_ok(tmp_path, monkeypatch):
    """Lo normal mientras se trabaja: el repo lleva el bump y PyPI todavía no."""
    result = _publicada(tmp_path, monkeypatch, "0.18.0", "0.17.0")
    assert result.status == checks.OK
    assert "por delante" in result.detail


def test_las_versiones_se_comparan_como_numeros_y_no_como_texto(tmp_path, monkeypatch):
    """Comparadas como texto, `"0.9.0" > "0.11.0"`. Si alguien compara strings, esto lo caza."""
    result = _publicada(tmp_path, monkeypatch, "0.9.0", "0.11.0")
    assert result.status == checks.WARN


@pytest.mark.parametrize(("instalada", "ultima"), [("0.17", "0.17.0"), ("0.17.0", "0.17")])
def test_una_version_mas_corta_no_inventa_una_actualizacion(
    tmp_path, monkeypatch, instalada, ultima
):
    """`0.17` y `0.17.0` son la misma: sin rellenar a la misma longitud, una saldría menor."""
    assert _publicada(tmp_path, monkeypatch, instalada, ultima).status == checks.OK


def test_sin_red_no_se_puede_comparar_y_eso_no_es_una_falta(tmp_path, monkeypatch):
    """`unknown`, nunca `missing`: no saber la última publicada no es que falte nada."""
    result = _publicada(tmp_path, monkeypatch, "0.17.0", None, "no se pudo consultar PyPI (…)")
    assert result.status == checks.UNKNOWN
    assert not checks.is_warning(result.status)
    assert "PyPI" in result.detail


def test_sin_version_instalada_tampoco_se_compara(tmp_path, monkeypatch):
    result = _publicada(tmp_path, monkeypatch, None, "0.17.0")
    assert result.status == checks.UNKNOWN


def test_una_consulta_que_revienta_no_tumba_el_diagnostico(tmp_path, monkeypatch):
    """El diagnóstico se ejecuta justo cuando algo va mal; no puede caerse por un dato accesorio."""

    def _revienta():
        raise RuntimeError("boom")

    results = checks.run_all(make_ctx(make_home(tmp_path), latest_release=_revienta))
    assert len(results) == len(checks.CHECKS)
    por_id = {check.id: result for check, result in results}
    assert por_id["cli.published"].status == checks.UNKNOWN


# --- Hooks huérfanos de instalaciones anteriores ------------------------------
# Las versiones viejas dejaban los scripts sueltos en `~/.claude/hooks/`; la actual los pone en
# `hooks/local-delegate/` y nunca limpiaba los otros. Esta máquina los tenía: cuatro.


def _con_huerfanos(home, *nombres):
    raiz = home / ".claude" / "hooks"
    raiz.mkdir(parents=True, exist_ok=True)
    for nombre in nombres:
        (raiz / nombre).write_text("# viejo\n", encoding="utf-8")
    return raiz


def test_los_huerfanos_se_reportan_con_su_numero_y_su_sitio(tmp_path):
    home = make_home(tmp_path)
    raiz = _con_huerfanos(home, "hook_common.py", "suggest_lint_summary.py")
    result = result_for("scaffold.hook_orphans", make_ctx(home))
    assert result.status == checks.WARN
    assert "2 script(s)" in result.detail
    assert str(raiz) in result.detail
    assert result.fix_hint == checks.INSTALL_HINT


def test_la_instalacion_buena_no_se_reporta_como_huerfana(tmp_path):
    """El fallo peor posible de este check, y está a un identificador de distancia.

    `ctx.hooks_dir` **ya es** `hooks/local-delegate/`. Un probe que mirara ahí reportaría como
    huérfanos los scripts recién instalados, e `install` los borraría acto seguido: la máquina se
    quedaría sin hooks y en bucle.
    """
    home = make_home(tmp_path, complete=True)
    assert list(make_ctx(home).hooks_dir.iterdir()), "el HOME completo debe traer los hooks buenos"
    assert result_for("scaffold.hook_orphans", make_ctx(home)).status == checks.OK


def test_un_fichero_ajeno_en_la_raiz_no_cuenta_como_huerfano(tmp_path):
    home = make_home(tmp_path)
    _con_huerfanos(home, "hook_de_terceros.py", "telemetry.jsonl")
    assert result_for("scaffold.hook_orphans", make_ctx(home)).status == checks.OK


def test_sin_claude_no_se_afirma_nada_sobre_huerfanos(tmp_path):
    home = make_home(tmp_path, claude=False, codex=True, complete=False)
    assert result_for("scaffold.hook_orphans", make_ctx(home)).status == checks.UNKNOWN


def test_la_pista_depende_de_como_este_instalado(tmp_path, monkeypatch):
    """Los tres comandos no son intercambiables, y darle el que no toca es un consejo que falla.

    En una editable `uv tool upgrade` no actualiza nada —el código sale del repo— y a quien
    instaló con `pip` mandarlo a `uv tool` lo deja igual que estaba. La decisión de cuál es cuál
    vive en `update.install_kind`, en un solo sitio.
    """
    from local_delegate import update

    def pista(modo, carpeta):
        monkeypatch.setattr(update, "install_kind", lambda: modo)
        return _publicada(tmp_path / carpeta, monkeypatch, "0.16.0", "0.17.0").fix_hint

    assert pista(update.UV_TOOL, "a") == update.UV_TOOL_UPGRADE

    monkeypatch.setattr(update, "editable_origin", lambda: tmp_path / "repo")
    hint = pista(update.EDITABLE, "b")
    assert "git -C" in hint and "uv sync" in hint

    assert pista(update.OTHER, "c") == update.GENERIC_UPGRADE


def test_el_detalle_y_la_pista_caben_en_la_consola_de_windows(tmp_path, monkeypatch):
    """Una flecha `→` mata el doctor con UnicodeEncodeError en la consola cp1252."""
    result = _publicada(tmp_path, monkeypatch, "0.16.0", "0.17.0")
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
    assert result.fix_hint == checks.RESTART_HINT


def test_daemon_mas_nuevo_que_lo_instalado_manda_actualizar_no_reiniciar(tmp_path, monkeypatch):
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
    assert result.fix_hint != checks.RESTART_HINT


def test_las_versiones_del_daemon_se_comparan_como_numeros_no_como_texto(tmp_path, monkeypatch):
    """Comparadas como texto, `"0.9.0" > "0.18.0"`. El daemon aquí es el VIEJO."""
    monkeypatch.setattr(checks, "_installed_version", lambda: "0.18.0")
    ctx = make_ctx(
        make_home(tmp_path),
        daemon_status=lambda host, port: {"version": "0.9.0", "pid": 42, "mcp_url": "u"},
    )
    result = result_for("service.daemon", ctx)
    assert result.fix_hint == checks.RESTART_HINT
    assert "el daemon sirve la vieja" in result.detail


def test_versiones_del_daemon_incomparables_avisan_sin_ofrecer_arreglo(tmp_path, monkeypatch):
    """Sin poder ordenarlas, cualquier arreglo que se sugiriera podría ser el equivocado."""
    monkeypatch.setattr(checks, "_installed_version", lambda: "0.18.0")
    ctx = make_ctx(
        make_home(tmp_path),
        daemon_status=lambda host, port: {"version": "vete-a-saber", "pid": 42, "mcp_url": "u"},
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
    def explota(_ctx):
        raise RuntimeError("boom")

    roto = checks.Check("test.roto", "cliente", "roto", explota)
    monkeypatch.setattr(checks, "CHECKS", (roto,) + checks.CHECKS)
    results = dict(checks.run_all(make_ctx(make_home(tmp_path))))
    assert results[roto].status == checks.UNKNOWN
    assert "boom" in results[roto].detail


# --- HOME completo: todo ok ---------------------------------------------------


def test_complete_home_is_all_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(checks.shutil, "which", lambda name: "/usr/local/bin/local-delegate")
    # `client.observed` hay que alimentarlo aparte: su registro **no vive en el HOME** —está en
    # `LOG_DIR`—, así que un HOME completo no lo pone `ok` por sí solo. Se le da una observación en
    # vez de excluirlo del test, para que aquí también se le exija estar `ok`.
    ctx = make_ctx(make_home(tmp_path), clients_seen=lambda: ([CLAUDE], None))
    for check, result in checks.run_all(ctx):
        assert result.status == checks.OK, f"{check.id}: {result.detail}"


# --- HOME vacío: missing con pista, nunca sin explicación ----------------------


def test_empty_home_reports_missing_with_fix_hint(tmp_path):
    # `scaffold.memory` queda fuera porque agrega dos clientes, y `scaffold.hook_orphans` porque
    # **nunca** puede ser `missing`: pregunta si SOBRA algo, no si falta. En un HOME vacío la
    # respuesta correcta es `ok` — no hay huérfanos que retirar.
    aparte = {"scaffold.memory", "scaffold.hook_orphans"}
    ctx = make_ctx(make_home(tmp_path, complete=False))
    scaffold = [
        (check, result)
        for check, result in checks.run_all(ctx)
        if check.group == "andamiaje" and check.id not in aparte
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
    ctx = make_ctx(make_home(tmp_path, claude=False, codex=False))
    for check, result in checks.run_all(ctx):
        if check.group == "andamiaje":
            assert result.status == checks.UNKNOWN, f"{check.id}: {result.detail}"
    assert result_for("client.presence", ctx).status == checks.UNKNOWN


def test_only_codex_installed_leaves_claude_checks_unknown(tmp_path):
    ctx = make_ctx(make_home(tmp_path, claude=False))
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

    def denegado(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("pathlib.Path.read_text", denegado)
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
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"otro": {}}}), encoding="utf-8")
    result = result_for("scaffold.mcp_claude", make_ctx(home))
    assert result.status == checks.MISSING
    assert result.fix_hint == checks.INSTALL_HINT


# --- Credencial del backend por el camino del cliente -------------------------
# El check nace de una avería que ningún otro veía: entradas MCP en `stdio`, el secreto solo en el
# lanzador del daemon y todas las tools `local_*` devolviendo 401 mientras `doctor` daba todo OK.


def _con_stdio(home):
    """Deja la entrada de Claude Code en modo stdio, como la escribe `install` por defecto."""
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {install.SERVER_NAME: {"type": "stdio", "command": "uvx"}}}),
        encoding="utf-8",
    )
    return home


def test_credencial_ok_cuando_el_backend_no_exige_key(tmp_path, monkeypatch):
    """Sin credencial de por medio, el modo de la entrada MCP no cambia nada."""
    monkeypatch.setattr(checks.config, "API_KEY", "")
    ctx = make_ctx(_con_stdio(make_home(tmp_path)), backend_needs_key=lambda: (False, ""))
    assert result_for("service.credential", ctx).status == checks.OK


def test_credencial_ok_cuando_las_entradas_van_por_el_daemon(tmp_path, monkeypatch):
    """Mismo backend que el test de abajo: lo único que cambia es el modo de la entrada.

    Los dos tests son pareja a propósito. Un probe que mirase solo el backend —y no el modo—
    pasaría este y fallaría el siguiente; uno que mirase solo el modo, al revés. Separados, ninguna
    de las dos mitades puede aprobar por la guarda de la otra.
    """
    monkeypatch.setattr(checks.config, "API_KEY", "")
    ctx = make_ctx(make_home(tmp_path), backend_needs_key=lambda: (True, ""))  # http
    assert result_for("service.credential", ctx).status == checks.OK


def test_credencial_warn_cuando_el_cliente_habla_por_stdio_sin_key(tmp_path, monkeypatch):
    monkeypatch.setattr(checks.config, "API_KEY", "")
    ctx = make_ctx(_con_stdio(make_home(tmp_path)), backend_needs_key=lambda: (True, ""))
    result = result_for("service.credential", ctx)
    assert result.status == checks.WARN
    assert "Claude Code" in result.detail and "401" in result.detail
    assert result.fix_hint == checks.CREDENTIAL_HINT


def test_credencial_ok_si_la_key_esta_en_el_entorno(tmp_path, monkeypatch):
    """Con la variable cargada, la entrada stdio la hereda y el 401 no llega a pasar."""
    monkeypatch.setattr(checks.config, "API_KEY", "secreto-de-mentira")
    ctx = make_ctx(_con_stdio(make_home(tmp_path)), backend_needs_key=lambda: (True, ""))
    assert result_for("service.credential", ctx).status == checks.OK


def test_credencial_unknown_si_no_se_pudo_preguntar(tmp_path):
    """Sin respuesta del backend no hay veredicto: lo no comprobable es `unknown`, nunca `missing`."""
    ctx = make_ctx(_con_stdio(make_home(tmp_path)), backend_needs_key=checks.NO_KEY_PROBE)
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
    assert result.fix_hint == checks.SERVE_HINT


def test_port_taken_by_another_process_is_warn_not_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(checks, "_port_taken", lambda host, port: True)
    ctx = make_ctx(make_home(tmp_path), daemon_status=lambda host, port: None)
    result = result_for("service.daemon", ctx)
    assert result.status == checks.WARN
    assert "no es nuestro daemon" in result.detail


def test_backend_down_is_warn(tmp_path):
    ctx = make_ctx(
        make_home(tmp_path), backend_models=lambda: (False, "no responde (ConnectError)")
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
        backend_models=lambda: (False, "responde 401: está arriba pero rechaza la credencial"),
    )
    result = result_for("service.backend", ctx)
    assert result.status == checks.UNKNOWN
    assert not checks.is_warning(result.status)
    assert "401" in result.detail


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


def observando(tmp_path, observaciones, motivo=None):
    return make_ctx(make_home(tmp_path), clients_seen=lambda: (observaciones, motivo))


def test_sin_clientes_vistos_es_unknown_y_no_suma_aviso(tmp_path):
    """El caso de HOY: `clients.py` está sin publicar, así que no hay registro en ninguna máquina.

    Tiene que ser `unknown` y no `missing`: no falta nada que instalar, simplemente todavía no ha
    hablado nadie. Un `missing` mandaría a arreglar una máquina sana.
    """
    result = result_for("client.observed", observando(tmp_path, []))
    assert result.status == checks.UNKNOWN
    assert not checks.is_warning(result.status)
    assert "todavía no ha hablado ningún cliente" in result.detail


def test_registro_ilegible_es_unknown_con_el_motivo(tmp_path):
    result = result_for("client.observed", observando(tmp_path, [], "no se pudo leer X: denegado"))
    assert result.status == checks.UNKNOWN
    assert "no se pudo leer X: denegado" in result.detail


def test_un_cliente_que_sabe_preguntar_sale_ok(tmp_path):
    result = result_for("client.observed", observando(tmp_path, [CLAUDE]))
    assert result.status == checks.OK
    assert "claude-code 2.1.220 [2025-11-25] elicitation" in result.detail


def test_un_cliente_sin_elicitation_sigue_siendo_ok(tmp_path):
    """La decisión de diseño del change, y por eso tiene test propio.

    Un cliente sin `elicitation` es información, no un defecto: no hay comando del repo que lo
    arregle y marcarlo como aviso subiría el exit code de una máquina sana.
    """
    mudo = {**CODEX, "client": "cliente-mudo", "caps": []}
    result = result_for("client.observed", observando(tmp_path, [CLAUDE, mudo]))
    assert result.status == checks.OK
    assert not checks.is_warning(result.status)
    assert "cliente-mudo 0.146.0 [2025-06-18] sin elicitation" in result.detail
    assert "claude-code 2.1.220 [2025-11-25] elicitation" in result.detail


def test_el_mismo_cliente_repetido_sale_una_vez_con_la_version_mas_reciente(tmp_path):
    """`clients.jsonl` acumula una línea por ARRANQUE de proceso: medido, no supuesto.

    La deduplicación de `clients.registrar` es intra-proceso, así que veinte lanzamientos de
    Claude Code dejan veinte líneas idénticas. Sin agrupar, el detail sería una lista repetida.

    La observación vieja va **la última** de la lista a propósito: si el check se quedara con la
    última que ve en vez de con la más reciente por `ts`, este test pasaría igual. Con ella al
    final, «agrupa por nombre» y «escoge la más reciente» quedan cubiertos por separado — puesta al
    principio, la segunda mitad no se probaba (comprobado introduciendo el defecto).
    """
    vieja = {**CLAUDE, "ts": "2026-07-01T09:00:00+00:00", "version": "2.1.219"}
    result = result_for("client.observed", observando(tmp_path, [CLAUDE] * 20 + [vieja]))
    assert result.detail.count("claude-code") == 1  # agrupa
    assert "2.1.220" in result.detail  # y se queda con la más reciente
    assert "2.1.219" not in result.detail


def test_una_observacion_sin_identidad_no_se_pierde(tmp_path):
    """Desde la revisión 2026-07-28 el `client_info` es opcional: hay capabilities sin nombre."""
    anonimo = {"ts": CODEX["ts"], "client": None, "protocol": "2026-07-28", "caps": ["elicitation"]}
    result = result_for("client.observed", observando(tmp_path, [anonimo]))
    assert result.status == checks.OK
    assert "(sin identificar) [2026-07-28] elicitation" in result.detail


def test_caps_que_no_es_lista_no_cuenta_como_elicitation(tmp_path):
    """El falso positivo por subcadena que cazó la revisión adversarial del plan.

    Con `caps` llegando como la cadena "no-elicitation", un `in` sin comprobar el tipo daría True
    y el check afirmaría justo lo contrario de la verdad.
    """
    sucio = {**CLAUDE, "caps": "no-elicitation"}
    result = result_for("client.observed", observando(tmp_path, [sucio]))
    assert "sin elicitation" in result.detail


def test_un_ts_ilegible_no_tumba_el_check(tmp_path):
    """Una fecha rota debe perder la carrera de «la más reciente», no llevarse el check por delante."""
    roto = {**CLAUDE, "ts": "ayer por la tarde", "version": "0.0.1"}
    result = result_for("client.observed", observando(tmp_path, [roto, CLAUDE]))
    assert result.status == checks.OK
    assert "2.1.220" in result.detail


def test_el_detail_es_imprimible_en_la_consola_de_windows(tmp_path):
    """El nombre lo pone el CLIENTE: es texto ajeno y puede traer lo que sea.

    Una flecha «→» ya mató este doctor una vez. Aquí el dato ni siquiera lo controla el repo.
    """
    exotico = {**CLAUDE, "client": "cliente-\U0001f600", "version": "1.0—beta"}
    result = result_for("client.observed", observando(tmp_path, [exotico]))
    result.detail.encode("cp1252")  # si no es codificable, esto lanza y el test falla


def test_client_observed_no_ofrece_arreglo(tmp_path):
    """Sin `fix_hint` a propósito: no existe comando de este repo que cambie con quién hablas."""
    home = make_home(tmp_path)
    for observaciones in ([], [CLAUDE]):
        ctx = make_ctx(home, clients_seen=lambda obs=observaciones: (obs, None))
        assert result_for("client.observed", ctx).fix_hint == ""


# --- El colaborador por defecto, que sí toca el disco -------------------------


def test_default_sin_fichero_no_es_un_error(tmp_path, monkeypatch):
    monkeypatch.setattr(checks.config, "LOG_DIR", tmp_path)
    assert checks._default_clients_seen() == ([], None)


def test_default_lee_el_registro_y_salta_lo_que_no_sirve(tmp_path, monkeypatch):
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
    observaciones, motivo = checks._default_clients_seen()
    assert motivo is None
    assert [o["client"] for o in observaciones] == ["claude-code", "codex-mcp-client"]


def test_default_no_crea_ni_el_directorio_ni_el_fichero(tmp_path, monkeypatch):
    """`probe` nunca escribe, y eso incluye no materializar el sitio donde iría el registro."""
    destino = tmp_path / "sin-crear"
    monkeypatch.setattr(checks.config, "LOG_DIR", destino)
    checks._default_clients_seen()
    assert not destino.exists()


# --- Ningún probe escribe (REQ-013 a nivel de registro) -----------------------


def test_no_probe_writes_anything(tmp_path):
    home = make_home(tmp_path)
    before = snapshot(home)
    checks.run_all(make_ctx(home))
    assert snapshot(home) == before


# --- El módulo no puede mentir sobre su propio tamaño ------------------------

_NUMERO = {
    10: "diez",
    11: "once",
    12: "doce",
    13: "trece",
    14: "catorce",
    15: "quince",
    16: "dieciséis",
}


def test_el_docstring_dice_cuantos_checks_hay_de_verdad():
    """El registro dice su tamaño en cuatro sitios, y llegó a decir «once» con doce dentro.

    `cli.path` entró en el PR #61 y nadie actualizó el texto, así que durante dos sesiones el
    módulo afirmaba un número falso sobre sí mismo — y se llegó a planificar sobre ese dato.
    Un comentario no es evidencia, salvo que algo lo obligue a serlo: esto lo obliga.
    """
    from pathlib import Path

    cuantos = _NUMERO[len(checks.CHECKS)]
    fuente = Path(checks.__file__).read_text(encoding="utf-8")

    afirmaciones = (
        f"los {cuantos} elementos del andamiaje",
        f"{cuantos.capitalize()} checks son una tupla",
        f"{cuantos.capitalize()} elementos, en orden de grupo",
        f"Corre los {cuantos} probes",
        f"ver los otros {_NUMERO[len(checks.CHECKS) - 1]}",
    )
    faltan = [texto for texto in afirmaciones if texto not in fuente]
    assert not faltan, f"el docstring de checks.py quedó desfasado: {faltan}"
