"""B2d-2: the output of `local_summarize` and `local_lint_summary` without losses.

Born of `evidence/B2d-fix/chunking-model-investigation.md` (§2 and §4) and of the live sample of
set 3 (`evidence/B2d-fix/lang-sample-set3-batch{1,2}.json`). One block per point of the plan, each
with its control and the mutant that makes it fail (recorded in `evidence/B2d-2/report.md`):

1. The output caps of `local_lint_summary` (single call and every step of the chunking).
2. A section empty in the document is not reported as not summarized, and gets no words.
3. The cut by `max_tokens` drops a last line only if it is a heading cut in the middle.
4. The usage log keeps the length of the raw model output (`chars_out_raw`).
5. A document with its own "Introduction" does not get the product's one too.
6. The fidelity counter of the lint answers (`scripts/score_lint_fidelity.py`).
7. The language order of `local_summarize` names the bold labels.
8. The language judge reads like the server (`errors="replace"`).

The backend is faked (`_run_chat` or the HTTP mock): no network.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from test_structured_summary import _call_summary, _events, _prompt_list

from local_delegate import config, i18n, sections, server

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = "LOCAL_DELEGATE_OUTPUT_LANGUAGE"
BATCHES = [("es", "en", "inglés"), ("en", "es", "español")]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _languages(monkeypatch, product: str, output: str | None) -> None:
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", product)
    if output is None:
        monkeypatch.delenv(OUTPUT, raising=False)
    else:
        monkeypatch.setenv(OUTPUT, output)
    i18n.reset()


@pytest.fixture
def captured(monkeypatch) -> list[dict]:
    """`_run_chat` doubled: the `system`, `user` and `max_tokens` of every call."""
    calls: list[dict] = []

    def run_chat(model, system, user, max_tokens, temperature, **_):
        calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        result = server.ChatResult(text="resumen breve", ok=True, finish_reason="stop")
        return result, 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    return calls


# --- 1. The output caps of local_lint_summary ---------------------------------------------------


def test_the_single_lint_call_asks_for_the_new_cap(captured):
    """Mutant "the cap of today" (`2·w+96`): the `==` fails with 496 for 200 words."""
    server.local_lint_summary(text="src/x.py:1:1: E501 Line too long")
    (call,) = captured
    assert call["max_tokens"] == 200 * server.LINT_TOKENS_PER_WORD + server.LINT_TOKENS_BASE
    assert call["max_tokens"] > 496  # guard: the cap that truncated gemma4 in 3 of 4 answers


def test_every_step_of_the_chunked_lint_asks_for_the_new_cap(monkeypatch, captured):
    """Mutant "no `max_tokens_for` for lint" (the shared `2·w+64`): every step has 464."""
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 1200)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 1200)
    server.local_lint_summary(text="tests/x.py:1: E1 fallo de prueba\n" * 120)
    assert len(captured) > 2  # guard: map and reduce really ran
    assert "Resume la siguiente salida" not in captured[-1]["user"]  # guard: the last one reduces
    expected = 200 * server.LINT_TOKENS_PER_WORD + server.LINT_CHUNK_TOKENS_BASE
    assert [c["max_tokens"] for c in captured] == [expected] * len(captured)


def test_the_other_tools_keep_the_shared_chunk_cap(monkeypatch, captured):
    """Control: the lint cap does not leak into the chunking of `local_summarize`."""
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 1200)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 1200)
    monkeypatch.setattr(config, "STRUCTURED_SUMMARY", False)
    server.local_summarize(text="Un párrafo de prueba que se repite. " * 120)
    assert len(captured) > 2
    assert {c["max_tokens"] for c in captured} == {150 * 2 + 64}


# --- 2. A section empty in the document ---------------------------------------------------------

DOC_EMPTY_SECTION = (
    "# Paquete\n\n## Features\n\nOfrece muchas cosas útiles a quien lo usa a diario.\n\n"
    "## Release Information\n\n## 2.13.1 (September 23rd, 2026)\n\n### Fixed\n\n"
    "* Calculate Content-Length correctly when a file is passed.\n"
)


def _httpx2_model(_payload, _n):
    """The model of the live case: it leaves the empty section empty, which is right."""
    answer = (
        "## Features\nOfrece muchas utilidades para el uso diario.\n\n"
        "## Release Information\n\n"
        "## 2.13.1 (September 23rd, 2026)\n**Fixed** Se corrige el cálculo de Content-Length."
    )
    return answer, "stop"


def test_a_section_empty_in_the_document_is_not_reported_as_not_summarized(monkeypatch, tmp_path):
    """Investigation test B1 (httpx2, batch 2). Mutant "`complete` counts it as `empty` without
    looking at the document" (no `empty_in_document`): the assert on the warning fails."""
    _languages(monkeypatch, "en", "es")
    out, seen = _call_summary(monkeypatch, tmp_path, _httpx2_model, text=DOC_EMPTY_SECTION)
    assert len(seen) == 1  # guard: one structured call
    assert _prompt_list(seen[0]["messages"][1]["content"])  # guard: it was the structured path
    assert sections.WARNING_MARKER not in out, out
    assert not any(form in out for form in sections.NOT_SUMMARIZED_FORMS), out


def test_an_empty_section_gets_no_words_in_the_prompt(monkeypatch, tmp_path):
    """Mutant "measure the span with the heading" (`content_size` -> `size`): the empty section
    is asked for words again, and the assert on its line fails."""
    _out, seen = _call_summary(monkeypatch, tmp_path, _httpx2_model, text=DOC_EMPTY_SECTION)
    user = seen[0]["messages"][1]["content"]
    line = next(x for x in user.splitlines() if "Release Information" in x)
    assert line == "- Release Information (vacía en el documento: solo el título)", line
    # Control: the sections with content still get their words.
    assert "- Features (unas " in user


def test_the_words_follow_the_body_not_the_heading(monkeypatch, tmp_path):
    """Mutant "measure the span with the heading" (`content_size` returns `size`): the section
    with the long heading gets more words for the same body, and the `==` fails."""
    body = "Texto de la sección con el mismo largo en las dos. " * 6
    long_heading = "Un título muy largo que ocupa mucho más que el cuerpo de otras secciones " * 3
    doc = f"# Doc\n\n## Corto\n\n{body}\n\n## {long_heading.strip()}\n\n{body}\n"
    _out, seen = _call_summary(monkeypatch, tmp_path, _httpx2_model, text=doc)
    listing = _prompt_list(seen[0]["messages"][1]["content"])
    assert len(listing) == 2  # guard: the two sections, no introduction
    assert listing[0][1] == listing[1][1], listing


def test_allocate_by_size_gives_0_words_to_a_span_without_body():
    """Mutant "the old `allocate_by_size`": the empty one gets the minimum (8), not 0."""
    assert sections.allocate_by_size([300, 0, 300], 100, minimum=8) == [50, 0, 50]
    # Control: without empty ones it is the proportional split with the minimum of always.
    assert sections.allocate_by_size([300, 300], 100, minimum=8) == [50, 50]


def test_the_body_is_measured_without_the_heading():
    plan = sections.sections_for_summary(DOC_EMPTY_SECTION, sections.detect(DOC_EMPTY_SECTION))
    by_heading = {s.heading: s for s in plan}
    assert by_heading["Release Information"].empty
    assert by_heading["Release Information"].content_size == 0
    assert by_heading["Release Information"].size > 0  # the span WITH the heading is not empty
    assert not by_heading["Features"].empty
    # A section that only holds a subheading and its text is not empty.
    assert not by_heading["2.13.1 (September 23rd, 2026)"].empty


def test_a_missing_empty_section_comes_back_without_the_placeholder():
    done = sections.complete(
        "## Features\nuno dos tres cuatro.\n\n## 2.13.1\ncinco seis siete ocho.",
        ["Features", "Release Information", "2.13.1"],
        empty_in_document=frozenset({1}),
    )
    assert "## Release Information" in done.text
    assert not any(form in done.text for form in sections.NOT_SUMMARIZED_FORMS)
    assert sections.WARNING_MARKER not in done.text
    assert (done.missing, done.empty) == (0, 0)


def test_a_section_with_content_left_empty_is_still_reported():
    """Control: the change only covers sections empty in the DOCUMENT."""
    done = sections.complete(
        "## Features\n\n## 2.13.1\ncinco seis siete ocho.",
        ["Features", "2.13.1"],
        empty_in_document=frozenset(),
    )
    assert sections.WARNING_MARKER in done.text
    assert done.empty == 1


# --- 3. The cut by the cap does not drop a whole section ----------------------------------------


def test_truncation_keeps_a_long_last_line_that_starts_with_hash():
    """Investigation test B2 (httpcore2, batch 1). Mutant "the condition of today" (any heading
    line is dropped): this `in` fails; the control below still passes."""
    body = "### 2.13.1 Fixed: " + "se corrige un fallo y se mejora otro aspecto; " * 80
    output = "## Intro\nTexto de la introducción breve.\n\n## Changelog\n" + body
    done = sections.complete(output, ["Intro", "Changelog"], truncated=True)
    assert "se corrige un fallo" in done.text, done.text


def test_truncation_still_drops_a_short_cut_heading():
    """Control: a heading cut in the middle goes, and the whole one comes back as missing."""
    output = "## Intro\nTexto de la introducción breve.\n\n## Chang"
    done = sections.complete(output, ["Intro", "Changelog"], truncated=True)
    assert "## Chang\n" not in done.text + "\n"
    assert "## Changelog" in done.text
    assert done.missing == 1


def test_without_truncation_a_last_heading_is_kept():
    output = "## Intro\nTexto de la introducción breve.\n\n## Changelog"
    done = sections.complete(output, ["Intro", "Changelog"], truncated=False)
    assert done.text.startswith(output)


# --- 4. The raw length of the model output in the usage log -------------------------------------

THINK = "<think>" + "razono sobre el documento " * 100 + "</think>\n"


def test_the_log_keeps_the_raw_length_before_the_post_processing(monkeypatch, tmp_path):
    """Mutant "log the length after the post-processing": the `==` with the raw length fails
    (201, the processed text, against 2656 generated)."""
    answer = THINK + "## Uno\nTexto uno dos tres cuatro.\n\n## Do"

    def _model(_payload, _n):
        return answer, "length"

    text = "# Doc\n\n## Uno\n\nPrimera parte del texto.\n\n## Dos\n\nSegunda parte del texto.\n"
    _out, _seen = _call_summary(monkeypatch, tmp_path, _model, text=text)
    (row,) = [e for e in _events(tmp_path) if e["tool"] == "local_summarize"]
    assert row["chars_out_raw"] == len(answer)
    assert row["chars_out_raw"] > row["chars_out"], row


def test_the_chunked_log_sums_the_raw_length_of_every_call(monkeypatch, tmp_path):
    """Mutant "no `raw_chars` in `_one`": the field is 0 and the `==` fails."""
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 1200)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 1200)

    def _model(_payload, _n):
        return THINK + "Un resumen parcial.", "stop"

    _out, seen = _call_summary(
        monkeypatch, tmp_path, _model, structured=False, text="Una frase de prueba. " * 200
    )
    assert len(seen) > 2  # guard: it really chunked
    (row,) = [e for e in _events(tmp_path) if e["tool"] == "local_summarize"]
    assert row["chars_out_raw"] == len(seen) * len(THINK + "Un resumen parcial.")


# --- 5. One introduction ------------------------------------------------------------------------

INTRO_TEXT = "Este documento explica " + "muchas cosas importantes " * 10 + "\n\n"


def _echo_headings(payload, _n):
    listing = _prompt_list(payload["messages"][1]["content"])
    return "\n\n".join(f"## {t}\nTexto del resumen de la sección." for t, _w, _s in listing), "stop"


def _introductions(output: str) -> int:
    forms = {sections.normalize_heading(f) for f in sections.INTRODUCTION_FORMS}
    return sum(1 for _i, t in sections.heading_lines(output) if t in forms)


@pytest.mark.parametrize(("product", "output"), [("es", "en"), ("en", "es"), ("es", None)])
@pytest.mark.parametrize("own", ["Introduction", "Introducción", "INTRODUCTION"])
def test_a_document_with_its_own_introduction_gets_only_one(
    monkeypatch, tmp_path, product, output, own
):
    """pycparser (set 3, batch 1). Mutant "always add the section": the count is 2."""
    _languages(monkeypatch, product, output)
    doc = f"# Guía\n\n{INTRO_TEXT}## {own}\n\nQué es.\n\n## Uso\n\nCómo se usa.\n"
    out, _seen = _call_summary(monkeypatch, tmp_path, _echo_headings, text=doc)
    assert _introductions(out) == 1, out


@pytest.mark.parametrize(("product", "output"), [("es", "en"), ("en", "es")])
def test_a_document_without_it_still_gets_the_products(monkeypatch, tmp_path, product, output):
    """Control: the synthetic introduction stays when the document has none."""
    _languages(monkeypatch, product, output)
    doc = f"# Guía\n\n{INTRO_TEXT}## Qué es\n\nQué es.\n\n## Uso\n\nCómo se usa.\n"
    out, seen = _call_summary(monkeypatch, tmp_path, _echo_headings, text=doc)
    listing = _prompt_list(seen[0]["messages"][1]["content"])
    assert listing[0][0] == sections.introduction()
    assert _introductions(out) == 1, out


# --- 7. The bold labels of local_summarize ------------------------------------------------------


@pytest.mark.parametrize(("product", "output", "name"), BATCHES)
def test_the_summarize_order_names_the_bold_labels(monkeypatch, captured, product, output, name):
    """Set 3 copied 5 + 4 subheadings as `**…**` labels in the other language. Mutant "without
    the rule": the first `in` fails; the rest of the hardened order is checked by
    `test_language_hardening.py`."""
    _languages(monkeypatch, product, output)
    server.local_summarize(text="Un texto corto para resumir.")
    (call,) = captured
    assert (
        f" También van en {name} las etiquetas en negrita, también las que nombran una "
        "subsección: tradúcelas aunque en el contenido aparezcan en otro idioma."
    ) in call["system"], call["system"][-500:]
    assert (
        "Solo se quedan tal cual los títulos de las líneas '## ' que se piden literales"
        in (call["system"])
    )
