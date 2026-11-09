"""#580, reopened: the single call of `local_summarize` still cut big inputs at 3w+64 tokens.

With 0.49.0 the cap was 514 tokens for the default 150 words. On the Mac, 5 of 5 calls over a
23 409-character Markdown ended in `length` at exactly 514: on a big input the model writes far more
than the words asked for, and the answers grow with the input (in the usage log the median output of
`stop` answers goes 442 -> 552 -> 769 tokens from 8-16 K to 16-24 K to 24-32 K characters; every cut
of a default-sized call is on 16 K characters or more). Now the cap grows with the input above
16 000 characters. An answer still cut ends at its last complete sentence with a notice (#581).
"""

from __future__ import annotations

from test_summarize_word_budget import _notice, _summarize

from local_delegate import server

#: A Markdown input of the Mac case's size, with sentences (no headings: the single prose call).
BIG = ("El daemon atiende las delegaciones y registra cada llamada en el log de uso. " * 310)[
    :23_409
]


def test_the_cap_grows_with_a_big_input_only():
    assert server._summary_max_tokens(150) == 514
    assert server._summary_max_tokens(150, 16_000) == 514
    assert server._summary_max_tokens(150, 16_020) == 515
    assert server._summary_max_tokens(150, 23_409) == 884
    assert server._summary_max_tokens(150, 48_000) == 2_114
    assert server._summary_max_tokens(40, 23_409) == 554


def test_the_single_call_of_a_big_input_asks_the_wider_cap(monkeypatch, tmp_path):
    assert len(BIG) == 23_409
    _, seen = _summarize(monkeypatch, tmp_path, "Resumen.", text=BIG)
    assert [c["max_tokens"] for c in seen] == [884]


def test_a_small_input_keeps_the_cap(monkeypatch, tmp_path):
    _, seen = _summarize(monkeypatch, tmp_path, "Resumen.", text=BIG[:16_000])
    assert [c["max_tokens"] for c in seen] == [514]


def test_a_big_input_still_cut_ends_at_a_sentence_with_a_notice(monkeypatch, tmp_path):
    answer = "El daemon registra cada llamada. Las delegaciones se atienden en orden y luego se"
    out, _seen = _summarize(monkeypatch, tmp_path, answer, finish="length", text=BIG)
    assert out.startswith("El daemon registra cada llamada.")
    assert "y luego se" not in out
    assert _notice("mcp.warning.output_trimmed") in out


def test_the_cap_counts_characters_not_bytes_of_a_file(monkeypatch, tmp_path):
    # Accented text: 23 409 characters are more bytes; the cap counts what reaches the model.
    text = ("La configuración del daemon está en el perfil y se lee al arrancar. " * 400)[:23_409]
    path = tmp_path / "doc.md"
    path.write_bytes(text.encode("utf-8"))
    assert path.stat().st_size > 23_409  # guard: bytes and characters differ
    _, seen = _summarize(monkeypatch, tmp_path, "Resumen.", path=str(path))
    assert [c["max_tokens"] for c in seen] == [884]
