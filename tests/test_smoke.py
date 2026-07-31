"""Smoke tests: el paquete importa, registra sus 11 tools y su config está desacoplada."""

from __future__ import annotations

import asyncio

from local_delegate import config, server

EXPECTED_TOOLS = {
    "local_summarize",
    "local_classify",
    "local_extract",
    "local_boilerplate",
    "local_delegate",
    "local_lint_summary",
    "local_commit_msg",
    "local_translate",
    "local_explain_code",
    "local_status",
    "local_describe_image",
}


def test_eleven_tools_registered():
    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS
    assert len(tools) == 11


def test_la_tabla_de_la_skill_no_puede_mentir_sobre_las_tools():
    """La skill es la fuente del catálogo que `install --agents` propaga a los subagentes.

    Sin este test, esa fuente puede desincronizarse **igual que se desincronizó la receta que
    sustituye** (decía «10 tools» habiendo once). Y la comparación es de conjuntos iguales, no
    de inclusión: una fila sobrante sería una tool retirada del servidor que se sigue anunciando
    al usuario, y que `--agents` propagaría a todos sus agentes.
    """
    from local_delegate import agents, install

    skill_md = install.resources_dir() / "skills" / install.SKILL_NAME / "SKILL.md"
    assert {name for name, _what in agents.tool_catalog(skill_md)} == EXPECTED_TOOLS


def test_config_defaults():
    assert config.BASE_URL == "http://127.0.0.1:9292/v1"


def test_backend_auth_headers(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "")
    assert config.auth_headers() == {}
    monkeypatch.setattr(config, "API_KEY", "secret-value")
    assert config.auth_headers() == {"Authorization": "Bearer secret-value"}


def test_config_defaults_without_user_environment(monkeypatch):
    monkeypatch.delenv("LOCAL_DELEGATE_AUTOSTART", raising=False)
    monkeypatch.delenv("LOCAL_DELEGATE_WEB", raising=False)
    monkeypatch.delenv("LOCAL_DELEGATE_MAX_CONCURRENT_REQUESTS", raising=False)
    assert config._env_flag("LOCAL_DELEGATE_AUTOSTART", False) is False
    assert config._env_flag("LOCAL_DELEGATE_WEB", True) is True
    assert config._env_int("LOCAL_DELEGATE_MAX_CONCURRENT_REQUESTS", 2) == 2
    # el log vive en el dir de datos de usuario, no en una ruta de máquina concreta
    assert config.USAGE_LOG.name == "usage.jsonl"


def test_allowed_models_derived_from_roles():
    assert config.MODEL_MECHANICAL in config.ALLOWED_MODELS
    assert config.MODEL_CODE in config.ALLOWED_MODELS


def test_dashboard_html_present():
    from local_delegate.web import metrics

    assert metrics.HTML.lstrip().startswith("<!doctype html>")
    assert "<script>" in metrics.HTML


# --- F7: main() delega a los subcomandos CLI opt-in sin arrancar el servidor MCP -------
def test_main_dispatches_known_cli_subcommand(monkeypatch):
    import sys

    from local_delegate import cli

    calls = []
    monkeypatch.setattr(cli, "run", lambda argv: calls.append(argv) or 42)
    monkeypatch.setattr(sys, "argv", ["local-delegate", "check-llamaswap", "--config", "x"])
    try:
        server.main()
    except SystemExit as e:
        assert e.code == 42
    else:  # pragma: no cover - main() debe salir con sys.exit
        raise AssertionError("se esperaba SystemExit")
    assert calls == [["check-llamaswap", "--config", "x"]]


# --- El binario responde a --help en vez de arrancar el servidor MCP -------------------
# Todo esto existe porque `local-delegate --help` no imprimía nada y se colgaba: `--help` no
# estaba en la lista literal de subcomandos que decidía el despacho, así que caía al servidor
# MCP stdio a esperar por stdin. Los cuatro primeros tests clavan la frontera nueva; el quinto,
# que sin argumentos NO se toca (es como lanzan el binario los hosts MCP).
def _run_main(monkeypatch, argv: list[str]) -> int:
    """Ejecuta main() con ese argv y devuelve el código de salida."""
    import sys

    monkeypatch.setattr(sys, "argv", ["local-delegate", *argv])
    try:
        server.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def test_help_imprime_la_ayuda_y_no_arranca_el_servidor(monkeypatch, capsys):
    from local_delegate import server as srv

    def _no_arrancar():  # pragma: no cover - si se llama, el test ya falló
        raise AssertionError("--help no debe arrancar el servidor MCP")

    monkeypatch.setattr(srv.mcp, "run", _no_arrancar)
    assert _run_main(monkeypatch, ["--help"]) == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_subcomando_desconocido_falla_en_vez_de_colgarse(monkeypatch, capsys):
    from local_delegate import server as srv

    def _no_arrancar():  # pragma: no cover
        raise AssertionError("un nombre inválido no debe arrancar el servidor MCP")

    monkeypatch.setattr(srv.mcp, "run", _no_arrancar)
    assert _run_main(monkeypatch, ["doctro"]) == 2
    assert "invalid choice" in capsys.readouterr().err


def test_sin_argumentos_sigue_arrancando_el_servidor_mcp(monkeypatch):
    """El contrato con los hosts MCP: romperlo deja a Claude Code y Codex sin servidor."""
    import sys

    from local_delegate import cli
    from local_delegate import server as srv

    arrancado = []
    monkeypatch.setattr(srv.mcp, "run", lambda: arrancado.append(True))
    monkeypatch.setattr(srv.config, "AUTOSTART", False)
    monkeypatch.setattr(srv.config, "WEB_ENABLED", False)
    monkeypatch.setattr(cli, "run", lambda argv: 0)  # no debe llamarse
    monkeypatch.setattr(sys, "argv", ["local-delegate"])
    server.main()
    assert arrancado == [True]


def test_el_aviso_de_terminal_solo_sale_con_tty_y_por_stderr(monkeypatch, capsys):
    import sys

    class _Stdin:
        def __init__(self, tty: bool) -> None:
            self._tty = tty

        def isatty(self) -> bool:
            return self._tty

    monkeypatch.setattr(sys, "stdin", _Stdin(False))
    server._aviso_de_terminal_interactiva()
    assert capsys.readouterr().err == ""

    monkeypatch.setattr(sys, "stdin", _Stdin(True))
    server._aviso_de_terminal_interactiva()
    salida = capsys.readouterr()
    assert "local-delegate --help" in salida.err
    assert salida.out == ""  # stdout es el canal del protocolo MCP: jamás se escribe ahí


def test_el_aviso_no_revienta_con_un_stdin_raro(monkeypatch, capsys):
    """Bajo un host MCP stdin puede estar cerrado o no ser un fichero de verdad."""
    import sys

    class _Cerrado:
        def isatty(self) -> bool:
            raise ValueError("I/O operation on closed file")

    monkeypatch.setattr(sys, "stdin", None)
    server._aviso_de_terminal_interactiva()
    monkeypatch.setattr(sys, "stdin", _Cerrado())
    server._aviso_de_terminal_interactiva()
    assert capsys.readouterr().err == ""


def test_los_subcomandos_estan_definidos_una_sola_vez(monkeypatch):
    """REQ-006/007: el parser es la única fuente; añadir uno no exige tocar nada más.

    Si vuelve a aparecer una lista literal de nombres, este test la detecta: cualquier
    subcomando registrado en el parser tiene que ser despachable sin que nadie lo dé de alta
    en otro sitio.
    """
    from local_delegate import cli
    from local_delegate import server as srv

    assert not hasattr(srv, "_CLI_COMMANDS")
    assert not hasattr(cli, "KNOWN_COMMANDS")

    sub = cli.build_parser()._subparsers._group_actions[0]  # type: ignore[union-attr]
    registrados = set(sub.choices)
    assert {"doctor", "install", "serve"} <= registrados

    recibidos: list[list[str]] = []
    monkeypatch.setattr(cli, "run", lambda argv: recibidos.append(argv) or 0)
    for nombre in sorted(registrados):
        assert _run_main(monkeypatch, [nombre]) == 0
    assert recibidos == [[nombre] for nombre in sorted(registrados)]
