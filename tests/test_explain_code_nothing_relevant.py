"""#527: the chunked `local_explain_code` answered «no information» with the name in the file.

Every chunk noted «Nada relevante en este fragmento», even the one holding `summarizable()`, and
the reduce concluded the code did not answer, while the exact search appended at the end found
the name. Now, with `path` and a question: each chunk is told which of the question's identifiers
it holds and on which lines; the reduce gets those lines for the whole file; and a final answer
that still claims there is no information gets a visible warning. The backend is faked
(`_run_chat`): no network, log in tmp.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from local_delegate import config, i18n, line_check, server

QUESTION = "¿Consulta summarizable() alguna lista de rutas protegidas antes de redirigir?"
NOTHING = "Nada relevante en este fragmento."
NO_INFO = (
    "El código proporcionado no contiene información suficiente para responder a la pregunta. "
    "Las notas indican «Nada relevante en este fragmento» para todas las secciones."
)
HINT = "Identificadores de la pregunta que aparecen en este fragmento"
EXACT = "Líneas del fichero donde aparecen los identificadores de la pregunta"


def _ok(text: str):
    return server.ChatResult(text=text, ok=True, finish_reason="stop")


@pytest.fixture
def backend(monkeypatch, tmp_path):
    """Every call recorded; the map answers «Nada relevante», the reduce `state['reduce']`."""
    calls: list[dict] = []
    state = {"reduce": NO_INFO}

    def run_chat(model, system, user, max_tokens, temperature, **_):
        calls.append({"system": system, "user": user})
        text = NOTHING if user.startswith("Toma notas") else state["reduce"]
        return _ok(text), 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.delenv("LOCAL_DELEGATE_DUMP_CHUNK_NOTES", raising=False)
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    monkeypatch.delenv("LOCAL_DELEGATE_OUTPUT_LANGUAGE", raising=False)
    i18n.reset()
    return calls, state


def _file(tmp_path: Path) -> tuple[Path, int]:
    """~45 KB of Python, three chunks or more; `summarizable` defined in the middle only.

    Returns the file and the line of `def summarizable`.
    """
    parts: list[str] = []
    i = 0
    while sum(map(len, parts)) < 22_000:
        body = "".join(f"    v{j} = helper_{i}_{j}(args)  # step {j}\n" for j in range(12))
        parts.append(f'def func_{i}(args):\n    """Do thing {i}."""\n{body}    return v0\n\n\n')
        i += 1
    head = "".join(parts)
    target = (
        "def summarizable(path, size):\n"
        '    """Whether the file is prose above the threshold."""\n'
        "    return path.endswith('.md') and size > 4096\n\n\n"
    )
    file = tmp_path / "classifier.py"
    file.write_bytes((head + target + head.replace("func_", "tail_")).encode("utf-8"))
    return file, head.count("\n") + 1


def test_the_chunk_holding_the_name_is_told_where_it_is(backend, tmp_path):
    """Mutant «no hint in the map» (`_map_hint` returns ""): the hint asserts fail."""
    calls = backend[0]
    file, line = _file(tmp_path)
    server.local_explain_code(path=str(file), question=QUESTION)
    maps = [c for c in calls if c["user"].startswith("Toma notas")]
    assert len(maps) >= 3  # guard: it chunked
    holding = [c for c in maps if f"{line}| def summarizable" in c["user"]]
    assert len(holding) == 1  # guard: the definition fell in exactly one chunk
    assert (
        f"{HINT} (búsqueda exacta, por programa): `summarizable` en las líneas {line}."
        in (holding[0]["user"])
    )
    # The hint goes before the code, after the question.
    assert holding[0]["user"].index(HINT) < holding[0]["user"].index(f"{line}| ")
    # The chunks without the name get no hint: it is computed, not a fixed sentence.
    for call in maps:
        if call is not holding[0]:
            assert HINT not in call["user"]
    # A code that shows something does NOT happen is relevant too.
    assert "NO ocurre también sirve" in maps[0]["system"]


def test_the_reduce_gets_the_exact_lines_of_the_file(backend, tmp_path):
    """Mutant «no exact lines in the reduce» (`exact_lines = ""`): the reduce assert fails."""
    calls = backend[0]
    file, line = _file(tmp_path)
    server.local_explain_code(path=str(file), question=QUESTION)
    reduce = calls[-1]
    assert not reduce["user"].startswith("Toma notas")  # guard: the last step is the reduce
    assert (
        f"{EXACT} (búsqueda exacta, por programa; fiables): `summarizable`: {line}."
        in (reduce["user"])
    )
    assert reduce["user"].index(EXACT) < reduce["user"].index("Estas son notas EN ORDEN")


def test_a_no_information_answer_with_the_name_in_the_file_is_flagged(backend, tmp_path):
    """The shape of #527: every note «Nada relevante», the reduce «no information».

    Mutant «no contradiction warning» (the `claims_no_information` branch of `_verified_lines`
    removed): the warning assert fails, the occurrences line still comes.
    """
    file, line = _file(tmp_path)
    answer = server.local_explain_code(path=str(file), question=QUESTION)
    assert answer.startswith(NO_INFO)
    warning = i18n.t("mcp.explain.contradiction", names="`summarizable`")
    assert f"{server.WARNING_MARKER}{warning}]" in answer
    assert i18n.t("mcp.explain.occurrences", name="summarizable", lines=str(line)) in answer


def test_a_real_answer_gets_no_warning(backend, tmp_path):
    """Control: an answer that answers is not flagged, even if the notes were empty."""
    state = backend[1]
    state["reduce"] = "No: `summarizable` solo mira la extensión y el tamaño."
    file, line = _file(tmp_path)
    answer = server.local_explain_code(path=str(file), question=QUESTION)
    assert i18n.t("mcp.explain.occurrences", name="summarizable", lines=str(line)) in answer
    assert "búsqueda exacta encuentra" not in answer


def test_no_information_is_not_flagged_when_the_name_is_not_in_the_file(backend, tmp_path):
    """Control: «no information» about a name the file does not hold is not a contradiction."""
    file = _file(tmp_path)[0]
    question = "¿Dónde se llama a load_protected_paths()?"
    answer = server.local_explain_code(path=str(file), question=question)
    assert answer.startswith(NO_INFO)
    assert "búsqueda exacta encuentra" not in answer
    assert i18n.t("mcp.explain.occurrences_none", name="load_protected_paths") in answer


def test_the_inline_code_gets_no_hint(backend, tmp_path):
    """Without `path` there are no line numbers: no hint, no exact lines, no warning."""
    calls = backend[0]
    file = _file(tmp_path)[0]
    code = file.read_text(encoding="utf-8")
    answer = server.local_explain_code(code=code, question=QUESTION)
    assert all(HINT not in c["user"] and EXACT not in c["user"] for c in calls)
    assert "búsqueda exacta encuentra" not in answer


# --- Pure helpers -------------------------------------------------------------------------------


def test_piece_hits_reads_only_numbered_lines():
    piece = "10| def summarizable(p):\n11|     return summarizable_x(p)\n12| summarizable()\n"
    assert line_check.piece_hits(piece, QUESTION) == [("summarizable", [10, 12])]
    # Notes (the regroup) carry no `N| ` prefix: nothing.
    assert line_check.piece_hits("- summarizable (línea 10): mira la extensión", QUESTION) == []
    assert line_check.piece_hits(piece, "¿qué hace este fichero?") == []


@pytest.mark.parametrize(
    "text",
    [
        NO_INFO,
        "Las notas no bastan para responder.",
        NOTHING,
        "There is not enough information in the notes to answer.",
        "Nothing relevant was found.",
        "Sin información suficiente para responder.",
    ],
)
def test_claims_no_information(text):
    assert line_check.claims_no_information(text)


@pytest.mark.parametrize(
    "text",
    [
        "No: `summarizable` solo mira la extensión y el tamaño.",
        "No se puede verificar la redirección desde aquí, pero la función no consulta listas.",
        "La información de configuración se lee en la línea 12.",
    ],
)
def test_real_answers_do_not_claim_no_information(text):
    assert not line_check.claims_no_information(text)
