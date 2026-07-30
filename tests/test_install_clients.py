"""Tests de las decisiones que toma `install` antes de escribir: a quién configura, qué no pisa
y dónde tiene permitido escribir.

Complementa `test_install.py`, que prueba el planificador y sus escrituras. Aquí se ejercita el
CLI entero, incluido **el camino por el binario `claude`** — el que la otra suite desactiva con
`use_cli=False` y que por eso nunca se probó, siendo justo donde vivía el defecto del HOME.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import make_home, snapshot

from local_delegate import cli
from local_delegate import install as inst


@pytest.fixture
def espia_claude(monkeypatch) -> list[list[str]]:
    """Finge que el binario `claude` existe y registra cada invocación, sin ejecutar nada."""
    llamadas: list[list[str]] = []
    real_which = inst.shutil.which

    def _which(name, *a, **kw):
        return "/fake/claude" if name == "claude" else real_which(name, *a, **kw)

    def _run(argv, **kwargs):
        llamadas.append(list(argv))
        return subprocess.CompletedProcess(list(argv), returncode=0, stdout="", stderr="")

    monkeypatch.setattr(inst.shutil, "which", _which)
    monkeypatch.setattr(inst.subprocess, "run", _run)
    return llamadas


def _home_real(monkeypatch, path: Path) -> Path:
    """Dobla el HOME «de verdad».

    Se parchea `Path.home` y NO una variable de entorno: `Path.home()` lee `USERPROFILE` en
    Windows y `HOME` en POSIX, así que un `setenv("HOME", ...)` pasaría en Linux y macOS y
    fallaría en el runner de Windows — y el CI corre en los tres.
    """
    path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: path))
    return path


def _codex_a_mano(home: Path) -> Path:
    """Un `config.toml` con nuestra sección escrita por el usuario: sin marcadores."""
    codex = home / ".codex"
    codex.mkdir(parents=True, exist_ok=True)
    path = codex / "config.toml"
    path.write_text(
        '[mcp_servers.otro]\ncommand = "ajeno"\n\n'
        '[mcp_servers.local-delegate]\ncommand = "lo-puse-yo"\n',
        encoding="utf-8",
    )
    return path


class _Stdin:
    """stdin de mentira: lo único que se le pregunta es si es una terminal."""

    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


# --- Las dos reglas del HOME, con una sola definición -------------------------
def test_is_simulated_home_distingue_el_home_real(monkeypatch, tmp_path):
    real = _home_real(monkeypatch, tmp_path / "real")
    assert inst.is_simulated_home(tmp_path / "otro") is True
    assert inst.is_simulated_home(real) is False


def test_is_simulated_home_ante_una_ruta_irresoluble_elige_el_lado_seguro(monkeypatch, tmp_path):
    _home_real(monkeypatch, tmp_path / "real")

    def _explota(self, *a, **kw):
        raise OSError("ruta irresoluble")

    monkeypatch.setattr(Path, "resolve", _explota)
    assert inst.is_simulated_home(tmp_path / "x") is True


@pytest.mark.parametrize(
    ("claude", "codex", "esperado"),
    [(True, True, {"claude", "codex"}), (True, False, {"claude"}), (False, False, set())],
)
def test_present_targets_mira_los_directorios(tmp_path, claude, codex, esperado):
    home = make_home(tmp_path, claude=claude, codex=codex, complete=False)
    assert inst.present_targets(home) == esperado


def test_update_y_install_comparten_la_misma_definicion(tmp_path):
    """Si alguien vuelve a duplicar la regla, esto lo caza."""
    from local_delegate import update as upd

    home = make_home(tmp_path, claude=True, codex=False, complete=False)
    assert upd._present_targets(home) == inst.present_targets(home)
    assert upd.Options(home=home).simulated_home == inst.is_simulated_home(home)


# --- El HOME simulado no toca nada global -------------------------------------
def test_home_simulado_no_invoca_el_binario_claude(monkeypatch, tmp_path, espia_claude, capsys):
    """`claude mcp add-json --scope user` escribe SIEMPRE en el HOME del usuario real.

    Con `--home` simulado eso significa escribir fuera del árbol pedido: la config de verdad se
    modificaba mientras el árbol simulado quedaba vacío.
    """
    real = _home_real(monkeypatch, tmp_path / "real")
    (real / ".claude").mkdir()
    (real / ".claude.json").write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    antes = snapshot(real)

    sim = make_home(tmp_path, claude=True, codex=False, complete=False)
    assert cli.run(["install", "--home", str(sim)]) == 0

    assert espia_claude == [], "se invocó el binario `claude` con un HOME simulado"
    assert snapshot(real) == antes, "se escribió fuera del HOME simulado"
    servers = json.loads((sim / ".claude.json").read_text(encoding="utf-8"))["mcpServers"]
    assert inst.SERVER_NAME in servers


def test_uninstall_con_home_simulado_tampoco_toca_el_real(monkeypatch, tmp_path, espia_claude):
    """El caso más dañino de los dos: por CLI, `uninstall` DESREGISTRA el MCP de verdad."""
    real = _home_real(monkeypatch, tmp_path / "real")
    (real / ".claude").mkdir()
    (real / ".claude.json").write_text(
        json.dumps({"mcpServers": {inst.SERVER_NAME: {"type": "http", "url": "u"}}}),
        encoding="utf-8",
    )
    antes = snapshot(real)

    sim = make_home(tmp_path, claude=True, codex=False, complete=True)
    assert cli.run(["uninstall", "--home", str(sim)]) == 0

    assert espia_claude == [], "se invocó el binario `claude` con un HOME simulado"
    assert snapshot(real) == antes, "se desregistró el MCP del usuario real"


def test_sin_home_simulado_si_se_usa_el_binario(monkeypatch, tmp_path, espia_claude):
    """El contrapeso: en el HOME de verdad el camino por CLI sigue siendo el preferido.

    Sin esta prueba, `use_cli=False` para todo pasaría los tests de arriba y rompería el motivo
    por el que existe ese camino (que escriba el propio cliente un `~/.claude.json` vivo).
    """
    real = _home_real(monkeypatch, tmp_path / "real")
    (real / ".claude").mkdir()
    assert cli.run(["install", "--home", str(real), "--no-hooks", "--no-skill", "--no-memory"]) == 0
    assert any("add-json" in " ".join(argv) for argv in espia_claude)


# --- Selección de clientes -----------------------------------------------------
def test_auto_configura_solo_el_cliente_presente(monkeypatch, tmp_path, capsys):
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=False, complete=False)

    assert cli.run(["install", "--home", str(home)]) == 0

    assert (home / ".claude" / "skills" / inst.SKILL_NAME / "SKILL.md").is_file()
    assert not (home / ".codex").exists(), "se creó ~/.codex en una máquina sin Codex"
    assert "deteccion automatica" in capsys.readouterr().out


def test_auto_sin_ningun_cliente_no_escribe_nada_y_sale_bien(monkeypatch, tmp_path, capsys):
    _home_real(monkeypatch, tmp_path / "real")
    home = tmp_path / "vacio"
    home.mkdir()

    assert cli.run(["install", "--home", str(home)]) == 0

    assert snapshot(home) == {}, "se escribió algo sin haber ningún cliente"
    salida = capsys.readouterr().out
    assert "No se encontró ningún cliente" in salida
    assert "--clients claude" in salida
    assert "[ -- ]" in salida, "el reporte final debe explicar por qué no se hizo nada"


def test_target_all_conserva_el_comportamiento_historico(monkeypatch, tmp_path):
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=False, complete=False)

    assert cli.run(["install", "--home", str(home), "--target", "all"]) == 0

    assert (home / ".codex" / "AGENTS.md").is_file(), "`--target all` debe forzar los dos"


def test_cliente_explicito_se_configura_aunque_no_este_instalado(monkeypatch, tmp_path):
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=False, complete=False)

    assert cli.run(["install", "--home", str(home), "--clients", "codex"]) == 0

    assert (home / ".codex" / "AGENTS.md").is_file()


def test_clients_y_target_juntos_es_error_de_uso(monkeypatch, tmp_path, capsys):
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=True, complete=False)
    antes = snapshot(home)

    assert (
        cli.run(["install", "--home", str(home), "--clients", "claude", "--target", "codex"]) == 2
    )

    assert snapshot(home) == antes, "un error de uso no debe escribir nada"
    assert "no se combinan" in capsys.readouterr().err


def test_auto_explicito_no_pelea_con_un_cliente_nombrado(monkeypatch, tmp_path):
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=True, complete=False)

    code = cli.run(["install", "--home", str(home), "--clients", "auto", "--clients", "claude"])

    assert code == 0
    assert not (home / ".codex" / "AGENTS.md").exists(), "lo explícito debe ganar sobre `auto`"


def test_uninstall_auto_limpia_solo_los_clientes_presentes(monkeypatch, tmp_path):
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=True, complete=True)
    ajeno = home / ".codex" / "config.toml"
    ajeno.write_text(
        ajeno.read_text(encoding="utf-8") + '\n[otro.mio]\nz = "1"\n', encoding="utf-8"
    )

    assert cli.run(["uninstall", "--home", str(home)]) == 0

    assert not (home / ".claude" / "skills" / inst.SKILL_NAME).exists()
    assert "[otro.mio]" in ajeno.read_text(encoding="utf-8"), "se llevó por delante lo ajeno"


# --- La entrada de Codex escrita a mano ----------------------------------------
def _prepara_codex_a_mano(monkeypatch, tmp_path) -> tuple[Path, Path]:
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=True, complete=False)
    return home, _codex_a_mano(home)


def test_sin_terminal_no_pregunta_y_conserva_la_entrada(monkeypatch, tmp_path, capsys):
    home, config_toml = _prepara_codex_a_mano(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", _Stdin(tty=False))
    original = config_toml.read_text(encoding="utf-8")

    assert cli.run(["install", "--home", str(home)]) == 0

    assert config_toml.read_text(encoding="utf-8") == original
    salida = capsys.readouterr().out
    assert "--force-mcp-codex" in salida
    assert (home / ".claude" / "skills" / inst.SKILL_NAME).is_dir(), "el resto sí se instala"


def test_respondiendo_que_no_se_conserva_la_entrada(monkeypatch, tmp_path):
    home, config_toml = _prepara_codex_a_mano(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", _Stdin(tty=True))
    monkeypatch.setattr("builtins.input", lambda *_a: "n")
    original = config_toml.read_text(encoding="utf-8")

    assert cli.run(["install", "--home", str(home)]) == 0

    assert config_toml.read_text(encoding="utf-8") == original


def test_respondiendo_que_si_la_reemplaza(monkeypatch, tmp_path):
    home, config_toml = _prepara_codex_a_mano(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", _Stdin(tty=True))
    monkeypatch.setattr("builtins.input", lambda *_a: "s")

    assert cli.run(["install", "--home", str(home)]) == 0

    texto = config_toml.read_text(encoding="utf-8")
    assert inst.TOML_BEGIN in texto
    assert "lo-puse-yo" not in texto
    assert "[mcp_servers.otro]" in texto, "la entrada ajena no se toca ni reemplazando"


def test_force_reemplaza_sin_preguntar_ni_terminal(monkeypatch, tmp_path):
    home, config_toml = _prepara_codex_a_mano(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", _Stdin(tty=False))

    def _no_preguntes(*_a, **_kw):
        raise AssertionError("con --force-mcp-codex no debe preguntar nada")

    monkeypatch.setattr("builtins.input", _no_preguntes)

    assert cli.run(["install", "--home", str(home), "--force-mcp-codex"]) == 0

    assert inst.TOML_BEGIN in config_toml.read_text(encoding="utf-8")


def test_dry_run_no_pregunta_y_lo_anuncia(monkeypatch, tmp_path, capsys):
    home, config_toml = _prepara_codex_a_mano(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", _Stdin(tty=True))

    def _no_preguntes(*_a, **_kw):
        raise AssertionError("--dry-run no debe preguntar nada")

    monkeypatch.setattr("builtins.input", _no_preguntes)
    original = config_toml.read_text(encoding="utf-8")

    assert cli.run(["install", "--home", str(home), "--dry-run"]) == 0

    assert config_toml.read_text(encoding="utf-8") == original
    assert "se pediría confirmación" in capsys.readouterr().out


def test_con_no_mcp_no_se_pregunta_nunca(monkeypatch, tmp_path):
    home, _config_toml = _prepara_codex_a_mano(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", _Stdin(tty=True))

    def _no_preguntes(*_a, **_kw):
        raise AssertionError("sin la acción en el plan no hay nada que preguntar")

    monkeypatch.setattr("builtins.input", _no_preguntes)

    assert cli.run(["install", "--home", str(home), "--no-mcp"]) == 0


def test_skip_codex_mcp_suprime_esa_accion_y_solo_esa(tmp_path):
    def _kinds(**kw):
        opts = inst.Options(
            home=tmp_path,
            components={"hooks", "skill", "memory", "mcp"},
            targets={"claude", "codex"},
            python_exe="python3",
            use_cli=False,
            **kw,
        )
        return [(a.kind, str(a.target)) for a in inst.plan_install(opts)]

    completo = _kinds()
    recortado = _kinds(skip_codex_mcp=True)
    quitadas = [a for a in completo if a not in recortado]
    assert len(quitadas) == 1
    assert quitadas[0][0] == "toml"


# --- Reporte final --------------------------------------------------------------
def test_install_termina_diciendo_el_estado_real(monkeypatch, tmp_path, capsys):
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=False, complete=False)

    assert cli.run(["install", "--home", str(home)]) == 0

    salida = capsys.readouterr().out
    assert "Estado del andamiaje después de escribir:" in salida
    assert "[ OK ]" in salida
    assert "MCP en Codex" in salida, "el reporte cubre el grupo andamiaje entero"


def test_el_reporte_no_altera_el_exit_code(monkeypatch, tmp_path, capsys):
    """Tras instalar quedan avisos legítimos (cliente ausente, CLI fuera del PATH con `uvx`).

    Si contaran para el exit code, cualquier script de instalación rompería.
    """
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=False, complete=False)

    assert cli.run(["install", "--home", str(home)]) == 0
    assert "[ -- ]" in capsys.readouterr().out, "debe haber al menos un aviso que no cuenta"


def test_el_reporte_sale_tambien_cuando_una_accion_falla(monkeypatch, tmp_path, capsys):
    """Con algo a medias es cuando más falta hace saber qué quedó escrito y qué no."""
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=False, complete=False)

    def _revienta() -> str:
        raise OSError("disco lleno")

    accion = inst.Action("copy", home, "acción que falla", _revienta)
    monkeypatch.setattr(inst, "plan_install", lambda opts: [accion])

    assert cli.run(["install", "--home", str(home)]) == 1

    salida = capsys.readouterr()
    assert "Estado del andamiaje después de escribir:" in salida.out
    assert "acción(es) fallaron" in salida.err


def test_dry_run_rotula_el_reporte_como_estado_actual(monkeypatch, tmp_path, capsys):
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=False, complete=False)

    assert cli.run(["install", "--home", str(home), "--dry-run"]) == 0

    salida = capsys.readouterr().out
    assert "Estado ACTUAL del andamiaje (no se escribió nada):" in salida
    assert "Estado del andamiaje después de escribir:" not in salida


def test_la_salida_nueva_cabe_en_la_consola_de_windows(monkeypatch, tmp_path, capsys):
    """Un carácter fuera de cp1252 mata el comando en la consola de Windows. Ya pasó."""
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=True, complete=False)
    _codex_a_mano(home)
    monkeypatch.setattr(sys, "stdin", _Stdin(tty=False))

    cli.run(["install", "--home", str(home)])

    capturado = capsys.readouterr()
    (capturado.out + capturado.err).encode("cp1252")  # revienta si se coló algo
