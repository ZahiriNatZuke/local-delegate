"""#665 and #666: `local_extract` with `path` and a field that asks for lines.

#665: over a large multi-file `.patch`, a field that asks for the files and their lines
(`ficheros_con_lineas`) came back with the first file only: a model that names the first
`diff --git` of each chunk leaves the rest out without a word. Such a field is answered by
program from the patch, with no backend call when it is the only one (#687).

#666: a location answer longer than the single call's `max_tokens` came back as a JSON cut in two,
an error whose only words were "not parseable". The cut single call is redone in halves (the
map/reduce splits again what is still cut), the location items are joined by program, and an
answer that stays cut says `max_tokens` in its error.

Since 0.54.0 (#692-#698) the value is a list of `{name, start, end}` with the program's lines,
the meta key is `located` (no more `diff_files` nor `lines_unverified`), and the model answers a
location field with anchors, never with numbers. Backend faked (`_run_chat` doubled), no network;
the usage log goes to `tmp_path`.
"""

from __future__ import annotations

import json
import re

import pytest

from local_delegate import config, i18n, line_check, locate, server

FILES_FIELD = "ficheros_con_lineas"
EXEC_FIELD = "lineas_con_red_o_exec_con_lineas"
INSTRUCTION = "Extrae los campos del siguiente contenido:\n\n"
#: The anchor of an exec line of `_skills`: unique in the file.
EXEC_ANCHOR = re.compile(r"en el paso \d+-\d+ con red")


def _ok(text: str, finish_reason: str = "stop"):
    return server.ChatResult(text=text, ok=True, finish_reason=finish_reason)


@pytest.fixture
def backend(monkeypatch, tmp_path):
    calls: list[dict] = []
    state = {"answer": lambda call: _ok("{}")}

    def run_chat(model, system, user, max_tokens, temperature, **_):
        call = {"system": system, "user": user, "max_tokens": max_tokens}
        calls.append(call)
        return state["answer"](call), 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    i18n.reset()
    return calls, state


def _write(tmp_path, text: str, name: str) -> str:
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return str(path)


def _diff(files: int, lines_per_file: int) -> tuple[str, list[dict]]:
    """A unified diff of `files` files with distinct names and the expected items.

    The expected ranges are counted here, line by line, not taken from the index.
    """
    out: list[str] = []
    expected: list[dict] = []
    for f in range(files):
        name = "package.json" if f == 0 else f"src/mod{f:02d}/pieza_{chr(97 + f % 26)}{f}.ts"
        first = len(out) + 1
        out += [
            f"diff --git a/{name} b/{name}",
            "index 1111111..2222222 100644",
            f"--- a/{name}",
            f"+++ b/{name}",
            f"@@ -240,{lines_per_file} +242,{lines_per_file} @@",
        ]
        out += [
            f"+const valor_{f}_{i} = calculaAlgoLargo({i}, 'texto de relleno');"
            for i in range(lines_per_file)
        ]
        expected.append({"name": name, "start": first, "end": len(out)})
    return "\n".join(out) + "\n", expected


def _summary_only(call):
    """The model answers the field it is asked; the files never reach it."""
    return _ok(json.dumps({"summary": "un cambio"}))


# --- #665 -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        FILES_FIELD,
        "files_with_lines",
        "archivos_y_lineas",
        "rutas_con_lineas",
        "lista_de_ficheros_con_sus_lineas",
        "fichero_con_lineas",  # singular: one file, chosen by the model
    ],
)
def test_fields_that_ask_for_the_files_of_a_diff(name):
    assert line_check.is_location_field(name)
    assert "files" in locate.classify_field(name).categories


@pytest.mark.parametrize("name", [EXEC_FIELD, "hunks_with_lines", "sections_with_lines"])
def test_location_fields_that_do_not(name):
    assert "files" not in locate.classify_field(name).categories


@pytest.mark.parametrize("name", ["file_name", "files"])
def test_fields_that_are_no_location(name):
    assert not line_check.is_location_field(name)


def test_every_file_of_a_chunked_diff_comes_back(backend, tmp_path):
    calls, _state = backend
    text, expected = _diff(30, 60)
    assert len(text) > config.max_chars_for_role("long"), "guard: it would chunk"
    data = server.local_extract(fields=[FILES_FIELD], path=_write(tmp_path, text, "big.patch"))
    assert calls == [], "#687: the program answers every field, no backend call"
    assert data[FILES_FIELD] == expected
    meta = data["_local_delegate"]
    assert meta["located"][FILES_FIELD] == {
        "by": "program",
        "index": "diff",
        "items": 30,
        "unlocated": 0,
    }
    assert "warning" not in meta, "a value by program is not a failure"


def test_a_single_call_diff_is_answered_by_program_too(backend, tmp_path):
    calls, state = backend
    state["answer"] = _summary_only
    text, expected = _diff(3, 4)
    data = server.local_extract(
        fields=["summary", FILES_FIELD], path=_write(tmp_path, text, "small.patch")
    )
    assert len(calls) == 1
    assert data == {"summary": "un cambio", FILES_FIELD: expected, "_local_delegate": data[
        "_local_delegate"
    ]}  # fmt: skip
    assert f'"{FILES_FIELD}"' not in calls[0]["system"], "the model is not asked for it"
    assert server._DIFF_LINES_CLAUSE not in calls[0]["system"]


def test_the_diff_files_survive_an_answer_that_is_not_json(backend, tmp_path):
    _calls, state = backend
    state["answer"] = lambda call: _ok("no es JSON")
    text, expected = _diff(3, 4)
    data = server.local_extract(
        fields=["summary", FILES_FIELD], path=_write(tmp_path, text, "small.patch")
    )
    assert data[FILES_FIELD] == expected
    assert data["summary"] is None
    assert data["_local_delegate"]["missing_keys"] == ["summary"]


def test_a_backend_error_beside_the_diff_files_is_not_silent(backend, tmp_path):
    """Review: with a field answered by program, an unusable reply must still be heard."""
    _calls, state = backend
    state["answer"] = lambda call: _ok('{"summary": "algo cort', "length")
    text, expected = _diff(3, 4)
    data = server.local_extract(
        fields=["summary", FILES_FIELD], path=_write(tmp_path, text, "small.patch")
    )
    meta = data["_local_delegate"]
    assert data[FILES_FIELD] == expected
    assert "error" not in meta, "the program's values are data, not a failed call"
    assert meta["model_error"]["error"] == i18n.t("mcp.extract.not_json_cut")
    assert meta["model_error"]["raw"].startswith('{"summary"')
    assert i18n.t("mcp.extract.not_json_cut") in meta["warning"]


def test_json_that_is_not_an_object_keeps_the_diff_files(backend, tmp_path):
    _calls, state = backend
    state["answer"] = lambda call: _ok('["package.json"]')
    text, expected = _diff(3, 4)
    data = server.local_extract(
        fields=["summary", FILES_FIELD], path=_write(tmp_path, text, "small.patch")
    )
    assert data[FILES_FIELD] == expected
    assert data["_local_delegate"]["model_error"]["error"] == i18n.t("mcp.extract.not_object")


def test_a_cut_call_with_only_diff_files_is_not_retried(backend, tmp_path):
    calls, state = backend
    state["answer"] = lambda call: _ok('{"summary": "algo cort', "length")
    text, expected = _diff(6, 30)
    assert len(text) > 2 * config.CHUNK_MIN_CHARS and len(text) < config.max_chars_for_role("long")
    data = server.local_extract(
        fields=["summary", FILES_FIELD], path=_write(tmp_path, text, "mid.patch")
    )
    assert len(calls) == 1, "the program answers the field: no more calls"
    assert data[FILES_FIELD] == expected


def test_another_location_field_over_a_diff_gets_the_programs_lines(backend, tmp_path):
    _calls, state = backend
    text, _expected = _diff(3, 4)
    anchor = "+const valor_1_2 = calculaAlgoLargo(2"
    state["answer"] = lambda call: _ok(
        json.dumps({EXEC_FIELD: [{"name": "valor_1_2", "anchor": anchor, "start": 1}]})
    )
    data = server.local_extract(fields=[EXEC_FIELD], path=_write(tmp_path, text, "small.patch"))
    line = text.split("\n").index(
        "+const valor_1_2 = calculaAlgoLargo(2, 'texto de relleno');"
    ) + 1  # fmt: skip
    assert data[EXEC_FIELD] == [{"name": "valor_1_2", "start": line, "end": line}]
    assert data["_local_delegate"]["located"][EXEC_FIELD]["by"] == "anchor"


def test_a_file_that_is_not_a_diff_is_left_to_the_model(backend, tmp_path):
    calls, state = backend
    state["answer"] = lambda call: _ok(
        json.dumps({FILES_FIELD: [{"name": "README.md", "anchor": "Texto del documento"}]})
    )
    data = server.local_extract(
        fields=[FILES_FIELD],
        path=_write(tmp_path, "# Título\n\nTexto del documento\n", "notes.md"),
    )
    assert len(calls) == 1
    assert data[FILES_FIELD] == [{"name": "README.md", "start": 3, "end": 3}]
    assert server._DIFF_LINES_CLAUSE not in calls[0]["system"]


def test_an_inline_diff_is_left_to_the_model(backend):
    _calls, state = backend
    value = ["package.json: líneas 1-9"]
    state["answer"] = lambda call: _ok(json.dumps({FILES_FIELD: value}))
    text, _expected = _diff(3, 4)
    data = server.local_extract(fields=[FILES_FIELD], text=text)
    assert data[FILES_FIELD] == value


# --- #666 -----------------------------------------------------------------------------------


def _skills(skills: int = 12) -> str:
    """Concatenated SKILL.md files (~29 K chars: one call of `long`), one exec line in four."""
    out = []
    for s in range(skills):
        out.append(f"# Skill {s}\n\n## Uso\n\n")
        for i in range(40):
            if i % 4 == 0:
                out.append(f"Ejecuta `subprocess.run` en el paso {s}-{i} con red hacia el host.\n")
            else:
                out.append(f"Texto descriptivo {s}-{i} sin nada especial que reportar aquí.\n")
        out.append("\n")
    text = "".join(out)
    assert config.max_chars_for_role("mechanical") < len(text) <= config.max_chars_for_role("long")
    return text


def _exec_lines(text: str) -> list[int]:
    return [n for n, line in enumerate(text.split("\n"), 1) if "subprocess" in line]


def _answer_up_to(cap: int):
    """A model whose answer is cut by `max_tokens` past `cap` items: it anchors each exec line
    of the piece it reads (never a number)."""

    def answer(call):
        found = EXEC_ANCHOR.findall(call["user"].split(INSTRUCTION, 1)[-1])
        items = [{"name": "subprocess", "anchor": anchor} for anchor in found]
        if len(found) > cap:
            cut = json.dumps({EXEC_FIELD: items[:2]})[:-3]
            return _ok(cut, "length")
        return _ok(json.dumps({EXEC_FIELD: items}))

    return answer


def test_a_cut_single_call_is_retried_in_halves(backend, tmp_path):
    calls, state = backend
    state["answer"] = _answer_up_to(40)
    text = _skills()
    data = server.local_extract(fields=[EXEC_FIELD], path=_write(tmp_path, text, "skills.md"))
    assert len(calls) > 1, "the cut call was redone"
    assert "error" not in data.get("_local_delegate", {})
    cited = [item["start"] for item in data[EXEC_FIELD]]
    assert cited == _exec_lines(text), "every line, each once, none invented"
    assert "unlocated" not in data["_local_delegate"]


def _rows(tmp_path) -> list[dict]:
    rows = []
    for file in sorted(tmp_path.glob("usage*.jsonl")):
        rows += [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()]
    return [row for row in rows if row.get("tool") == "local_extract"]


def test_a_retried_call_is_one_usage_row_that_reads_the_file_once(backend, tmp_path):
    """Review: the cut call and its redo read the same file; the panel counts it once."""
    calls, state = backend
    state["answer"] = _answer_up_to(40)
    text = _skills()
    server.local_extract(fields=[EXEC_FIELD], path=_write(tmp_path, text, "skills.md"))
    [row] = _rows(tmp_path)
    assert row["ok"] is True
    assert row["chunks"] == len(calls), "every backend call is counted, the cut one too"
    assert row["steps"][0] == {
        "kind": "map", "chars_out": row["steps"][0]["chars_out"], "finish_reason": "length",
        "retried": True,
    }  # fmt: skip
    assert server._accounting(row)["chars_saved_text"] == len(text), "the file, once"


def test_an_answer_that_stays_cut_says_max_tokens(backend, tmp_path):
    calls, state = backend
    state["answer"] = _answer_up_to(-1)  # every call is cut, the reduce too
    text = _skills()
    data = server.local_extract(fields=[EXEC_FIELD], path=_write(tmp_path, text, "skills.md"))
    meta = data["_local_delegate"]
    assert len(calls) > 1, "guard: it was redone"
    assert meta["truncated"] is True
    assert "lines_unverified" not in meta
    assert meta["error"] == i18n.t("mcp.extract.not_json_cut")


def test_a_cut_chunk_beside_good_ones_leaves_the_others(backend, tmp_path):
    """The redone call recovers the good chunks; the one still cut is left out."""
    _calls, state = backend
    good = _answer_up_to(40)
    first_anchor = EXEC_ANCHOR.findall(_skills())[0]

    def answer(call):
        found = EXEC_ANCHOR.findall(call["user"].split(INSTRUCTION, 1)[-1])
        if found and found[0] == first_anchor and len(found) <= 40:
            return _ok(f'{{"{EXEC_FIELD}": [{{"name": "x", "anchor": "', "length")
        return good(call)

    state["answer"] = answer
    data = server.local_extract(fields=[EXEC_FIELD], path=_write(tmp_path, _skills(), "skills.md"))
    meta = data["_local_delegate"]
    assert "error" not in meta and data[EXEC_FIELD], "the other chunks are kept"
    assert meta["truncated"] is True


def test_a_cut_call_too_small_to_split_says_max_tokens(backend, tmp_path):
    calls, state = backend
    state["answer"] = _answer_up_to(-1)
    text = "# Skill\n\nEjecuta `subprocess.run` en el paso 0-0 con red.\n"
    data = server.local_extract(fields=[EXEC_FIELD], path=_write(tmp_path, text, "tiny.md"))
    meta = data["_local_delegate"]
    assert len(calls) == 1, "nothing to split"
    assert meta["error"] == i18n.t("mcp.extract.not_json_cut")
    assert "max_tokens" in meta["error"]
    assert meta["truncated"] is True
    assert "lines_unverified" not in meta


def test_a_cut_answer_without_location_fields_is_not_retried(backend, tmp_path):
    calls, state = backend
    state["answer"] = lambda call: _ok('{"summary": "algo cort', "length")
    data = server.local_extract(fields=["summary"], path=_write(tmp_path, _skills(), "skills.md"))
    assert len(calls) == 1
    assert data["_local_delegate"]["error"] == i18n.t("mcp.extract.not_json_cut")
    assert "lines_unverified" not in data["_local_delegate"]


def test_an_answer_that_is_not_json_without_a_cut_keeps_its_error(backend, tmp_path):
    _calls, state = backend
    state["answer"] = lambda call: _ok("no es JSON")
    data = server.local_extract(fields=[EXEC_FIELD], path=_write(tmp_path, _skills(), "skills.md"))
    assert data["_local_delegate"]["error"] == i18n.t("mcp.extract.not_json")
