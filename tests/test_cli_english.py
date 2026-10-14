"""El CLI en español y en inglés (frente B, ola B1a): REQ-021, REQ-026 y REQ-034, y D8.

Cuatro cosas:

- **El armazón de argparse** («usage:», «options:», sus errores) sale en el idioma vigente. Los
  msgid salen del `argparse` del intérprete que corre la suite (`test_argparse_msgids_covered`), y
  el trabajo `cli-python-matrix` de CI corre este fichero en cada versión de Python admitida.
- **La ayuda y las salidas en inglés** no llevan ningún texto del catálogo español. El criterio
  son las *palabras distintivas*: las del catálogo español de la superficie que no aparecen en
  ningún valor del catálogo inglés. Se buscan por palabra entera, así que no les afecta cómo
  argparse parta las líneas.
- **El parche se deshace** al salir de `run()`, pase lo que pase: la suite corre en un solo
  proceso y con `xdist`.
- **Los números** con los separadores de cada idioma (REQ-026) y, en modo máquina, sin ellos.

`benchmark` (B1c) todavía no pasa por el catálogo: su ayuda no entra aquí hasta esa ola, y la
ayuda raíz, que la incluye, solo se comprueba en español.
"""

from __future__ import annotations

import argparse
import ast
import gettext
import json
import re
from importlib.resources import files
from pathlib import Path

import pytest

from local_delegate import cli, i18n, recompute

# Subcomandos cuya ayuda ya es de B1a. `benchmark` llega en B1c.
HELP_PATHS = (
    ["test-window"],
    ["test-window", "start"],
    ["test-window", "stop"],
    ["test-window", "add"],
    ["test-window", "list"],
    ["recompute-cost"],
    ["install"],
    ["update"],
    ["uninstall"],
    ["check-llamaswap"],
    ["init-llamaswap"],
    ["llamaswap"],
    ["llamaswap", "residency"],
    ["doctor"],
    ["serve"],
)
SURFACES = ("cli", "argparse")
_WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,}")
_ACCENTS = re.compile(r"[áéíóúñÁÉÍÓÚÑ¿¡«»]")


def _catalog(lang: str, surface: str) -> dict[str, str]:
    path = files("local_delegate").joinpath("resources", "i18n", lang, f"{surface}.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _distinctive_spanish_words() -> set[str]:
    """Palabras del catálogo español (cli y argparse) que no salen en ningún valor inglés."""
    english = set()
    for surface in SURFACES:
        for text in _catalog("en", surface).values():
            english.update(w.lower() for w in _WORD.findall(text))
    spanish = set()
    for surface in SURFACES:
        es, en = _catalog("es", surface), _catalog("en", surface)
        for key, text in es.items():
            if text != en[key]:
                spanish.update(w.lower() for w in _WORD.findall(text))
    return spanish - english


def _set_language(monkeypatch, lang: str) -> None:
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", lang)
    i18n.reset()


def _run(argv: list[str], capsys) -> tuple[int, str]:
    try:
        code = cli.run(argv)
    except SystemExit as exc:
        code = int(exc.code or 0)
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def _machine_names() -> list[str]:
    """Subcomandos y opciones del parser, ocultos incluidos: no se traducen (REQ-021).

    Se quitan de la salida antes de buscar palabras, porque `recalcular-coste` y
    `--reiniciar-calibracion` son alias en español que siguen vivos hasta su retirada.
    """
    names: set[str] = set()
    pending = [cli.build_parser()]
    while pending:
        parser = pending.pop()
        for action in parser._actions:
            names.update(action.option_strings)
            if isinstance(action, argparse._SubParsersAction):
                names.update(action.choices)
                pending.extend(action.choices.values())
    return sorted(names, key=len, reverse=True)


def _spanish_in(text: str, words: set[str]) -> list[str]:
    for name in _machine_names():
        text = re.sub(rf"(?<![\w-]){re.escape(name)}(?![\w-])", " ", text)
    return sorted({w for w in (m.lower() for m in _WORD.findall(text)) if w in words})


# --- D8: los msgid del argparse en ejecución -------------------------------------------------


def _runtime_msgids() -> set[str]:
    """Todo literal pasado a `_()` y a `ngettext()` en el `argparse` de este intérprete."""
    tree = ast.parse(Path(argparse.__file__).read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("_", "ngettext"):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
    return found


def test_argparse_msgids_covered():
    msgids = _runtime_msgids()
    assert len(msgids) >= 20, "el escáner no encontró los msgid: no comprobaría nada"
    en, es = _catalog("en", "argparse"), _catalog("es", "argparse")
    by_text = {text: key for key, text in en.items()}
    missing = sorted(m for m in msgids if m not in by_text)
    assert not missing, f"msgid de argparse sin clave en argparse.json: {missing}"
    untranslated = sorted(by_text[m] for m in msgids if not es.get(by_text[m]))
    assert not untranslated, f"claves de argparse sin español: {untranslated}"


# --- REQ-021: la ayuda ---------------------------------------------------------------------


@pytest.mark.parametrize("path", [[], *HELP_PATHS], ids=lambda p: " ".join(p) or "root")
def test_help_in_spanish_has_no_english_frame(path, monkeypatch, capsys):
    _set_language(monkeypatch, "es")
    code, out = _run([*path, "--help"], capsys)
    assert code == 0
    assert "uso: local-delegate" in out
    for frame in ("usage:", "options:", "show this help", "positional arguments"):
        assert frame not in out, f"armazón inglés en la ayuda española: {frame!r}"


@pytest.mark.parametrize("path", HELP_PATHS, ids=lambda p: " ".join(p))
def test_help_in_english_has_no_spanish_catalog_text(path, monkeypatch, capsys):
    words = _distinctive_spanish_words()
    assert len(words) >= 100, "sin palabras distintivas el test no discrimina"
    _set_language(monkeypatch, "en")
    code, out = _run([*path, "--help"], capsys)
    assert code == 0
    assert "usage: local-delegate" in out
    assert not _spanish_in(out, words), (
        f"texto español en la ayuda inglesa: {_spanish_in(out, words)}"
    )
    assert not _ACCENTS.search(out), out


# --- D8: el parche se deshace --------------------------------------------------------------


def test_the_patch_is_restored(monkeypatch, capsys):
    _set_language(monkeypatch, "es")
    code, _out = _run(["--help"], capsys)
    assert code == 0
    assert argparse._ is gettext.gettext
    assert argparse.ngettext is gettext.ngettext


def test_the_patch_is_restored_after_an_error(monkeypatch, capsys):
    _set_language(monkeypatch, "es")
    code, out = _run(["test-window", "bogus"], capsys)
    assert code == 2
    assert "opción no válida" in out
    assert argparse._ is gettext.gettext


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        ("es", ("error: los siguientes argumentos son obligatorios: --config, --vram-gb", "uso: ")),
        ("en", ("error: the following arguments are required: --config, --vram-gb", "usage: ")),
    ],
)
def test_errors_in_both_languages(lang, expected, monkeypatch, capsys):
    _set_language(monkeypatch, lang)
    code, out = _run(["check-llamaswap"], capsys)
    assert code == 2
    for text in expected:
        assert text in out


# --- REQ-034: humo en inglés de las salidas ------------------------------------------------


def _english_outputs(tmp_path, capsys) -> dict[str, tuple[int, str]]:
    claude = tmp_path / "claude"
    claude.mkdir()
    runs = {
        "start": ["test-window", "start", "--label", "smoke"],
        "list": ["test-window", "list"],
        "stop": ["test-window", "stop"],
        "stop_again": ["test-window", "stop"],
        "add": ["test-window", "add", "2026-10-01T00:00:00Z", "2026-10-01T01:00:00Z"],
        "add_again": ["test-window", "add", "2026-10-01T00:00:00Z", "2026-10-01T01:00:00Z"],
        "add_backwards": ["test-window", "add", "2026-10-02T00:00:00Z", "2026-10-01T00:00:00Z"],
        "recompute": ["recompute-cost", "--claude-dir", str(claude)],
        "legacy_alias": ["recalcular-coste", "--claude-dir", str(claude)],
        "init_without_models": ["init-llamaswap", "--config", "x.yaml", "--vram-gb", "8"],
        "clients_and_target": [
            "install",
            "--clients",
            "claude",
            "--target",
            "codex",
            "--home",
            str(tmp_path / "home"),
        ],
        "unknown_option": ["doctor", "--bogus"],
    }
    return {name: _run(argv, capsys) for name, argv in runs.items()}


def test_smoke_in_english(tmp_path, monkeypatch, capsys):
    words = _distinctive_spanish_words()
    _set_language(monkeypatch, "en")
    outputs = _english_outputs(tmp_path, capsys)
    # Guarda de «esto llegó a comprobar algo»: cada caso salió por el camino que se quería.
    assert outputs["stop"][0] == 0 and "closed:" in outputs["stop"][1]
    assert "there is no open window" in outputs["stop_again"][1]
    assert "added" in outputs["add"][1] and "already there" in outputs["add_again"][1]
    assert "the start has to be before the end" in outputs["add_backwards"][1]
    assert "Transcripts read:" in outputs["recompute"][1]
    assert "warning: recalcular-coste is deprecated" in outputs["legacy_alias"][1]
    assert "at least --resident or --swap" in outputs["init_without_models"][1]
    assert "cannot be combined" in outputs["clients_and_target"][1]
    assert "unrecognized arguments: --bogus" in outputs["unknown_option"][1]
    for name, (_code, out) in outputs.items():
        assert not _spanish_in(out, words), f"{name}: {_spanish_in(out, words)}\n{out}"
        assert not _ACCENTS.search(out), f"{name}: {out}"


def test_the_same_smoke_in_spanish_does_trip_the_detector(tmp_path, monkeypatch, capsys):
    """Control positivo permanente: las mismas salidas en español sí tienen palabras distintivas."""
    words = _distinctive_spanish_words()
    _set_language(monkeypatch, "es")
    outputs = _english_outputs(tmp_path, capsys)
    tripped = [name for name, (_code, out) in outputs.items() if _spanish_in(out, words)]
    assert len(tripped) >= len(outputs) - 2, tripped


# --- REQ-026: números ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lang", "value", "decimals", "expected"),
    [
        ("es", 20027, 0, "20.027"),
        ("en", 20027, 0, "20,027"),
        ("es", 1.5, 1, "1,5"),
        ("en", 1.5, 1, "1.5"),
        ("es", 1234567.891, 2, "1.234.567,89"),
        ("en", 1234567.891, 2, "1,234,567.89"),
        ("es", 45.0, None, "45"),
        ("es", 2.5, None, "2,5"),
    ],
)
def test_number_format(lang, value, decimals, expected):
    assert i18n.format_number(value, decimals, language=lang) == expected


@pytest.mark.parametrize("lang", ["es", "en"])
def test_machine_numbers_have_no_separators_in_any_language(lang, monkeypatch):
    _set_language(monkeypatch, lang)
    assert i18n.format_number(20027.5, 1, machine=True) == "20027.5"
    assert i18n.format_number(20027, machine=True) == "20027"


@pytest.mark.parametrize(("lang", "expected"), [("es", "20.027"), ("en", "20,027")])
def test_a_real_cli_output_uses_the_language_separators(lang, expected, monkeypatch):
    _set_language(monkeypatch, lang)
    summary = {
        "cleanup_days": 30,
        "transcripts": 20027,
        "corrupt_lines": 0,
        "backfilled_lines": 0,
        "matches": {},
        "n_cases": 0,
        "check": None,
        "points": {},
        "discards": {},
        "quota": {"five_hour": "calibrated", "seven_day": "calibrated"},
    }
    assert f": {expected} (" in recompute.summary_text(summary)
