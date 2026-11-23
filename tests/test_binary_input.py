"""#693: a binary file passed by `path` to a text tool is refused before the model.

The issue: `local_extract(path=<a JPEG screenshot>)` warned that the file was not UTF-8, read it as
Latin-1 (#672 decodes any byte), split it in 6 chunks and answered every field `null`: 6 calls to
the model for nothing. Now the shared reader (`server._read_input`) looks at the bytes first: a
known signature (PNG, JPEG, GIF, WebP, PDF, ZIP, gzip, 7z), a NUL byte outside a UTF-16 file with
its BOM, or more than 10 % of C0 control bytes is a binary, and the tool raises `InputError`; for
an image the message points to `local_describe_image`.

The reader is shared by six tools, so each one is run on the same JPEG: the combination, not only
the function. The images are real (a 1x1 PNG and an 8x8 baseline JPEG, both decodable), built
here byte by byte. The backend is faked (`_run_chat`): a call to it is counted, never made.
"""

from __future__ import annotations

import struct
import zlib

import pytest

from local_delegate import config, i18n, server


def _png() -> bytes:
    """A valid 1x1 RGB PNG."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _jpeg() -> bytes:
    """A valid 8x8 grayscale baseline JPEG: one block, DC 0, end of block, mid gray."""
    soi, eoi = b"\xff\xd8", b"\xff\xd9"
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    dqt = b"\xff\xdb" + struct.pack(">H", 67) + b"\x00" + b"\x01" * 64
    sof0 = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, 8, 8, 1) + b"\x01\x11\x00"
    # One code of length 1 in each table: DC category 0, AC end of block.
    dht_dc = b"\xff\xc4" + struct.pack(">H", 20) + b"\x00" + b"\x01" + b"\x00" * 15 + b"\x00"
    dht_ac = b"\xff\xc4" + struct.pack(">H", 20) + b"\x10" + b"\x01" + b"\x00" * 15 + b"\x00"
    sos = b"\xff\xda" + struct.pack(">HB", 8, 1) + b"\x01\x00" + b"\x00\x3f\x00"
    scan = b"\x3f"  # bits 0 (DC) and 0 (EOB), padded with ones
    return soi + app0 + dqt + sof0 + dht_dc + dht_ac + sos + scan + eoi


GIF = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00"
WEBP = b"RIFF\x1a\x00\x00\x00WEBPVP8L\x0d\x00\x00\x00\x2f\x00\x00\x00\x10\x07\x10\x11\x11\x88\x88\xfe\x07"
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
ZIP = b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + b"x" * 40
GZIP = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03" + b"y" * 40
SEVEN_Z = b"7z\xbc\xaf\x27\x1c\x00\x04" + b"z" * 40


@pytest.fixture
def calls(monkeypatch, tmp_path) -> list[str]:
    """The users of every backend call; the backend never runs."""
    seen: list[str] = []

    def run_chat(model, system, user, max_tokens, temperature, **_):
        seen.append(user)
        result = server.ChatResult(text='{"campo": "x"}', ok=True, finish_reason="stop")
        return result, 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(server, "_summary_language", lambda: "es")
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    i18n.reset()
    token = server._INPUT_ENCODING.set(None)
    yield seen
    server._INPUT_ENCODING.reset(token)
    i18n.reset()


def _write(tmp_path, name: str, data: bytes):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


#: Each text tool that reads `path`, called on a file. Every call goes through `_read_input`.
TOOLS = {
    "summarize": lambda p: server.local_summarize(path=p),
    "extract": lambda p: server.local_extract(fields=["campo"], path=p),
    "lint_summary": lambda p: server.local_lint_summary(path=p),
    "commit_msg": lambda p: server.local_commit_msg(path=p),
    "translate": lambda p: server.local_translate(target_lang="English", path=p),
    "explain_code": lambda p: server.local_explain_code(path=p),
}


# --- Images: refused, and pointed to local_describe_image ----------------------------------------


@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_a_jpeg_is_refused_by_every_text_tool_before_the_model(calls, tmp_path, tool):
    """Mutant "no binary check in `_read_input`": the JPEG is read as Latin-1, the tool calls the
    model (or answers), and `pytest.raises` fires."""
    path = _write(tmp_path, "screenshot.jpg", _jpeg())
    with pytest.raises(server.InputError) as error:
        TOOLS[tool](path)
    assert "JPEG" in str(error.value)
    assert "local_describe_image" in str(error.value)
    assert calls == []


@pytest.mark.parametrize(
    ("name", "data", "kind"),
    [("a.png", _png(), "PNG"), ("a.gif", GIF, "GIF"), ("a.webp", WEBP, "WebP")],
)
def test_other_images_are_refused_with_their_format(calls, tmp_path, name, data, kind):
    with pytest.raises(server.InputError) as error:
        server.local_extract(fields=["campo"], path=_write(tmp_path, name, data))
    assert kind in str(error.value) and "local_describe_image" in str(error.value)
    assert calls == []


def test_the_signature_counts_not_the_extension(calls, tmp_path):
    """A PNG saved as `.txt` is still an image; the bytes decide."""
    with pytest.raises(server.InputError, match="PNG"):
        server.local_summarize(path=_write(tmp_path, "notes.txt", _png()))
    assert calls == []


def test_the_message_is_in_english_too(calls, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    i18n.reset()
    with pytest.raises(server.InputError) as error:
        server.local_extract(fields=["campo"], path=_write(tmp_path, "a.jpg", _jpeg()))
    assert "image" in str(error.value) and "local_describe_image" in str(error.value)


# --- Other binaries ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "kind"),
    [(PDF, "PDF"), (ZIP, "ZIP"), (GZIP, "gzip"), (SEVEN_Z, "7z")],
    ids=["pdf", "zip", "gzip", "7z"],
)
def test_documents_and_archives_are_refused_by_signature(calls, tmp_path, data, kind):
    with pytest.raises(server.InputError) as error:
        server.local_summarize(path=_write(tmp_path, "file.bin", data))
    assert kind in str(error.value)
    assert "local_describe_image" not in str(error.value)
    assert calls == []


def test_nul_bytes_make_a_file_binary(calls, tmp_path):
    """An executable or a UTF-16 file without BOM: NUL bytes, which no text carries."""
    data = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"texto\n" * 20
    with pytest.raises(server.InputError):
        server.local_lint_summary(path=_write(tmp_path, "output.log", data))
    assert calls == []


def test_utf16_without_bom_is_refused_with_a_hint(calls, tmp_path):
    data = "línea 1\nlínea 2\n".encode("utf-16-le")
    with pytest.raises(server.InputError) as error:
        server.local_summarize(path=_write(tmp_path, "output.txt", data))
    assert "UTF-16" in str(error.value)
    assert calls == []


def test_many_control_bytes_make_a_file_binary(calls, tmp_path):
    """No NUL and no signature, but 20 % of C0 control bytes."""
    data = (b"abcd\x01" * 400) + b"\n"
    with pytest.raises(server.InputError):
        server.local_summarize(path=_write(tmp_path, "odd.dat", data))
    assert calls == []


# --- Text keeps being read (controls: these pass before and after the fix) -----------------------


TEXTS = {
    "utf8_accents": "Informe técnico: el área es de 500 m² y el caudal 120 m³/ha. Señal ñandú.\n".encode(),
    "utf8_bom": b"\xef\xbb\xbf" + "área\r\n".encode(),
    "utf16_le_bom": b"\xff\xfe" + "línea 1\r\nlínea 2\r\n".encode("utf-16-le"),
    "utf16_be_bom": b"\xfe\xff" + "línea 1\r\nlínea 2\r\n".encode("utf-16-be"),
    "latin1": "café, área, m²\n".encode("latin-1"),
    "ansi_colours": b"\x1b[31mE501\x1b[0m src/a.py:1:1 line too long\n" * 30,
    "one_stray_control": b"src/a.py:1:1: E501 line too long\x0c\n" * 5 + b"\x07 bell\n",
    "form_feed_and_tabs": b"col1\tcol2\x0c\ncol3\tcol4\x0b\n" * 10,
    "empty": b"",
    # Review of #709: a stray NUL in a long log, and one BEL in a tiny file, are not binaries.
    "one_stray_nul": b"src/a.py:1:1: E501 line too long\n" * 50 + b"\x00\n" + b"tail\n" * 50,
    "nul_past_the_sample": b"ok\n" * 40_000 + b"\x00" * 64,
    "tiny_with_bell": b"hi\x07\n",
}


@pytest.mark.parametrize("name", sorted(TEXTS))
def test_text_files_are_not_refused(calls, tmp_path, name):
    path = _write(tmp_path, f"{name}.txt", TEXTS[name])
    content, _truncated, _raw = server._read_input(None, path, server._NO_TRUNCATE)
    assert "�" not in content


def test_an_accented_utf8_file_reaches_the_model_intact(calls, tmp_path):
    path = _write(tmp_path, "report.txt", TEXTS["utf8_accents"])
    server.local_summarize(path=path)
    assert len(calls) == 1  # guard: the model ran
    assert "500 m²" in calls[0] and "ñandú" in calls[0]


def test_a_utf16_file_with_its_bom_reaches_the_model(calls, tmp_path):
    path = _write(tmp_path, "output.txt", TEXTS["utf16_le_bom"])
    server.local_summarize(path=path)
    assert len(calls) == 1
    assert "línea 2" in calls[0]


def test_inline_text_is_never_checked(calls):
    """`text` is already a string: the check is for bytes read from `path`."""
    content, _t, _r = server._read_input("a\x00b", None, server._NO_TRUNCATE)
    assert content == "a\x00b"
