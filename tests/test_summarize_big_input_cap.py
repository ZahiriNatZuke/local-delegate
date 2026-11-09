"""#580, reopened: the single call of `local_summarize` still cut big inputs at 3w+64 tokens.

With 0.49.0 the cap was 514 tokens for the default 150 words. On the Mac, 5 of 5 calls over a
23 409-character Markdown ended in `length` at exactly 514: on a big input the model writes far more
than the words asked for, and the answers grow with the input (in the usage log the median output of
`stop` answers goes 442 -> 552 -> 769 tokens from 8-16 K to 16-24 K to 24-32 K characters; every cut
of a default-sized call is on 16 K characters or more). Now the cap grows with the input above
16 000 characters. An answer still cut ends at its last complete sentence with a notice (#581).
"""

from __future__ import annotations

import json

import backend_mock
import httpx2
import pytest
from test_summarize_word_budget import _notice, _summarize

from local_delegate import config, sections, server

#: A Markdown input of the Mac case's size, with sentences (no headings: the single prose call).
BIG = ("El daemon atiende las delegaciones y registra cada llamada en el log de uso. " * 310)[
    :23_409
]


@pytest.fixture(autouse=True)
def _no_llamaswap_config(monkeypatch):
    # Whatever llama-swap config this machine has: the estimate, as on a remote backend.
    monkeypatch.setattr(server.llamaswap_config, "model_context_size", lambda model: (8192, True))


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


@backend_mock.mock
def _summarize_structured(monkeypatch, tmp_path, answer: str, **kw):
    """`_summarize` of the word-budget tests with `LOCAL_DELEGATE_STRUCTURED_SUMMARY` on."""
    monkeypatch.setattr(server, "_summary_language", lambda: "es")
    monkeypatch.setattr(config, "STRUCTURED_SUMMARY", True)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    seen: list[dict] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": answer}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    return server.local_summarize(**kw), seen


# --- The ceiling (review of #615) ------------------------------------------------------------------


def _context(monkeypatch, n_ctx: int | None) -> None:
    """The model's context as the llama-swap config gives it; `None`: no config (the estimate)."""
    value = (8192, True) if n_ctx is None else (n_ctx, False)
    monkeypatch.setattr(server.llamaswap_config, "model_context_size", lambda model: value)


def test_the_widening_stops_at_the_chunk_cap(monkeypatch, tmp_path):
    _context(monkeypatch, None)
    _, seen = _summarize(monkeypatch, tmp_path, "Resumen.", text=(BIG * 3)[:48_000])
    assert server._summary_max_tokens(150, 48_000) == 2_114  # what it would ask uncapped
    assert [c["max_tokens"] for c in seen] == [config.CHUNK_MAX_TOKENS] == [2_048]


def test_a_raised_long_limit_does_not_ask_more_than_the_chunk_cap(monkeypatch, tmp_path):
    _context(monkeypatch, None)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 200_000)
    _, seen = _summarize(monkeypatch, tmp_path, "Resumen.", text=(BIG * 9)[:200_000])
    assert len(seen) == 1  # guard: one single call, no map/reduce
    assert [c["max_tokens"] for c in seen] == [2_048]


def test_the_context_left_after_the_prompt_bounds_the_widening(monkeypatch, tmp_path):
    # 23 409 characters are about 11 900 tokens with the margin of `_reasoning_fits`.
    _context(monkeypatch, 12_800)
    _, seen = _summarize(monkeypatch, tmp_path, "Resumen.", text=BIG)
    (cap,) = [c["max_tokens"] for c in seen]
    assert 514 < cap < 884
    # A context the prompt already fills: the usual cap, never less.
    _context(monkeypatch, 8_192)
    _, seen = _summarize(monkeypatch, tmp_path, "Resumen.", text=BIG)
    assert [c["max_tokens"] for c in seen] == [514]
    # A context with room: the whole widening.
    _context(monkeypatch, 65_536)
    _, seen = _summarize(monkeypatch, tmp_path, "Resumen.", text=BIG)
    assert [c["max_tokens"] for c in seen] == [884]


def test_the_structured_single_call_gets_the_same_room(monkeypatch, tmp_path):
    # With `LOCAL_DELEGATE_STRUCTURED_SUMMARY` on, a Markdown of the `long` role takes
    # `_structured_summary`, whose cap grows with the sections and not with the size.
    _context(monkeypatch, None)
    body = BIG[: 23_409 // 3 - 20]
    doc = f"## Uno\n\n{body}\n\n## Dos\n\n{body}\n\n## Tres\n\n{body}\n"
    plan = sections.sections_for_summary(doc, sections.detect(doc))
    base = server._structured_max_tokens(150, plan)
    answer = "## Uno\n\nUno.\n\n## Dos\n\nDos.\n\n## Tres\n\nTres.\n"
    _, seen = _summarize_structured(monkeypatch, tmp_path, answer, text=doc)
    (payload,) = seen
    assert "Secciones, en orden" in payload["messages"][1]["content"]  # guard: structured path
    assert payload["max_tokens"] == base + server._big_input_extra(len(doc)) > base
