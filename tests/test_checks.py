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
    por haber instalado unos hooks. Los colaboradores revientan el test si alguien los llama.
    """

    def _prohibido(*_a, **_kw):
        raise AssertionError("el reporte del andamiaje no debe salir a la red ni lanzar binarios")

    home = make_home(tmp_path, complete=False)
    ctx = make_ctx(home, daemon_status=_prohibido, backend_models=_prohibido, version_of=_prohibido)

    results = checks.run_all(ctx, groups=("entorno", "andamiaje"))

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
    ctx = make_ctx(make_home(tmp_path))
    for check, result in checks.run_all(ctx):
        assert result.status == checks.OK, f"{check.id}: {result.detail}"


# --- HOME vacío: missing con pista, nunca sin explicación ----------------------


def test_empty_home_reports_missing_with_fix_hint(tmp_path):
    ctx = make_ctx(make_home(tmp_path, complete=False))
    scaffold = [
        (check, result)
        for check, result in checks.run_all(ctx)
        if check.group == "andamiaje" and check.id != "scaffold.memory"
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


# --- Ningún probe escribe (REQ-013 a nivel de registro) -----------------------


def test_no_probe_writes_anything(tmp_path):
    home = make_home(tmp_path)
    before = snapshot(home)
    checks.run_all(make_ctx(home))
    assert snapshot(home) == before


# --- El módulo no puede mentir sobre su propio tamaño ------------------------

_NUMERO = {10: "diez", 11: "once", 12: "doce", 13: "trece", 14: "catorce"}


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
