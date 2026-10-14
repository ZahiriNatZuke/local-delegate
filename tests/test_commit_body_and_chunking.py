"""Cuerpo de `local_commit_msg` y troceado de `local_explain_code`/`local_extract` (ola B2c).

Causas medidas en la revisión del 2026-10-14 (`evidence/local-tools-review/report.md`): el commit
salía de una línea porque el formato decía «cuerpo opcional» y los topes eran 256 tokens (una
llamada) y 90 palabras (paso final del troceado); `explain_code` y `extract` truncaban a 20 000
caracteres en una sola llamada. Los prompts y los topes se capturan con un backend falso
(`_run_chat` doblado), sin red.
"""

from __future__ import annotations

import pytest

from local_delegate import config, i18n, server

BODY = "cuerpo OBLIGATORIO de 2 a 6 viñetas"
OUTPUT = "LOCAL_DELEGATE_OUTPUT_LANGUAGE"


def _ok(text: str, finish: str = "stop"):
    return server.ChatResult(text=text, ok=True, finish_reason=finish)


@pytest.fixture
def backend(monkeypatch):
    """Captura cada llamada; `answer` decide la respuesta a partir de la llamada."""
    calls: list[dict] = []
    state = {"answer": lambda call: _ok("respuesta")}

    def run_chat(model, system, user, max_tokens, temperature, **kwargs):
        call = {
            "system": system,
            "user": user,
            "max_tokens": max_tokens,
            "response_format": kwargs.get("response_format"),
        }
        calls.append(call)
        return state["answer"](call), 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    return calls, state


# --- Cuerpo y topes del commit -----------------------------------------------------------------


def _diff(files: int, lines: int = 30) -> str:
    out = []
    for n in range(files):
        body = "".join(f"+linea {i} del archivo {n}\n" for i in range(lines))
        out.append(
            f"diff --git a/src/m{n}.py b/src/m{n}.py\n--- a/src/m{n}.py\n+++ b/src/m{n}.py\n"
            f"@@ -0,0 +1,{lines} @@\n{body}"
        )
    return "".join(out)


@pytest.mark.parametrize("style", ["conventional", "plain"])
def test_the_single_call_asks_for_a_body_and_has_room_for_it(backend, style):
    """Mutante «formato y topes de hoy»: falla primero por el cuerpo y luego por el tope."""
    calls, _ = backend
    server.local_commit_msg(diff=_diff(1, 3), style=style)
    assert len(calls) == 1  # guarda: la llamada única, no el troceado
    assert BODY in calls[0]["system"], calls[0]["system"]
    assert "opcional" not in calls[0]["system"]
    assert calls[0]["max_tokens"] >= 700


def test_the_final_step_of_the_chunking_asks_for_a_body_and_has_room_for_it(monkeypatch, backend):
    calls, _ = backend
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "code", 2000)
    monkeypatch.setattr(config, "CHUNK_MIN_CHARS", 200)
    server.local_commit_msg(diff=_diff(6))
    assert len(calls) > 2  # guarda: troceó y redujo
    final = calls[-1]
    assert BODY in final["system"], final["system"]
    assert "cuerpo de 2 a 6 viñetas" in final["user"]
    # `_tokens(250)` = 564: el tope del paso final para 250 palabras.
    assert final["max_tokens"] >= 564
    # El map no redacta el mensaje: ni lleva el cuerpo ni la orden del commit.
    assert all(BODY not in c["system"] for c in calls[:-1])


# --- Troceado de `local_explain_code` ----------------------------------------------------------


def _big_module(target: int = 60_000) -> str:
    blocks = ['"""Módulo de prueba."""\n\nimport os\n\n']
    n = 0
    while sum(map(len, blocks)) < target:
        blocks.append(
            f"@decorator(\n    option={n},\n)\ndef function_{n}(value):\n"
            + "".join(f"    value = value + {i}  # paso {i}\n" for i in range(20))
            + "    return value\n\n\n"
        )
        n += 1
    blocks.append("class Last:\n    pass\n\n\ndef ZZZ_marker():\n    return 'fin'\n")
    return "".join(blocks)


def test_explain_code_reads_a_large_file_whole(backend, tmp_path):
    """El fichero de ~60 000 chars con `def ZZZ_marker` al final llega entero al backend y el
    paso final lleva el inventario y la pregunta. Mutante «el camino de hoy» (truncar al tope del
    rol y una sola llamada): falla en el assert de `ZZZ_marker`."""
    calls, _ = backend
    source = tmp_path / "big.py"
    source.write_text(_big_module(), encoding="utf-8")
    assert len(source.read_text(encoding="utf-8")) > 55_000
    server.local_explain_code(path=str(source), question="qué devuelve cada función")
    assert any("def ZZZ_marker" in c["user"] for c in calls), "el final del fichero no llegó"
    assert len(calls) > 2  # guarda: troceó y redujo
    final = calls[-1]
    assert "ZZZ_marker" in final["user"].split("\n\n", 1)[0], "el inventario no lo nombra"
    assert "Enfócate en: qué devuelve cada función." in final["system"]


def test_explain_code_does_not_split_a_definition(backend, tmp_path):
    calls, _ = backend
    source = tmp_path / "big.py"
    source.write_text(_big_module(), encoding="utf-8")
    server.local_explain_code(path=str(source))
    pieces = [c["user"].split("\n\n", 1)[1] for c in calls[:-1]]
    assert len(pieces) > 1
    for piece in pieces[1:]:
        assert piece.startswith(("@decorator(", "class ", "def ")), piece[:40]
    # Cada decorador viaja con su función: ningún corte entre los dos.
    for piece in pieces:
        assert piece.count("@decorator(") == piece.count("def function_"), piece[:80]


def test_explain_code_asks_for_the_language_in_every_step(monkeypatch, backend, tmp_path):
    calls, _ = backend
    monkeypatch.setenv(OUTPUT, "fr")
    source = tmp_path / "big.py"
    source.write_text(_big_module(), encoding="utf-8")
    server.local_explain_code(path=str(source))
    assert len(calls) > 2
    order = " Responde en francés, aunque el contenido esté en otro idioma."
    assert all(c["system"].endswith(order) for c in calls)


def test_explain_code_that_fits_is_the_single_call_of_before(backend):
    calls, _ = backend
    server.local_explain_code(code="x = 1")
    assert len(calls) == 1
    assert calls[0]["user"] == "Explica el siguiente código:\n\nx = 1"
    assert calls[0]["max_tokens"] == 700


def test_split_by_top_level_defs_keeps_the_text_and_the_decorators():
    text = (
        "import os\n\nX = 1\n\n"
        "@a\n@b(\n    c=1,\n)\ndef f():\n    def inner():\n        pass\n\n"
        "class K:\n    def m(self):\n        pass\n\n"
        "async def g():\n    pass\n"
    )
    pieces = server._split_by_top_level_defs(text)
    assert "".join(pieces) == text
    assert [p.split("\n", 1)[0] for p in pieces] == [
        "import os",
        "@a",
        "class K:",
        "async def g():",
    ]


def test_code_without_definitions_falls_back_to_the_text_chunking():
    assert server._code_pieces("SELECT 1;\n" * 10, 50) is None


def test_the_inventory_is_cut_with_its_count():
    text = server._format_names([f"name_{i}" for i in range(50)], 120)
    assert text.startswith("Definiciones de primer nivel del fichero (50 en total):")
    assert text.endswith(" más") and len(text) < 140


# --- Troceado de `local_extract` ---------------------------------------------------------------


def _big_text(final: str) -> str:
    return "Línea de relleno sin datos útiles.\n" * 1800 + final


def test_extract_reads_a_large_input_whole(backend):
    """El valor que solo está al final sale en el objeto, sin llamada de reducción (un solo
    parcial con datos). Mutante «el camino de hoy»: el final no llega y `a` es None."""
    calls, state = backend
    state["answer"] = lambda call: _ok(
        '{"a": "ZZZ_value"}' if "ZZZ_value" in call["user"] else '{"a": null}'
    )
    data = server.local_extract(fields=["a"], text=_big_text("a = ZZZ_value\n"))
    assert data["a"] == "ZZZ_value", "el final de la entrada no llegó"
    assert len(calls) > 1  # guarda: troceó
    assert all(c["response_format"] is not None for c in calls), "un paso sin schema"
    assert all("Combina" not in c["system"] for c in calls), "redujo sin necesidad"
    assert "_local_delegate" not in data


def test_extract_with_several_values_reduces_with_the_model_and_the_schema(backend):
    calls, state = backend

    def answer(call):
        if "Combina" in call["system"]:
            return _ok('{"a": "final"}')
        return _ok('{"a": "parcial"}')

    state["answer"] = answer
    data = server.local_extract(fields=["a"], text=_big_text("a = x\n"))
    assert data["a"] == "final"
    reduce = calls[-1]
    assert "Combina" in reduce["system"] and reduce["response_format"] is not None


def test_extract_truncated_means_a_truncated_output_in_the_chunking(backend):
    """`truncated`/`warning` = salida truncada en un trozo (decisión 8 de B2)."""
    calls, state = backend
    state["answer"] = lambda call: _ok('{"a": null}', "length" if len(calls) == 1 else "stop")
    data = server.local_extract(fields=["a"], text=_big_text(""))
    meta = data["_local_delegate"]
    assert meta["truncated"] is True
    assert meta["warning"] == i18n.t(
        "mcp.warning.output_truncated_calls", truncated=1, calls=len(calls)
    )


def test_extract_truncated_means_a_truncated_output_in_one_call(backend):
    calls, state = backend
    state["answer"] = lambda call: _ok('{"a": 1}', "length")
    data = server.local_extract(fields=["a"], text="a=1")
    assert len(calls) == 1
    assert data["a"] == 1
    assert data["_local_delegate"]["truncated"] is True


def test_extract_no_longer_marks_a_large_input_as_truncated(backend):
    calls, state = backend
    state["answer"] = lambda call: _ok('{"a": null}')
    data = server.local_extract(fields=["a"], text=_big_text(""))
    assert len(calls) > 1
    assert "_local_delegate" not in data
