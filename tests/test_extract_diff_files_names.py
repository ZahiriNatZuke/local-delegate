"""#665 (reopened): the files of a diff by program, for more field names and more patch forms.

The #676 path answered `ficheros_con_lineas` from the patch. Two reports of the same day came back
with `null` in every chunk: `ficheros_y_hunks_con_lineas` over a 92 KB `.patch` of 14 files (new
files with long `@@ -0,0 +1,N @@` hunks, 3 chunks) and `ficheros_con_lineas` over a diff of about
6000 lines (7 chunks). The calls ran 0.52.0, without #676; on `main` the second name was answered,
but a field that asks for the files AND their hunks, `changed_files_with_lines` (the count word
`changed` read as a count of lines) and a `.patch` that does not open with a patch header (a
preamble before the first `diff --git`) still went to the model, chunk by chunk.

Inputs here have the SHAPE of the reports, never their content. Backend faked (`_run_chat`
doubled, a model that answers null), no network; the usage log goes to `tmp_path`.
"""

from __future__ import annotations

import pytest

from local_delegate import config, i18n, line_check, server

HUNKS_FIELD = "ficheros_y_hunks_con_lineas"
FILES_FIELD = "ficheros_con_lineas"


def _ok(text: str):
    return server.ChatResult(text=text, ok=True, finish_reason="stop")


@pytest.fixture
def backend(monkeypatch, tmp_path):
    calls: list[dict] = []

    def run_chat(model, system, user, max_tokens, temperature, **_):
        calls.append({"system": system, "user": user})
        # The model of the reports: every chunk gives no value for any field.
        return _ok("{}"), 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    i18n.reset()
    return calls


def _write(tmp_path, text: str, name: str) -> str:
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return str(path)


FORMAT_PATCH_HEAD = [
    "From 0123456789abcdef0123456789abcdef01234567 Mon Sep 17 00:00:00 2001",
    "From: Autor de Prueba <autor@example.invalid>",
    "Date: Mon, 16 Nov 2026 10:00:00 -0300",
    "Subject: [PATCH] feat: cambio de prueba",
    "",
    "Cuerpo del mensaje.",
    "---",
    " src/a.ts | 3 ++-",
    " 1 file changed, 2 insertions(+), 1 deletion(-)",
    "",
]


def _shaped_diff(
    files: int, new_files: int, new_len: int, mod_hunks: int, hunk_len: int, head: list[str]
) -> tuple[str, list[str], list[str]]:
    """A diff of `files` files: the first `new_files` new (one `@@ -0,0 +1,N @@` hunk of `new_len`
    lines), the rest modified with `mod_hunks` hunks of `hunk_len` lines each.

    Returns the text, the expected `path: first-last` per file and the expected value of a
    files-and-hunks field, counted here line by line, not taken from `diff_file_ranges`.
    """
    out: list[str] = list(head)
    files_expected: list[str] = []
    hunks_expected: list[str] = []
    for f in range(files):
        name = f"src/modulo{f:02d}/componente_{f}.spec.ts"
        first = len(out) + 1
        hunks: list[str] = []
        if f < new_files:
            out += [
                f"diff --git a/{name} b/{name}",
                "new file mode 100644",
                "index 0000000..1234567",
                "--- /dev/null",
                f"+++ b/{name}",
            ]
            start = len(out) + 1
            out.append(f"@@ -0,0 +1,{new_len} @@")
            out += [
                f"+  it('caso {i} del fichero {f}', () => expect(valor).toBe({i}));"
                for i in range(new_len)
            ]
            hunks.append(f"{start}-{len(out)}")
        else:
            out += [
                f"diff --git a/{name} b/{name}",
                "index 1111111..2222222 100644",
                f"--- a/{name}",
                f"+++ b/{name}",
            ]
            for h in range(mod_hunks):
                start = len(out) + 1
                base = 10 + h * 100
                out.append(f"@@ -{base},{hunk_len} +{base},{hunk_len + 1} @@ export class Algo {{")
                out += [f"   const contexto_{h}_{i} = {i};" for i in range(hunk_len - 1)]
                out += ["-  viejo();", "+  nuevo();", "+  otro();"]
                hunks.append(f"{start}-{len(out)}")
        files_expected.append(f"{name}: {first}-{len(out)}")
        hunks_expected.append(f"{name}: {first}-{len(out)} (hunks: {', '.join(hunks)})")
    return "\n".join(out) + "\n", files_expected, hunks_expected


# --- names -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        HUNKS_FIELD,
        "files_and_hunks_with_lines",
        "archivos_y_hunks_con_lineas",
        "files_with_hunks_and_lines",
    ],
)
def test_fields_that_ask_for_the_files_and_their_hunks(name):
    assert line_check.asks_for_diff_hunks(name)
    assert not line_check.asks_for_diff_files(name), "files only is the other answer"


@pytest.mark.parametrize(
    "name",
    ["hunks_with_lines", "hunks_con_lineas", "fichero_y_hunks_con_lineas", "files_and_hunks"],
)
def test_fields_that_do_not_ask_for_files_and_hunks(name):
    assert not line_check.asks_for_diff_hunks(name)


@pytest.mark.parametrize(
    "name",
    ["changed_files_with_lines", "modified_files_with_lines", "ficheros_modificados_con_lineas"],
)
def test_changed_files_is_not_a_count_of_lines(name):
    assert line_check.is_location_field(name)
    assert line_check.asks_for_diff_files(name)


@pytest.mark.parametrize(
    "name", ["lines_changed", "changed_lines", "changed_files_count", "lineas_modificadas"]
)
def test_counts_stay_counts(name):
    assert not line_check.is_location_field(name)


# --- the reports ------------------------------------------------------------------------------


def test_files_and_hunks_of_a_92_kb_patch_come_back_by_program(backend, tmp_path):
    """First report: ~92 KB, 14 files, several new with long `@@ -0,0 +1,N @@` hunks."""
    text, _files, hunks = _shaped_diff(14, 6, 330, 3, 40, [])
    assert len(text) > 90_000 and len(text) > config.max_chars_for_role("long"), "guard: chunks"
    data = server.local_extract(fields=[HUNKS_FIELD], path=_write(tmp_path, text, "pr.patch"))
    assert backend == [], "#687: the program answers every field, no backend call"
    assert data[HUNKS_FIELD] == hunks
    meta = data["_local_delegate"]
    assert meta["diff_files"]["fields"] == [HUNKS_FIELD]
    assert meta["diff_files"]["files"] == 14
    assert "chunked" not in meta and "warning" not in meta


def test_files_of_a_6000_line_format_patch_come_back_by_program(backend, tmp_path):
    """Second report: ~6000 lines, 7 chunks; here with the mail header of `git format-patch`."""
    text, files, _hunks = _shaped_diff(20, 8, 500, 4, 45, FORMAT_PATCH_HEAD)
    assert text.count("\n") > 5500
    data = server.local_extract(fields=[FILES_FIELD], path=_write(tmp_path, text, "series.patch"))
    assert backend == [], "#687: the program answers every field, no backend call"
    assert data[FILES_FIELD] == files


def test_changed_files_with_lines_over_a_chunked_diff(backend, tmp_path):
    text, files, _hunks = _shaped_diff(14, 6, 330, 3, 40, [])
    data = server.local_extract(
        fields=["changed_files_with_lines"], path=_write(tmp_path, text, "pr.diff")
    )
    assert data["changed_files_with_lines"] == files


def test_a_patch_with_a_preamble_is_still_read_as_a_diff(backend, tmp_path):
    """A `.patch` whose first lines are not a patch header (a note, a stat) is still a diff."""
    head = ["Cambios del PR, generado a mano", "", " 14 files changed", ""]
    text, files, hunks = _shaped_diff(14, 6, 330, 3, 40, head)
    data = server.local_extract(
        fields=[FILES_FIELD, HUNKS_FIELD], path=_write(tmp_path, text, "pr.patch")
    )
    assert data[FILES_FIELD] == files
    assert data[HUNKS_FIELD] == hunks


def test_a_preamble_in_a_file_that_is_not_a_patch_is_not_read_as_one(backend, tmp_path):
    """Without the `.patch`/`.diff` suffix the start of the file still decides (#499)."""
    head = ["# Notas", "", "Texto que enseña un diff:", ""]
    text, _files, _hunks = _shaped_diff(2, 1, 5, 1, 5, head)
    data = server.local_extract(fields=[FILES_FIELD], path=_write(tmp_path, text, "notes.md"))
    assert "diff_files" not in data.get("_local_delegate", {})


def test_a_patch_without_file_headers_says_so(backend, tmp_path):
    """A `.patch` the program cannot read: a warning, never a silent null."""
    text = "Esto no es un parche.\nNi tiene cabeceras de fichero.\n"
    data = server.local_extract(fields=[HUNKS_FIELD], path=_write(tmp_path, text, "broken.patch"))
    meta = data["_local_delegate"]
    assert data[HUNKS_FIELD] is None
    assert i18n.t("mcp.warning.extract_diff_unparsed", fields=HUNKS_FIELD) in meta["warning"]


def test_a_null_location_field_over_a_chunked_diff_names_the_program_fields(backend, tmp_path):
    """A field the program does not answer, null in every chunk: the warning says what would."""
    text, _files, _hunks = _shaped_diff(14, 6, 330, 3, 40, [])
    data = server.local_extract(
        fields=["hunks_with_lines"], path=_write(tmp_path, text, "pr.patch")
    )
    meta = data["_local_delegate"]
    assert data["hunks_with_lines"] is None
    hint = i18n.t("mcp.warning.extract_diff_null_hint", fields="hunks_with_lines")
    assert hint in meta["warning"]
    assert meta["chunked"]["null_fields"] == ["hunks_with_lines"]


def test_a_file_without_hunks_gets_its_range_alone(backend, tmp_path):
    """A binary file has no `@@`: its range, without an empty hunk list."""
    text, _files, hunks = _shaped_diff(2, 1, 5, 1, 5, [])
    first = text.count("\n") + 1
    text += (
        "diff --git a/assets/logo.png b/assets/logo.png\n"
        "new file mode 100644\n"
        "index 0000000..abcdef1\n"
        "Binary files /dev/null and b/assets/logo.png differ\n"
    )
    data = server.local_extract(fields=[HUNKS_FIELD], path=_write(tmp_path, text, "bin.patch"))
    assert data[HUNKS_FIELD] == [*hunks, f"assets/logo.png: {first}-{first + 3}"]


# --- #687: only program fields, no backend call ------------------------------------------------


def _big_pr_diff() -> tuple[str, list[str], list[str]]:
    """The shape of the #687 report: a ~150 KB patch of 26 files that the long role chunks."""
    text, files, hunks = _shaped_diff(26, 10, 330, 3, 40, [])
    assert len(text) > 140_000 and len(text) > config.max_chars_for_role("long"), "guard: chunks"
    return text, files, hunks


def test_only_diff_fields_never_reach_the_backend(backend, tmp_path):
    """Every field answered by program: the model's reply would be thrown away, so no call."""
    text, _files, _hunks = _big_pr_diff()
    server.local_extract(
        fields=[HUNKS_FIELD, "changed_files_with_lines"], path=_write(tmp_path, text, "pr.patch")
    )
    assert backend == [], "no backend call when the program answers every field"
    usage = tmp_path / "usage.jsonl"
    assert not usage.exists() or usage.read_text(encoding="utf-8") == "", "no backend, no row"


def test_only_diff_fields_give_the_same_answer_as_with_the_model(backend, tmp_path):
    """The answer is the one the model path gave when the model added nothing (`{}`)."""
    text, files, hunks = _big_pr_diff()
    fields = [HUNKS_FIELD, "changed_files_with_lines"]
    data = server.local_extract(fields=fields, path=_write(tmp_path, text, "pr.patch"))
    notice = i18n.t("mcp.extract.diff_files_by_program", fields=", ".join(fields), count=26)
    assert data == {
        HUNKS_FIELD: hunks,
        "changed_files_with_lines": files,
        "_local_delegate": {"diff_files": {"fields": fields, "files": 26, "notice": notice}},
    }


def test_only_diff_fields_still_say_the_file_was_read_server_side(backend, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", True)
    text, _files, _hunks = _big_pr_diff()
    data = server.local_extract(fields=[FILES_FIELD], path=_write(tmp_path, text, "pr.patch"))
    assert backend == []
    meta = data["_local_delegate"]
    assert meta["read_server_side"]["chars"] == len(text)
    assert "chunked" not in meta


def test_an_extra_field_still_goes_to_the_backend(backend, tmp_path):
    """One field the program does not answer: the model is called as before (#687 scope)."""
    text, files, _hunks = _big_pr_diff()
    data = server.local_extract(
        fields=[FILES_FIELD, "summary"], path=_write(tmp_path, text, "pr.patch")
    )
    assert len(backend) > 1, "the extra field is the model's: it chunked"
    assert data[FILES_FIELD] == files
    assert data["summary"] is None
