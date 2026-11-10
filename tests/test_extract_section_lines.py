"""#633: a location field over a Markdown section, as the model answers it.

Two subagents asked `local_extract` (with `path`) for `tareas_con_lineas`,
`tabla_de_mutantes_con_lineas` and the like over a plan. The model answered each with the range of
the section that holds them («Tareas: líneas 24-63»), without the items, and the check of the cited
lines reported correct ranges as false: the range starts after the heading and its blank line, so
the words it names («Tareas») are not on the cited lines. Now a range is held by the heading of the
section it starts in, a field that asks for items and got only section ranges is reported in
`section_only_keys` with a warning, and the prompt asks for each item with its line. Backend faked
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


def test_a_section_range_is_held_by_its_heading():
    text = _plan()
    outline = line_check.markdown_outline(text)
    start, end = _body(text, "## Tareas")
    # «Tareas» is on no line of 24-63 nor around them: only the heading of the section says it.
    assert line_check.check_values(f"Tareas: líneas {start}-{end}", text, outline) == []
    start, end = _body(text, "## Tabla de mutantes")
    assert line_check.check_values(f"Tabla de mutantes: líneas {start}-{end}", text, outline) == []


def test_a_range_in_another_section_is_still_reported():
    text = _plan()
    outline = line_check.markdown_outline(text)
    start, end = _body(text, "## Tabla de mutantes")
    bad = line_check.check_values(f"Tareas: líneas {start}-{end}", text, outline)
    assert [c.label() for c in bad] == [f"{start}-{end}"]


def test_without_the_outline_the_check_is_unchanged():
    text = _plan()
    start, end = _body(text, "## Tareas")
    bad = line_check.check_values(f"Tareas: líneas {start}-{end}", text)
    assert [c.label() for c in bad] == [f"{start}-{end}"]


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
    outline = line_check.markdown_outline(text)
    start, end = _body(text, "## Tareas")
    value = f"Tareas: líneas {start}-{end}"
    assert line_check.section_only(field, value, outline) is expected


def test_items_with_their_lines_are_not_section_only():
    text = _plan()
    outline = line_check.markdown_outline(text)
    first = _line_of(text, "- [ ] T1:")
    value = [f"T{i}: implementar la pieza {i}: línea {first + 2 * (i - 1)}" for i in range(1, 11)]
    assert line_check.section_only("tareas_con_lineas", value, outline) is False
    assert line_check.check_values(value, text, outline) == []
    # Each task with its two lines: ranges too, but inside the section, not its whole body.
    ranges = [f"T{i}: líneas {first + 2 * (i - 1)}-{first + 2 * i - 1}" for i in range(1, 11)]
    assert line_check.section_only("tareas_con_lineas", ranges, outline) is False


def test_the_shape_of_the_issue_is_reported_and_its_ranges_hold(backend, tmp_path):
    _calls, state = backend
    text = _plan()
    tasks = _body(text, "## Tareas")
    table = _body(text, "## Tabla de mutantes")
    steps = _body(text, "## Estrategia de verificación")
    answer = {
        "tareas_con_lineas": f"Tareas: líneas {tasks[0]}-{tasks[1]}",
        "tabla_de_mutantes_con_lineas": f"Tabla de mutantes: líneas {table[0]}-{table[1]}",
        "estrategia_de_verificacion_con_lineas": (
            f"Estrategia de verificación: líneas {steps[0]}-{steps[1]}"
        ),
    }
    state["answer"] = lambda call: _ok(json.dumps(answer))
    data = server.local_extract(fields=list(answer), path=_write(tmp_path, text))
    meta = data["_local_delegate"]
    assert "lines_unverified" not in meta
    assert meta["section_only_keys"] == ["tareas_con_lineas"]
    assert meta["warning"] == i18n.t("mcp.warning.extract_section_only", fields="tareas_con_lineas")
    # The values are never rewritten.
    assert {k: data[k] for k in answer} == answer


def test_the_prompt_asks_for_each_item_with_its_line(backend, tmp_path):
    calls, _state = backend
    server.local_extract(fields=["tareas_con_lineas"], path=_write(tmp_path, _plan()))
    (call,) = calls
    assert "cada elemento con su línea" in call["system"]
