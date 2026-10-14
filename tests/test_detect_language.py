"""El detector de idioma de D10 (`scripts/detect_language.py`), juez de la muestra de REQ-028.

El control de B0b son 20 + 20 frases congeladas (`tests/data/detect_language_control.json`). No es
un control independiente: «ambos» y «casi» entraron en la lista española a la vista de sus dos
fallos (38/40 antes del ajuste, 0/40 con las listas invertidas). Por eso aquí se exige como mucho
un fallo en 40 (≥ 97,5 %). El control de verdad llega en B1: 60 + 60 frases nuevas, congeladas
antes de ver la lista, con ≥ 98 % (como mucho 2 fallos en 120) y sin ajustar las listas a la vista
de los fallos.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "detect_language.py"
CONTROL = ROOT / "tests" / "data" / "detect_language_control.json"
#: B0b: como mucho un fallo en 40. B1 lo sube a 0.98 sobre 60 + 60 frases nuevas.
MIN_ACCURACY = 0.975
#: Las frases del control tienen 8 palabras o más; el umbral por defecto (20) es el de la muestra.
CONTROL_MIN_TOKENS = 8


def _load_module():
    spec = importlib.util.spec_from_file_location("detect_language", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["detect_language"] = module
    spec.loader.exec_module(module)
    return module


detect_language = _load_module()


def _control() -> dict[str, list[dict]]:
    data = json.loads(CONTROL.read_text(encoding="utf-8"))
    return {"es": data["es"], "en": data["en"]}


def accuracy(words: dict[str, frozenset[str]]) -> float:
    control = _control()
    total = hits = 0
    for lang, entries in control.items():
        for entry in entries:
            total += 1
            found = detect_language.detect(
                entry["text"], min_tokens=CONTROL_MIN_TOKENS, words=words
            )
            hits += found.lang == lang
    return hits / total


def test_the_control_is_the_frozen_20_plus_20():
    control = _control()
    assert (len(control["es"]), len(control["en"])) == (20, 20)
    for entries in control.values():
        for entry in entries:
            assert len(entry["text"].split()) >= 8, entry
            assert entry["source"], entry


def test_the_detector_passes_its_control():
    assert accuracy(detect_language.load_function_words()) >= MIN_ACCURACY


def test_with_the_lists_swapped_the_control_fails():
    """Control positivo permanente: si el control no cae con las listas al revés, no mide nada."""
    words = detect_language.load_function_words()
    assert accuracy({"es": words["en"], "en": words["es"]}) < MIN_ACCURACY


def test_the_lists_are_disjoint_and_big_enough():
    words = detect_language.load_function_words()
    assert not words["es"] & words["en"]
    assert len(words["es"]) >= 120 and len(words["en"]) >= 120
    # Las que comparten los dos idiomas quedan fuera a propósito.
    assert not {"a", "no", "me", "era", "come", "os"} & (words["es"] | words["en"])


def test_too_few_tokens_is_unknown():
    text = "el modelo resume el fichero y devuelve el texto"
    assert detect_language.detect(text).lang == "unknown"  # 9 < 20
    assert detect_language.detect(text, min_tokens=8).lang == "es"


def test_a_small_margin_is_unknown():
    text = " ".join(["el"] * 10 + ["the"] * 9 + ["modelo"] * 5)
    result = detect_language.detect(text)
    assert result.tokens == 24
    # 0,15 es el margen que fija D10; se escribe aquí a propósito, no se lee del módulo.
    assert abs(result.es_ratio - result.en_ratio) < 0.15
    assert result.lang == "unknown"


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        (
            "Esta es una prueba del detector, que cuenta las palabras funcionales de cada idioma "
            * 2,
            "es",
        ),
        (
            "This is a test of the detector, which counts the function words of each language " * 2,
            "en",
        ),
        ("", "unknown"),
    ],
)
def test_detect_decides_by_function_words(text, lang):
    assert detect_language.detect(text).lang == lang


def test_the_command_prints_one_json_line_per_file(tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text(
        "Este es el texto que se resume, y es para la prueba del detector. " * 3, "utf-8"
    )
    out = subprocess.run(
        [sys.executable, str(SCRIPT), str(sample)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    ).stdout.strip()
    row = json.loads(out)
    assert set(row) == {"path", "lang", "tokens", "es_ratio", "en_ratio"}
    assert row["lang"] == "es"
