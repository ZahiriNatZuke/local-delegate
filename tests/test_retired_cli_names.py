"""Nombres viejos del CLI retirados con sucesor (SDD retire-legacy-aliases, L3).

REQ-008: `cli.run` rechaza, antes de construir el parser, el subcomando o la opción de un retirado
con sucesor (`cli_entries()` con `is_retired`): `stderr` con `cli.error` y el aviso del registro, y
código 2 sin ejecutar nada. Un alias vigente **nunca** se rechaza. REQ-011, filas 6 y 7: el nombre
viejo no hace nada y su gemelo nuevo sí, con los mismos datos.

Los casos con **registro sintético** marcan las entradas como retiradas y publicadas en la 0.38.0
(o como alias vivos); desde el volteo (L6), los del final prueban además el registro real.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from test_recompute import _delegation_with_n
from test_transcripts import subagent

from local_delegate import cli, config, deprecations, entrypoint, i18n, recompute
from local_delegate.deprecation_notices import warning_text

_CLI_KINDS = ("cli_command", "cli_option")


def retired_cli_registry(
    entries: tuple[deprecations.DeprecatedName, ...] | None = None,
) -> tuple[deprecations.DeprecatedName, ...]:
    """El registro con sus entradas del CLI como retiradas con sucesor ya publicadas (0.38.0).

    Sirve para alias (los marca retirados) y para el registro real, que ya los tiene retirados
    pero aún `UNRELEASED`: así el aviso lleva la versión.
    """
    source = deprecations.DEPRECATED_NAMES if entries is None else entries
    return tuple(
        replace(
            e,
            kind="retired",
            retired_from=deprecations.effective_kind(e),
            introduced="0.38.0",
            warn_until="0.40.0",
        )
        if deprecations.effective_kind(e) in _CLI_KINDS
        else e
        for e in source
    )


def _entry(kind: str) -> deprecations.DeprecatedName:
    """La entrada del CLI de esa superficie, sacada del registro vigente (sin literales)."""
    return next(e for e in deprecations.cli_entries() if deprecations.effective_kind(e) == kind)


@pytest.fixture
def retired(monkeypatch):
    monkeypatch.setattr(deprecations, "DEPRECATED_NAMES", retired_cli_registry())
    assert deprecations.class_problems() == []
    assert len(deprecations.cli_entries()) >= 2
    assert all(e.is_retired for e in deprecations.cli_entries())


@pytest.fixture
def spy(monkeypatch, tmp_path):
    """Espía sobre `recompute.run` que llama al de verdad, con `LOG_DIR` temporal."""
    calls: list[str | None] = []
    real = recompute.run

    def wrapper(claude_dir, log_dir, *, reset=None, **kw):
        calls.append(reset)
        return real(claude_dir, log_dir, reset=reset, **kw)

    monkeypatch.setattr(recompute, "run", wrapper)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "log")
    return calls


def _run(argv: list[str]) -> int:
    try:
        return cli.run(argv)
    except SystemExit as e:
        return int(e.code or 0)


def _claude_dir(tmp_path: Path) -> Path:
    claude = tmp_path / "claude"
    _delegation_with_n(subagent(claude, "a1"), "toolu_cli", 3)
    return claude


# --- REQ-011, fila 6: subcomando ----------------------------------------------------------------


@pytest.mark.parametrize("lang", ["es", "en"])
def test_retired_command_exits_2_and_writes_nothing(
    lang, retired, spy, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", lang)
    i18n.reset()
    entry = _entry("cli_command")
    claude = _claude_dir(tmp_path)
    written = tmp_path / "log" / recompute.FILE_NAME

    assert _run([entry.old, "--claude-dir", str(claude)]) == 2
    captured = capsys.readouterr()
    assert captured.err == i18n.t("cli.error", detail=warning_text(entry)) + "\n"
    assert captured.out == ""
    assert spy == [] and not written.exists()

    # Gemelo: el nombre nuevo, con los mismos datos, sí recalcula y escribe.
    assert _run([entry.new, "--claude-dir", str(claude)]) == 0
    assert spy == [None]
    assert json.loads(written.read_text(encoding="utf-8"))
    assert capsys.readouterr().err == ""


def test_retired_command_message_names_the_new_name(retired, spy, tmp_path, capsys):
    entry = _entry("cli_command")
    assert _run([entry.old, "--claude-dir", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert entry.old in err and entry.new in err and "0.38.0" in err


# --- REQ-011, fila 7: opción --------------------------------------------------------------------


@pytest.mark.parametrize("form", ["separate", "equals"])
def test_retired_option_exits_2(form, retired, spy, tmp_path, capsys):
    entry = _entry("cli_option")
    command = _entry("cli_command").new
    claude = _claude_dir(tmp_path)
    old = [entry.old, "five_hour"] if form == "separate" else [f"{entry.old}=five_hour"]

    assert _run([command, "--claude-dir", str(claude), *old]) == 2
    assert capsys.readouterr().err == i18n.t("cli.error", detail=warning_text(entry)) + "\n"
    assert spy == []

    # Gemelo: la opción nueva llega al argumento.
    new = [entry.new, "five_hour"] if form == "separate" else [f"{entry.new}=five_hour"]
    assert _run([command, "--claude-dir", str(claude), *new]) == 0
    assert spy == ["five_hour"]


def test_retired_option_after_double_dash_is_not_checked():
    entry = _entry("cli_option")
    assert cli._reject_retired_names(["x", "--", entry.old]) is None


# --- Solo retirados: un alias vigente funciona ----------------------------------------------------


def test_live_alias_is_never_rejected(monkeypatch, spy, tmp_path, capsys):
    """Un alias vivo con el nombre de un subcomando y una opción reales no da 2 (REQ-008, I1)."""
    claude = _claude_dir(tmp_path)
    argv = ["recompute-cost", "--claude-dir", str(claude), "--reset-calibration", "five_hour"]
    aliases = (
        deprecations.DeprecatedName("cli_command", "recompute-cost", "other-cmd", "UNRELEASED"),
        deprecations.DeprecatedName(
            "cli_option", "--reset-calibration", "--other-opt", "UNRELEASED"
        ),
    )
    monkeypatch.setattr(deprecations, "DEPRECATED_NAMES", aliases)
    assert deprecations.class_problems() == []
    assert _run(argv) == 0
    assert spy == ["five_hour"]
    capsys.readouterr()

    # Control: las mismas entradas, retiradas, sí cortan antes de ejecutar.
    monkeypatch.setattr(deprecations, "DEPRECATED_NAMES", retired_cli_registry(aliases))
    assert _run(argv) == 2
    assert spy == ["five_hour"]
    assert "other-cmd" in capsys.readouterr().err


def test_old_name_as_value_of_another_option_is_not_rejected(retired, capsys):
    """`--label recalcular-coste`: el subcomando solo se mira en el primer token posicional."""
    entry = _entry("cli_command")
    assert cli._reject_retired_names(["test-window", "start", "--label", entry.old]) is None
    assert _run(["test-window", "start", "--label", entry.old]) == 0
    assert entry.new not in capsys.readouterr().err


def test_unknown_command_keeps_the_argparse_error(retired, capsys):
    entry = _entry("cli_command")
    assert _run(["noexiste"]) == 2
    err = capsys.readouterr().err
    assert "noexiste" in err and entry.new in err
    assert entry.old not in err


def test_help_shows_only_the_new_names(capsys):
    command, option = _entry("cli_command"), _entry("cli_option")
    assert _run(["--help"]) == 0
    top = capsys.readouterr().out
    assert _run([command.new, "--help"]) == 0
    sub = capsys.readouterr().out
    assert command.new in top and option.new in sub
    for old in (command.old, option.old, "SUPPRESS"):
        assert old not in top + sub, old


def test_old_names_are_gone_from_the_parser():
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if a.dest == "command")
    command, option = _entry("cli_command"), _entry("cli_option")
    assert command.new in sub.choices and command.old not in sub.choices
    options = sub.choices[command.new]._option_string_actions
    assert option.new in options and option.old not in options


# --- Camino de los dos ejecutables ------------------------------------------------------------


@pytest.mark.parametrize("prog", ["local-delegate", "local-delegate-mcp"])
def test_entrypoint_goes_through_the_check(prog, retired, spy, tmp_path, monkeypatch, capsys):
    entry = _entry("cli_command")
    monkeypatch.setattr(sys, "argv", [prog, entry.old, "--claude-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        entrypoint.main()
    assert exc.value.code == 2
    assert capsys.readouterr().err == i18n.t("cli.error", detail=warning_text(entry)) + "\n"
    assert spy == []


# --- Con el registro real (L6): las dos entradas ya son retiradas con sucesor -------------------


def _real(new: str) -> deprecations.DeprecatedName:
    """La entrada real por su nombre nuevo (sin escribir el viejo)."""
    return next(e for e in deprecations.DEPRECATED_NAMES if e.new == new)


def test_real_registry_rejects_the_old_command_and_option(spy, tmp_path, capsys):
    command, option = _real("recompute-cost"), _real("--reset-calibration")
    assert command.is_retired and option.is_retired
    claude = _claude_dir(tmp_path)

    assert _run([command.old, "--claude-dir", str(claude)]) == 2
    err = capsys.readouterr().err
    assert err == i18n.t("cli.error", detail=warning_text(command)) + "\n"
    assert command.new in err and deprecations.UNRELEASED not in err
    assert _run([command.new, "--claude-dir", str(claude), option.old, "five_hour"]) == 2
    assert option.new in capsys.readouterr().err
    assert spy == []

    # Gemelo: los nombres nuevos, con los mismos datos, sí recalculan.
    assert _run([command.new, "--claude-dir", str(claude), option.new, "five_hour"]) == 0
    assert spy == ["five_hour"]


@pytest.mark.parametrize("prog", ["local-delegate", "local-delegate-mcp"])
def test_real_registry_entrypoint_rejects_the_old_command(prog, spy, tmp_path, monkeypatch, capsys):
    command = _real("recompute-cost")
    monkeypatch.setattr(sys, "argv", [prog, command.old, "--claude-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        entrypoint.main()
    assert exc.value.code == 2
    # El mensaje del chequeo previo, no el error genérico de argparse (que también da 2).
    assert capsys.readouterr().err == i18n.t("cli.error", detail=warning_text(command)) + "\n"
    assert spy == []
