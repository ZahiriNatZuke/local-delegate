"""#568, #692-#698: `local_extract` with `path` answers "which lines" for a field that asks.

#568 numbered the input (`N| line`) so the model could write the lines, and checked them by
words; #694 and #696 showed that the model still wrote wrong lines and that the check marked
good ranges as doubtful. Since 0.54.0 the model never sees nor writes a line number (REQ-012):
an index of the file answers alone when it can, and otherwise the model chooses names of the
catalogue or copies an anchor, and the program computes the lines (REQ-001). Without a location
field, or with `text=`, nothing changes. Backend faked (`_run_chat` doubled), no network.
"""

from __future__ import annotations

import json
import re

import pytest

from local_delegate import config, i18n, line_check, server

LOCATION = "sections_with_lines"
NUMBERED = re.compile(r"^(\d+)\|(?: (.*))?$")
INSTRUCTION = "Extrae los campos del siguiente contenido:\n\n"


def _ok(text: str):
    return server.ChatResult(text=text, ok=True, finish_reason="stop")


@pytest.fixture
def backend(monkeypatch, tmp_path):
    calls: list[dict] = []
    state = {"answer": lambda call: _ok("{}")}

    def run_chat(model, system, user, max_tokens, temperature, **_):
        call = {"system": system, "user": user}
        calls.append(call)
        return state["answer"](call), 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    i18n.reset()
    return calls, state


def _name(n: int) -> str:
    """A distinct component name made of letters only (`Patronbq`): numbers confirm nothing."""
    return "Patron" + chr(97 + n // 26) + chr(97 + n % 26)


def _catalog(sections: int = 60) -> str:
    """A Markdown catalogue shaped like the one of the issue: `###` sections, > 48 K chars."""
    out = ["# Catálogo de componentes\n\n", "## Patrones de página\n\n"]
    for n in range(sections):
        out.append(f"### {_name(n)}\n\n")
        out.extend(
            f"Detalle {i} del componente {n}: uso, variantes y estados.\n" for i in range(26)
        )
        out.append("\n```python\n# comentario que no es un encabezado\nx = 1\n```\n\n")
    text = "".join(out)
    if sections >= 60:  # it must chunk
        assert len(text) > max(48_000, 1.5 * config.max_chars_for_role("long"))
    return text


def _write(tmp_path, text: str, name: str = "catalog.md") -> str:
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return str(path)


def _line_of(text: str, needle: str) -> int:
    return text.count("\n", 0, text.index(needle)) + 1


def _content_of(user: str) -> str:
    return user.split(INSTRUCTION, 1)[1]


# --- the criterion ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        LOCATION, "secciones_con_lineas", "lines", "líneas", "lineRange", "line_number",
        "start_line", "lineno", "endLine", "sectionLineNumbers", "heading_line", "section_line",
        "linea_del_titulo", "seccion_y_linea",
    ],
)  # fmt: skip
def test_location_fields(name):
    assert line_check.is_location_field(name)


@pytest.mark.parametrize(
    "name",
    [
        "name", "components", "allocation", "pipeline", "deadline", "outline", "inline",
        "line_items", "address_line", "lineItems", "price_range", "age_range", "location",
        "locality", "position", "timezone_offset", "headline",
        # A quantity of lines is not a place in the file.
        "lines_of_code", "total_lines", "num_lines", "lines_added", "lines_removed",
        "lines_count", "lineas_modificadas", "number_of_lines", "changed_lines",
    ],
)  # fmt: skip
def test_not_location_fields(name):
    assert not line_check.is_location_field(name)


def test_markdown_outline_skips_fenced_code():
    text = "# A\n\n```\n# not a heading\n```\n  ## B\n#nope\n"
    assert line_check.markdown_outline(text) == [(1, "# A"), (6, "## B")]


# --- REQ-012: what the model sees ------------------------------------------------------------

#: A line number the model could copy: a `N| ` prefix, «líneas 12» or «línea 12».
LINE_NUMBER = re.compile(r"(?m)^\s*\d+\|(?: |$)|l[ií]neas? \d")


def test_no_line_number_reaches_the_model(backend, tmp_path):
    """No prefix, no «líneas N» and no «Título» example in any call, chunked or not."""
    calls, state = backend
    state["answer"] = lambda call: _ok(json.dumps({"components": None, "lines": None}))
    text = _catalog()
    lines = text.split("\n")
    data = server.local_extract(fields=["components", "lines"], path=_write(tmp_path, text))
    assert len(calls) > 1, "guard: it chunked"
    assert data["_local_delegate"]["chunked"]["pieces"] == len(calls)
    budget = server._map_budget(config.max_chars_for_role("long")) + len(INSTRUCTION)
    seen: list[str] = []
    for call in calls:
        assert len(call["user"]) <= budget
        assert not LINE_NUMBER.search(call["system"]) and not LINE_NUMBER.search(call["user"])
        assert "Título" not in call["system"] and "Título" not in call["user"]
        assert '"lines"' in call["system"] and "anchor" in call["system"]
        catalogue, content = call["user"].split(INSTRUCTION, 1)
        heading = f"### {_name(42)}"
        assert f"- section: {heading}\n" in catalogue, "the catalogue of the whole file"
        assert "# comentario que no es un encabezado" not in catalogue
        seen.extend(content.split("\n"))
    # Every non-blank line of the file reached some chunk, bare.
    assert {ln for ln in lines if ln.strip()} <= set(seen)


def test_a_single_call_is_bare_and_carries_the_catalogue(backend, tmp_path):
    calls, _state = backend
    text = "# Ficha\n\nNombre: Ana\n"
    server.local_extract(fields=["name_lines"], path=_write(tmp_path, text, "a.md"))
    (call,) = calls
    assert call["user"] == (
        "Catálogo de elementos del fichero (tipo y nombre, calculado por programa):\n"
        "- section: # Ficha\n\n" + INSTRUCTION + text
    )


def test_the_catalogue_is_left_out_when_too_long(backend, tmp_path):
    calls, _state = backend
    text = "".join(f"# H{n}\n" for n in range(3000)) + "fin\n"
    server.local_extract(fields=["lines"], path=_write(tmp_path, text, "h.md"))
    assert calls and all(c["user"].startswith(INSTRUCTION) for c in calls)


# --- REQ-002: nothing changes without a location field or without `path` ----------------------


def test_without_a_location_field_the_prompt_is_unchanged(backend, tmp_path):
    calls, _state = backend
    text = "# Título\n\nNombre: Ana\n"
    server.local_extract(fields=["name"], path=_write(tmp_path, text, "a.md"))
    (call,) = calls
    assert call["user"] == INSTRUCTION + text
    assert "«| »" not in call["system"]


def test_without_a_location_field_chunks_are_bare(backend, tmp_path):
    calls, _state = backend
    server.local_extract(fields=["components"], path=_write(tmp_path, _catalog()))
    assert len(calls) > 1
    assert not any(NUMBERED.match(c["user"].split(INSTRUCTION)[1].split("\n")[0]) for c in calls)


def test_inline_text_is_never_numbered(backend):
    calls, _state = backend
    text = "# Título\n\nNombre: Ana\n"
    server.local_extract(fields=[LOCATION], text=text)
    (call,) = calls
    assert call["user"] == INSTRUCTION + text


# --- what the other fields keep -------------------------------------------------------------


def test_a_table_row_is_not_a_prefix(backend, tmp_path):
    _calls, state = backend
    text = "# Ficha\n\nfila\n"
    state["answer"] = lambda call: _ok(json.dumps({"row": "2|3", "row_lines": None}))
    data = server.local_extract(fields=["row", "row_lines"], path=_write(tmp_path, text, "t.md"))
    assert data["row"] == "2|3"


# --- REQ-001 / REQ-009 / REQ-018: what comes back ---------------------------------------------


def test_the_index_answers_a_section_with_its_real_line(backend, tmp_path):
    """The issue's flow: `sections_with_lines` over the catalogue, by the index, no model."""
    calls, _state = backend
    text = _catalog()
    data = server.local_extract(fields=[LOCATION], path=_write(tmp_path, text))
    assert calls == []
    [item] = [i for i in data[LOCATION] if i["name"] == f"### {_name(42)}"]
    assert item["start"] == _line_of(text, f"### {_name(42)}")
    assert item["end"] < _line_of(text, f"### {_name(43)}")


def test_the_models_numbers_never_reach_the_output(backend, tmp_path):
    _calls, state = backend
    text = _catalog(sections=3)
    value = [
        {"name": _name(2), "anchor": f"### {_name(2)}", "start": 99999},
        {"name": "otro", "line": 7},
    ]
    state["answer"] = lambda call: _ok(json.dumps({"lines": value}))
    data = server.local_extract(fields=["lines"], path=_write(tmp_path, text, "c.md"))
    start = _line_of(text, f"### {_name(2)}")
    assert data["lines"][0]["start"] == start, "the anchor's line, not 99999"
    assert data["lines"][1] == {"name": "otro", "start": None, "end": None}
    assert "99999" not in json.dumps(data)
    assert "lines_unverified" not in data["_local_delegate"]


def test_a_file_that_is_not_markdown_is_bare_too(backend, tmp_path):
    calls, _state = backend
    text = "# comment\nx = 1\n"
    server.local_extract(fields=["lines"], path=_write(tmp_path, text, "a.py"))
    (call,) = calls
    assert call["user"].endswith(INSTRUCTION + text)
    assert "- variable: x" in call["user"].split(INSTRUCTION)[0]


def test_the_unlocated_warning_is_appended_to_an_earlier_one(backend, tmp_path):
    _calls, state = backend
    text = "# Ficha\n\nNombre: Ana\n"
    state["answer"] = lambda call: _ok(
        json.dumps({"name_lines": [{"name": "Zzzz", "anchor": "no está en el fichero"}]})
    )
    data = server.local_extract(fields=["name", "name_lines"], path=_write(tmp_path, text, "w.md"))
    meta = data["_local_delegate"]
    assert meta["missing_keys"] == ["name"]
    missing = i18n.t("mcp.warning.extract_missing_keys", fields="name")
    unlocated = i18n.t("mcp.warning.extract_unlocated", items="name_lines: Zzzz (not_found)")
    assert meta["warning"] == f"{missing}; {unlocated}"


def _expected_sections(text: str) -> list[dict]:
    """Every heading of the catalogue and the line it starts at, from `markdown_outline`."""
    return [{"name": h, "start": n} for n, h in line_check.markdown_outline(text)]


def _components_answer(call, components):
    if call["user"].startswith("Estos son objetos JSON parciales"):
        # A reduce cut by `max_tokens`.
        return server.ChatResult(text='{"components": "X", "', ok=True, finish_reason="length")
    return _ok(json.dumps({"components": components}))


def test_sixty_sections_are_answered_by_program_without_a_reduce(backend, tmp_path):
    calls, state = backend
    text = _catalog()
    state["answer"] = lambda call: _components_answer(call, None)
    data = server.local_extract(fields=["components", LOCATION], path=_write(tmp_path, text))
    assert calls, "guard: `components` needs the model"
    assert not any(c["user"].startswith("Estos son objetos") for c in calls)
    assert all(f'"{LOCATION}"' not in c["system"] for c in calls), "never asked to the model"
    got = [{"name": i["name"], "start": i["start"]} for i in data[LOCATION]]
    assert got == _expected_sections(text)
    assert sum(i["name"].startswith("### ") for i in data[LOCATION]) == 60


def test_sixty_sections_survive_a_cut_reduce(backend, tmp_path):
    """The other field needs the model's judgment; its cut reply does not lose the sections."""
    calls, state = backend
    text = _catalog()
    state["answer"] = lambda call: _components_answer(call, "X")
    data = server.local_extract(fields=["components", LOCATION], path=_write(tmp_path, text))
    assert any(c["user"].startswith("Estos son objetos") for c in calls), "guard: reduce ran"
    assert "error" not in data["_local_delegate"]
    assert data["components"] == "X"
    got = [{"name": i["name"], "start": i["start"]} for i in data[LOCATION]]
    assert got == _expected_sections(text)


# --- REQ-013: anchors of a chunked call -------------------------------------------------------


def _notes() -> str:
    """Paragraphs of filler with marked lines: a unique one late, one repeated in two places."""
    out: list[str] = []
    for k in range(400):
        out.append(f"Párrafo {k}: relleno sin nada que buscar en esta línea.")
        if k == 20:
            out.append("MARCA-A: el valor repetido vive aquí")
        if k == 300:
            out.append("MARCA-B: el valor repetido vive aquí")
        if k == 330:
            out.append("una línea única al final del documento")
        out.append("")
    return "\n".join(out) + "\n"


def test_chunked_anchors_are_resolved_against_the_whole_file(backend, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "max_chars_for_role", lambda role: 4_000)
    calls, state = backend
    text = _notes()

    def answer(call):
        content = call["user"].split(INSTRUCTION, 1)[-1]
        found = []
        if "MARCA-B" in content:
            # Unique in this piece, repeated in the file: this piece's line, not `ambiguous`.
            found.append({"name": "repetido", "anchor": "el valor repetido vive aquí"})
        if "una línea única" in content or "MARCA-A" in content:
            # Two pieces anchor the same element (the second only knows it from elsewhere).
            found.append({"name": "único", "anchor": "una línea única al final"})
        return _ok(json.dumps({"lines": found or None}))

    state["answer"] = answer
    data = server.local_extract(fields=["lines"], path=_write(tmp_path, text, "notas.txt"))
    assert len(calls) > 3, "guard: it chunked"
    unique = _line_of(text, "una línea única")
    repeated = _line_of(text, "MARCA-B")
    assert data["lines"] == [
        {"name": "repetido", "start": repeated, "end": repeated},
        {"name": "único", "start": unique, "end": unique},
    ]
    assert "unlocated" not in data["_local_delegate"]
