"""#586 and #594: `local_extract` no longer returns, in silence, a value it made up or copied.

#586: the model answered `review_verdict: "positive"` for a PR JSON with no review in it; a short
value with words the input does not hold now comes back with `ungrounded_keys` and a warning.
#594: a field asking for the line of ONE heading got the whole heading outline (the one the prompt
carries since #568), and «Título: línea 1» on the document title was flagged. Backend faked
(`_run_chat` doubled), no network.
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


#: The issue's input: `gh pr view --json body,comments,reviews` with no review and no comment.
_PR_JSON = json.dumps(
    {
        "body": "## Qué cambia\n\n- Arreglo del recuento.\n- Closes #586\n",
        "comments": [],
        "reviews": [],
    },
    ensure_ascii=False,
)


# --- #586, REQ-001: a value with words the input does not hold is said ------------------------


def test_a_made_up_verdict_is_said(backend, tmp_path):
    _calls, state = backend
    path = tmp_path / "pr.json"
    path.write_text(_PR_JSON, encoding="utf-8")
    _answer(state, {"review_verdict": "positive", "closes_issue": "#586"})
    data = server.local_extract(fields=["review_verdict", "closes_issue"], path=str(path))
    meta = data.pop("_local_delegate", {})
    # The value is not erased: it may be a legitimate inference.
    assert data == {"review_verdict": "positive", "closes_issue": "#586"}
    assert meta.get("ungrounded_keys") == {"review_verdict": ["positive"]}
    assert meta.get("warning") == i18n.t(
        "mcp.warning.extract_ungrounded_keys", pairs="review_verdict (positive)"
    )


def test_case_accents_plurals_and_substrings_hold():
    grounding = line_check.Grounding("La Revisión de Ana: aprobado. Ver https://github.com/x")
    assert grounding.missing("revision") == []
    assert grounding.missing("Aprobado por Ana") == []
    assert grounding.missing("revisiones") == []
    assert grounding.missing("github") == []
    assert grounding.missing(["aprobado", "rechazado"]) == ["rechazado"]


@pytest.mark.parametrize(
    "value",
    [
        None,
        42,
        True,
        {"verdict": "positive"},
        ["ok", 3],
        "127.0.0.1",  # numbers are reformatted: not checked
        "none",  # shorter than 5 letters
        # A long text paraphrases (a summary): not checked word by word.
        "positive overall with several minor requested adjustments around tests and docs",
    ],
)
def test_values_that_are_not_checked(value):
    assert line_check.Grounding("texto de entrada").missing(value) == []


# --- #586, REQ-002: a value copied from the input passes as before --------------------------


def test_a_json_input_is_read_decoded():
    """An escaped accent or a `\\n` glued to a word in the JSON text is not a missing word."""
    raw = json.dumps({"body": "Tras la revisión\narreglos hechos"})  # ensure_ascii: `ón`
    assert "revisión" not in raw
    grounding = line_check.Grounding(raw)
    assert grounding.missing("revisión") == []
    assert grounding.missing("arreglos") == []


def test_normalized_answers_and_nulls_in_a_list_are_not_flagged():
    grounding = line_check.Grounding("texto de entrada")
    assert grounding.missing("ninguno") == []
    assert grounding.missing(["entrada", None]) == []
    assert grounding.missing(["entrada", None, "positive"]) == ["positive"]


def test_values_from_the_input_leave_no_meta(backend):
    _calls, state = backend
    _answer(state, {"plan": "Enterprise", "domains": "Std 1–5, Ent 1–3"})
    text = "<tr><td>Custom domains</td><td>Std 1–5</td><td>Ent 1–3</td></tr> Enterprise"
    data = server.local_extract(fields=["plan", "domains"], text=text)
    assert "_local_delegate" not in data


def test_the_warning_is_appended_to_an_earlier_one(backend, monkeypatch):
    _calls, state = backend
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    _answer(state, {"verdict": "positive"})
    data = server.local_extract(fields=["verdict", "other"], text="texto")
    meta = data.get("_local_delegate", {})
    assert meta.get("warning") == (
        i18n.t("mcp.warning.extract_missing_keys", fields="other")
        + "; "
        + i18n.t("mcp.warning.extract_ungrounded_keys", pairs="verdict (positive)")
    )


# --- #594: the outline copied into the field of one heading ---------------------------------

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


def test_a_field_that_asks_for_the_whole_outline_is_left_alone(backend, tmp_path):
    """REQ-004: `sections_with_lines` names no heading; the outline is its answer."""
    _calls, state = backend
    text = _doc()
    path = tmp_path / "tools.md"
    path.write_text(text, encoding="utf-8")
    copy = _outline_copy(text)
    _answer(state, {"sections_with_lines": copy})
    data = server.local_extract(fields=["sections_with_lines"], path=str(path))
    assert data == {"sections_with_lines": copy}


def test_a_field_word_that_starts_a_heading_word_picks_it():
    """`intro_heading_line` names «Introducción»; `cuando` names «Cuándo NO delegar» (camelCase)."""
    outline = [(1, "# Guía"), (3, "## Introducción"), (9, "## Uso"), (15, "## Cuándo NO delegar")]
    value = "Guía: línea 1; Introducción: línea 3; Uso: línea 9; Cuándo NO delegar: línea 15"
    assert line_check.outline_copy("intro_heading_line", value, outline) == (
        True,
        (3, "Introducción"),
    )
    assert line_check.outline_copy("cuandoHeadingLine", value, outline) == (
        True,
        (15, "Cuándo NO delegar"),
    )


@pytest.mark.parametrize(
    "name", ["tools_with_lines", "tool_sections_with_lines", "local_headings_lines", "outline"]
)
def test_a_field_that_asks_for_several_places_is_never_cut(name):
    """A plural (`lines`, `sections`, `headings`), or no singular place word, asks for several."""
    text = _doc()
    outline = line_check.markdown_outline(text)
    assert line_check.outline_copy(name, _outline_copy(text), outline) == (False, None)


def test_a_title_word_on_a_front_matter_still_holds():
    text = "---\ntitle: Guía\n---\n\nTexto.\n"
    assert line_check.check_values("title: línea 2", text) == []


def test_a_value_that_cites_few_headings_is_not_a_copy():
    outline = line_check.markdown_outline(_doc())
    value = "`local_extract`: línea 25; `local_classify`: línea 21"
    assert line_check.outline_copy("local_extract_heading_line", value, outline) == (False, None)


# --- #594, REQ-005: «Título: línea 1» on a heading holds -----------------------------------


def test_a_generic_title_on_a_heading_holds():
    text = _doc()
    assert line_check.check_values("Título: línea 1", text) == []
    # Line 3 is not a heading, nor are its neighbours (2 and 4 are blank).
    assert [c.label() for c in line_check.check_values("Título: línea 3", text)] == ["3"]
