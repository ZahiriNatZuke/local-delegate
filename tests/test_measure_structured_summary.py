"""Controles de la métrica de la etapa 1 (SDD `resumen-por-secciones`, T6).

La métrica usa el emparejamiento de producción, así que no puede señalar un fallo de esa función:
por eso cada control lleva el resultado esperado **escrito a mano**, contado sobre la salida de
ejemplo, y los hay en los dos sentidos —salidas que tienen que pasar y salidas que no—.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "measure_structured_summary", ROOT / "scripts" / "measure_structured_summary.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["measure_structured_summary"] = module
    spec.loader.exec_module(module)
    return module


measure = _load().measure
verdict = sys.modules["measure_structured_summary"].verdict

EXPECTED = ["Por qué existe", "Arranque", "Clientes", "Autenticación del puerto"]
SENTENCE = "El daemon arranca una vez y sirve a todos los clientes por HTTP."  # 13 palabras


def _good() -> str:
    return "\n\n".join(f"## {t}\n{SENTENCE}" for t in EXPECTED)


def test_a_good_summary_passes():
    r = measure(_good(), EXPECTED, 500)
    assert (r["paired"], r["with_content"], r["out_of_order"]) == (4, 4, 0)
    assert r["coverage"] == 1.0
    assert r["words"] == 4 * 13
    assert r["passes_structure"] is True


def test_titles_only_fails_the_content():
    r = measure("\n\n".join(f"## {t}" for t in EXPECTED), EXPECTED, 500)
    assert (r["paired"], r["with_content"]) == (4, 0)
    assert r["passes_structure"] is False


def test_prose_mentioning_the_titles_gives_low_coverage():
    prose = (
        "El documento explica por qué existe el daemon, su arranque, los clientes y la "
        "autenticación del puerto, todo en prosa y sin títulos."
    )
    r = measure(prose, EXPECTED, 500)
    assert r["paired"] == 0
    assert r["coverage"] == 0.0
    assert r["passes_structure"] is False


def test_unordered_titles_fail_the_order():
    order = [EXPECTED[1], EXPECTED[0], EXPECTED[2], EXPECTED[3]]
    r = measure("\n\n".join(f"## {t}\n{SENTENCE}" for t in order), EXPECTED, 500)
    assert r["out_of_order"] == 1
    assert r["paired"] == 3
    assert r["passes_structure"] is False


def test_the_ones_completed_by_the_server_do_not_count():
    output = (
        f"## Por qué existe\n{SENTENCE}\n\n## Arranque\n(sin resumir)\n\n"
        f"## Clientes\n{SENTENCE}\n\n## Autenticación del puerto\n(sin resumir)\n\n"
        "[local-delegate aviso: 2 secciones sin resumir por el límite de palabras o del modelo]"
    )
    r = measure(output, EXPECTED, 500)
    assert (r["paired"], r["completed_by_server"]) == (2, 2)
    assert r["coverage"] == 0.5
    assert r["words"] == 2 * 13  # ni los «(sin resumir)» ni el aviso cuentan
    assert r["passes_structure"] is False


def test_changelog_half_completed_fails():
    versions = [f"[0.{i}.0] - 2026-09-{i:02d}" for i in range(1, 21)]
    parts = [
        f"## {v}\n" + (SENTENCE if i % 2 == 0 else "(sin resumir)") for i, v in enumerate(versions)
    ]
    r = measure("\n\n".join(parts), versions, 500)
    assert (r["paired"], r["completed_by_server"]) == (10, 10)
    assert r["passes_structure"] is False
    assert verdict({"changelog": {**r, "finish_reason": "stop"}})["changelog"] is False


def test_bold_inside_a_section_is_content():
    output = _good().replace(
        f"## Arranque\n{SENTENCE}", "## Arranque\n**Puntos clave:**\n- " + SENTENCE
    )
    r = measure(output, EXPECTED, 500)
    assert r["with_content"] == 4
    assert r["passes_structure"] is True


def test_title_with_suffix_matches_and_duplicate_with_one_occurrence_counts_once():
    output = _good().replace("## Clientes", "## Clientes: Codex, Claude y opencode")
    assert measure(output, EXPECTED, 500)["paired"] == 4
    doubles = ["Notas", "Notas"]
    r = measure(f"## Notas\n{SENTENCE}", doubles, 500)
    assert r["paired"] == 1
    assert r["coverage"] == 0.5


def test_the_verdict_requires_the_three_documents_and_ignores_the_judgement():
    good = measure(_good(), EXPECTED, 500)
    bad = measure("prosa", EXPECTED, 500)
    base = {"readme": good, "installation": good, "daemon": good}
    assert verdict(base)["three_documents"] is True
    assert verdict({**base, "daemon": bad})["three_documents"] is False
    assert verdict({"changelog": {**good, "finish_reason": "length"}})["changelog"] is False


def test_subsection_coverage_is_informative_and_by_words():
    coverage = sys.modules["measure_structured_summary"].subsection_coverage
    output = "## Arranque\n**La sesión del navegador**: se entra con el token.\n"
    subs = ["La sesión del navegador", "Linux", "sesión"]
    assert coverage(output, subs) == {"total": 3, "named": 2}
    assert coverage("Linuxero", ["Linux"])["named"] == 0


def test_the_short_one_has_to_be_in_prose():
    assert verdict({"short-4b": {"coverage": 0.0, "log_sections": None}})["short_4b_in_prose"]
    structured = {"short-4b": {"coverage": 1.0, "log_sections": 7}}
    assert verdict(structured)["short_4b_in_prose"] is False
    assert verdict({})["short_4b_in_prose"] is False
