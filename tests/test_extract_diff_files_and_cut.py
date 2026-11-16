"""#665 and #666: `local_extract` with `path` and a field that asks for lines.

#665: over a large multi-file `.patch`, a field that asks for the files and their lines
(`ficheros_con_lineas`) came back with the first file only. The join of the chunks was right
(lists add up, #568); what each chunk got was the model's list, and a model that names the first
`diff --git` of each chunk leaves the rest out without a word. Now such a field is answered by
program from the patch (`line_check.diff_file_ranges`, #582), with `_local_delegate.diff_files`.

#666: a location answer longer than the single call's `max_tokens` came back as a JSON cut in two,
an error whose only words were "not parseable", and the lines it invented unchecked. Now the cut
single call is redone in halves (the map/reduce splits again what is still cut), the location
values are joined by program, and an answer that stays cut says `max_tokens` in its error and
lists the cited lines that do not hold in `lines_unverified`.

Backend faked (`_run_chat` doubled), no network; the usage log goes to `tmp_path`.
"""

from __future__ import annotations

import json
import re

import pytest

from local_delegate import config, i18n, line_check, server

FILES_FIELD = "ficheros_con_lineas"
EXEC_FIELD = "lineas_con_red_o_exec_con_lineas"
DIFF_HEADER = re.compile(r"^(\d+)\| diff --git a/(\S+) ", re.MULTILINE)
EXEC_LINE = re.compile(r"^(\d+)\| .*subprocess", re.MULTILINE)


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


def _diff(files: int, lines_per_file: int) -> tuple[str, list[str]]:
    """A unified diff of `files` files with distinct names and the expected `path: first-last`.

    The expected ranges are counted here, line by line, not taken from `diff_file_ranges`.
    """
    out: list[str] = []
    expected: list[str] = []
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
        expected.append(f"{name}: {first}-{len(out)}")
    return "\n".join(out) + "\n", expected


def _first_file_only(call):
    """The model of the issue: it names the first `diff --git` of what it reads, and stops."""
    found = DIFF_HEADER.findall(call["user"])[:1]
    return _ok(json.dumps({FILES_FIELD: [f"{name}: líneas {line}-21" for line, name in found]}))


# --- #665 -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", [FILES_FIELD, "files_with_lines", "archivos_y_lineas", "rutas_con_lineas"]
)
def test_fields_that_ask_for_the_files_of_a_diff(name):
    assert line_check.asks_for_diff_files(name)


@pytest.mark.parametrize(
    "name",
    [
        EXEC_FIELD,
        "hunks_with_lines",
        "sections_with_lines",
        "file_name",
        "files",
        "fichero_con_lineas",
    ],
)
def test_fields_that_do_not(name):
    assert not line_check.asks_for_diff_files(name)


def test_every_file_of_a_chunked_diff_comes_back(backend, tmp_path):
    calls, state = backend
    state["answer"] = _first_file_only
    text, expected = _diff(30, 60)
    assert len(text) > config.max_chars_for_role("long"), "guard: it must chunk"
    data = server.local_extract(fields=[FILES_FIELD], path=_write(tmp_path, text, "big.patch"))
    assert len(calls) > 1, "guard: it chunked"
    assert data[FILES_FIELD] == expected
    meta = data["_local_delegate"]
    assert meta["diff_files"]["fields"] == [FILES_FIELD]
    assert meta["diff_files"]["files"] == 30
    assert "30" in meta["diff_files"]["notice"]
    assert "warning" not in meta, "a value by program is not a failure"


def test_a_single_call_diff_is_answered_by_program_too(backend, tmp_path):
    calls, state = backend
    state["answer"] = _first_file_only
    text, expected = _diff(3, 4)
    data = server.local_extract(fields=[FILES_FIELD], path=_write(tmp_path, text, "small.patch"))
    assert len(calls) == 1
    assert data[FILES_FIELD] == expected
    # #582: the model is told the `@@` numbers are not lines of the patch.
    assert server._DIFF_LINES_CLAUSE in calls[0]["system"]


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
    data = server.local_extract(fields=[FILES_FIELD], path=_write(tmp_path, text, "small.patch"))
    assert data[FILES_FIELD] == expected
    assert data["_local_delegate"]["model_error"]["error"] == i18n.t("mcp.extract.not_object")


def test_a_cut_call_with_only_diff_files_is_not_retried(backend, tmp_path):
    calls, state = backend
    state["answer"] = lambda call: _ok(f'{{"{FILES_FIELD}": ["package.json: 1-', "length")
    text, expected = _diff(6, 30)
    assert len(text) > 2 * config.CHUNK_MIN_CHARS and len(text) < config.max_chars_for_role("long")
    data = server.local_extract(fields=[FILES_FIELD], path=_write(tmp_path, text, "mid.patch"))
    assert len(calls) == 1, "the program answers the field: no more calls"
    assert data[FILES_FIELD] == expected


def test_another_location_field_over_a_diff_keeps_the_models_value(backend, tmp_path):
    _calls, state = backend
    value = ["package.json: línea 6"]
    state["answer"] = lambda call: _ok(json.dumps({"hunks_with_lines": value}))
    text, _expected = _diff(3, 4)
    data = server.local_extract(
        fields=["hunks_with_lines"], path=_write(tmp_path, text, "small.patch")
    )
    assert data["hunks_with_lines"] == value
    assert "diff_files" not in data.get("_local_delegate", {})


def test_a_file_that_is_not_a_diff_is_left_to_the_model(backend, tmp_path):
    calls, state = backend
    value = ["README.md: líneas 1-3"]
    state["answer"] = lambda call: _ok(json.dumps({FILES_FIELD: value}))
    data = server.local_extract(
        fields=[FILES_FIELD], path=_write(tmp_path, "# Título\n\nTexto\n", "notes.md")
    )
    assert data[FILES_FIELD] == value
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
    """A model whose answer is cut by `max_tokens` past `cap` items, after an invented line."""

    def answer(call):
        found = EXEC_LINE.findall(call["user"])
        if len(found) > cap:
            found = found or ["1"]
            cut = f'{{"{EXEC_FIELD}": ["subprocess: línea 99999", "subprocess: línea {found[0]}", "'
            return _ok(cut, "length")
        return _ok(json.dumps({EXEC_FIELD: [f"subprocess: línea {n}" for n in found]}))

    return answer


def test_a_cut_single_call_is_retried_in_halves(backend, tmp_path):
    calls, state = backend
    state["answer"] = _answer_up_to(40)
    text = _skills()
    data = server.local_extract(fields=[EXEC_FIELD], path=_write(tmp_path, text, "skills.md"))
    assert len(calls) > 1, "the cut call was redone"
    assert "error" not in data.get("_local_delegate", {})
    cited = [int(re.search(r"\d+$", v).group()) for v in data[EXEC_FIELD]]
    assert cited == _exec_lines(text), "every line, each once, none invented"
    assert "lines_unverified" not in data.get("_local_delegate", {})


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


def test_an_answer_that_stays_cut_says_max_tokens_and_checks_its_lines(backend, tmp_path):
    calls, state = backend
    state["answer"] = _answer_up_to(-1)  # every call is cut, the reduce too
    text = _skills()
    data = server.local_extract(fields=[EXEC_FIELD], path=_write(tmp_path, text, "skills.md"))
    meta = data["_local_delegate"]
    assert len(calls) > 1, "guard: it was redone"
    assert meta["truncated"] is True
    unverified = meta["lines_unverified"]
    assert unverified.count("raw: 99999") == 1, "the invented line, once"
    assert not {f"raw: {n}" for n in _exec_lines(text)} & set(unverified), "real lines hold"
    assert meta["error"] == i18n.t("mcp.extract.not_json_cut")


def test_a_cut_chunk_beside_good_ones_has_its_lines_checked(backend, tmp_path):
    """The redone call recovers the good chunks; the one still cut is left out, but checked."""
    _calls, state = backend
    good = _answer_up_to(40)

    def answer(call):
        found = EXEC_LINE.findall(call["user"])
        if found and found[0] == str(_exec_lines(_skills())[0]) and len(found) <= 40:
            return _ok(f'{{"{EXEC_FIELD}": ["subprocess: línea 88888", "', "length")
        return good(call)

    state["answer"] = answer
    data = server.local_extract(fields=[EXEC_FIELD], path=_write(tmp_path, _skills(), "skills.md"))
    meta = data["_local_delegate"]
    assert "error" not in meta and data[EXEC_FIELD], "the other chunks are kept"
    assert meta["truncated"] is True
    assert "raw: 88888" in meta["lines_unverified"]


def test_a_cut_call_too_small_to_split_says_max_tokens(backend, tmp_path):
    calls, state = backend
    state["answer"] = _answer_up_to(-1)
    text = "# Skill\n\nEjecuta `subprocess.run` con red.\n"
    data = server.local_extract(fields=[EXEC_FIELD], path=_write(tmp_path, text, "tiny.md"))
    meta = data["_local_delegate"]
    assert len(calls) == 1, "nothing to split"
    assert meta["error"] == i18n.t("mcp.extract.not_json_cut")
    assert "max_tokens" in meta["error"]
    assert meta["truncated"] is True
    assert meta["lines_unverified"] == ["raw: 99999"]


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
