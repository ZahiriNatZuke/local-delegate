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
def claude_spy(monkeypatch) -> list[list[str]]:
    """Finge que el binario `claude` existe y registra cada invocación, sin ejecutar nada."""
    calls: list[list[str]] = []
    real_which = inst.shutil.which

    def _which(name, *a, **kw):
        return "/fake/claude" if name == "claude" else real_which(name, *a, **kw)

    def _run(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(list(argv), returncode=0, stdout="", stderr="")

    monkeypatch.setattr(inst.shutil, "which", _which)
    monkeypatch.setattr(inst.subprocess, "run", _run)
    return calls


def _home_real(monkeypatch, path: Path) -> Path:
    """Dobla el HOME «de verdad».

    Se parchea `Path.home` y NO una variable de entorno: `Path.home()` lee `USERPROFILE` en
    Windows y `HOME` en POSIX, así que un `setenv("HOME", ...)` pasaría en Linux y macOS y
    fallaría en el runner de Windows — y el CI corre en los tres.
    """
    path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: path))
    return path


def _codex_by_hand(home: Path) -> Path:
    """Un `config.toml` con nuestra sección escrita por el usuario: sin marcadores."""
    codex = home / ".codex"
    codex.mkdir(parents=True, exist_ok=True)
    path = codex / "config.toml"
    path.write_text(
        '[mcp_servers.otro]\ncommand = "ajeno"\n\n'
        '[mcp_servers.local-delegate]\ncommand = "i-put-it-there"\n',
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
def test_is_simulated_home_tells_the_real_home_apart(monkeypatch, tmp_path):
    real = _home_real(monkeypatch, tmp_path / "real")
    assert inst.is_simulated_home(tmp_path / "otro") is True
    assert inst.is_simulated_home(real) is False


def test_is_simulated_home_on_an_unresolvable_path_picks_the_safe_side(monkeypatch, tmp_path):
    _home_real(monkeypatch, tmp_path / "real")

    def _explodes(self, *a, **kw):
        raise OSError("ruta irresoluble")

    monkeypatch.setattr(Path, "resolve", _explodes)
    assert inst.is_simulated_home(tmp_path / "x") is True


@pytest.mark.parametrize(
    ("claude", "codex", "opencode", "expected"),
    [
        (True, True, True, {"claude", "codex", "opencode"}),
        (True, False, False, {"claude"}),
        (False, False, True, {"opencode"}),
        (False, False, False, set()),
    ],
)
def test_present_targets_looks_at_the_directories(tmp_path, claude, codex, opencode, expected):
    home = make_home(tmp_path, claude=claude, codex=codex, opencode=opencode, complete=False)
    assert inst.present_targets(home) == expected


def test_update_and_install_share_the_same_definition(tmp_path):
    """Si alguien vuelve a duplicar la regla, esto lo caza."""
    from local_delegate import update as upd

    home = make_home(tmp_path, claude=True, codex=False, opencode=True, complete=False)
    assert upd._present_targets(home) == inst.present_targets(home)
    assert upd.Options(home=home).simulated_home == inst.is_simulated_home(home)


# --- El HOME simulado no toca nada global -------------------------------------
def test_simulated_home_does_not_invoke_the_claude_binary(
    monkeypatch, tmp_path, claude_spy, capsys
):
    """`claude mcp add-json --scope user` escribe SIEMPRE en el HOME del usuario real.

    Con `--home` simulado eso significa escribir fuera del árbol pedido: la config de verdad se
    modificaba mientras el árbol simulado quedaba vacío.
    """
    real = _home_real(monkeypatch, tmp_path / "real")
    (real / ".claude").mkdir()
    (real / ".claude.json").write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    before = snapshot(real)

    sim = make_home(tmp_path, claude=True, codex=False, complete=False)
    assert cli.run(["install", "--home", str(sim)]) == 0

    assert claude_spy == [], "se invocó el binario `claude` con un HOME simulado"
    assert snapshot(real) == before, "se escribió fuera del HOME simulado"
    servers = json.loads((sim / ".claude.json").read_text(encoding="utf-8"))["mcpServers"]
    assert inst.SERVER_NAME in servers


def test_uninstall_with_simulated_home_does_not_touch_the_real_one_either(
    monkeypatch, tmp_path, claude_spy
):
    """El caso más dañino de los dos: por CLI, `uninstall` DESREGISTRA el MCP de verdad."""
    real = _home_real(monkeypatch, tmp_path / "real")
    (real / ".claude").mkdir()
    (real / ".claude.json").write_text(
        json.dumps({"mcpServers": {inst.SERVER_NAME: {"type": "http", "url": "u"}}}),
        encoding="utf-8",
    )
    before = snapshot(real)

    sim = make_home(tmp_path, claude=True, codex=False, complete=True)
    assert cli.run(["uninstall", "--home", str(sim)]) == 0

    assert claude_spy == [], "se invocó el binario `claude` con un HOME simulado"
    assert snapshot(real) == before, "se desregistró el MCP del usuario real"


def test_without_simulated_home_the_binary_is_used(monkeypatch, tmp_path, claude_spy):
    """El contrapeso: en el HOME de verdad el camino por CLI sigue siendo el preferido.

    Sin esta prueba, `use_cli=False` para todo pasaría los tests de arriba y rompería el motivo
    por el que existe ese camino (que escriba el propio cliente un `~/.claude.json` vivo).
    """
    real = _home_real(monkeypatch, tmp_path / "real")
    (real / ".claude").mkdir()
    assert cli.run(["install", "--home", str(real), "--no-hooks", "--no-skill", "--no-memory"]) == 0
    assert any("add-json" in " ".join(argv) for argv in claude_spy)


# --- Selección de clientes -----------------------------------------------------
def test_auto_configures_only_the_present_client(monkeypatch, tmp_path, capsys):
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=False, complete=False)

    assert cli.run(["install", "--home", str(home)]) == 0

    assert (home / ".claude" / "skills" / inst.SKILL_NAME / "SKILL.md").is_file()
    assert not (home / ".codex").exists(), "se creó ~/.codex en una máquina sin Codex"
    assert "deteccion automatica" in capsys.readouterr().out


def test_auto_without_any_client_writes_nothing_and_exits_fine(monkeypatch, tmp_path, capsys):
    _home_real(monkeypatch, tmp_path / "real")
    home = tmp_path / "vacio"
    home.mkdir()

    assert cli.run(["install", "--home", str(home)]) == 0

    assert snapshot(home) == {}, "se escribió algo sin haber ningún cliente"
    output = capsys.readouterr().out
    assert "No se encontró ningún cliente" in output
    assert "--clients claude" in output
    assert "[ -- ]" in output, "el reporte final debe explicar por qué no se hizo nada"


def test_target_all_keeps_the_historical_behavior(monkeypatch, tmp_path):
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=False, complete=False)

    assert cli.run(["install", "--home", str(home), "--target", "all"]) == 0

    assert (home / ".codex" / "AGENTS.md").is_file(), "`--target all` debe forzar los dos"


def test_explicit_client_is_configured_even_if_not_installed(monkeypatch, tmp_path):
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=False, complete=False)

    assert cli.run(["install", "--home", str(home), "--clients", "codex"]) == 0

    assert (home / ".codex" / "AGENTS.md").is_file()


def test_clients_and_target_together_is_a_usage_error(monkeypatch, tmp_path, capsys):
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=True, complete=False)
    before = snapshot(home)

    assert (
        cli.run(["install", "--home", str(home), "--clients", "claude", "--target", "codex"]) == 2
    )

    assert snapshot(home) == before, "un error de uso no debe escribir nada"
    assert "no se combinan" in capsys.readouterr().err


def test_explicit_auto_does_not_clash_with_a_named_client(monkeypatch, tmp_path):
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=True, complete=False)

    code = cli.run(["install", "--home", str(home), "--clients", "auto", "--clients", "claude"])

    assert code == 0
    assert not (home / ".codex" / "AGENTS.md").exists(), "lo explícito debe ganar sobre `auto`"


def test_install_does_not_query_pypi_when_reporting_the_scaffolding(monkeypatch, tmp_path, capsys):
    """Instalar unos hooks no es motivo para salir a internet.

    El reporte final de `install` corre el grupo `environment`, donde vive la comprobación de la
    versión publicada. Se dobla `update.latest_version` —el destino real del colaborador por
    defecto, no un kwarg— para que el test ejercite el camino de `cli.py` y no el doble.
    """
    from local_delegate import update as upd

    queries: list[float] = []

    def _spy(timeout=0.0):
        queries.append(timeout)
        return "9.9.9", None

    monkeypatch.setattr(upd, "latest_version", _spy)
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=False, complete=False)

    assert cli.run(["install", "--home", str(home)]) == 0

    assert queries == [], "el reporte del andamiaje consultó PyPI"
    assert "no se consulta PyPI" in capsys.readouterr().out


def test_uninstall_auto_cleans_only_the_present_clients(monkeypatch, tmp_path):
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=True, complete=True)
    foreign = home / ".codex" / "config.toml"
    foreign.write_text(
        foreign.read_text(encoding="utf-8") + '\n[otro.mio]\nz = "1"\n', encoding="utf-8"
    )

    assert cli.run(["uninstall", "--home", str(home)]) == 0

    assert not (home / ".claude" / "skills" / inst.SKILL_NAME).exists()
    assert "[otro.mio]" in foreign.read_text(encoding="utf-8"), "se llevó por delante lo ajeno"


# --- La entrada de Codex escrita a mano ----------------------------------------
def _prepare_codex_by_hand(monkeypatch, tmp_path) -> tuple[Path, Path]:
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=True, complete=False)
    return home, _codex_by_hand(home)


def test_without_terminal_it_does_not_ask_and_keeps_the_entry(monkeypatch, tmp_path, capsys):
    home, config_toml = _prepare_codex_by_hand(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", _Stdin(tty=False))
    original = config_toml.read_text(encoding="utf-8")

    assert cli.run(["install", "--home", str(home)]) == 0

    assert config_toml.read_text(encoding="utf-8") == original
    output = capsys.readouterr().out
    assert "--force-mcp-codex" in output
    assert (home / ".claude" / "skills" / inst.SKILL_NAME).is_dir(), "el resto sí se instala"


def test_answering_no_keeps_the_entry(monkeypatch, tmp_path):
    home, config_toml = _prepare_codex_by_hand(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", _Stdin(tty=True))
    monkeypatch.setattr("builtins.input", lambda *_a: "n")
    original = config_toml.read_text(encoding="utf-8")

    assert cli.run(["install", "--home", str(home)]) == 0

    assert config_toml.read_text(encoding="utf-8") == original


def test_answering_yes_replaces_it(monkeypatch, tmp_path):
    home, config_toml = _prepare_codex_by_hand(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", _Stdin(tty=True))
    monkeypatch.setattr("builtins.input", lambda *_a: "s")

    assert cli.run(["install", "--home", str(home)]) == 0

    text = config_toml.read_text(encoding="utf-8")
    assert inst.TOML_BEGIN in text
    assert "i-put-it-there" not in text
    assert "[mcp_servers.otro]" in text, "la entrada ajena no se toca ni reemplazando"


def test_force_replaces_without_asking_or_terminal(monkeypatch, tmp_path):
    home, config_toml = _prepare_codex_by_hand(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", _Stdin(tty=False))

    def _do_not_ask(*_a, **_kw):
        raise AssertionError("con --force-mcp-codex no debe preguntar nada")

    monkeypatch.setattr("builtins.input", _do_not_ask)

    assert cli.run(["install", "--home", str(home), "--force-mcp-codex"]) == 0

    assert inst.TOML_BEGIN in config_toml.read_text(encoding="utf-8")


def test_dry_run_does_not_ask_and_announces_it(monkeypatch, tmp_path, capsys):
    home, config_toml = _prepare_codex_by_hand(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", _Stdin(tty=True))

    def _do_not_ask(*_a, **_kw):
        raise AssertionError("--dry-run no debe preguntar nada")

    monkeypatch.setattr("builtins.input", _do_not_ask)
    original = config_toml.read_text(encoding="utf-8")

    assert cli.run(["install", "--home", str(home), "--dry-run"]) == 0

    assert config_toml.read_text(encoding="utf-8") == original
    assert "se pediría confirmación" in capsys.readouterr().out


def test_with_no_mcp_it_never_asks(monkeypatch, tmp_path):
    home, _config_toml = _prepare_codex_by_hand(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", _Stdin(tty=True))

    def _do_not_ask(*_a, **_kw):
        raise AssertionError("sin la acción en el plan no hay nada que preguntar")

    monkeypatch.setattr("builtins.input", _do_not_ask)

    assert cli.run(["install", "--home", str(home), "--no-mcp"]) == 0


def test_skip_codex_mcp_removes_that_action_and_only_that(tmp_path):
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

    complete = _kinds()
    trimmed = _kinds(skip_codex_mcp=True)
    removed = [a for a in complete if a not in trimmed]
    assert len(removed) == 1
    assert removed[0][0] == "toml"


# --- Reporte final --------------------------------------------------------------
def test_install_ends_by_stating_the_real_state(monkeypatch, tmp_path, capsys):
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=False, complete=False)

    assert cli.run(["install", "--home", str(home)]) == 0

    output = capsys.readouterr().out
    assert "Estado del andamiaje después de escribir:" in output
    assert "[ OK ]" in output
    assert "MCP en Codex" in output, "el reporte cubre el grupo andamiaje entero"


def test_the_report_does_not_alter_the_exit_code(monkeypatch, tmp_path, capsys):
    """Tras instalar quedan avisos legítimos (cliente ausente, CLI fuera del PATH con `uvx`).

    Si contaran para el exit code, cualquier script de instalación rompería.
    """
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=False, complete=False)

    assert cli.run(["install", "--home", str(home)]) == 0
    assert "[ -- ]" in capsys.readouterr().out, "debe haber al menos un aviso que no cuenta"


def test_the_report_is_shown_also_when_an_action_fails(monkeypatch, tmp_path, capsys):
    """Con algo a medias es cuando más falta hace saber qué quedó escrito y qué no."""
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=False, complete=False)

    def _blows_up() -> str:
        raise OSError("disco lleno")

    action = inst.Action("copy", home, "acción que falla", _blows_up)
    monkeypatch.setattr(inst, "plan_install", lambda opts: [action])

    assert cli.run(["install", "--home", str(home)]) == 1

    output = capsys.readouterr()
    assert "Estado del andamiaje después de escribir:" in output.out
    assert "acción(es) fallaron" in output.err


def test_dry_run_labels_the_report_as_current_state(monkeypatch, tmp_path, capsys):
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=False, complete=False)

    assert cli.run(["install", "--home", str(home), "--dry-run"]) == 0

    output = capsys.readouterr().out
    assert "Estado ACTUAL del andamiaje (no se escribió nada):" in output
    assert "Estado del andamiaje después de escribir:" not in output


def test_the_new_output_fits_in_the_windows_console(monkeypatch, tmp_path, capsys):
    """Un carácter fuera de cp1252 mata el comando en la consola de Windows. Ya pasó."""
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=True, complete=False)
    _codex_by_hand(home)
    monkeypatch.setattr(sys, "stdin", _Stdin(tty=False))

    cli.run(["install", "--home", str(home)])

    captured = capsys.readouterr()
    (captured.out + captured.err).encode("cp1252")  # revienta si se coló algo
