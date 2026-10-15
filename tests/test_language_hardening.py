"""B2d hardening: the language order of summarize/lint_summary and the duplicated sections.

The live sample of B2d (`evidence/B2/lang-sample.json`) recognized 34 of 40 answers in the
requested language: summarize 8/10, lint_summary 6/10, and none in the opposite language. The
failures were MIXED answers, from two causes, each with its own fix and its own tests here:

1. The order only said "answer in X". The model translated the frame and kept fragments of the
   input as they were, in noun phrases ("Múltiples `if` statements", "Restoration
   successful."). The order of these two tools now says what is written in X (every sentence, in
   full sentences, not copied) and what stays verbatim (`server._written_language_clause`).
2. The structured summary came out with a section twice. The synthetic introduction went in the
   PRODUCT language ("Introducción") while the model was told to answer in English: it wrote
   "Introduction", and `sections.complete`, which matches by text, inserted "Introducción" again
   as not summarized. The introduction now goes in the response language
   (`sections.introduction`), and `complete` pairs a heading the model translated in its slot
   (`sections._pair_translated`), narrowly, and puts back the document's wording.

The prompts are captured with a fake backend (`_run_chat` doubled), with no network.
"""

from __future__ import annotations

import base64

import pytest
from test_structured_summary import _call_summary, _prompt_list

from local_delegate import config, i18n, sections, server

OUTPUT = "LOCAL_DELEGATE_OUTPUT_LANGUAGE"
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

#: The two batches of the live sample: (product language, output variable, name in the order).
BATCHES = [("es", "en", "inglés"), ("en", "es", "español")]


@pytest.fixture
def captured(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def run_chat(model, system, user, max_tokens, temperature, **_):
        calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        result = server.ChatResult(text="resumen", ok=True, finish_reason="stop")
        return result, 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    return calls


def _languages(monkeypatch, product: str, output: str | None) -> None:
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", product)
    if output is None:
        monkeypatch.delenv(OUTPUT, raising=False)
    else:
        monkeypatch.setenv(OUTPUT, output)
    i18n.reset()


def _assert_hardened(system: str, name: str, tool: str = "local_summarize") -> None:
    assert f" Escribe toda la respuesta en {name}, aunque el contenido esté en otro idioma" in (
        system
    ), system[-400:]
    assert f"redacta en {name} cada frase" in system, system[-400:]
    assert "con frases completas y sin copiar frases del contenido" in system, system[-400:]
    assert " Responde en " not in system, "the plain order stayed next to the hardened one"
    if tool == "local_lint_summary":
        _assert_lint_labels(system, name)
    else:
        assert (
            "Solo se quedan tal cual los títulos de las líneas '## ' que se piden literales"
        ) in system, system[-400:]
        # B2d-2: summarize names its bold labels too, but not lint's sections and checks.
        assert "las etiquetas en negrita, también las que nombran una subsección" in system
        assert "nombres de cada chequeo o prueba" not in system, "the lint order leaked"


def _assert_lint_labels(system: str, name: str) -> None:
    """B2d-fix: lint names its labels as text to write in `name`; nothing about literal headings."""
    assert (
        f" También van en {name} las etiquetas en negrita, los nombres de sección y los nombres "
        "de cada chequeo o prueba: tradúcelos aunque en el contenido aparezcan en otro idioma."
    ) in system, system[-500:]
    assert (
        " Solo se quedan tal cual las rutas, el código, los identificadores y los códigos de "
        "regla o de error."
    ) in system, system[-500:]
    assert "títulos que se piden literales" not in system, system[-500:]


def _clause(tool: str) -> str:
    if tool == "local_lint_summary":
        return server._lint_language_clause()
    return server._written_language_clause()


def _single(tool: str):
    if tool == "local_summarize":
        return lambda: server.local_summarize(text="Un texto corto para resumir.")
    return lambda: server.local_lint_summary(text="src/x.py:1:1: E501 Line too long")


def _structured():
    parts = "".join(f"## Parte {i}\n\n" + "Texto de la parte. " * 60 + "\n\n" for i in range(12))
    return server.local_summarize(text="# Documento\n\n" + parts)


def _lint_in_chunks():
    return server.local_lint_summary(text="tests/x.py:1: E1 fallo de prueba\n" * 120)


# --- 1. The order of summarize and lint_summary ----------------------------------------------


@pytest.mark.parametrize(("product", "output", "name"), BATCHES)
@pytest.mark.parametrize("tool", ["local_summarize", "local_lint_summary"])
def test_summarize_and_lint_ask_for_full_sentences_in_the_requested_language(
    monkeypatch, captured, product, output, name, tool
):
    """Mutant "the plain order back in these two tools": every `in` of `_assert_hardened` fails."""
    _languages(monkeypatch, product, output)
    _single(tool)()
    (call,) = captured
    _assert_hardened(call["system"], name, tool)
    assert call["system"].endswith(_clause(tool))


@pytest.mark.parametrize(("product", "output", "name"), BATCHES)
@pytest.mark.parametrize("call", [_structured, _lint_in_chunks], ids=lambda c: c.__name__)
def test_the_hardened_order_is_in_every_step_of_the_chunking(
    monkeypatch, captured, product, output, name, call
):
    _languages(monkeypatch, product, output)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 1200)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 1200)
    monkeypatch.setattr(config, "STRUCTURED_SUMMARY", True)
    call()
    assert len(captured) > 2  # guard: it really chunked
    tool = "local_lint_summary" if call is _lint_in_chunks else "local_summarize"
    for step in captured:
        _assert_hardened(step["system"], name, tool)


@pytest.mark.parametrize(("product", "output", "name"), BATCHES)
def test_lint_labels_go_in_the_requested_language_in_map_and_reduce(
    monkeypatch, captured, product, output, name
):
    """B2d-fix: probe X copied 5-8 Spanish bold labels of `doctor`; the order now names them.

    Mutant "lint keeps the summarize order": `_assert_lint_labels` fails at its first `in`, in
    the single call and in every map and reduce step.
    """
    _languages(monkeypatch, product, output)
    server.local_lint_summary(text="**Servicios:** [ OK ] daemon")
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 1200)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 1200)
    _lint_in_chunks()
    single, *steps = captured
    assert len(steps) > 2  # guard: map and reduce really ran
    assert "Resume la siguiente salida" not in steps[-1]["user"]  # guard: the last one reduces
    for call in [single, *steps]:
        _assert_lint_labels(call["system"], name)


SUMMARIZE_ORDER_BEFORE = (
    " Escribe toda la respuesta en inglés, aunque el contenido esté en otro idioma: redacta en "
    "inglés cada frase, también la descripción de cada error o regla, con frases completas y sin "
    "copiar frases del contenido. También van en inglés las etiquetas en negrita, también las que "
    "nombran una subsección: tradúcelas aunque en el contenido aparezcan en otro idioma. Solo se "
    "quedan tal cual los títulos de las líneas '## ' que se piden literales, las rutas, el código, "
    "los identificadores y los códigos de regla o de error."
)


def test_the_summarize_order_does_not_change(monkeypatch, captured):
    """Its `##` headings must stay verbatim: the text of commit 71846c1, byte by byte, plus the
    rule of the bold labels that B2d-2 added (set 3 copied 5 + 4 subheadings as labels)."""
    _languages(monkeypatch, "es", "en")
    server.local_summarize(text="Un texto corto para resumir.")
    (call,) = captured
    assert server._written_language_clause() == SUMMARIZE_ORDER_BEFORE
    assert call["system"].endswith(SUMMARIZE_ORDER_BEFORE)


def test_explain_code_and_describe_image_keep_the_plain_order(monkeypatch, captured, tmp_path):
    """They gave 10/10 in the live sample: their prompt does not change in this wave."""
    _languages(monkeypatch, "es", "en")
    image = tmp_path / "x.png"
    image.write_bytes(_PNG)
    server.local_explain_code(code="x = 1")
    server.local_describe_image(path=str(image))
    assert len(captured) == 2
    for call in captured:
        assert call["system"].endswith(
            " Responde en inglés, aunque el contenido esté en otro idioma."
        )
        assert "Escribe toda la respuesta" not in call["system"]


# --- 2a. The introduction goes in the response language --------------------------------------

INTRO_DOC = (
    "# Guía\n\nEste documento explica " + "muchas cosas importantes " * 10 + "\n\n"
    "## Uno\n\nPrimera parte.\n\n## Dos\n\nSegunda parte.\n"
)


@pytest.mark.parametrize(
    ("product", "output", "expected"),
    [
        ("es", "en", "Introduction"),  # batch 1 of the live sample
        ("en", "es", "Introducción"),  # batch 2
        ("en", None, "Introduction"),  # no variable: the product language, as before
        ("es", None, "Introducción"),
        ("es", "fr", "Introducción"),  # a language without catalog: the product one
        ("en", "en-GB", "Introduction"),  # a regional code is read by its first part
    ],
)
def test_the_introduction_is_in_the_response_language(monkeypatch, product, output, expected):
    """Mutant "the introduction in the product language" (`i18n.t`): the first two cases fail on
    the `==` with the heading of the other language."""
    _languages(monkeypatch, product, output)
    plan = sections.sections_for_summary(INTRO_DOC, sections.detect(INTRO_DOC))
    assert plan[0].synthetic
    assert plan[0].heading == expected


def test_the_b2d_case_comes_out_once_and_summarized(monkeypatch, tmp_path):
    """The live case: product es, answer in English, a document with an introduction."""
    _languages(monkeypatch, "es", "en")

    def _model(_payload, _n):
        answer = (
            "## Introduction\nThis document explains several important things.\n\n"
            "## Uno\nThe first part of the text.\n\n## Dos\nThe second part of the text."
        )
        return answer, "stop"

    output, seen = _call_summary(monkeypatch, tmp_path, _model, text=INTRO_DOC)
    # The output first: with both fixes removed it is the duplicated section of the live sample.
    assert "Introducción" not in output, output
    assert output.count("Introduction") == 1
    assert not any(form in output for form in sections.NOT_SUMMARIZED_FORMS)
    assert sections.WARNING_MARKER not in output
    # And the prompt: the model is asked for the heading in the language it must answer in.
    listing = _prompt_list(seen[0]["messages"][1]["content"])
    assert [t for t, _w, _s in listing] == ["Introduction", "Uno", "Dos"]


# --- 2b. A heading the model translated is paired in its slot --------------------------------

EXPECTED = ["Instalación", "Configuración", "Uso"]
TRANSLATED = (
    "## Instalación\nSe instala con uv y nada más.\n\n"
    "## Configuration\nVariables de entorno y un fichero de configuración.\n\n"
    "## Uso\nSe llama con path y devuelve el resumen."
)


def test_a_translated_heading_is_not_duplicated_and_gets_its_wording_back():
    """Mutant "`complete` without `positional`": the section comes out twice ("Configuration"
    summarized and "Configuración" not summarized), and the heading count fails first."""
    done = sections.complete(TRANSLATED, EXPECTED)
    headings = [text for _index, text in sections.heading_lines(done.text)]
    assert len(headings) == len(EXPECTED), done.text
    assert done.text.count("Configuración") == 1, done.text
    assert done.missing == 0
    assert "## Configuración\nVariables de entorno" in done.text
    assert "Configuration" not in done.text
    assert not any(form in done.text for form in sections.NOT_SUMMARIZED_FORMS)
    assert sections.WARNING_MARKER not in done.text


def test_the_rescue_keeps_the_level_of_the_heading():
    text = TRANSLATED.replace("## ", "### ")
    done = sections.complete(text, EXPECTED)
    assert "### Configuración\nVariables" in done.text
    assert done.missing == 0


def test_the_measurement_keeps_matching_by_text():
    """`scripts/measure_structured_summary.py` uses the default: its baseline was frozen with it."""
    assert sections.match_headings(TRANSLATED, EXPECTED).missing == [1]
    rescued = sections.match_headings(TRANSLATED, EXPECTED, positional=True)
    assert rescued.missing == [] and rescued.translated == {1: 3}


@pytest.mark.parametrize(
    "output",
    [
        # Two missing in the same slot: the order of the translations is not known. No rescue.
        (
            "## Instalación\nuno dos tres\n\n## Configuration\ncuatro cinco seis\n\n"
            "## Usage notes\nsiete ocho nueve"
        ),
        # The candidate is a subsection (### among ##): it is not a section of the list.
        "## Instalación\nuno dos tres\n\n### Detalles\ncuatro cinco seis\n\n## Uso\nsiete ocho",
        # The candidate is a bold line, not a heading.
        "## Instalación\nuno dos tres\n\n**Configuration**\ncuatro cinco seis\n\n## Uso\nsiete",
    ],
    ids=["two_missing_in_a_slot", "subsection_level", "bold_line"],
)
def test_the_rescue_does_not_take_what_is_not_a_translation(output):
    """Controls of the narrowness: in these the section stays missing and is completed as before."""
    done = sections.complete(output, EXPECTED)
    assert done.missing >= 1
    assert any(form in done.text for form in sections.NOT_SUMMARIZED_FORMS)
    assert "## Configuración" in done.text


def test_an_invented_heading_with_nothing_missing_is_left_alone():
    output = (
        "## Instalación\nuno dos tres\n\n## Configuración\ncuatro cinco\n\n"
        "## Extra notes\nseis siete\n\n## Uso\nocho nueve diez"
    )
    done = sections.complete(output, EXPECTED)
    assert done.text == output
    assert done.missing == 0
