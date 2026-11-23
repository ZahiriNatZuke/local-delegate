"""#594: `local_extract` never returns the whole outline for ONE heading.

A field asking for the line of one heading got the whole heading outline (the one the prompt
carried since #568), and «Título: línea 1» on the document title was flagged. #594 cut such a
copy by words. Since 0.54.0 (#692-#698) the model chooses one heading of the catalogue, the
schema caps the list at one item and the program gives its line, so a copy cannot happen and
`outline_copy` is gone. Backend faked (`_run_chat` doubled), no network.
"""

from __future__ import annotations

import json

import pytest

from local_delegate import config, i18n, line_check, locate, server


def _ok(text: str):
    return server.ChatResult(text=text, ok=True, finish_reason="stop")


@pytest.fixture
def backend(monkeypatch, tmp_path):
    calls: list[dict] = []
    state = {"answer": lambda call: _ok("{}")}

    def run_chat(model, system, user, max_tokens, temperature, **_):
        calls.append({"system": system, "user": user, **_})
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


def _line_of(text: str, heading: str) -> int:
    return text.split("\n").index(f"## {heading}") + 1


def _enum(call: dict, field: str) -> list[str]:
    schema = call["response_format"]["schema"]["properties"][field]
    return schema["items"]["properties"]["name"].get("enum") or []


# --- REQ-009 / REQ-010: a field of one heading gives that heading only --------------------------


def test_a_field_of_one_heading_gives_only_that_heading(backend, tmp_path):
    """#594: the model chooses ONE heading of the catalogue (`maxItems: 1`); it can no longer
    copy the whole outline into the field, and the line is the program's."""
    calls, state = backend
    text = _doc()
    path = tmp_path / "tools.md"
    path.write_text(text, encoding="utf-8")
    field = "local_extract_section_heading_line"

    def answer(call):
        prop = call["response_format"]["schema"]["properties"][field]
        assert prop["maxItems"] == 1
        [name] = [n for n in _enum(call, field) if "`local_extract`" in n]
        return _ok(json.dumps({field: [{"name": name}]}))

    state["answer"] = answer
    data = server.local_extract(fields=[field], path=str(path))
    assert len(calls) == 1
    [item] = data[field]
    assert item["start"] == _line_of(text, "`local_extract`")
    assert "outline_copies" not in data["_local_delegate"]


def test_a_free_answer_with_several_headings_keeps_them_and_counts_the_extra(
    backend, tmp_path, monkeypatch
):
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    _calls, state = backend
    text = _doc()
    path = tmp_path / "tools.md"
    path.write_text(text, encoding="utf-8")
    field = "local_section_line"
    _answer(state, {field: [{"name": "## `local_extract`"}, {"name": "## `local_classify`"}]})
    data = server.local_extract(fields=[field], path=str(path))
    assert [i["start"] for i in data[field]] == [
        _line_of(text, "`local_classify`"),
        _line_of(text, "`local_extract`"),
    ]
    assert data["_local_delegate"]["located"][field]["extra"] == 1


def test_a_field_that_asks_for_the_whole_outline_gets_every_heading(backend, tmp_path):
    """`sections_with_lines` names no heading: the index answers with all, and no model runs."""
    calls, _state = backend
    text = _doc()
    path = tmp_path / "tools.md"
    path.write_text(text, encoding="utf-8")
    data = server.local_extract(fields=["sections_with_lines"], path=str(path))
    assert calls == []
    got = [(i["name"], i["start"]) for i in data["sections_with_lines"]]
    assert got == [(h, n) for n, h in line_check.markdown_outline(text)]


# --- the catalogue ---------------------------------------------------------------------------


def test_a_comment_in_fenced_code_is_no_heading():
    text = "Intro.\n\n## Uso\n\n```python\n# comentario\nx = 1\n```\n"
    catalogue = locate.catalogue(locate.build_index(text, "a.md"), 10_000)
    assert "## Uso" in catalogue
    assert "comentario" not in catalogue
