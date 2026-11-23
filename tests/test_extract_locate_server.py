"""#692-#698: `local_extract` with `path` and location fields, end to end with a faked backend.

The lines of a location field are the program's (REQ-001): the index of the file answers alone
when it can (REQ-009), the model chooses names of the index (REQ-010) or copies anchors
(REQ-011), and the value has one shape (REQ-002). Inputs are synthetic, built here with the
lines each test expects counted here, never taken from `locate`. Backend faked (`_run_chat`
doubled), no network; the usage log goes to `tmp_path`.
"""

from __future__ import annotations

import json

import pytest

from local_delegate import config, i18n, server


def _ok(text: str, finish: str = "stop"):
    return server.ChatResult(text=text, ok=True, finish_reason=finish)


@pytest.fixture
def backend(monkeypatch, tmp_path):
    """A model whose answer is `state["answer"](call)`; each call is recorded."""
    state: dict = {"answer": lambda call: "{}", "calls": [], "log_dir": tmp_path}

    def run_chat(model, system, user, max_tokens, temperature, **kwargs):
        call = {
            "model": model,
            "system": system,
            "user": user,
            "max_tokens": max_tokens,
            "role": kwargs.get("role"),
            "response_format": kwargs.get("response_format"),
        }
        state["calls"].append(call)
        answer = state["answer"](call)
        result = answer if isinstance(answer, server.ChatResult) else _ok(answer)
        return result, 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "MODEL_CODE", "code-model")
    monkeypatch.setattr(config, "MODEL_LONG", "long-model")
    monkeypatch.setattr(config, "MODEL_MECHANICAL", "mechanical-model")
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    i18n.reset()
    return state


def _write(tmp_path, text: str, name: str) -> str:
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return str(path)


def _rows(state) -> list[dict]:
    rows: list[dict] = []
    for file in sorted(state["log_dir"].glob("usage*.jsonl")):
        rows += [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()]
    return [row for row in rows if row.get("tool") == "local_extract"]


def _enum(call: dict, field: str) -> list[str]:
    schema = call["response_format"]["schema"]["properties"][field]
    return schema["items"]["properties"]["name"].get("enum") or []


def _line_of(text: str, needle: str) -> int:
    """The 1-based line of the only line of `text` that holds `needle` (checked)."""
    hits = [n for n, line in enumerate(text.split("\n"), start=1) if needle in line]
    assert len(hits) == 1, (needle, hits)
    return hits[0]


# --- inputs ----------------------------------------------------------------------------------


def _python(functions: int = 6) -> str:
    out = ['"""Módulo de prueba."""', "", "import os", "", "LIMIT = 3", ""]
    for k in range(functions):
        name = f"validate_{k}" if k % 2 == 0 else f"render_{k}"
        out += [
            f"def {name}(value):",
            f"    # comprueba el caso {k}",
            f"    return value + {k}",
            "",
        ]
    out += ["class Store:", "    def save(self):", "        return 1", ""]
    return "\n".join(out)


def _markdown(sections: int = 5) -> str:
    out = ["# Documento", "", "Introducción breve.", ""]
    for k in range(sections):
        out += [f"## Sección {k}", "", f"Texto de la sección {k}.", ""]
    return "\n".join(out)


def _requirements() -> str:
    out = ["# Spec", ""]
    for k in range(1, 8):
        out += [f"- **REQ-{k:03d}** — Requisito número {k}.", f"  - Verify: test {k}", ""]
    return "\n".join(out)


def _diff(files: int) -> tuple[str, list[tuple[str, int, int]]]:
    out: list[str] = []
    expected: list[tuple[str, int, int]] = []
    for k in range(files):
        first = len(out) + 1
        out += [
            f"diff --git a/src/f{k}.ts b/src/f{k}.ts",
            "index 0000000..1111111 100644",
            f"--- a/src/f{k}.ts",
            f"+++ b/src/f{k}.ts",
            "@@ -1,2 +1,2 @@",
            " const a = 1;",
            f"-const b = {k};",
            f"+const b = {k + 1};",
        ]
        expected.append((f"src/f{k}.ts", first, len(out)))
    return "\n".join(out) + "\n", expected


def _typescript(functions: int, methods: int) -> str:
    out = [
        "export interface Row {",
        "  id: number;",
        "}",
        "",
        "export interface Column {",
        "  name: string;",
        "}",
        "",
        "export const LIMIT = 10;",
        "const OTHER = 'x';",
        "",
    ]
    for k in range(functions):
        out += [
            f"export function helper{k}(row: Row): number {{",
            f"  return row.id + {k};",
            "}",
            "",
        ]
    out += ["export class StepsPanel {", "  private count = 0;", ""]
    for k in range(methods):
        out += [f"  method{k}(row: Row): number {{", f"    return this.count + {k};", "  }", ""]
    out += ["}", ""]
    return "\n".join(out)


# --- REQ-001 / REQ-002 --------------------------------------------------------------------------

ANCHOR_FIELD = "orden_local_y_barra_con_lineas"


@pytest.mark.parametrize(
    "item",
    [
        {"name": "barra", "anchor": "la barra lateral se pliega", "start": 99, "end": 120},
        {"name": "barra", "anchor": "la barra lateral se pliega", "lines": [5, 9]},
    ],
)
def test_model_numbers_never_reach_the_value(backend, tmp_path, item):
    text = "\n".join(f"Línea de relleno número {k}." for k in range(30))
    text += "\nAquí la barra lateral se pliega al abrir el panel.\n"
    path = _write(tmp_path, text, "notas.txt")
    backend["answer"] = lambda call: json.dumps({ANCHOR_FIELD: [item]})
    data = server.local_extract(fields=[ANCHOR_FIELD], path=path)
    line = _line_of(text, "la barra lateral se pliega")
    assert data[ANCHOR_FIELD] == [{"name": "barra", "start": line, "end": line}]
    assert "99" not in json.dumps(data["_local_delegate"])


def test_a_model_number_without_an_anchor_is_null(backend, tmp_path):
    text = "\n".join(f"Línea de relleno número {k}." for k in range(30)) + "\n"
    path = _write(tmp_path, text, "notas.txt")
    backend["answer"] = lambda call: json.dumps({ANCHOR_FIELD: [{"name": "barra", "start": 5}]})
    data = server.local_extract(fields=[ANCHOR_FIELD], path=path)
    assert data[ANCHOR_FIELD] == [{"name": "barra", "start": None, "end": None}]
    assert data["_local_delegate"]["unlocated"][ANCHOR_FIELD][0]["name"] == "barra"


def test_a_line_string_from_the_model_is_a_type_mismatch(backend, tmp_path):
    text = "\n".join(f"Línea de relleno número {k}." for k in range(30)) + "\n"
    path = _write(tmp_path, text, "notas.txt")
    backend["answer"] = lambda call: json.dumps({ANCHOR_FIELD: "barra: líneas 5-9"})
    data = server.local_extract(fields=[ANCHOR_FIELD], path=path)
    assert len(backend["calls"]) == 2, "one retry"
    assert data[ANCHOR_FIELD] is None
    assert ANCHOR_FIELD in data["_local_delegate"]["type_mismatch_keys"]


def _shape_ok(value, total_lines: int) -> None:
    assert isinstance(value, list) and value
    starts = []
    for item in value:
        assert set(item) <= {"name", "start", "end", "hunks"}
        assert isinstance(item["name"], str)
        if item["start"] is None:
            assert item["end"] is None
            continue
        assert 1 <= item["start"] <= item["end"] <= total_lines
        starts.append(item["start"])
    assert starts == sorted(starts)


def _selection_answer(field):
    def answer(call):
        names = _enum(call, field)
        return json.dumps({field: [{"name": n} for n in names[:2]]})

    return answer


def _anchor_answer(field, anchor):
    return lambda call: json.dumps({field: [{"name": "x", "anchor": anchor}]})


@pytest.mark.parametrize(
    ("name", "text", "field", "answer", "small"),
    [
        ("mod.py", _python(), "funciones_con_lineas", None, False),
        ("mod.py", _python(), "funciones_que_validan_con_lineas", "selection", False),
        ("notas.txt", "uno\ndos\nla barra lateral\ntres\n", ANCHOR_FIELD, "anchor", False),
        ("pr.patch", _diff(5)[0], "ficheros_y_hunks_con_lineas", None, False),
        ("doc.md", _markdown(40), "secciones_con_lineas", None, True),
        ("notas.txt", "relleno\n" * 600 + "la barra lateral\n", ANCHOR_FIELD, "anchor", True),
    ],
    ids=["index", "selection", "anchor", "diff", "index-chunked", "anchor-chunked"],
)
def test_every_location_value_has_the_new_shape(
    backend, tmp_path, monkeypatch, name, text, field, answer, small
):
    if small:
        monkeypatch.setattr(config, "max_chars_for_role", lambda role: 1_500)
    if answer == "selection":
        backend["answer"] = _selection_answer(field)
    elif answer == "anchor":
        backend["answer"] = _anchor_answer(field, "la barra lateral")
    data = server.local_extract(fields=[field], path=_write(tmp_path, text, name))
    total = len(text.split("\n")) - (1 if text.endswith("\n") else 0)
    _shape_ok(data[field], total)


# --- REQ-009 ----------------------------------------------------------------------------------


def test_index_only_fields_never_reach_the_backend_over_a_patch(backend, tmp_path):
    """#697: the literal name of the issue and its synonym give the same files, with no call."""
    text, expected = _diff(26)
    path = _write(tmp_path, text, "pr.patch")
    fields = ["ficheros_con_lineas", "lista_de_ficheros_con_sus_lineas"]
    data = server.local_extract(fields=fields, path=path)
    assert backend["calls"] == []
    want = [{"name": p, "start": a, "end": b} for p, a, b in expected]
    assert data["ficheros_con_lineas"] == want
    assert data["lista_de_ficheros_con_sus_lineas"] == want
    meta = data["_local_delegate"]
    assert "chunked" not in meta
    assert meta["located"]["ficheros_con_lineas"]["by"] == "program"
    assert meta["located"]["ficheros_con_lineas"]["index"] == "diff"


def test_the_functions_of_a_typescript_file_are_only_functions(backend, tmp_path):
    """#698: 30 functions and 30 methods beside a class, two interfaces and constants."""
    text = _typescript(30, 30)
    data = server.local_extract(
        fields=["funciones_con_lineas"], path=_write(tmp_path, text, "panel.ts")
    )
    assert backend["calls"] == []
    names = [item["name"] for item in data["funciones_con_lineas"]]
    assert len(names) == 60
    assert not {"Row", "Column", "LIMIT", "OTHER", "StepsPanel"} & set(names)
    first = data["funciones_con_lineas"][0]
    assert first["start"] == _line_of(text, "export function helper0(")


@pytest.mark.parametrize(
    ("name", "text", "field", "first"),
    [
        ("mod.py", _python(), "funciones_con_lineas", "def validate_0("),
        ("doc.md", _markdown(), "secciones_con_lineas", "# Documento"),
        ("spec.md", _requirements(), "requisitos_con_lineas", "**REQ-001**"),
    ],
)
def test_index_only_fields_never_reach_the_backend(backend, tmp_path, name, text, field, first):
    data = server.local_extract(fields=[field], path=_write(tmp_path, text, name))
    assert backend["calls"] == []
    assert data[field][0]["start"] == _line_of(text, first)


def test_program_only_row_is_written(backend, tmp_path):
    text, _expected = _diff(3)
    server.local_extract(fields=["ficheros_con_lineas"], path=_write(tmp_path, text, "a.patch"))
    [row] = _rows(backend)
    assert row["model"] == server.PROGRAM_MODEL
    assert row.get("program_only") is True
    assert row.get("tokens_in") == 0


def test_a_singular_heading_field_gets_one_heading(backend, tmp_path):
    """#594: the model chooses one heading of the catalogue; one item, with its line."""
    text = _markdown()
    chosen: list[str] = []

    def answer(call):
        names = _enum(call, "intro_heading_line")
        assert (
            call["response_format"]["schema"]["properties"]["intro_heading_line"]["maxItems"] == 1
        )
        chosen.append(next(n for n in names if "Sección 2" in n))
        return json.dumps({"intro_heading_line": [{"name": chosen[0]}]})

    backend["answer"] = answer
    data = server.local_extract(fields=["intro_heading_line"], path=_write(tmp_path, text, "d.md"))
    [item] = data["intro_heading_line"]
    assert item["name"] == chosen[0]
    assert item["start"] == _line_of(text, "## Sección 2")


# --- REQ-010 ----------------------------------------------------------------------------------


def test_selected_names_get_the_index_lines(backend, tmp_path):
    text = _python()
    field = "funciones_que_validan_con_lineas"

    def answer(call):
        names = _enum(call, field)
        assert "validate_0" in names and "validate_2" in names
        return json.dumps({field: [{"name": "validate_2"}, {"name": "validate_0"}]})

    backend["answer"] = answer
    data = server.local_extract(fields=[field], path=_write(tmp_path, text, "m.py"))
    assert [(i["name"], i["start"]) for i in data[field]] == [
        ("validate_0", _line_of(text, "def validate_0(")),
        ("validate_2", _line_of(text, "def validate_2(")),
    ]
    assert data["_local_delegate"]["located"][field]["by"] == "selection"


def test_a_name_outside_the_index_is_unlocated(backend, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")  # free mode: no enum holds it
    field = "funciones_que_validan_con_lineas"
    backend["answer"] = lambda call: json.dumps({field: [{"name": "no_existe"}]})
    data = server.local_extract(fields=[field], path=_write(tmp_path, _python(), "m.py"))
    assert data[field] == [{"name": "no_existe", "start": None, "end": None}]
    [miss] = data["_local_delegate"]["unlocated"][field]
    assert miss["reason"] == "not_in_index"


# --- REQ-011 (#694) ---------------------------------------------------------------------------


def test_a_jsdoc_anchor_is_never_returned_as_code(backend, tmp_path):
    text = (
        "/**\n"
        " * Guarda el orden local de la barra.\n"
        " */\n"
        "export function saveOrder(order: number[]): void {\n"
        "  localStorage.setItem('order', JSON.stringify(order));\n"
        "}\n"
    )
    backend["answer"] = lambda call: json.dumps(
        {
            ANCHOR_FIELD: [
                {"name": "doc", "anchor": "Guarda el orden local de la barra."},
                {"name": "code", "anchor": "localStorage.setItem('order'"},
            ]
        }
    )
    data = server.local_extract(fields=[ANCHOR_FIELD], path=_write(tmp_path, text, "bar.ts"))
    by_name = {item["name"]: item for item in data[ANCHOR_FIELD]}
    assert by_name["doc"]["start"] is None
    assert by_name["code"]["start"] == _line_of(text, "localStorage.setItem")
    [miss] = data["_local_delegate"]["unlocated"][ANCHOR_FIELD]
    assert miss == {"name": "doc", "reason": "in_comment"}


# --- REQ-014 ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "text", "role"),
    [
        ("big.ts", _typescript(40, 0), "code"),
        ("notes.md", _markdown(60), "long"),
        ("table.md", "| a | b |\n|---|---|\n| 1 | 2 |\n\nla barra lateral\n", "long"),
    ],
)
def test_location_fields_never_go_to_the_mechanical_role(backend, tmp_path, name, text, role):
    backend["answer"] = _anchor_answer(ANCHOR_FIELD, "la barra lateral")
    data = server.local_extract(fields=[ANCHOR_FIELD, "titulo"], path=_write(tmp_path, text, name))
    assert backend["calls"], "guard: the model was called"
    assert {c["role"] for c in backend["calls"]} == {role}
    assert {c["model"] for c in backend["calls"]} == {f"{role}-model"}
    reason = data["_local_delegate"]["role_reason"]
    assert reason["reason"] == "location" and reason["role"] == role
    [row] = _rows(backend)
    assert row.get("role_reason") == "location"


def test_code_falls_back_to_long_when_it_is_not_configured(backend, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODEL_CODE", "")
    backend["answer"] = _anchor_answer(ANCHOR_FIELD, "return row.id + 1;")
    server.local_extract(fields=[ANCHOR_FIELD], path=_write(tmp_path, _typescript(3, 0), "a.ts"))
    assert {c["role"] for c in backend["calls"]} == {"long"}


def test_an_answer_by_program_has_no_role(backend, tmp_path):
    data = server.local_extract(
        fields=["funciones_con_lineas"], path=_write(tmp_path, _python(), "m.py")
    )
    assert backend["calls"] == []
    assert "role_reason" not in data.get("_local_delegate", {})


# --- REQ-017 ----------------------------------------------------------------------------------


def test_the_real_max_tokens(backend, tmp_path, monkeypatch):
    """#698: 60 functions to choose from ask 64 + 40*60 tokens, in one call and in each piece."""
    text = _python(60)
    field = "funciones_que_validan_con_lineas"
    backend["answer"] = _selection_answer(field)
    path = _write(tmp_path, text, "m.py")
    server.local_extract(fields=[field], path=path)
    assert [c["max_tokens"] for c in backend["calls"]] == [64 + 40 * 60]
    assert len(_enum(backend["calls"][0], field)) == 60, "guard: 60 names to choose from"
    backend["calls"].clear()
    monkeypatch.setattr(config, "max_chars_for_role", lambda role: 1_500)
    server.local_extract(fields=[field], path=path)
    assert len(backend["calls"]) > 2, "guard: it went through the map"
    assert {c["max_tokens"] for c in backend["calls"]} == {2464}


# --- REQ-018 / REQ-019 / REQ-022 --------------------------------------------------------------


def test_meta_keys(backend, tmp_path):
    text = "\n".join(f"Línea de relleno número {k}." for k in range(20)) + "\nla barra lateral\n"
    backend["answer"] = lambda call: json.dumps(
        {
            ANCHOR_FIELD: [
                {"name": "a", "anchor": "la barra lateral"},
                {"name": "b", "anchor": "Línea de relleno"},
            ],
            "tres_reglas": True,
        }
    )
    data = server.local_extract(
        fields=[ANCHOR_FIELD, "tres_reglas"], path=_write(tmp_path, text, "n.txt")
    )
    meta = data["_local_delegate"]
    assert meta["located"][ANCHOR_FIELD] == {
        "by": "anchor",
        "index": meta["located"][ANCHOR_FIELD]["index"],
        "items": 2,
        "unlocated": 1,
    }
    [miss] = meta["unlocated"][ANCHOR_FIELD]
    assert miss["name"] == "b" and miss["reason"] == "ambiguous" and len(miss["candidates"]) == 5
    assert meta["type_mismatch_keys"] == {"tres_reglas": {"expected": "array", "got": "boolean"}}
    for retired in ("lines_unverified", "outline_copies", "diff_files"):
        assert retired not in meta
    assert meta["warning"].endswith(
        i18n.t("mcp.warning.extract_unlocated", items=f"{ANCHOR_FIELD}: b (ambiguous)")
    )


def test_inline_text_keeps_todays_location_value(backend):
    backend["answer"] = lambda call: json.dumps({"secciones_con_lineas": "Intro: líneas 1-3"})
    data = server.local_extract(fields=["secciones_con_lineas"], text=_markdown())
    assert data["secciones_con_lineas"] == "Intro: líneas 1-3"
    assert "located" not in data.get("_local_delegate", {})
    assert "|" not in backend["calls"][0]["user"].split("\n\n", 1)[1][:3]


def test_an_index_that_cannot_be_built_is_said(backend, tmp_path):
    text = "def roto(:\n    pass\n\nla barra lateral = 1\n"
    backend["answer"] = _anchor_answer(ANCHOR_FIELD, "la barra lateral")
    data = server.local_extract(fields=[ANCHOR_FIELD], path=_write(tmp_path, text, "roto.py"))
    assert data[ANCHOR_FIELD] == [{"name": "x", "start": 4, "end": 4}]
    meta = data["_local_delegate"]
    assert meta["located"][ANCHOR_FIELD]["index"] is None
    assert "syntax_error" in meta["warning"]
