"""#568: `local_extract` with `path` can answer "which lines" for a field that asks for them.

Before, a field like `secciones_con_lineas` over a large Markdown came back null from every chunk:
the model saw the text bare and each chunk started without knowing where it fell. Now, with
`path` and a location field (`line_check.is_location_field`), the model sees `N| line` with the
file's ABSOLUTE line in the single call and in every map piece, a Markdown outline (by program)
precedes the content, the `N| ` copied into the other fields is dropped, and the lines cited in
the location fields are checked against the file. Without a location field, or with `text=`,
nothing changes. Backend faked (`_run_chat` doubled), no network.
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


# --- REQ-001 / REQ-004: what the model sees ----------------------------------------------------


def test_every_chunk_carries_its_absolute_lines_and_the_outline(backend, tmp_path):
    calls, state = backend
    state["answer"] = lambda call: _ok(json.dumps({"components": None, LOCATION: None}))
    text = _catalog()
    lines = text.split("\n")
    data = server.local_extract(fields=["components", LOCATION], path=_write(tmp_path, text))
    assert len(calls) > 1, "guard: it chunked"
    assert data["_local_delegate"]["chunked"]["pieces"] == len(calls)
    seen: set[int] = set()
    # The outline is taken out of the piece's budget: prompt and piece fit together.
    budget = server._map_budget(config.max_chars_for_role("long")) + len(INSTRUCTION)
    for call in calls:
        assert len(call["user"]) <= budget
        assert "«| »" in call["system"] and f'"{LOCATION}"' in call["system"]
        assert call["user"].startswith("Esquema de encabezados del documento completo")
        heading = f"### {_name(42)}"
        assert f"{_line_of(text, heading)}: {heading}\n" in call["user"]
        assert "# comentario que no es un encabezado" not in call["user"].split(INSTRUCTION)[0]
        piece_lines = [ln for ln in _content_of(call["user"]).split("\n") if ln]
        numbers = []
        for piece_line in piece_lines:
            m = NUMBERED.match(piece_line)
            assert m, piece_line
            number = int(m.group(1))
            assert (m.group(2) or "").rstrip() == lines[number - 1].rstrip(), number
            numbers.append(number)
        assert numbers == sorted(numbers)
        seen.update(numbers)
    # Every non-blank line of the file reached some chunk, under its own number.
    assert {n for n, ln in enumerate(lines, 1) if ln.strip()} <= seen
    assert max(seen) > 1000, "later chunks are not numbered from 1"


def test_a_single_call_is_numbered_too(backend, tmp_path):
    calls, _state = backend
    text = "# Título\n\nNombre: Ana\n"
    server.local_extract(fields=["name_lines"], path=_write(tmp_path, text, "a.md"))
    (call,) = calls
    assert call["user"] == (
        "Esquema de encabezados del documento completo (línea: encabezado; calculado por "
        "programa, fiable):\n1: # Título\n\n" + INSTRUCTION + "1| # Título\n2| \n3| Nombre: Ana\n"
    )


def test_an_outline_too_long_is_left_out(backend, tmp_path):
    calls, _state = backend
    text = "".join(f"# H{n}\n" for n in range(3000)) + "fin\n"
    server.local_extract(fields=["lines"], path=_write(tmp_path, text, "h.md"))
    assert calls and all(INSTRUCTION in c["user"] for c in calls)
    assert not any(c["user"].startswith("Esquema") for c in calls)
    assert all(c["user"].split(INSTRUCTION)[1].startswith(tuple("0123456789")) for c in calls)


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


# --- REQ-003 / REQ-005: what comes back --------------------------------------------------------


def test_the_prefix_leaves_the_other_fields(backend, tmp_path):
    _calls, state = backend
    text = "# Ficha\n\nNombre: Juan Pérez\n"
    state["answer"] = lambda call: _ok(
        json.dumps({"name": "3| Juan Pérez", "name_lines": "Juan Pérez: línea 3"})
    )
    data = server.local_extract(fields=["name", "name_lines"], path=_write(tmp_path, text, "f.md"))
    assert data["name"] == "Juan Pérez"
    assert data["name_lines"] == "Juan Pérez: línea 3"
    assert "_local_delegate" not in data


def test_a_table_row_is_not_a_prefix(backend, tmp_path):
    _calls, state = backend
    text = "# Ficha\n\nfila\n"
    state["answer"] = lambda call: _ok(json.dumps({"row": "2|3", "row_lines": None}))
    data = server.local_extract(fields=["row", "row_lines"], path=_write(tmp_path, text, "t.md"))
    assert data["row"] == "2|3"


def test_the_model_reading_the_prefix_answers_with_real_lines(backend, tmp_path):
    """The issue's flow: the chunk holding the section reports it with the line it was shown."""
    _calls, state = backend
    text = _catalog()

    def answer(call):
        for piece_line in _content_of(call["user"]).split("\n"):
            m = NUMBERED.match(piece_line)
            if m and m.group(2) == f"### {_name(42)}":
                found = f"{_name(42)}: línea {m.group(1)}"
                return _ok(json.dumps({"components": None, LOCATION: found}))
        return _ok(json.dumps({"components": None, LOCATION: None}))

    state["answer"] = answer
    data = server.local_extract(fields=["components", LOCATION], path=_write(tmp_path, text))
    expected = _line_of(text, f"### {_name(42)}")
    assert data[LOCATION] == f"{_name(42)}: línea {expected}"
    assert "lines_unverified" not in data["_local_delegate"]


def test_cited_lines_are_checked(backend, tmp_path):
    _calls, state = backend
    text = _catalog(sections=3)
    good = _line_of(text, f"### {_name(2)}")
    wrong = _line_of(text, f"### {_name(0)}")
    value = [
        f"{_name(2)}: líneas {good}-{good + 3}",
        f"{_name(1)}: línea {wrong}",
        {"heading": f"### {_name(2)}", "start": good, "end": good + 20},
        f"{_name(0)}: línea 99999",
    ]
    state["answer"] = lambda call: _ok(json.dumps({LOCATION: value}))
    data = server.local_extract(fields=[LOCATION], path=_write(tmp_path, text, "c.md"))
    assert data[LOCATION] == value  # the location field is never rewritten
    meta = data["_local_delegate"]
    assert meta["lines_unverified"] == [f"{LOCATION}: {wrong}", f"{LOCATION}: 99999"]
    assert meta["warning"] == i18n.t(
        "mcp.warning.extract_lines_unverified", lines=", ".join(meta["lines_unverified"])
    )


def test_value_shapes_of_check_values():
    text = _catalog(sections=3)
    good = _line_of(text, f"### {_name(2)}")
    wrong = _line_of(text, f"### {_name(0)}")
    # A name -> [start, end] map is one range, not two loose lines.
    assert line_check.check_values({_name(2): [good, good + 20]}, text) == []
    # An object whose line key holds [start, end] is checked too.
    bad = line_check.check_values({"title": _name(2), "lines": [wrong, wrong + 1]}, text)
    assert [c.label() for c in bad] == [f"{wrong}-{wrong + 1}"]
    # Odd values never raise and cite nothing.
    assert line_check.check_values(["²", 1.5, True, None, {"x": {"y": "z"}}], text) == []


def test_a_file_that_is_not_markdown_gets_no_outline(backend, tmp_path):
    calls, _state = backend
    text = "# comment\nx = 1\n"
    server.local_extract(fields=["lines"], path=_write(tmp_path, text, "a.py"))
    (call,) = calls
    assert call["user"] == INSTRUCTION + "1| # comment\n2| x = 1\n"


def test_a_loose_number_next_to_an_explicit_citation_is_not_a_line():
    text = _catalog(sections=3)
    good = _line_of(text, f"### {_name(2)}")
    # `3-4` is part of the name; `L{good}` is the citation.
    assert line_check.check_values(f"{_name(2)} 3-4 del manual: L{good}", text) == []


def test_each_citation_is_checked_against_its_own_name():
    text = _catalog(sections=3)
    good = _line_of(text, f"### {_name(2)}")
    value = f"{_name(2)}: línea {good}; {_name(1)}: línea {good}"
    bad = line_check.check_values(value, text)
    assert [(c.label(), c.words) for c in bad] == [(str(good), (_name(1),))]


def test_the_lines_warning_is_appended_to_an_earlier_one(backend, tmp_path):
    _calls, state = backend
    text = "# Ficha\n\nNombre: Ana\n"
    state["answer"] = lambda call: _ok(json.dumps({"name_lines": "Zzzz: línea 2"}))
    data = server.local_extract(fields=["name", "name_lines"], path=_write(tmp_path, text, "w.md"))
    meta = data["_local_delegate"]
    assert meta["missing_keys"] == ["name"]
    missing = i18n.t("mcp.warning.extract_missing_keys", fields="name")
    lines = i18n.t("mcp.warning.extract_lines_unverified", lines="name_lines: 2")
    assert meta["warning"] == f"{missing}; {lines}"


def _sections_answer(call, components):
    """The map of a model that reads the prefix: every heading of its piece with its line."""
    if call["user"].startswith("Estos son objetos JSON parciales"):
        # A reduce cut by `max_tokens`, as with ~60 sections and a 512-token cap.
        return server.ChatResult(
            text='{"components": "X", "sections_with_lines": [{"heading": "',
            ok=True,
            finish_reason="length",
        )
    found = []
    for piece_line in _content_of(call["user"]).split("\n"):
        m = NUMBERED.match(piece_line)
        if m and (m.group(2) or "").startswith("### "):
            found.append({"heading": m.group(2), "line": int(m.group(1))})
    return _ok(json.dumps({"components": components, LOCATION: found or None}))


def _expected_sections(text: str) -> list[dict]:
    return [{"heading": h, "line": n} for n, h in line_check.markdown_outline(text) if "###" in h]


def test_sixty_sections_are_joined_by_program_without_a_reduce(backend, tmp_path):
    calls, state = backend
    text = _catalog()
    state["answer"] = lambda call: _sections_answer(call, None)
    data = server.local_extract(fields=["components", LOCATION], path=_write(tmp_path, text))
    assert not any(c["user"].startswith("Estos son objetos") for c in calls)
    assert data[LOCATION] == _expected_sections(text)
    assert len(data[LOCATION]) == 60
    assert "lines_unverified" not in data["_local_delegate"]


def test_sixty_sections_survive_a_cut_reduce(backend, tmp_path):
    """The other field needs the model's judgment; its cut reply does not lose the sections."""
    calls, state = backend
    text = _catalog()
    state["answer"] = lambda call: _sections_answer(call, "X")
    data = server.local_extract(fields=["components", LOCATION], path=_write(tmp_path, text))
    assert any(c["user"].startswith("Estos son objetos") for c in calls), "guard: reduce ran"
    assert "error" not in data["_local_delegate"]
    assert data["components"] == "X"
    assert data[LOCATION] == _expected_sections(text)
    assert "Deja a null las claves de ubicación" in calls[-1]["system"]
