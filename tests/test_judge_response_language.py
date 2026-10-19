"""El juez de idioma «solo prosa» (`scripts/judge_response_language.py`, frente B, ola B2d).

Casos sintéticos, no los fallos vistos en vivo. Cada regla de exclusión (R1-R8) tiene un caso en
la frontera: 19 tokens de prosa más un elemento que solo esa regla quita. Con la regla, quedan 19
(`not_judgeable`); sin ella (el mutante), el elemento aporta tokens, se llega a 20 y el veredicto
cambia. Los mutantes aplicados de verdad están en `evidence/B2d-fix/judge-mutants.md`.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "judge_response_language.py"
_spec = importlib.util.spec_from_file_location("judge_response_language", SCRIPT)
assert _spec is not None and _spec.loader is not None
judge_mod = importlib.util.module_from_spec(_spec)
sys.modules["judge_response_language"] = judge_mod
_spec.loader.exec_module(judge_mod)

EN_WORDS = [
    "the",
    "summary",
    "of",
    "this",
    "log",
    "is",
    "written",
    "in",
    "plain",
    "words",
    "and",
    "it",
    "says",
    "what",
    "failed",
    "with",
    "each",
    "check",
    "for",
    "you",
    "today",
]
ES_WORDS = [
    "el",
    "resumen",
    "de",
    "este",
    "registro",
    "está",
    "escrito",
    "en",
    "palabras",
    "simples",
    "y",
    "dice",
    "qué",
    "falló",
    "con",
    "cada",
    "prueba",
    "para",
    "ti",
    "hoy",
]
DOCUMENT = "# Guía\n\nTexto.\n\n## Configuración del sistema\n\nMás texto.\n\n## Errores\n\nFin.\n"
LIMIT = judge_mod.MIN_TOKENS


def en(n: int) -> str:
    return " ".join(EN_WORDS[i % len(EN_WORDS)] for i in range(n))


def es(n: int) -> str:
    return " ".join(ES_WORDS[i % len(ES_WORDS)] for i in range(n))


def run(response: str, requested: str = "en", document: str = DOCUMENT):
    return judge_mod.judge(response, document, requested)


def assert_excluded(response: str) -> None:
    """19 tokens de prosa + algo que solo una regla quita: debe quedar fuera del juicio."""
    result = run(response)
    assert result.tokens == LIMIT - 1, (result.tokens, result.judged_text)
    assert result.verdict == "not_judgeable", result


# --- Veredictos ----------------------------------------------------------------------------------


def test_the_threshold_is_the_detectors_own():
    import detect_language

    assert LIMIT == detect_language.MIN_TOKENS == 20
    assert judge_mod.MIN_MARGIN == detect_language.MIN_MARGIN == 0.15


def test_enough_prose_in_the_requested_language_is_requested():
    result = run(en(LIMIT))
    assert result.verdict == "requested"
    assert result.lang == "en"
    assert result.tokens == LIMIT


def test_prose_in_the_other_language_is_opposite():
    result = run(es(30))
    assert result.verdict == "opposite"
    assert result.lang == "es"


def test_the_requested_language_is_spanish_too():
    assert run(es(30), requested="es").verdict == "requested"
    assert run(en(30), requested="es").verdict == "opposite"


def test_a_half_and_half_mix_is_unknown():
    result = run(en(15) + " " + es(15))
    assert result.verdict == "unknown"
    assert result.margin < judge_mod.MIN_MARGIN


def test_one_token_short_is_not_judgeable_and_not_a_failure():
    result = run(en(LIMIT - 1))
    assert result.verdict == "not_judgeable"
    assert result.lang == "not_judged"


def test_an_unknown_requested_language_is_refused():
    with pytest.raises(ValueError):
        run(en(30), requested="fr")


# --- Lo que NO se excluye -------------------------------------------------------------------------


def test_bold_labels_are_judged():
    result = run(en(LIMIT - 1) + "\n**Errores:**")
    assert result.tokens == LIMIT
    assert "Errores" in result.judged_text


def test_copied_bold_labels_in_the_other_language_weigh_against():
    response = "\n".join(f"- **{w} de la prueba**: {w}" for w in ES_WORDS[:12]) + "\n" + en(10)
    assert run(response).verdict != "requested"


def test_a_heading_not_in_the_document_is_judged():
    result = run("## The section about the setup\n" + en(LIMIT - 1))
    assert result.tokens == LIMIT - 1 + 5
    assert "section about the setup" in result.judged_text


def test_a_translated_document_heading_is_judged():
    result = run("## System configuration\n" + en(LIMIT - 1))
    assert result.tokens == LIMIT + 1


# --- Una frontera por regla (R1-R8) ----------------------------------------------------------------


def test_r1_product_lines_are_dropped():
    assert_excluded(en(LIMIT - 1) + "\n\n(read server-side: some file of the repo)")
    assert_excluded(en(LIMIT - 1) + "\n(sin resumir)")
    assert_excluded(en(LIMIT - 1) + "\n[local-delegate warning: one section not summarized]")


def _not_mentioned_lines() -> list[tuple[str, str, str]]:
    """(language, key, line) for every `NOT_MENTIONED_KEYS` in every catalog language."""
    from importlib.resources import files

    from local_delegate import i18n

    root = files("local_delegate").joinpath("resources", "i18n")
    languages = sorted(item.name for item in root.iterdir() if item.is_dir())
    return [
        (lang, key, i18n.t_lang(lang, key, items="alpha, beta, gamma"))
        for lang in languages
        for key in judge_mod.NOT_MENTIONED_KEYS
    ]


def test_r1_the_not_mentioned_line_comes_from_every_catalog_language():
    lines = _not_mentioned_lines()
    # Guard that the case below checks something: es and en today, both keys, real catalog text.
    assert {lang for lang, _key, _line in lines} >= {"es", "en"}
    assert len(judge_mod.NOT_MENTIONED_PREFIXES) == len(lines)
    for _lang, key, line in lines:
        assert line != key and "alpha, beta, gamma" in line, (key, line)


def test_r1_the_not_mentioned_line_is_dropped_in_every_language():
    for lang, key, line in _not_mentioned_lines():
        result = run(en(LIMIT - 1) + "\n\n" + line)
        assert result.tokens == LIMIT - 1, (lang, key, result.judged_text)
        assert result.verdict == "not_judgeable", (lang, key, result)


def test_r1_the_not_mentioned_text_inside_a_sentence_is_judged():
    # Positive control: only the whole product line goes, not the same words quoted in prose.
    _lang, _key, line = _not_mentioned_lines()[0]
    result = run(en(LIMIT - 1) + " " + line)
    assert result.tokens > LIMIT, result.judged_text


def test_r2_a_document_heading_copied_literally_is_dropped():
    assert_excluded("## Configuración del sistema\n" + en(LIMIT - 1))


def test_r2_matches_after_normalization():
    assert_excluded("### 2. CONFIGURACION DEL SISTEMA ##\n" + en(LIMIT - 1))


def test_r3_inline_code_is_dropped():
    assert_excluded(en(LIMIT - 1) + " `return the value`")


def test_r3_fenced_code_is_dropped():
    assert_excluded(en(LIMIT - 1) + "\n```text\nthe and of in\n```\n")


def test_r4_only_the_url_goes_not_the_link_text():
    result = run(en(LIMIT - 2) + " [guide](https://example.org/a/b)")
    assert result.tokens == LIMIT - 1
    assert "guide" in result.judged_text


def test_r5_paths_are_dropped():
    assert_excluded(en(LIMIT - 1) + " src/app/main C:\\tools\\bin")


def test_r8_rule_codes_with_digits_are_dropped():
    assert_excluded(en(LIMIT - 1) + " E501 I001 UP006 TS2345")


def test_r6_kebab_rule_names_are_dropped():
    assert_excluded(en(LIMIT - 1) + " no-unused-vars")


def test_r7_identifiers_are_dropped():
    assert_excluded(en(LIMIT - 1) + " load_config parseArgs")


def test_r8_numbers_are_dropped():
    assert_excluded(en(LIMIT - 1) + " 12ms 57")


# --- CLI ------------------------------------------------------------------------------------------


def test_cli_prints_one_json_line_per_response(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text(DOCUMENT, encoding="utf-8")
    good = tmp_path / "good.txt"
    good.write_text(en(30), encoding="utf-8")
    short = tmp_path / "short.txt"
    short.write_text(en(5), encoding="utf-8")
    out = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--document",
            str(doc),
            "--requested",
            "en",
            str(good),
            str(short),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.splitlines()
    rows = [json.loads(line) for line in out]
    assert [r["verdict"] for r in rows] == ["requested", "not_judgeable"]
    assert "judged_text" not in rows[0]
