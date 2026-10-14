"""El detector de idioma de D10 (`scripts/detect_language.py`), juez de la muestra de REQ-028.

El control de B0b son 20 + 20 frases congeladas (`tests/data/detect_language_control.json`). No es
un control independiente: «ambos» y «casi» entraron en la lista española a la vista de sus dos
fallos (38/40 antes del ajuste, 0/40 con las listas invertidas). Por eso aquí se exige como mucho
un fallo en 40 (≥ 97,5 %).

El control de verdad es el de B1e (`tests/data/detect_language_control_b1_20.json`): 60 + 60 frases
de al menos 20 tokens, congeladas en `cb90910` antes de correr el detector, medidas con
`min_tokens=20` y como mucho 2 fallos en 120, sin ajustar las listas a la vista de los fallos. El
inglés es traducción automática de la wiki (límite conocido; `plan.md`, D10). El primer control de
B1e, a 8 tokens (`detect_language_control_b1.json`), salió FALLIDO (116/120: el detector se abstiene
en textos cortos); se conserva como registro y aquí solo se comprueba que no cambia.
"""

from __future__ import annotations

import copy
import hashlib
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
#: B1e: el control independiente, a 20 tokens (el umbral de la muestra de REQ-028).
CONTROL_B1 = ROOT / "tests" / "data" / "detect_language_control_b1_20.json"
CONTROL_B1_MIN_TOKENS = 20
#: 0,98 sobre 120: 118 pasa, 117 no.
MAX_FAILURES_B1 = 2
#: El control a 8 tokens que falló (116/120): registro, no criterio.
CONTROL_B1_FAILED = ROOT / "tests" / "data" / "detect_language_control_b1.json"


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


def _b1_control(path: Path = CONTROL_B1) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def frozen_entry_errors(control: dict) -> list[str]:
    """Frases cuyo `sha256` ya no es el de `source + "\\n" + text` (alguien tocó el control)."""
    errors = []
    for lang in ("es", "en"):
        for entry in control[lang]:
            key = entry["source"] + "\n" + entry["text"]
            digest = hashlib.sha256(key.encode()).hexdigest()
            if digest != entry["sha256"]:
                errors.append(f"{lang}: {entry['text'][:60]}")
    return errors


def b1_failures(words: dict[str, frozenset[str]], control: dict | None = None) -> list[str]:
    control = control or _b1_control()
    failures = []
    for lang in ("es", "en"):
        for entry in control[lang]:
            found = detect_language.detect(
                entry["text"], min_tokens=CONTROL_B1_MIN_TOKENS, words=words
            )
            if found.lang != lang:
                failures.append(f"{lang} -> {found.lang}: {entry['text'][:60]}")
    return failures


def test_the_b1_control_is_frozen():
    control = _b1_control()
    assert (len(control["es"]), len(control["en"])) == (60, 60)
    assert frozen_entry_errors(control) == []
    for lang in ("es", "en"):
        for entry in control[lang]:
            assert len(entry["text"].split()) <= 40, entry
            assert len(detect_language._TOKEN.findall(entry["text"].lower())) >= 20, entry
    for entry in control["en"]:
        # La traducción se guardó sin editar: su sha256 es el de la salida literal.
        literal = hashlib.sha256(entry["translation"].encode()).hexdigest()
        assert literal == entry["translation_sha256"], entry


def test_an_altered_phrase_breaks_the_freeze():
    """Control positivo permanente: cambiar una palabra de una frase la delata por su sha256."""
    control = copy.deepcopy(_b1_control())
    control["en"][0]["text"] = control["en"][0]["text"].replace(" the ", " a ", 1)
    assert len(frozen_entry_errors(control)) == 1


def test_the_detector_passes_the_b1_control():
    failures = b1_failures(detect_language.load_function_words())
    assert len(failures) <= MAX_FAILURES_B1, failures


def test_with_the_lists_swapped_the_b1_control_fails():
    """Control positivo permanente: con las listas al revés, el control de B1 tiene que caer."""
    words = detect_language.load_function_words()
    swapped = {"es": words["en"], "en": words["es"]}
    assert len(b1_failures(swapped)) > MAX_FAILURES_B1


def test_the_failed_8_token_control_is_kept_unchanged():
    """El control a 8 tokens (FALLIDO, 116/120) es registro: no se mide, pero no se toca."""
    control = _b1_control(CONTROL_B1_FAILED)
    assert (len(control["es"]), len(control["en"])) == (60, 60)
    assert frozen_entry_errors(control) == []


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
