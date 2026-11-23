"""#633: a location field over a Markdown section, as the model answers it.

Two subagents asked `local_extract` (with `path`) for `tareas_con_lineas`,
`tabla_de_mutantes_con_lineas` and the like over a plan. The model answered each with the range of
the section that holds them, without the items. A field that asks for items and got only section
ranges is reported in `section_only_keys` with a warning. Since 0.54.0 the model anchors the
heading and the program gives the section's lines (#692-#698): the check by words of #633 is
gone with the model's numbers, and `section_only` reads the items already placed. Backend faked
(`_run_chat` doubled), no network.
"""

from __future__ import annotations

import json

import pytest

from local_delegate import config, i18n, locate, server


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


def _plan() -> str:
    """A plan shaped like the one of the issue: tasks as checkboxes, a table, numbered steps."""
    out = ["# Plan: cambio de ejemplo", "", "## Contexto", ""]
    out += [f"Párrafo {i} de contexto con texto de relleno para dar volumen." for i in range(8)]
    out += ["", "## Tareas", ""]
    for i in range(1, 11):
        out += [f"- [ ] T{i}: implementar la pieza {i} del reparto", f"  - Detalle del caso {i}."]
    out += ["", "## Tabla de mutantes", "", "Cada mutante debe hacer fallar un test.", ""]
    out += ["| Id | Mutación | Test |", "|----|----------|------|"]
    out += [f"| M{i} | invertir la condición {i} | test_caso_{i} |" for i in range(1, 13)]
    out += ["", "## Estrategia de verificación", ""]
    out += [f"{i}. Paso {i}: ejecutar la suite parcial {i}." for i in range(1, 8)]
    return "\n".join(out) + "\n"


def _line_of(text: str, needle: str) -> int:
    return text.count("\n", 0, text.index(needle)) + 1


def _body(text: str, heading: str) -> tuple[int, int]:
    """The lines of a section's content, without its heading and the blank line after it."""
    start = _line_of(text, heading) + 2
    lines = text.split("\n")
    end = start
    while end < len(lines) and not lines[end].startswith("#"):
        end += 1
    while not lines[end - 1].strip():
        end -= 1
    return start, end


def _write(tmp_path, text: str, name: str = "plan.md") -> str:
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return str(path)


def _section(text: str, heading: str) -> locate.Item:
    """The item of a whole section, heading included, as an anchor on its heading gives it."""
    index = locate.build_index(text, "plan.md")
    [block] = [b for b in index.blocks if b.kind == "section" and b.name == heading]
    return locate.Item(name=heading, start=block.start, end=block.end, source="anchor")


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("tareas_con_lineas", True),  # asks for items: the tasks
        ("requisitos_candidatos_con_lineas", True),
        ("estrategia_de_verificacion_con_lineas", False),  # one section: its range is the answer
        ("tabla_de_mutantes_con_lineas", False),  # a table: its range is the answer
        ("secciones_con_lineas", False),  # sections: their ranges are the answer
    ],
)
def test_section_only_depends_on_what_the_field_asks_for(field, expected):
    text = _plan()
    index = locate.build_index(text, "plan.md")
    items = [_section(text, "## Tareas")]
    assert locate.section_only(locate.classify_field(field), items, index) is expected


def test_items_with_their_lines_are_not_section_only():
    text = _plan()
    index = locate.build_index(text, "plan.md")
    req = locate.classify_field("tareas_con_lineas")
    first = _line_of(text, "- [ ] T1:")
    lines = [
        locate.Item(name=f"T{i}", start=first + 2 * (i - 1), end=first + 2 * (i - 1))
        for i in range(1, 11)
    ]
    assert locate.section_only(req, lines, index) is False
    # Each task with its two lines: ranges too, but inside the section, not its whole body.
    ranges = [
        locate.Item(name=f"T{i}", start=first + 2 * (i - 1), end=first + 2 * i - 1)
        for i in range(1, 11)
    ]
    assert locate.section_only(req, ranges, index) is False


def test_the_shape_of_the_issue_is_reported(backend, tmp_path):
    _calls, state = backend
    text = _plan()
    headings = {
        "tareas_con_lineas": "## Tareas",
        "tabla_de_mutantes_con_lineas": "## Tabla de mutantes",
        "estrategia_de_verificacion_con_lineas": "## Estrategia de verificación",
    }
    answer = {
        field: [{"name": heading.lstrip("# "), "anchor": heading}]
        for field, heading in headings.items()
    }
    state["answer"] = lambda call: _ok(json.dumps(answer))
    data = server.local_extract(fields=list(answer), path=_write(tmp_path, text))
    meta = data["_local_delegate"]
    assert "lines_unverified" not in meta
    assert meta["section_only_keys"] == ["tareas_con_lineas"]
    assert meta["warning"] == i18n.t("mcp.warning.extract_section_only", fields="tareas_con_lineas")
    for field, heading in headings.items():
        [item] = data[field]
        assert item["start"] == _line_of(text, heading), field
        section = _section(text, heading)
        assert (item["start"], item["end"]) == (section.start, section.end), field


def test_the_prompt_does_not_ask_for_line_numbers(backend, tmp_path):
    """#694: the example «Título: líneas 120-160» biased the model to headings and bullets."""
    calls, _state = backend
    server.local_extract(fields=["tareas_con_lineas"], path=_write(tmp_path, _plan()))
    (call,) = calls
    assert "Título" not in call["system"]
    assert "líneas 1" not in call["system"]
    assert "anchor" in call["system"]
    assert "No escribas números de línea" in call["system"]
