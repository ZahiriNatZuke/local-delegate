"""#672: a `path` input that is not UTF-8 is decoded right and says so, in every tool that reads it.

The issue: `local_summarize(path=...)` on a Latin-1 text (the output of `pdftotext -layout` on
Windows, with `m²`, `m³` and accents) read it as UTF-8 with `errors="replace"`, so `²` (byte 0xB2)
became U+FFFD, no notice said the file was not UTF-8, and the #630 check of the summary against
that broken text took the `m²`/`m³` the summary wrote (and the file does hold) for invented.

The reader (`server._read_input`) is shared by summarize, extract, explain_code, lint_summary,
commit_msg and translate, so each one is run here on the same Latin-1 file: the combination, not
only the function. The inputs are synthetic, with the shape of the issue.
"""

from __future__ import annotations

import json

import backend_mock
import httpx2
import pytest

from local_delegate import config, grounding, i18n, server

#: Spanish technical text with the characters of the issue: `²`, `³`, accents and an `ñ`.
SOURCE = (
    "Informe técnico de la parcela\r\n"
    "\r\n"
    "El volumen medido fue de 120 m³/ha y el área de 500 m².\r\n"
    "La señal del caudalímetro se calibró en la estación norte.\r\n"
)

#: What the model answered in the issue: a faithful summary that names `m²` and `m³`.
SUMMARY = "La parcela tiene 500 m² de área y un volumen de 120 m³/ha; el caudalímetro se calibró."

#: Characters of the issue on a single line, for the tools that are not about summaries.
CODE = "# Área en m²\r\nAREA = 500  # m²\r\n"


def _latin1(tmp_path, text: str = SOURCE, name: str = "report.txt"):
    path = tmp_path / name
    path.write_bytes(text.encode("latin-1"))
    return path


def _notice(encoding: str) -> str:
    return i18n.t("mcp.warning.input_not_utf8", encoding=encoding)


@pytest.fixture(autouse=True)
def _clean_encoding_state():
    """Each test starts and ends without an encoding left by another read."""
    token = server._INPUT_ENCODING.set(None)
    yield
    server._INPUT_ENCODING.reset(token)


def _isolate(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(server, "_summary_language", lambda: "es")
    monkeypatch.setattr(config, "SUMMARIZE_TABLE_LONG", False)


def _answer(content: str, seen: list[str] | None = None):
    def _handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        if seen is not None:
            seen.append(body["messages"][-1]["content"])
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)


# --- The reader ----------------------------------------------------------------------------------


def test_a_latin1_file_is_read_with_its_characters(tmp_path):
    content, _truncated, raw_len = server._read_input(None, str(_latin1(tmp_path)), 10_000)
    assert "m²" in content and "m³" in content and "señal" in content
    assert "�" not in content
    # Line ends normalized as `read_text` did.
    assert "\r" not in content
    assert raw_len == len(content)
    assert server._INPUT_ENCODING.get() == "cp1252"


def test_a_utf8_file_reads_as_before_and_carries_no_encoding(tmp_path):
    path = tmp_path / "f.txt"
    path.write_bytes(SOURCE.encode("utf-8"))
    content, _truncated, _raw_len = server._read_input(None, str(path), 10_000)
    assert content == path.read_text(encoding="utf-8")
    assert server._INPUT_ENCODING.get() is None
    assert server._with_input_encoding_notice("hola") == "hola"


def test_windows_1252_punctuation_is_kept(tmp_path):
    path = tmp_path / "f.txt"
    path.write_bytes("Precio: 5 € … «nota»".encode("cp1252"))
    content, _truncated, _raw_len = server._read_input(None, str(path), 10_000)
    assert content == "Precio: 5 € … «nota»"


def test_bytes_cp1252_leaves_undefined_fall_back_to_latin1(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(b"caf\xe9 \x81\x8d")
    content, _truncated, _raw_len = server._read_input(None, str(path), 10_000)
    assert content.startswith("café ")
    assert server._INPUT_ENCODING.get() == "latin-1"


@pytest.mark.parametrize("codec", ["utf-16-le", "utf-16-be"])
def test_a_utf16_file_with_its_bom_is_read_as_utf16(tmp_path, codec):
    # PowerShell 5 writes redirected output as UTF-16 LE with a BOM.
    bom = b"\xff\xfe" if codec == "utf-16-le" else b"\xfe\xff"
    path = tmp_path / "out.txt"
    path.write_bytes(bom + "línea 1\r\nlínea 2\r\n".encode(codec))
    content, _truncated, _raw_len = server._read_input(None, str(path), 10_000)
    assert content == "línea 1\nlínea 2\n"
    assert server._INPUT_ENCODING.get() == "utf-16"


def test_a_utf8_file_with_its_bom_reads_as_before(tmp_path):
    path = tmp_path / "bom.txt"
    path.write_bytes(b"\xef\xbb\xbf" + "área\r\n".encode())
    content, _truncated, _raw_len = server._read_input(None, str(path), 10_000)
    # Byte for byte what `read_text(encoding="utf-8")` gave: the BOM stays, as before.
    assert content == path.read_text(encoding="utf-8") == "﻿área\n"
    assert server._INPUT_ENCODING.get() is None


def test_a_utf16_bom_over_a_broken_body_reads_as_before(tmp_path):
    path = tmp_path / "broken.txt"
    path.write_bytes(b"\xff\xfe" + "ab".encode("utf-16-le") + b"\x00\xd8")  # a lone surrogate
    content, _truncated, _raw_len = server._read_input(None, str(path), 10_000)
    assert content == path.read_text(encoding="utf-8", errors="replace")
    assert server._INPUT_ENCODING.get() is None


def test_inline_text_clears_the_encoding_of_an_earlier_read(tmp_path):
    server._read_input(None, str(_latin1(tmp_path)), 10_000)
    server._read_input("texto", None, 10_000)
    assert server._INPUT_ENCODING.get() is None


def test_an_error_keeps_its_prefix_first(tmp_path):
    server._read_input(None, str(_latin1(tmp_path)), 10_000)
    error = server.ERROR_PREFIX + "backend caído"
    assert server._with_input_encoding_notice(error) == error
    assert server._with_input_encoding_notice("ok").startswith(server.WARNING_MARKER)


# --- The check of the summary against its input -------------------------------------------------


def test_a_unit_with_a_superscript_is_not_a_foreign_word():
    # The source writes `m2`: `²` is a digit, not a letter of another alphabet.
    found = grounding.check("El área es de 500 m².", "El área es de 500 m2.", language="es")
    assert found.foreign_words == []
    # A real foreign letter glued to the unit is still judged.
    found = grounding.check("Uma área de 500 m² ção.", "Área de 500 m2.", language="es")
    assert found.foreign_words == ["ção"]


def test_a_decomposed_accent_in_the_source_holds_the_composed_word():
    # macOS and some PDF tools write `ç` as `c` + U+0327: the same letter.
    source = "A verificação foi feita."
    decomposed = "A verificação foi feita."
    assert grounding.check("Hubo verificação.", source, language="es").foreign_words == []
    assert grounding.check("Hubo verificação.", decomposed, language="es").foreign_words == []


# --- Every tool that reads a `path`, on the same Latin-1 file -----------------------------------


@backend_mock.mock
def test_summarize_of_the_issue_warns_of_the_encoding_and_not_of_invented_data(
    monkeypatch, tmp_path
):
    _isolate(monkeypatch, tmp_path)
    seen: list[str] = []
    _answer(SUMMARY, seen)
    output = server.local_summarize(path=str(_latin1(tmp_path)), focus="volumen y área")
    # The model saw the file's characters, not U+FFFD.
    assert "m²" in seen[0] and "�" not in seen[0]
    assert output.startswith(server.WARNING_MARKER + _notice("cp1252"))
    assert SUMMARY in output
    assert output.count(server.WARNING_MARKER) == 1


@backend_mock.mock
def test_summarize_of_a_utf8_file_has_no_encoding_notice(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _answer(SUMMARY)
    path = tmp_path / "report.txt"
    path.write_bytes(SOURCE.encode("utf-8"))
    output = server.local_summarize(path=str(path), focus="volumen y área")
    assert server.WARNING_MARKER not in output


@backend_mock.mock
def test_summarize_split_in_chunks_warns_too(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "STRUCTURED_SUMMARY", False)
    _answer(SUMMARY)
    big = SOURCE * (config.max_chars_for_role("long") // len(SOURCE) + 2)
    output = server.local_summarize(path=str(_latin1(tmp_path, big)))
    assert output.startswith(server.WARNING_MARKER + _notice("cp1252"))


@backend_mock.mock
def test_extract_reports_the_encoding_in_its_metadata(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    seen: list[str] = []
    _answer(json.dumps({"area": "500 m²"}), seen)
    data = server.local_extract(fields=["area"], path=str(_latin1(tmp_path)))
    assert "m²" in seen[0] and "�" not in seen[0]
    assert data["area"] == "500 m²"
    meta = data["_local_delegate"]
    assert meta["input_encoding"] == "cp1252"
    assert _notice("cp1252") in meta["warning"]


@backend_mock.mock
def test_extract_of_a_utf8_file_has_no_encoding_key(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _answer(json.dumps({"area": "500 m²"}))
    path = tmp_path / "report.txt"
    path.write_bytes(SOURCE.encode("utf-8"))
    data = server.local_extract(fields=["area"], path=str(path))
    assert "input_encoding" not in data.get("_local_delegate", {})


@backend_mock.mock
def test_explain_code_warns_of_the_encoding(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    seen: list[str] = []
    _answer("Define el área en m².", seen)
    output = server.local_explain_code(path=str(_latin1(tmp_path, CODE, "area.py")))
    assert "m²" in seen[0]
    assert output.startswith(server.WARNING_MARKER + _notice("cp1252"))


@backend_mock.mock
def test_lint_summary_warns_of_the_encoding(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _answer("src/área.py: 1 error E501.")
    log = "src/área.py:1:1: E501 line too long (m²)\r\nFound 1 error.\r\n"
    output = server.local_lint_summary(path=str(_latin1(tmp_path, log, "lint.log")))
    assert output.startswith(server.WARNING_MARKER + _notice("cp1252"))


@backend_mock.mock
def test_lint_summary_of_a_clean_log_warns_too(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    # Answered by the program (#525), before the backend: no route is mocked.
    log = "tests/test_área.py ....\r\n===== 42 passed in 3.21s =====\r\n"
    output = server.local_lint_summary(path=str(_latin1(tmp_path, log, "lint.log")))
    assert output.startswith(server.WARNING_MARKER + _notice("cp1252"))


@backend_mock.mock
def test_translate_warns_of_the_encoding(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    seen: list[str] = []
    _answer("The area is 500 m².", seen)
    output = server.local_translate(target_lang="en", path=str(_latin1(tmp_path)))
    assert "m²" in seen[0]
    assert output.startswith(server.WARNING_MARKER + _notice("cp1252"))


@backend_mock.mock
def test_commit_msg_warns_of_the_encoding(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _answer("docs: área en m²")
    diff = (
        "diff --git a/notas.txt b/notas.txt\r\n"
        "--- a/notas.txt\r\n"
        "+++ b/notas.txt\r\n"
        "@@ -1 +1 @@\r\n"
        "-área\r\n"
        "+área en m²\r\n"
    )
    output = server.local_commit_msg(path=str(_latin1(tmp_path, diff, "change.diff")))
    assert output.startswith(server.WARNING_MARKER + _notice("cp1252"))


@backend_mock.mock
def test_the_structured_summary_warns_too(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "STRUCTURED_SUMMARY", True)
    filler = "\n".join(f"Línea de relleno {chr(97 + i % 26)} del área en m²." for i in range(400))
    source = "# Informe\n\n## Parcela\n\n" + SOURCE + "\n## Anexo\n\n" + filler + "\n"
    assert len(source) > config.LONG_INPUT_CHARS
    _answer("## Parcela\n\n" + SUMMARY + "\n\n## Anexo\n\nRelleno.")
    output = server.local_summarize(path=str(_latin1(tmp_path, source)))
    assert output.startswith(server.WARNING_MARKER + _notice("cp1252"))


@backend_mock.mock
def test_an_extract_error_carries_the_encoding_too(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    _answer("esto no es JSON")
    data = server.local_extract(fields=["area"], path=str(_latin1(tmp_path)))
    meta = data["_local_delegate"]
    assert "error" in meta
    assert meta["input_encoding"] == "cp1252"
    assert _notice("cp1252") in meta["warning"]
