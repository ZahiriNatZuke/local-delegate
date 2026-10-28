"""#460: `local_explain_code` con `path` ve el código numerado con las líneas ABSOLUTAS del fichero.

Antes, «¿en qué línea está el método X?» recibía «el texto no contiene números de línea»: el
código llegaba pelado y, al trocear, cada trozo empezaba sin saber dónde caía. Con `path` cada línea
viaja como `N| línea` (N la del fichero, la que usa `Read offset`), también en cada trozo del map; el
map pide `nombre (línea N):`, el inventario del reduce lleva `nombre:línea` calculado por programa y
el reduce pide conservarlas. Con `code=` en línea nada cambia. Backend falso (`_run_chat` doblado),
sin red.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from local_delegate import config, i18n, server

# El map recorta el trozo (`strip`): una línea en blanco al final queda como `N|`.
PREFIX = re.compile(r"^(\d+)\|(?: |$)", re.MULTILINE)


@pytest.fixture
def calls(monkeypatch, tmp_path) -> list[dict]:
    captured: list[dict] = []

    def run_chat(model, system, user, max_tokens, temperature, **_):
        captured.append({"system": system, "user": user})
        result = server.ChatResult(text="- nota", ok=True, finish_reason="stop")
        return result, 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    monkeypatch.delenv("LOCAL_DELEGATE_OUTPUT_LANGUAGE", raising=False)
    i18n.reset()
    return captured


def _python_module(target: int = 60_000) -> str:
    blocks = ['"""Módulo."""\n\nimport os\n\n']
    n = 0
    while sum(map(len, blocks)) < target:
        blocks.append(
            f"def function_{n}(value):\n"
            + "".join(f"    value = value + {i}  # paso {i}\n" for i in range(20))
            + "    return value\n\n\n"
        )
        n += 1
    blocks.append("class Last:\n    pass\n\n\ndef ZZZ_marker():\n    return 'fin'\n")
    return "".join(blocks)


def _typescript_component(target: int = 30_000) -> str:
    """Como el del issue: sin `def`/`class` en la columna 0, así que no hay inventario."""
    out = ["import { Component } from '@angular/core';\n\n", "export class Dialog {\n"]
    n = 0
    while sum(map(len, out)) < target:
        out.append(
            f"  method{n}(value: number): number {{\n"
            + "".join(f"    value = value + {i}; // paso {i}\n" for i in range(12))
            + "    return value;\n  }\n\n"
        )
        n += 1
    out.append("  onKeydown(event: KeyboardEvent): void {\n    this.close();\n  }\n}\n")
    return "".join(out)


def _line_of(text: str, needle: str) -> int:
    """La línea (desde 1) donde empieza `needle`, como la contaría `Read`."""
    return text.count("\n", 0, text.index(needle)) + 1


def _map_pieces(captured: list[dict]) -> list[str]:
    return [c["user"].split("\n\n", 1)[1] for c in captured[:-1]]


def _assert_numbered_absolute(pieces: list[str], original: str) -> None:
    """Cada línea lleva su número del fichero, sin reiniciar entre trozos, y nada se pierde."""
    lines = original.split("\n")
    expected = 1
    for piece in pieces:
        for row in piece.rstrip("\n").split("\n"):
            match = PREFIX.match(row)
            assert match, f"línea sin prefijo: {row[:60]!r}"
            number = int(match.group(1))
            assert number == expected, (number, expected, row[:60])
            assert row[match.end() :] == lines[number - 1], row[:60]
            expected += 1
    assert expected - 1 == len(original.rstrip("\n").split("\n"))  # todas las líneas llegaron


def test_number_lines_counts_from_the_offset_and_only_on_newlines():
    assert server._number_lines("a\nb\n", 7) == "7| a\n8| b\n"
    assert server._number_lines("a\n\nlast", 1) == "1| a\n2| \n3| last"
    # `\f` no es fin de línea para `Read`: no adelanta la cuenta.
    assert server._number_lines("a\fb\nc\n") == "1| a\fb\n2| c\n"


def test_a_file_that_fits_reaches_the_model_numbered(calls, tmp_path: Path):
    source = tmp_path / "small.py"
    source.write_text("def f():\n    return 1\n\n\ndef g():\n    return 2\n", encoding="utf-8")
    server.local_explain_code(path=str(source), question="¿en qué línea está g?")
    (call,) = calls
    assert call["user"].endswith(
        "1| def f():\n2|     return 1\n3| \n4| \n5| def g():\n6|     return 2\n"
    )
    assert server._LINE_NUMBERS_CLAUSE in call["system"]
    # La orden de idioma sigue cerrando el system (la piden otros tests).
    assert call["system"].index(server._LINE_NUMBERS_CLAUSE) < call["system"].index("Responde en")


def test_a_chunked_python_file_keeps_absolute_numbers_in_every_piece(calls, tmp_path: Path):
    """Mutante «trozos numerados desde 1» (o sin numerar): falla `_assert_numbered_absolute`."""
    code = _python_module()
    source = tmp_path / "big.py"
    source.write_text(code, encoding="utf-8")
    server.local_explain_code(path=str(source), question="¿en qué línea está ZZZ_marker?")
    pieces = _map_pieces(calls)
    assert len(pieces) > 2  # guarda: troceó de verdad
    _assert_numbered_absolute(pieces, code)
    budget = server._map_budget(config.max_chars_for_role("code"))
    assert all(len(p) <= budget for p in pieces)  # el prefijo cuenta en el presupuesto
    # El map pide la línea de cada definición y explica el prefijo.
    assert all("(línea N)" in c["system"] for c in calls[:-1])
    assert all(server._LINE_NUMBERS_CLAUSE in c["system"] for c in calls)
    # El reduce: inventario con la línea REAL, calculada por programa, y la orden de conservarlas.
    reduce_user = calls[-1]["user"]
    inventory = reduce_user.split("\n\n", 1)[0]
    assert f"ZZZ_marker:{_line_of(code, 'def ZZZ_marker')}" in inventory
    assert f"function_0:{_line_of(code, 'def function_0(')}" in inventory
    assert "responde con «nombre: línea»" in reduce_user


def test_a_chunked_file_without_top_level_defs_is_numbered_too(calls, tmp_path: Path):
    """El caso del issue: TypeScript sin `def`/`class` en la columna 0 (troceo por párrafos)."""
    code = _typescript_component()
    assert len(code) > config.max_chars_for_role("code")
    source = tmp_path / "dialog.component.ts"
    source.write_text(code, encoding="utf-8")
    server.local_explain_code(path=str(source), question="¿en qué línea está onKeydown?")
    pieces = _map_pieces(calls)
    assert len(pieces) > 1  # guarda: troceó
    _assert_numbered_absolute(pieces, code)
    line = _line_of(code, "  onKeydown(")
    assert f"{line}|   onKeydown(" in pieces[-1]
    # Los cortes siguen cayendo en líneas en blanco, no a mitad de un método.
    assert all(re.search(r"\n\d+\|$", p) for p in pieces[:-1]), [p[-40:] for p in pieces]


def test_numbering_does_not_make_a_file_that_fits_bare_chunk(calls, tmp_path: Path):
    """Trocear se decide sobre el fichero pelado, como antes de #460 (el corpus de calidad
    `explicar-install-20k` sigue siendo una llamada); la llamada única lo lleva numerado.
    Mutante «el tope sobre lo numerado»: trocea y falla `(call,) = calls`."""
    max_chars = config.max_chars_for_role("code")
    row = "x = 1\n"
    code = row * (max_chars // len(row))
    assert len(code) <= max_chars < len(server._number_lines(code))  # guarda: el caso frontera
    source = tmp_path / "dense.py"
    source.write_text(code, encoding="utf-8")
    server.local_explain_code(path=str(source))
    (call,) = calls
    assert call["user"].endswith(server._number_lines(code))


def test_inline_code_is_not_numbered(calls):
    """Control: con `code=` nada cambia (sin prefijo ni cláusula)."""
    server.local_explain_code(code="def f():\n    return 1\n")
    (call,) = calls
    assert call["user"] == "Explica el siguiente código:\n\ndef f():\n    return 1\n"
    assert server._LINE_NUMBERS_CLAUSE not in call["system"]
