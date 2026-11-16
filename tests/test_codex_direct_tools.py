"""Tools directas en Codex: `omit_tools_from = ["deferred"]` en la tabla de local-delegate (#671).

Codex 0.169 deja toda tool MCP detrás de `tool_search` salvo que la tabla del servidor declare
`omit_tools_from` con `deferred`. `install --codex-direct-tools` lo pone, `--no-codex-direct-tools`
quita solo `deferred`, y sin flag `install` y `update` conservan la lista tal cual (el comentario
de fin de línea, como en los plazos, no se conserva). Cada
caso valida el fichero con `tomllib`: una clave repetida o una lista cortada dejaría a Codex sin
ningún MCP.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest
from conftest import make_home

from local_delegate import checks, cli, i18n, update
from local_delegate import install as inst

OLD_VERSION = "0.1.0"
NEW_VERSION = "0.99.0"


def _home_real(monkeypatch, path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: path))


def _write_table(home: Path, *extra: str) -> None:
    """La entrada gestionada vieja con ``extra`` dentro, como la dejaría una persona a mano."""
    lines = inst.codex_mcp_block(inst.mcp_entry("stdio", None, False, OLD_VERSION)).split("\n")
    text = "\n".join([inst.TOML_BEGIN, lines[0], *extra, *lines[1:], inst.TOML_END, ""])
    (home / ".codex" / "config.toml").write_text(text, encoding="utf-8")


def _home(monkeypatch, tmp_path: Path, *extra: str) -> Path:
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=False, codex=True, opencode=False, complete=False)
    _write_table(home, *extra)
    return home


def _install(home: Path, *flags: str) -> int:
    argv = ["install", "--home", str(home), "--clients", "codex"]
    argv += ["--no-hooks", "--no-skill", "--no-memory", *flags]
    return cli.run(argv)


def _text(home: Path) -> str:
    return (home / ".codex" / "config.toml").read_text(encoding="utf-8")


def _table(home: Path) -> dict:
    return tomllib.loads(_text(home))["mcp_servers"][inst.SERVER_NAME]


def _rewritten(home: Path) -> None:
    """Guarda: la tabla se reescribió de verdad (el pin viejo ya no está)."""
    assert f"=={OLD_VERSION}" not in _text(home)


# --- install con flag -----------------------------------------------------------------------
def test_the_flag_writes_deferred_in_the_codex_table(monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path)

    assert _install(home, "--codex-direct-tools") == 0

    _rewritten(home)
    assert _table(home)["omit_tools_from"] == ["deferred"]


def test_without_the_flag_nothing_is_added(monkeypatch, tmp_path):
    """Control: el valor por defecto no inventa la clave (cuesta ~15 KB por turno en Codex)."""
    home = _home(monkeypatch, tmp_path)

    assert _install(home) == 0

    _rewritten(home)
    assert "omit_tools_from" not in _table(home)


def test_the_flag_adds_deferred_to_a_hand_written_list(monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path, 'omit_tools_from = ["code_mode"]')

    assert _install(home, "--codex-direct-tools") == 0

    assert _table(home)["omit_tools_from"] == ["code_mode", "deferred"]
    assert _text(home).count("omit_tools_from") == 1


def test_the_no_flag_removes_only_deferred(monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path, 'omit_tools_from = ["deferred", "code_mode"]')

    assert _install(home, "--no-codex-direct-tools") == 0

    assert _table(home)["omit_tools_from"] == ["code_mode"]


def test_the_no_flag_drops_a_list_left_empty(monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path, 'omit_tools_from = ["deferred"]')

    assert _install(home, "--no-codex-direct-tools") == 0

    _rewritten(home)
    assert "omit_tools_from" not in _table(home)


# --- install sin flag: se conserva lo escrito a mano --------------------------------------------
@pytest.mark.parametrize(
    "line",
    [
        'omit_tools_from = ["deferred", "code_mode"]   # puesto a mano',
        'omit_tools_from = [\n  "deferred",\n  "code_mode",\n]',
    ],
    ids=["one-line-with-spaces-and-comment", "multi-line"],
)
def test_without_flag_a_hand_written_list_is_kept_whole(monkeypatch, tmp_path, line):
    """La lista con espacios o en varias líneas sale entera: cortarla daría TOML inválido."""
    home = _home(monkeypatch, tmp_path, line)

    assert _install(home) == 0
    assert _install(home) == 0

    _rewritten(home)
    assert _table(home)["omit_tools_from"] == ["deferred", "code_mode"]
    assert _text(home).count("omit_tools_from") == 1
    # El texto de la lista sale tal cual, no rehecho (sin el comentario de fin de línea).
    assert line.split("=", 1)[1].split("#")[0].strip() in _text(home)


@pytest.mark.parametrize("flags", [(), ("--codex-direct-tools",)], ids=["no-flag", "flag"])
def test_a_bracket_in_a_comment_inside_the_list_loses_nothing(monkeypatch, tmp_path, flags):
    """La regex se para en el `]` del comentario; los valores salen de `tomllib`, no de ella."""
    line = 'omit_tools_from = [\n  "deferred", # ver [docs]\n  "code_mode",\n]'
    home = _home(monkeypatch, tmp_path, line)

    assert _install(home, *flags) == 0

    _rewritten(home)
    assert _table(home)["omit_tools_from"] == ["deferred", "code_mode"]
    assert i18n.t("doctor.probe.mcp_codex.direct_tools") in _codex_detail(home)


def test_the_flag_keeps_a_list_that_already_has_deferred_byte_for_byte(monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path, "omit_tools_from = ['deferred',   'code_mode']")

    assert _install(home, "--codex-direct-tools") == 0

    _rewritten(home)
    assert "omit_tools_from = ['deferred',   'code_mode']" in _text(home)


def test_the_two_flags_exclude_each_other(monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path)

    with pytest.raises(SystemExit):
        _install(home, "--codex-direct-tools", "--no-codex-direct-tools")


def test_a_value_that_is_not_a_list_of_strings_is_not_carried_over(monkeypatch, tmp_path):
    """Texto que no es una lista TOML de textos no se reemite: el fichero sale válido."""
    home = _home(monkeypatch, tmp_path, "omit_tools_from = [deferred]")

    assert _install(home) == 0

    _rewritten(home)
    assert "omit_tools_from" not in _table(home)


def test_the_flag_ignored_without_codex_says_so(monkeypatch, tmp_path, capsys):
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, claude=True, codex=False, opencode=False, complete=False)
    argv = ["install", "--home", str(home), "--clients", "claude", "--no-hooks", "--no-skill"]
    argv += ["--no-memory", "--codex-direct-tools", "--dry-run"]

    cli.run(argv)

    assert i18n.t("cli.install.codex_direct_tools_ignored") in capsys.readouterr().out


def test_the_flag_with_no_mcp_says_so(monkeypatch, tmp_path, capsys):
    home = _home(monkeypatch, tmp_path)

    _install(home, "--no-mcp", "--codex-direct-tools", "--dry-run")

    assert i18n.t("cli.install.codex_direct_tools_ignored") in capsys.readouterr().out


def _write_hand_table(home: Path, *extra: str) -> None:
    """La entrada sin marcadores, como la escribiría una persona."""
    lines = inst.codex_mcp_block(inst.mcp_entry("stdio", None, False, OLD_VERSION)).split("\n")
    text = "\n".join([lines[0], *extra, *lines[1:], ""])
    (home / ".codex" / "config.toml").write_text(text, encoding="utf-8")


def test_a_refused_hand_entry_says_the_flag_did_nothing(monkeypatch, tmp_path, capsys):
    """Sin terminal no se reemplaza la entrada a mano: el flag no puede tener efecto."""
    home = _home(monkeypatch, tmp_path)
    _write_hand_table(home)
    monkeypatch.setattr(cli, "_has_terminal", lambda: False)

    _install(home, "--codex-direct-tools")

    assert i18n.t("cli.install.codex_direct_tools_ignored") in capsys.readouterr().out
    assert "omit_tools_from" not in _text(home)


def test_a_replaced_hand_entry_keeps_its_list(monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path)
    _write_hand_table(home, 'omit_tools_from = ["deferred", "code_mode"]')

    assert _install(home, "--force-mcp-codex") == 0

    _rewritten(home)
    assert inst.TOML_BEGIN in _text(home)
    assert _table(home)["omit_tools_from"] == ["deferred", "code_mode"]


# --- update ----------------------------------------------------------------------------------
def test_update_keeps_the_hand_written_list(monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path, 'omit_tools_from = ["deferred", "code_mode"]')
    opts = update.Options(
        home=home,
        version=NEW_VERSION,
        no_restart=True,
        runner=lambda argv: subprocess.CompletedProcess(argv, 0, "", ""),
        daemon_status=lambda host, port: None,
        sleep=lambda s: None,
        spawn=lambda argv: None,
    )

    update.run_update(opts, out=lambda *a: None)

    assert f"local-delegate-mcp=={NEW_VERSION}" in _text(home)
    assert _table(home)["omit_tools_from"] == ["deferred", "code_mode"]


def test_update_that_repairs_the_codex_entry_keeps_the_list(monkeypatch, tmp_path):
    """El camino en que `update` llama a `install` (`repair_install_options`) con `None`."""
    home = _home(monkeypatch, tmp_path, 'omit_tools_from = ["deferred"]')
    results = [
        (
            check,
            checks.Result(checks.MISSING if check.id == "scaffold.mcp_codex" else checks.OK, "x"),
        )
        for check in checks.CHECKS
    ]
    actions, _notes = update.plan_repairs(results, update.Options(home=home))
    assert any(a.kind == "toml" and str(a.target).endswith("config.toml") for a in actions)

    inst.apply(actions, dry_run=False, out=lambda *a: None)

    _rewritten(home)
    assert _table(home)["omit_tools_from"] == ["deferred"]


# --- doctor ----------------------------------------------------------------------------------
def _codex_detail(home: Path) -> str:
    probe = {c.id: c for c in checks.CHECKS}["scaffold.mcp_codex"].probe
    ctx = checks.Context(
        home=home, daemon_status=lambda host, port: None, latest_release=checks.SKIP_PYPI
    )
    return probe(ctx).detail


def test_doctor_says_the_tools_are_direct(monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path, 'omit_tools_from = ["deferred"]')

    assert i18n.t("doctor.probe.mcp_codex.direct_tools") in _codex_detail(home)


@pytest.mark.parametrize("extra", [(), ('omit_tools_from = ["code_mode"]',)], ids=["none", "other"])
def test_doctor_is_silent_without_deferred(monkeypatch, tmp_path, extra):
    home = _home(monkeypatch, tmp_path, *extra)

    assert i18n.t("doctor.probe.mcp_codex.direct_tools") not in _codex_detail(home)


# --- textos -------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "key",
    [
        "cli.help.install.codex_direct_tools",
        "cli.help.install.no_codex_direct_tools",
        "cli.install.codex_direct_tools_ignored",
        "install.mcp.codex_direct_tools",
        "doctor.probe.mcp_codex.direct_tools",
    ],
)
def test_the_new_texts_exist_in_both_languages(key):
    es, en = i18n.t_lang("es", key), i18n.t_lang("en", key)
    assert es != key and en != key and es != en
