"""Los tres scripts de B1 en español y en inglés (frente B, ola B1d): REQ-021, REQ-026 y REQ-034.

- `scripts/script_i18n.py` da lo mismo que `local_delegate.i18n` (idioma, textos y números) sin
  importar el paquete, que `pair_sheet.py` y `analyze_benchmark.py` no pueden importar.
- `pair_sheet` escribe la hoja en el idioma del proceso y lee las dos formas: la hoja congelada de
  `benchmarks/afinidad-2026-10/hoja/` (española, con «si», «parcial» y «empate») se lee igual con el
  proceso en inglés, y una hoja inglesa se lee con el proceso en español.
- La elección «=» se escribe `tie` en `unblind --json` y `analyze_benchmark` lee `tie` y `empate`.
- Humo en inglés de los informes de `measure_cooldown` y `analyze_benchmark`, sin palabras
  distintivas del catálogo español, con su control positivo permanente en español.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from importlib.resources import files
from pathlib import Path

import pytest

from local_delegate import i18n

ROOT = Path(__file__).parents[1]
FROZEN_AFFINITY = ROOT / "benchmarks" / "afinidad-2026-10"
SCRIPTS = ("measure_cooldown.py", "pair_sheet.py", "analyze_benchmark.py")
_WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,}")
_ACCENTS = re.compile(r"[áéíóúñÁÉÍÓÚÑ¿¡«»]")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pair_sheet = _load("pair_sheet")
analyze = _load("analyze_benchmark")
measure_cooldown = _load("measure_cooldown")
script_i18n = sys.modules["script_i18n"]


def _set_language(monkeypatch, lang: str) -> None:
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", lang)
    i18n.reset()
    script_i18n.reset()


def _catalog(lang: str) -> dict[str, str]:
    path = files("local_delegate").joinpath("resources", "i18n", lang, "cli.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _distinctive_spanish_words() -> set[str]:
    es, en = _catalog("es"), _catalog("en")
    english = {w.lower() for text in en.values() for w in _WORD.findall(text)}
    spanish = {
        w.lower() for key, text in es.items() if text != en[key] for w in _WORD.findall(text)
    }
    return spanish - english


def _spanish_in(text: str, words: set[str]) -> list[str]:
    return sorted({w for w in (m.lower() for m in _WORD.findall(text)) if w in words})


# --- script_i18n: lo mismo que el paquete ---------------------------------------------------------


@pytest.mark.parametrize("lang", ["es", "en"])
def test_script_i18n_gives_the_same_as_the_package(lang, monkeypatch):
    _set_language(monkeypatch, lang)
    assert script_i18n.lang() == i18n.lang() == lang
    for key in ("cli.script.pair_sheet.better", "cli.script.measure_cooldown.result.keep"):
        assert script_i18n.t(key) == i18n.t(key)
    assert script_i18n.t("cli.script.pair_sheet.generated", n=3, path="x") == i18n.t(
        "cli.script.pair_sheet.generated", n=3, path="x"
    )
    for value, decimals in ((20027, 0), (1.5, 1), (1234567.891, 2), (2.5, None)):
        assert script_i18n.format_number(value, decimals) == i18n.format_number(value, decimals)


def test_script_i18n_follows_the_language_file_like_the_package(tmp_path, monkeypatch):
    """Sin la variable, la preferencia de `language.json` del `LOG_DIR` (la regla de `hook_common`)."""
    monkeypatch.delenv("LOCAL_DELEGATE_LANG")
    (tmp_path / "language.json").write_text(json.dumps({"lang": "en"}), encoding="utf-8")
    i18n.reset()
    script_i18n.reset()
    assert script_i18n.lang() == i18n.lang() == "en"


def _keys_used(path: Path) -> list[tuple[int, str]]:
    """Las claves literales de `t(...)`, `t_lang(_, ...)` y de los atajos `_t("sufijo")`."""
    prefix = f"cli.script.{path.stem}."
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        arg = node.args[0]
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
            continue
        if name == "t" and arg.value.startswith("cli."):
            found.append((node.lineno, arg.value))
        elif name == "_t":
            found.append((node.lineno, prefix + arg.value))
    return found


def test_every_key_the_scripts_use_exists():
    known = _catalog("es").keys() & _catalog("en").keys()
    used = [
        (name, line, key) for name in SCRIPTS for line, key in _keys_used(ROOT / "scripts" / name)
    ]
    assert len(used) > 100, "el escáner no encontró las claves: no comprobaría nada"
    assert [u for u in used if u[2] not in known] == []


# --- pair_sheet: la hoja en el idioma del proceso y el lector de las dos formas -------------------

_SPANISH_WORDS = {"s": "si", "n": "no", "p": "parcial"}


def _fill_frozen_sheet(answers: dict) -> str:
    """La hoja congelada (española) contestada a mano como la contestaría una persona en español."""
    filled = []
    pair = None
    names = {"Inventa": "inventa", "Lo principal": "principal", "Específico": "especifico"}
    for line in (FROZEN_AFFINITY / "hoja" / "hoja-1.md").read_text(encoding="utf-8").splitlines():
        if m := re.match(r"^## Par (\d+)\s*$", line):
            pair = answers["respuestas"].get(m.group(1), {})
        elif pair is not None:
            for label, question in names.items():
                if m := re.match(rf"^{label} ([AB]) \(", line):
                    value = (pair.get(question) or {}).get(m.group(1))
                    if value:
                        line = f"{line.rstrip()} {_SPANISH_WORDS[value]}"
            if line.startswith("Mejor (A/B/=):") and pair.get("preferencia"):
                choice = pair["preferencia"]
                line = f"Mejor (A/B/=): {'empate' if choice == '=' else choice}"
        filled.append(line)
    return "\n".join(filled)


def test_the_frozen_spanish_sheet_is_read_with_the_process_in_english(monkeypatch):
    """La hoja congelada, contestada con «si», «parcial» y «empate», se lee con el proceso en inglés
    y da el mismo juicio que las respuestas de la página (`respuestas-1.json`)."""
    key = json.loads((FROZEN_AFFINITY / "clave" / "clave-1.json").read_text(encoding="utf-8"))
    answers = json.loads(
        (FROZEN_AFFINITY / "hoja" / "respuestas-1.json").read_text(encoding="utf-8")
    )
    rules = pair_sheet.read_rules(FROZEN_AFFINITY / "reglas.json")
    sheet = _fill_frozen_sheet(answers)
    # Control: la hoja lleva de verdad las palabras españolas, también «empate» (2 pares).
    assert sheet.count("Mejor (A/B/=): empate") == 2 and " parcial\n" in sheet
    _set_language(monkeypatch, "en")
    from_md, missing = pair_sheet.read_commit(pair_sheet.md_answers(sheet), key, rules)
    from_page, _ = pair_sheet.read_commit(answers, key, rules)
    assert missing == []
    assert from_md == from_page
    assert sum(p["preference"] == "=" for p in from_md["pairs"].values()) == 2


def _minimal_sheet() -> tuple[dict, dict]:
    sheet = {
        "id": "a" * 64,
        "n": 7,
        "optional": [],
        "pairs": [
            {
                "num": "01",
                "files": 1,
                "more": 2,
                "fewer": 1,
                "diff": "diff --git a/x b/x",
                "A": "feat: x",
                "B": "fix: y",
            }
        ],
    }
    key = {
        "schema_version": 1,
        "sheet": 7,
        "sha256": "a" * 64,
        "label_26b": "m26",
        "label_qwen": "mq",
        "pairs": {"01": {"kind": "real", "case": "c1", "sides": {"A": "m26", "B": "mq"}}},
    }
    return sheet, key


def _frozen_rules() -> dict:
    rules = pair_sheet.read_rules(FROZEN_AFFINITY / "reglas.json")
    return {**rules, "optional_questions": []}


def test_an_english_sheet_is_read_with_the_process_in_spanish(monkeypatch):
    sheet, key = _minimal_sheet()
    rules = _frozen_rules()
    _set_language(monkeypatch, "en")
    md = pair_sheet.render_md(sheet, rules)
    assert "Invents A (y/n):" in md and "Better (A/B/=):" in md and "## Pair 01" in md
    answers = {
        "Invents A": "yes",
        "Invents B": "no",
        "Main point A": "partial",
        "Main point B": "y",
        "Specific A": "yes",
        "Specific B": "n",
        "Better": "tie",
    }
    lines = []
    for line in md.splitlines():
        for start, value in answers.items():
            if line.startswith(start + " ("):
                line = f"{line.rstrip()} {value}"
        lines.append(line)
    _set_language(monkeypatch, "es")
    judgement, missing = pair_sheet.read_commit(pair_sheet.md_answers("\n".join(lines)), key, rules)
    assert missing == []
    pair = judgement["pairs"]["01"]
    assert pair["made_up"] == {"A": "s", "B": "n"}
    assert pair["principal"] == {"A": "p", "B": "s"}
    assert pair["specific"] == {"A": "s", "B": "n"}
    assert pair["preference"] == "="


@pytest.mark.parametrize(
    ("lang", "present", "absent"),
    [
        ("en", ('lang="en"', "Download answers", "Can I stop now?"), ("Descargar respuestas",)),
        ("es", ('lang="es"', "Descargar respuestas", "¿Puedo parar ya?"), ("Download answers",)),
    ],
)
def test_the_page_follows_the_language(lang, present, absent, monkeypatch):
    sheet, _key = _minimal_sheet()
    _set_language(monkeypatch, lang)
    page = pair_sheet.render_html(sheet, _frozen_rules())
    for text in present:
        assert text in page, text
    for text in absent:
        assert text not in page, text
    texts = json.loads(
        page.split('<script type="application/json" id="textos">', 1)[1].split("<")[0]
    )
    assert set(texts) == set(pair_sheet._PAGE_TEXTS)
    assert texts["tie"] == ("Tie" if lang == "en" else "Empate")


def test_the_p15_sheet_is_read_in_both_forms():
    spanish = "## Par 01\n\nMejor (A/B/=): A\n\n## Par 02\n\nMejor (A/B/=): =\n"
    english = spanish.replace("## Par", "## Pair").replace("Mejor", "Better")
    assert (
        pair_sheet.read_choices(spanish)
        == pair_sheet.read_choices(english)
        == {
            "01": "A",
            "02": "=",
        }
    )


def test_analyze_reads_tie_and_the_old_word():
    """`human` de `unblind --json`: `tie` desde el frente B, `empate` antes; los dos cuentan."""
    corpus = {"open-1": {"role": "long", "kind": "quality", "automatic_scoring": False}}
    pairs = {"open-1": {"human": {"cand": 4, "inc": 1, "tie": 2, "empate": 3}}}
    count = analyze.pairs_for_role(pairs, corpus, "long", "inc", "cand")
    assert (count["candidate"], count["incumbent"], count["ties"]) == (4, 1, 5)


# --- Humo de los informes en inglés ---------------------------------------------------------------


def _reports() -> dict[str, str]:
    measurement = measure_cooldown.measure(None, None, [], include_tests=True)
    measurement.update(
        {"result": "change", "rule": 1, "noted": [4], "R": 0.75}
        | {"outside_p4_immediate_failures_over_5_pct": True, "delegations": 20027}
    )
    cp3 = {
        "small": "v",
        "large": "c",
        "entry_control": True,
        "roles": {
            "code": {
                "aggregate": {"small": 1.0, "large": 0.5, "separates": True},
                "passes": False,
                "band": 0.125,
                "admitted_cases": ["x"],
                "cases": {
                    "x": {
                        "small": 1.0,
                        "large": 0.5,
                        "difference": -0.5,
                        "band": 0.125,
                        "separates": True,
                        "reason": None,
                    },
                    "y": {"small": 1.0, "large": 1.0, "separates": False, "reason": "ceiling"},
                },
                "can_fire": False,
                "review_only": ["z"],
            }
        },
    }
    verdict = {
        "cells": [
            {
                "tool": "local_commit_msg",
                "alternative": "a",
                "compared_role": "r",
                "state": "no_baseline",
                "report": "repetir hoja",
                "criteria": {"valid_sheet": {"ok": False}},
                "published": {"a": dict.fromkeys(analyze._PUBLISHED_ROW, 1)},
            }
        ]
    }
    return {
        "measure_cooldown": measure_cooldown.report(measurement),
        "cp3": analyze.cp3_report(cp3),
        "verdict": analyze.verdict_table(verdict),
        "stop": pair_sheet.stop_text(pair_sheet.CAN_STOP),
    }


def test_the_reports_in_english_have_no_spanish(monkeypatch):
    words = _distinctive_spanish_words()
    assert len(words) >= 100, "sin palabras distintivas el test no discrimina"
    _set_language(monkeypatch, "en")
    reports = _reports()
    # Guarda de «esto llegó a comprobar algo» y números con los separadores ingleses.
    assert "RESULT: change" in reports["measure_cooldown"]
    assert "Delegations:               20,027" in reports["measure_cooldown"]
    assert "(R: 0.75)" in reports["measure_cooldown"]
    assert "| x | 1.000 | 0.500 | -0.500 | 0.125 | yes |" in reports["cp3"]
    assert "| no baseline (repeat the sheet) |" in reports["verdict"]
    assert reports["stop"] == "you can stop"
    for name, text in reports.items():
        assert not _spanish_in(text, words), f"{name}: {_spanish_in(text, words)}\n{text}"
        assert not _ACCENTS.search(text), f"{name}: {text}"


def test_the_same_reports_in_spanish_do_trip_the_detector(monkeypatch):
    """Control positivo permanente: en español sí hay palabras distintivas, y coma decimal."""
    words = _distinctive_spanish_words()
    _set_language(monkeypatch, "es")
    reports = _reports()
    assert all(_spanish_in(text, words) for text in reports.values()), reports
    assert "Delegaciones:              20.027" in reports["measure_cooldown"]
    assert "| x | 1,000 | 0,500 | -0,500 | 0,125 | si |" in reports["cp3"]


@pytest.mark.parametrize(
    ("lang", "frame", "foreign"), [("es", "uso: ", "usage: "), ("en", "usage: ", "uso: ")]
)
def test_the_argparse_frame_of_the_scripts_follows_the_language(
    lang, frame, foreign, monkeypatch, capsys
):
    """D8 en los scripts: «usage:»/«uso:» como en el CLI, y el parche se deshace al salir."""
    import argparse
    import gettext

    _set_language(monkeypatch, lang)
    monkeypatch.setattr(sys, "argv", ["measure_cooldown.py", "--help"])
    runs = (
        lambda: pair_sheet.main(["read-commit", "--help"]),
        lambda: analyze.main(["decide", "--help"]),
        measure_cooldown.main,
    )
    for run in runs:
        with pytest.raises(SystemExit):
            run()
        out = capsys.readouterr().out
        assert out.startswith(frame) and foreign not in out, out
        assert argparse._ is gettext.gettext and argparse.ngettext is gettext.ngettext
