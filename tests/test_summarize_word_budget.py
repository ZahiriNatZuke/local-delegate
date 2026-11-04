"""#580: the flat `local_summarize` cut its summary in the middle of a word with `max_words=150`.

The single call asked for `max_tokens = 2 * max_words + 64` (364 with 150). Measured against the
real backend, the model spends 1.46-1.67 tokens per Spanish word and writes up to 1.49x the words
asked for, so 364 tokens ran out mid-sentence. Now the cap is `3 * max_words + 64`, the same in the
map/reduce, and an answer still cut by `max_tokens` ends at its last complete sentence.
"""

from __future__ import annotations

import json

import backend_mock
import httpx2
import pytest

from local_delegate import config, i18n, sections, server


def _notice(key: str) -> str:
    return server.WARNING_MARKER + i18n.t(key) + "]"


@backend_mock.mock
def _summarize(monkeypatch, tmp_path, answer: str, finish: str = "stop", **kw):
    monkeypatch.setattr(server, "_summary_language", lambda: "es")
    monkeypatch.setattr(config, "STRUCTURED_SUMMARY", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    seen: list[dict] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": answer}, "finish_reason": finish}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    return server.local_summarize(**kw), seen


# --- The cap -----------------------------------------------------------------------------------


def test_the_single_call_asks_three_tokens_per_word(monkeypatch, tmp_path):
    """Mutant (the old 2w+64): the default call asks 364 and the first assert fails."""
    _, seen = _summarize(monkeypatch, tmp_path, "Resumen.", text="Un texto corto.")
    assert [c["max_tokens"] for c in seen] == [514]
    _, seen = _summarize(monkeypatch, tmp_path, "Resumen.", text="Un texto corto.", max_words=40)
    assert [c["max_tokens"] for c in seen] == [184]


def test_the_map_reduce_uses_the_same_cap(monkeypatch, tmp_path):
    """Mutant (no `max_tokens_for`): the map and the reduce ask 2w+64 = 364."""
    monkeypatch.setattr(config, "max_chars_for_role", lambda role: 4_000)
    text = "".join(
        f"Párrafo {i}. " + "Texto de relleno con frases. " * 20 + "\n\n" for i in range(40)
    )
    _, seen = _summarize(monkeypatch, tmp_path, "Resumen parcial.", text=text)
    assert len(seen) > 2  # guard: it went through the map/reduce
    assert {c["max_tokens"] for c in seen} == {server._summary_max_tokens(150)} == {514}


@backend_mock.mock
def test_the_other_map_reduce_tools_keep_the_shared_cap(monkeypatch, tmp_path):
    """Control: the summarize cap does not leak into `_chat_map_reduce`'s default. Mutant (3w+64
    as the default of `_tokens`): `local_extract` asks 3*224+64 = 736 instead of 512."""
    monkeypatch.setattr(config, "max_chars_for_role", lambda role: 4_000)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    seen: list[dict] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        message = {"content": '{"a": "1"}'}
        return httpx2.Response(
            200, json={"choices": [{"message": message, "finish_reason": "stop"}]}
        )

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    text = "".join(f"Línea {i}: a vale 1 en este bloque de relleno.\n" for i in range(600))
    server.local_extract(fields=["a"], text=text)
    assert len(seen) > 2  # guard: it went through the map/reduce
    assert {c["max_tokens"] for c in seen} == {2 * server._EXTRACT_WORDS + 64} == {512}


def test_an_answer_that_ends_well_comes_back_unchanged(monkeypatch, tmp_path):
    """REQ-005: without `length` nothing is cut, not even an answer without a final dot."""
    answer = "Primera frase. Segunda sin punto final"
    out, _ = _summarize(monkeypatch, tmp_path, answer, text="Un texto corto.")
    assert out == answer


# --- The cut answer ----------------------------------------------------------------------------


def test_a_cut_answer_ends_at_its_last_sentence_with_the_notice(monkeypatch, tmp_path):
    """Mutant (no `trim_cut`): the text keeps «Tercera a medi» and the old notice."""
    answer = "Primera frase completa. Segunda frase también.\n\nTercera a medi"
    out, _ = _summarize(monkeypatch, tmp_path, answer, finish="length", text="Un texto corto.")
    trimmed = _notice("mcp.warning.output_trimmed")
    assert out == "Primera frase completa. Segunda frase también.\n\n" + trimmed
    assert "salida truncada por max_tokens" in out  # the phrase of the old notice is still there


def test_a_cut_answer_without_a_sentence_end_keeps_today_s_output(monkeypatch, tmp_path):
    out, _ = _summarize(monkeypatch, tmp_path, "cort", finish="length", text="Un texto corto.")
    assert out == "cort\n\n" + _notice("mcp.warning.output_truncated")


def test_the_trimmed_notice_in_english(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    i18n.reset()
    out, _ = _summarize(monkeypatch, tmp_path, "Done. Half a", finish="length", text="Short.")
    assert out.startswith("Done.\n\n[local-delegate warning: output truncated by max_tokens; cut")


# --- The pure function -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cut", "expected"),
    [
        # A list whose last item was cut: the complete items stay, the list ends closed.
        ("Intro.\n\n**Puntos:**\n* uno.\n* dos a medi", "Intro.\n\n**Puntos:**\n* uno."),
        # List items without a final dot are complete lines too.
        ("Intro.\n\n- uno\n- dos\n- tres a me", "Intro.\n\n- uno\n- dos"),
        # A label left announcing a paragraph that never came.
        ("Intro completa.\n\n**Configuración:**\nSe usa `LOCAL_DE", "Intro completa."),
        # A heading left alone.
        ("Intro completa.\n\n## Detalles\nLa parte que se co", "Intro completa."),
        # A line ending in `:` that introduced a list cut at its first item.
        ("Uno. Dos.\nLos pasos son:\n1. Abrir el fich", "Uno. Dos."),
        # An unclosed code block goes whole.
        ("Texto.\n\n```python\nx = 1.\ny = 2", "Texto."),
        # A dot inside inline code or a version number is not a sentence end.
        ("Uno. Se lee `a. b` y sig", "Uno."),
        ("Va en la 0.48.0 y se publ", None),
        # The end of a bold span closes the sentence with it.
        ("Esto es **importante.** Y lo otr", "Esto es **importante.**"),
        # A whole bold line that is a sentence is kept; a bold label with nothing below is not.
        (
            "Intro.\n**Primera conclusión completa.**\n**Segunda conclusión completa.**\nTercera sin ter",
            "Intro.\n**Primera conclusión completa.**\n**Segunda conclusión completa.**",
        ),
        ("Intro.\n\n**Arranque**\nSe ini", "Intro."),
        ("**Arranque**\nSe inicia con uv. Y lue", "**Arranque**\nSe inicia con uv."),
        # Chinese and Japanese end their sentences with no space after them.
        ("第一句。第二句！第三句没有结", "第一句。第二句！"),
        ("最初の文です。次の文で", "最初の文です。"),
        # A cut table row goes whole, even with a dot inside a cell.
        (
            "Tabla.\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n| 3 | fin. y m",
            "Tabla.\n\n| a | b |\n| --- | --- |\n| 1 | 2 |",
        ),
        # Known limit: an abbreviation counts as a sentence end.
        ("Se usa p. ej. un fich", "Se usa p. ej."),
        # A cut that fell right after a full sentence leaves nothing to trim.
        ("Primera. Segunda.", None),
        ("sin ninguna frase completa", None),
    ],
)
def test_trim_to_last_sentence(cut, expected):
    assert sections.trim_to_last_sentence(cut) == expected
