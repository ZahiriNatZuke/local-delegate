"""#594: `local_extract` no longer returns, in silence, the whole outline for ONE heading.

A field asking for the line of one heading got the whole heading outline (the one the prompt
carries since #568), and «Título: línea 1» on the document title was flagged. The outline copy is
cut only without doubt (singular subject, one heading); with any doubt it is said and left as it
came. Backend faked (`_run_chat` doubled), no network.
"""

from __future__ import annotations

import json

import pytest

from local_delegate import config, i18n, line_check, server


def _ok(text: str):
    return server.ChatResult(text=text, ok=True, finish_reason="stop")


@pytest.fixture
def backend(monkeypatch, tmp_path):
    calls: list[dict] = []
    state = {"answer": lambda call: _ok("{}")}

    def run_chat(model, system, user, max_tokens, temperature, **_):
        calls.append({"system": system, "user": user})
        return state["answer"](calls[-1]), 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    i18n.reset()
    yield calls, state
    i18n.reset()


def _answer(state, payload: dict) -> None:
    state["answer"] = lambda call: _ok(json.dumps(payload, ensure_ascii=False))


_SECTIONS = [
    "La regla que gobierna todas",
    "De un vistazo",
    "`local_summarize`",
    "Resumen por secciones",
    "`local_classify`",
    "`local_extract`",
    "`local_explain_code`",
    "Cuándo NO delegar",
]


def _doc() -> str:
    out = ["# Catálogo de tools", "", "Intro del catálogo.", ""]
    for title in _SECTIONS:
        out += [f"## {title}", "", f"Texto de {title.strip('`')}.", ""]
    return "\n".join(out) + "\n"


def _outline_copy(text: str) -> str:
    """The value of the issue: «Título: línea 1; <heading>: línea N; …»."""
    outline = line_check.markdown_outline(text)
    parts = ["Título: línea 1"]
    parts += [f"{line_check.heading_text(h).strip('`')}: línea {n}" for n, h in outline[1:]]
    return "; ".join(parts)


def _line_of(text: str, heading: str) -> int:
    return text.split("\n").index(f"## {heading}") + 1


# --- REQ-003: cut only without doubt --------------------------------------------------------


def test_the_outline_copy_is_cut_to_the_heading_the_field_names(backend, tmp_path):
    _calls, state = backend
    text = _doc()
    path = tmp_path / "tools.md"
    path.write_text(text, encoding="utf-8")
    copy = _outline_copy(text)
    fields = ["local_extract_section_heading_line", "local_summarize_section_heading_line"]
    _answer(state, dict.fromkeys(fields, copy))
    data = server.local_extract(fields=fields, path=str(path))
    meta = data.pop("_local_delegate", {})
    extract_line = _line_of(text, "`local_extract`")
    summarize_line = _line_of(text, "`local_summarize`")
    assert data == {
        fields[0]: f"`local_extract`: {extract_line}",
        fields[1]: f"`local_summarize`: {summarize_line}",
    }
    assert meta.get("outline_copies") == {fields[0]: extract_line, fields[1]: summarize_line}
    assert "lines_unverified" not in meta


def test_an_outline_copy_with_no_single_heading_is_kept_and_said(backend, tmp_path):
    _calls, state = backend
    text = _doc()
    path = tmp_path / "tools.md"
    path.write_text(text, encoding="utf-8")
    copy = _outline_copy(text)
    # `local` is in four headings; three of them have one other word: no single one.
    _answer(state, {"local_section_line": copy})
    data = server.local_extract(fields=["local_section_line"], path=str(path))
    meta = data.get("_local_delegate", {})
    assert data["local_section_line"] == copy
    assert meta.get("outline_copies") == {"local_section_line": None}
    assert meta.get("warning") == i18n.t(
        "mcp.warning.extract_outline_copies",
        pairs="local_section_line -> " + i18n.t("mcp.warning.extract_outline_kept"),
    )


#: An outline with a plural heading next to its singular, a Spanish plural and chapters.
_OUTLINE = [
    (1, "# Guía"),
    (5, "## Tools"),
    (9, "## Pasos de instalación"),
    (14, "## Capítulos"),
    (19, "## Uso"),
]
_OUTLINE_VALUE = "Guía: línea 1; Tools: línea 5; Pasos de instalación: línea 9; Uso: línea 19"


@pytest.mark.parametrize(
    "name",
    [
        "tools_section_line",  # plural subject: may ask for several tools
        "tool_heading_line",  # only a heading word that it starts (`tools`): doubtful
        "pasos_heading_line",  # Spanish plural subject
        "intro_heading_line",  # no whole-word match («Introducción» is not in the outline)
    ],
)
def test_a_doubtful_field_is_said_and_never_cut(name):
    assert line_check.outline_copy(name, _OUTLINE_VALUE, _OUTLINE) == (True, None)


def test_a_singular_subject_with_one_heading_is_cut():
    assert line_check.outline_copy("uso_heading_line", _OUTLINE_VALUE, _OUTLINE) == (
        True,
        (19, "Uso"),
    )
    # camelCase and accents: `guia` is «Guía».
    assert line_check.outline_copy("guiaHeadingLine", _OUTLINE_VALUE, _OUTLINE) == (
        True,
        (1, "Guía"),
    )


# --- REQ-004: a field that asks for several places is no copy ---------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "tools_with_lines",
        "tool_sections_with_lines",
        "local_headings_lines",
        "outline",
        "capitulos_con_linea",  # a Spanish plural place word
        "line_of_each_heading",  # `each`
        "linea_de_cada_seccion",  # `cada`
    ],
)
def test_a_field_that_asks_for_several_places_is_no_copy(name):
    assert line_check.outline_copy(name, _OUTLINE_VALUE, _OUTLINE) == (False, None)
    text = _doc()
    outline = line_check.markdown_outline(text)
    assert line_check.outline_copy(name, _outline_copy(text), outline) == (False, None)


def test_a_field_that_asks_for_the_whole_outline_is_left_alone(backend, tmp_path):
    """`sections_with_lines` names no heading; the outline is its answer."""
    _calls, state = backend
    text = _doc()
    path = tmp_path / "tools.md"
    path.write_text(text, encoding="utf-8")
    copy = _outline_copy(text)
    _answer(state, {"sections_with_lines": copy})
    data = server.local_extract(fields=["sections_with_lines"], path=str(path))
    assert data == {"sections_with_lines": copy}


def test_a_value_that_cites_few_headings_is_not_a_copy():
    outline = line_check.markdown_outline(_doc())
    value = "`local_extract`: línea 25; `local_classify`: línea 21"
    assert line_check.outline_copy("local_extract_heading_line", value, outline) == (False, None)


# --- REQ-005: «Título: línea N» holds on a real heading --------------------------------------


def test_a_generic_title_on_a_heading_holds():
    text = _doc()
    assert line_check.check_values("Título: línea 1", text) == []
    # Line 3 is not a heading, nor are its neighbours (2 and 4 are blank).
    assert [c.label() for c in line_check.check_values("Título: línea 3", text)] == ["3"]


def test_a_generic_title_next_to_a_heading_does_not_hold():
    """Line 2 is blank: the heading of line 1 is in the tolerance window, but it is not cited."""
    assert [c.label() for c in line_check.check_values("Título: línea 2", _doc())] == ["2"]


def test_a_comment_in_fenced_code_is_no_heading():
    text = "Intro.\n\n```python\n# comentario\nx = 1\n```\n"
    assert [c.label() for c in line_check.check_values("Título: línea 4", text)] == ["4"]


def test_a_title_word_on_a_front_matter_still_holds():
    text = "---\ntitle: Guía\n---\n\nTexto.\n"
    assert line_check.check_values("title: línea 2", text) == []
