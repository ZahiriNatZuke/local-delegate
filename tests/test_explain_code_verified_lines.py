"""#460 (reopened): the line numbers of `local_explain_code` are checked by the program.

The model sees `N| line` and still cites lines off by a few: for a `focus()` called on 233, 270,
328 and 336 it answered 228/233/236/270. With `path` and a question, the answer now ends with a
warning naming the cited lines that do not contain what they are cited for, and with the exact
lines of each code identifier of the question (whole-word search over the whole file). Without
`path` or without a question, the output is the model's text byte for byte. Fake backend
(`_run_chat` doubled), no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from local_delegate import config, i18n, line_check, server

FOCUS_LINES = (233, 270, 328, 336)
HANDLERS = {231: "onKeydown", 268: "onOpen", 326: "onClick", 334: "onBlur"}
ISSUE_ANSWER = (
    "`focus()` pone el foco en el campo de texto. Se llama desde `onKeydown` (línea 228), "
    "`onOpen` (línea 233), `onClick` (línea 236) y `onBlur` (línea 270)."
)
QUESTION = "¿Qué hace focus() y desde qué handlers se llama? Devuelve los números de línea."


def _component(total: int = 365) -> str:
    """A TypeScript component of `total` lines: `this.focus()` only on FOCUS_LINES."""
    rows = []
    for n in range(1, total + 1):
        if n in FOCUS_LINES:
            rows.append("    this.focus();")
        elif n in HANDLERS:
            rows.append(f"  {HANDLERS[n]}(event: Event): void {{")
        else:
            rows.append(f"    value = value + {n}; // paso {n}")
    return "\n".join(rows) + "\n"


@pytest.fixture
def answer(monkeypatch, tmp_path) -> dict:
    """The fake backend answers `state["text"]` to every call."""
    state = {"text": ISSUE_ANSWER, "calls": 0}

    def run_chat(model, system, user, max_tokens, temperature, **_):
        state["calls"] += 1
        result = server.ChatResult(text=state["text"], ok=True, finish_reason="stop")
        return result, 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    monkeypatch.delenv("LOCAL_DELEGATE_OUTPUT_LANGUAGE", raising=False)
    i18n.reset()
    return state


@pytest.fixture
def component(tmp_path: Path) -> Path:
    source = tmp_path / "dialog.component.ts"
    source.write_text(_component(), encoding="utf-8")
    return source


def _extra(result: str, text: str) -> str:
    assert result.startswith(text.rstrip())  # the prose is not rewritten
    return result[len(text.rstrip()) :]


def test_the_issue_case_flags_228_and_236_and_lists_the_real_lines(answer, component):
    """Mutant «every citation verifies»: the `lines_unverified` assert falls.
    Mutant «no occurrences line»: the `occurrences` assert falls."""
    result = server.local_explain_code(path=str(component), question=QUESTION)
    extra = _extra(result, ISSUE_ANSWER)
    warning = i18n.t("mcp.explain.lines_unverified", lines="228, 236")
    assert f"{server.WARNING_MARKER}{warning}]" in extra
    assert i18n.t("mcp.explain.occurrences", name="focus", lines="233, 270, 328, 336") in extra
    assert answer["calls"] == 1  # guard: one chunk, as in the issue


def test_a_range_counts_as_verified_when_the_identifier_falls_inside(answer, component):
    """Mutant «a range checks only its first line»: 230-235 starts on a line without `focus`."""
    answer["text"] = "`focus()` se llama en las líneas 230-235 y en las líneas 100-110."
    result = server.local_explain_code(path=str(component), question=QUESTION)
    warning = i18n.t("mcp.explain.lines_unverified", lines="100-110")
    assert f"{server.WARNING_MARKER}{warning}]" in _extra(result, answer["text"])


def test_without_path_the_output_is_the_model_text_byte_for_byte(answer, component):
    """Mutant «verify without `path` too»: the equality falls."""
    code = component.read_text(encoding="utf-8")
    result = server.local_explain_code(code=code, question=QUESTION)
    assert result == ISSUE_ANSWER


def test_without_a_question_the_output_is_the_model_text_byte_for_byte(answer, component):
    """Mutant «verify without a question too»: the equality falls."""
    answer["text"] = "- `onKeydown` (línea 228): gestiona el teclado.\n- `onBlur` (línea 334)."
    result = server.local_explain_code(path=str(component))
    assert result == answer["text"]


def test_short_or_common_identifiers_add_nothing(answer, component):
    """Mutant «MIN_IDENTIFIER_LEN = 1» or «no common words»: `i`/`this` get a line."""
    answer["text"] = "La variable `i` cuenta las vueltas y `this` es el componente."
    result = server.local_explain_code(
        path=str(component),
        question="¿Qué hace `i`, qué es `this()` y para qué sirven los handlers?",
    )
    assert result == answer["text"]


def test_a_chunked_file_is_checked_once_at_the_end_against_the_whole_file(answer, tmp_path):
    """#505's path: the reduce answers the question; the check goes after it, on the whole file."""
    code = _component(total=4_000)
    assert len(code) > config.max_chars_for_role("code")
    source = tmp_path / "big.component.ts"
    source.write_text(code, encoding="utf-8")
    result = server.local_explain_code(path=str(source), question=QUESTION)
    assert answer["calls"] > 2  # guard: it chunked
    line = i18n.t("mcp.explain.occurrences", name="focus", lines="233, 270, 328, 336")
    assert result.count(line) == 1
    assert result.rstrip().endswith(line)


def test_occurrences_are_capped_with_a_count_of_the_rest(answer, tmp_path):
    source = tmp_path / "many.py"
    source.write_text("".join("fooBar()\n" for _ in range(25)), encoding="utf-8")
    answer["text"] = "Se llama muchas veces."
    result = server.local_explain_code(path=str(source), question="¿Dónde se llama `fooBar`?")
    shown = ", ".join(str(n) for n in range(1, 21)) + i18n.t(
        "mcp.explain.occurrences_more", count=5
    )
    assert i18n.t("mcp.explain.occurrences", name="fooBar", lines=shown) in result


def test_an_identifier_that_is_not_in_the_file_says_so(answer, component):
    answer["text"] = "`openDialog()` no aparece."
    result = server.local_explain_code(path=str(component), question="¿Dónde está openDialog()?")
    assert i18n.t("mcp.explain.occurrences_none", name="openDialog") in result


def test_the_lines_come_in_english_too(answer, component, monkeypatch):
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    i18n.reset()
    result = server.local_explain_code(path=str(component), question=QUESTION)
    assert "Occurrences of `focus` in the file (exact search): 233, 270, 328, 336" in result


# --- the pure functions -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (QUESTION, ["focus"]),
        ("¿Dónde se usa `this.dialogRef.close` y fooBar?", ["close", "dialogRef", "fooBar"]),
        ("¿Qué hace load_config o `Dialog`?", ["Dialog", "load_config"]),
        # Plain words of the language never count, nor short or common identifiers.
        ("¿Qué hacen los handlers y the x?", []),
        ("¿Qué hace `i`, `id` o `this`? ¿Y return()?", []),
    ],
)
def test_identifiers_keep_only_code_like_words(text, expected):
    """Mutant «any word counts»: «handlers»/«the» appear in the empty cases."""
    assert sorted(line_check.identifiers(text)) == sorted(expected)


@pytest.mark.parametrize(
    ("answer_text", "expected"),
    [
        ("`focus()` en las líneas 228, 233 y 236.", [(228, 228), (233, 233), (236, 236)]),
        ("focus en lineas 228/233/236/270", [(228, 228), (233, 233), (236, 236), (270, 270)]),
        ("focus() at line 233 and lines 120-130", [(233, 233), (120, 130)]),
        ("focus() está en L233 y en L120-L130.", [(233, 233), (120, 130)]),
        ("focus: 233", [(233, 233)]),
        ("ver dialog.ts:233", [(233, 233)]),
        ("233| this.focus();", [(233, 233)]),
        ("`focus()` 228/233/236/270", [(228, 228), (233, 233), (236, 236), (270, 270)]),
        # Not citations: a plain word before the colon, a date.
        ("`focus()` Nota: 3 llamadas el 30/10/2026.", []),
    ],
)
def test_citation_forms(answer_text, expected):
    found = line_check.citations(answer_text, ["focus"], total_lines=365)
    assert [(c.start, c.end) for c in found] == expected


def test_a_citation_with_nothing_to_check_against_is_left_out():
    assert line_check.citations("Se llama en la línea 12.", [], total_lines=365) == []
