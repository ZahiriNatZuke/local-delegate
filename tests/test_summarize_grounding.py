"""#630: `local_summarize` warns when its summary carries data the input does not hold.

The issue: the mechanical model summarized two short Markdown files (a verification record with
three evidence tables and a handoff note) and expanded «SDD» as «Sistema de Diagnóstico Dinámico»,
which the file never expands, and wrote «deviações» in a Spanish summary (the file says
«Deviations»), with no warning. A third case of the same family (#586, last comment) put a figure
in the summary that the table does not hold. The check is by program, after the answer, against
the whole input: an acronym expanded in the summary whose expansion the input does not hold, a
figure the input does not hold, a word whose letters are not of the summary's language and that
the input does not hold. Only a warning: the summary is not changed. The inputs are synthetic,
with the shape of the issue.
"""

from __future__ import annotations

import json

import backend_mock
import httpx2
import pytest

from local_delegate import config, grounding, server, table_detect

#: A verification record with the shape of the issue: tables of evidence and an English list.
SOURCE = """\
# Verificación del cambio de prompt de extracción

Registro de verificación del cambio SDD `prompt-extraccion-listas`. El cambio se revirtió.

## Resultado del CI

En el commit de mezcla salió en rojo un test ajeno e intermitente. El cambio se revirtió por dos
regresiones en la prueba en vivo.

## Mutantes

| Mutante | Efecto |
|---|---|
| M1: quitar la regla de listas | hace fallar los 3 tests y los 6 de cuerpos |
| M2: invertir la condición de vacío | hace fallar los 4 casos |

## Prueba en vivo por modelo

| Modelo | Casos | Aciertos | Media |
|---|---|---|---|
| gemma3-4b | 12 | 7 | 2,5 s |
| qwen3-8b | 12 | 9 | 41 s |

La entrada pesaba 2 862 caracteres y tres fixtures eran privados.

## Deviations

- The live probe used 12 cases instead of the 15 planned.
- The SDD plan gate was passed early.
"""

#: What the model did in the issue: an invented expansion, a Portuguese word, a figure of its own.
BAD_SUMMARY = (
    "El cambio SDD (Sistema de Diagnóstico Dinámico) se revirtió. Las **deviações** se limitaron "
    "a usar 12 casos en vez de 15. gemma3-4b acertó 7 de 12 y qwen3-8b 9 de 12; hubo 5 "
    "regresiones."
)

#: A faithful summary of the same file: its figures in other spellings, its words, no expansion.
GOOD_SUMMARY = (
    "El cambio SDD se revirtió por dos regresiones en la prueba en vivo. M1 hace fallar los 3 "
    "tests y los 6 de cuerpos; M2, los 4 casos. gemma3-4b acertó 7 de 12 (2,5 s de media) y "
    "qwen3-8b 9 de 12 (41 s). La entrada pesaba 2862 caracteres; 3 fixtures eran privados. Las "
    "desviaciones: 12 casos en lugar de 15.\n\n1. Primer punto.\n2. Segundo punto."
)


# --- The check, as a pure function -----------------------------------------------------------------


def test_an_expansion_the_input_does_not_hold_is_reported():
    found = grounding.check(BAD_SUMMARY, SOURCE, language="es")
    assert found.acronyms == ["SDD (Sistema de Diagnóstico Dinámico)"]


def test_an_expansion_written_before_the_acronym_is_reported_too():
    summary = "El Sistema de Diagnóstico Dinámico (SDD) se revirtió."
    assert grounding.check(summary, SOURCE, language="es").acronyms == [
        "Sistema de Diagnóstico Dinámico (SDD)"
    ]


def test_the_live_answer_on_a_handoff_note_is_reported():
    # What gemma3-4b wrote on 2026-11-10 for a synthetic handoff note that never expands «SDD».
    note = (
        "# Relevo: cambio SDD\n\n- La puerta de plan del SDD está aprobada.\n- El PR está abierto."
    )
    summary = (
        "Un cambio en el Sistema de Desarrollo de Datos (SDD); la puerta del SDD está aprobada."
    )
    assert grounding.check(summary, note, language="es").acronyms == [
        "Sistema de Desarrollo de Datos (SDD)"
    ]


def test_an_expansion_the_input_holds_is_not_reported():
    source = SOURCE + "\nSDD quiere decir Spec-Driven Development.\n"
    summary = "Es un cambio SDD (Spec-Driven Development) que se revirtió."
    assert grounding.check(summary, source, language="es").acronyms == []


def test_a_parenthesis_that_is_not_an_expansion_is_not_reported():
    # The words in the parenthesis do not spell the acronym: it is an aside, not an expansion.
    summary = "El cambio SDD (revertido en el PR del revert) no se mezcla."
    assert grounding.check(summary, SOURCE, language="es").acronyms == []


def test_a_figure_the_input_does_not_hold_is_reported():
    assert grounding.check(BAD_SUMMARY, SOURCE, language="es").numbers == ["5"]


def test_figures_in_other_spellings_and_list_markers_are_not_reported():
    # 2 862 → 2862, «tres» → 3, the list markers 1. and 2., and the model names with digits.
    assert grounding.check(GOOD_SUMMARY, SOURCE, language="es").numbers == []


def test_a_number_written_as_a_word_in_the_input_holds_its_figure():
    source = "| Prueba | Nota |\n|---|---|\n| ttl | tres fixtures eran privados |\n"
    assert grounding.check("Hubo 3 fixtures privados.", source, language="es").numbers == []
    assert grounding.check("Hubo 4 fixtures privados.", source, language="es").numbers == ["4"]


def test_a_list_marker_is_not_a_figure():
    source = "| Paso | Estado |\n|---|---|\n| relanzar | pendiente |\n"
    summary = "Pasos:\n\n1. Relanzar el job.\n2) Revisar.\n  3. Probar."
    assert grounding.check(summary, source, language="es").numbers == []


def test_a_word_of_another_language_is_reported():
    assert grounding.check(BAD_SUMMARY, SOURCE, language="es").foreign_words == ["deviações"]


def test_spanish_letters_and_words_copied_from_the_input_are_not_reported():
    source = SOURCE + "\nEl módulo `façade` sigue igual.\n"
    summary = "La «façade» del módulo sigue igual; también la sección de pingüinos."
    assert grounding.check(summary, source, language="es").foreign_words == []


def test_an_english_summary_judges_against_the_english_alphabet():
    summary = "The change was reverted; the también word is not from the input."
    assert grounding.check(summary, SOURCE, language="en").foreign_words == ["también"]


def test_a_language_without_an_alphabet_here_skips_the_word_check():
    assert grounding.check(BAD_SUMMARY, SOURCE, language="fr").foreign_words == []


def test_text_in_code_spans_is_not_judged():
    summary = "El fichero `configuração.json` y la cifra `99` son literales."
    found = grounding.check(summary, SOURCE, language="es")
    assert found.foreign_words == []
    assert found.numbers == []


def test_a_faithful_summary_has_no_finding():
    found = grounding.check(GOOD_SUMMARY, SOURCE, language="es")
    assert not found


def test_a_long_input_without_markup_is_checked_in_linear_time():
    # Untrusted input: no pattern here may backtrack. 200 000 characters of digits and dots.
    source = "1." * 100_000
    summary = "(" + "A" * 50_000 + " " + "Sistema de " * 5_000
    found = grounding.check(summary, source, language="es")
    assert found.acronyms == []


# --- local_summarize end to end, with a fake backend -----------------------------------------------


@backend_mock.mock
def _summarize(monkeypatch, tmp_path, answer: str, **kwargs):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(server, "_summary_language", lambda: "es")
    # #650: these tests count the #630 warning; the table rule's own notice is tested apart
    # (`tests/test_summarize_table_routing.py`).
    monkeypatch.setattr(config, "SUMMARIZE_TABLE_LONG", False)

    def _handler(request: httpx2.Request) -> httpx2.Response:
        json.loads(request.content)
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": answer}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    return server.local_summarize(**kwargs)


def _write(tmp_path, text: str):
    path = tmp_path / "verification.md"
    path.write_bytes(text.encode("utf-8"))
    return path


def test_the_fixture_goes_to_the_mechanical_role_like_the_issue():
    assert len(SOURCE) < config.LONG_INPUT_CHARS


def test_the_summary_of_the_issue_comes_with_one_warning(monkeypatch, tmp_path):
    path = _write(tmp_path, SOURCE)
    output = _summarize(monkeypatch, tmp_path, BAD_SUMMARY, path=str(path), max_words=300)
    result = json.loads(output)["result"] if output.startswith("{") else output
    # The summary is kept as it came; the warning goes after it, before the savings receipt.
    assert BAD_SUMMARY in result
    assert result.count(server.WARNING_MARKER) == 1
    warning = result[result.index(server.WARNING_MARKER) :]
    assert "Sistema de Diagnóstico Dinámico" in warning
    assert "deviações" in warning
    assert "5" in warning
    assert warning.index(server.WARNING_MARKER) < warning.index("leído server-side")


def test_a_faithful_summary_comes_without_a_warning(monkeypatch, tmp_path):
    path = _write(tmp_path, SOURCE)
    output = _summarize(monkeypatch, tmp_path, GOOD_SUMMARY, path=str(path), max_words=300)
    assert server.WARNING_MARKER not in output


def test_figures_are_judged_only_on_an_input_with_a_table(monkeypatch, tmp_path):
    # A lint log: the summary counts on its own («5 errores»), which is no invented figure.
    log = "src/a.py:1:1: E501 line too long\nsrc/b.py:2:1: F401 unused import\n" * 3
    path = _write(tmp_path, log)
    summary = "Hay 5 errores en dos ficheros: líneas largas e imports sin usar."
    output = _summarize(monkeypatch, tmp_path, summary, path=str(path))
    assert server.WARNING_MARKER not in output
    # The same summary of an input with a table is judged.
    path = _write(tmp_path, log + "\n| fichero | errores |\n|---|---|\n| a | 3 |\n")
    output = _summarize(monkeypatch, tmp_path, summary, path=str(path))
    assert "«5»" in output[output.index(server.WARNING_MARKER) :]


@pytest.mark.parametrize(
    "log",
    [
        # A CI log of `gh run view --log`: job, step and line, separated by tabs (TSV to #650).
        (
            "build\tSet up job\tCurrent runner version\n"
            "build\tRun tests\t2 errores en src/a.py\n"
            "build\tRun tests\t3 errores en src/b.py\n"
        ),
        "fichero,linea,regla\nsrc/a.py,1,E501\nsrc/b.py,2,F401\n",  # a CSV of findings
    ],
    ids=["tsv-ci-log", "csv-findings"],
)
def test_csv_and_tsv_do_not_open_the_figures_check(monkeypatch, tmp_path, log):
    """#650: the figures stay on the formats #630 measured (HTML, Markdown): a count is no noise."""
    assert table_detect.table_format(log) in ("csv", "tsv"), "the input is a table to #650"
    path = _write(tmp_path, log)
    output = _summarize(monkeypatch, tmp_path, "Hay 5 errores en dos ficheros.", path=str(path))
    assert server.WARNING_MARKER not in output


def test_the_structured_path_warns_too(monkeypatch, tmp_path):
    # A long input takes the structured path with the switch on: the check runs there as well.
    monkeypatch.setattr(config, "STRUCTURED_SUMMARY", True)
    filler = "\n".join(f"Línea de relleno {chr(97 + i % 26)} del registro." for i in range(400))
    source = SOURCE + "\n## Anexo\n\n" + filler + "\n"
    assert len(source) > config.LONG_INPUT_CHARS
    path = _write(tmp_path, source)
    answer = "## Resultado del CI\n\n" + BAD_SUMMARY + "\n\n## Anexo\n\nRelleno."
    output = _summarize(monkeypatch, tmp_path, answer, path=str(path), max_words=300)
    assert "Sistema de Diagnóstico Dinámico" in output[output.index(server.WARNING_MARKER) :]
