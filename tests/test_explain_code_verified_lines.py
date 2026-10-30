"""#460 (reopened): the line numbers of `local_explain_code` are checked by the program.

The model sees `N| line` and still cites lines off by a few: for a `focus()` called on 233, 270,
328 and 336 it answered 228/233/236/270. With `path` and a question, the answer now ends with a
warning naming the cited lines that do not contain what they are cited for, and with the exact
lines of each code identifier of the question (whole-word search over the whole file). Without
`path` or without a question, the output is the model's text byte for byte. Fake backend
(`_run_chat` doubled), no network.
"""

from __future__ import annotations

import time
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


# --- the review of #507: correct answers must not warn ---------------------------------------
#
# The first version warned on 17 of 26 correct answers (a decorator above the `def`, the `if`
# that opens a block, «port: 9393», «línea 4, 2 veces»...). A warning that almost always shows
# gets ignored. These are the reviewer's 26 correct answers and 5 real errors; the goal is at
# most 2 false warnings and the 5 errors caught.

TS = """import { Component } from '@angular/core';

@Component({ selector: 'app-dialog' })
export class DialogComponent {
  @HostListener('keydown', ['$event'])
  onKeyDown(event: KeyboardEvent) {
    if (event.key === 'Tab') {
      this.trapFocus(event);
    }
  }

  // move focus to the first element
  private trapFocus(event: KeyboardEvent) {
    const el = this.first;
    el.focus();
  }

  open() {
    const msg = "focus is restored on close";
    this.lastActive = document.activeElement;
    setTimeout(() => {
      this.first.focus();
    }, 0);
  }
}
"""
PY = """import functools

@functools.lru_cache
def load_config(path):
    return read(path)

class Server:
    def __init__(self, port=9393):
        self.port = port

    @property
    def url(self):
        return f"http://localhost:{self.port}"

    def handle(self, request):
        if request.status == 404:
            return None
        return self.dispatch(request)
"""

# (question, answer, file, the citations it warns about)
CORRECT = [
    ("¿Dónde se define `load_config`?", "`load_config` se define en la línea 3 (con su decorador) y lee el fichero.", PY, []),
    ("¿Qué hace `onKeyDown`?", "`onKeyDown` está en la línea 5, registrado con @HostListener para keydown.", TS, []),
    ("¿Qué hace `onKeyDown`?", "El manejador ocupa las líneas 6-10 y llama a trapFocus si la tecla es Tab.", TS, []),
    ("¿Dónde se llama `trapFocus`?", "Dentro del if de la línea 7 se llama a trapFocus.", TS, []),
    ("¿Dónde se mueve el foco en `trapFocus`?", "El comentario de la línea 12 explica que se mueve el foco al primer elemento.", TS, []),
    ("¿Qué hace `open()`?", "En la línea 19 se define un mensaje que dice que el foco se restaura al cerrar.", TS, []),
    ("¿Dónde se llama `focus()`?", "Se llama a this.first.focus() en la línea 22 y a el.focus() en la línea 15.", TS, []),
    ("¿Qué evento escucha `onKeyDown`?", "Escucha el evento keydown, registrado en la línea 5.", TS, []),
    ("¿Qué hace `handle`?", "`handle` recibe 1 parámetro; tiene 3 ramas. Devuelve None con HTTP 404 (línea 16).", PY, []),
    ("¿Qué puerto usa `Server`?", "Usa el puerto 9393 por defecto (línea 8).", PY, []),
    ("¿Qué hace `load_config`?", "Desde la versión 1.2.3, `load_config` (línea 4) cachea; probado a las 12:30.", PY, []),
    ("¿Qué hace `handle`?", "Paso 1: comprueba el status. Paso 2: llama a dispatch en la línea 18.", PY, []),
    ("¿Dónde está `handle`?", "handle: 15", PY, []),
    # The one false warning left: 18 holds `dispatch`, and the answer says «despacha».
    ("¿Qué hace `handle`?", "`handle` (líneas 15, 16 y 18) despacha la petición.", PY, ["18"]),
    ("¿Qué devuelve `url`?", "La propiedad url (línea 11, decorador @property) devuelve la URL.", PY, []),
    ("¿Dónde está `trapFocus`?", "trapFocus está en la línea 12 justo tras el comentario.", TS, []),
    ("¿Dónde está `trapFocus`?", "Ver L13-L16 para trapFocus.", TS, []),
    ("¿cómo maneja el teclado?", "El teclado se maneja en onKeyDown (línea 6).", TS, []),
    ("¿Qué hace `self.port`?", "El puerto se guarda en la línea 9 como atributo.", PY, []),
    ("¿Dónde está `dispatch`?", "18| return self.dispatch(request)", PY, []),
    ("¿Qué hace `__init__`?", "El constructor (línea 8) guarda el puerto.", PY, []),
    ("¿Qué puerto usa `port`?", "`port`: 9393 por defecto.", PY, []),
    ("¿Qué hace `load_config`?", "`load_config` lee de example.com:8080 en la línea 4.", PY, []),
    ("¿Qué hace `load_config`?", "`load_config` está en la línea 4, 2 veces se llama.", PY, []),
    ("¿Qué hace `load_config`?", "`load_config` está en la línea 4 y 3 módulos lo usan.", PY, []),
    ("¿Qué hace `handle`?", "`handle` cambió el 1/2/3 (línea 15).", PY, []),
]  # fmt: skip
WRONG = [
    ("¿Dónde está `handle`?", "`handle` está en la línea 12.", PY, ["12"]),
    ("¿Dónde se llama `trapFocus`?", "Se llama a trapFocus en la línea 3.", TS, ["3"]),
    ("¿Dónde se llama `dispatch`?", "Se llama en la línea 5.", PY, ["5"]),
    ("¿Qué hace `open()`?", "`open()` se define en la línea 24.", TS, ["24"]),
    ("¿Qué devuelve `url`?", "url en la línea 99.", PY, ["99"]),
]  # fmt: skip


def _warned(question: str, answer_text: str, content: str, truncated: bool = False) -> list[str]:
    result = line_check.check(answer_text, question, content, truncated)
    return [c.label() for c in result.mismatched]


@pytest.mark.parametrize(("question", "answer_text", "content", "expected"), CORRECT + WRONG)
def test_the_review_cases(question, answer_text, content, expected):
    """Each adjustment of the review has a mutant that makes some of these fall (see the PR)."""
    assert _warned(question, answer_text, content) == expected


def test_at_most_two_false_warnings_and_every_real_error():
    false_warnings = sum(bool(_warned(q, a, c)) for q, a, c, _ in CORRECT)
    caught = sum(bool(_warned(q, a, c)) for q, a, c, _ in WRONG)
    assert len(CORRECT) == 26 and len(WRONG) == 5  # guard: the reviewer's whole set
    assert false_warnings <= 2
    assert caught == 5


def test_a_cited_number_does_not_confirm_itself():
    """The answer's own «228» is not a word that confirms line 228, even if the line says 228.
    Mutant «cited numbers count as words»: it stops warning."""
    content = "".join(f"value = value + {n}; // paso {n}\n" for n in range(1, 301))
    text = "`focus()` en la línea 228 según el modelo"
    assert _warned("¿Dónde se llama `focus()`?", text, content) == ["228"]


def test_the_citation_keyword_does_not_confirm_a_citation():
    """«line» in the answer is the citation, not something it names: a `// line 12` comment does
    not make «focus() at line 12» right. Mutant «the keyword counts as a word»: no warning."""
    content = "".join(f"value = {n}  # line {n}\n" for n in range(1, 31)) + "focus()\n"
    assert _warned("Where is `focus()` called?", "`focus()` is called at line 12", content) == [
        "12"
    ]


def test_a_truncated_answer_does_not_check_its_last_line():
    """Mutant «ignore `truncated`»: the cut «línea 2» of the last line warns."""
    text = "`handle` en la línea 15.\n`handle` también en la línea 2"
    assert _warned("¿`handle`?", text, PY, truncated=True) == []
    assert _warned("¿`handle`?", text, PY) == ["2"]  # guard: untruncated, it does warn


def test_a_truncated_answer_reaches_the_check_from_the_tool(answer, tmp_path, monkeypatch):
    """`finish_reason: length` reaches `check` as `truncated` (mutant «pass False»: warns)."""
    source = tmp_path / "server.py"
    source.write_text(PY, encoding="utf-8")

    def run_chat(model, system, user, max_tokens, temperature, **_):
        text = "`handle` en la línea 15.\n`handle` en la línea 2"
        result = server.ChatResult(text=text, ok=True, finish_reason="length")
        return result, 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    result = server.local_explain_code(path=str(source), question="¿Dónde está `handle`?")
    assert i18n.t("mcp.explain.occurrences", name="handle", lines="15") in result  # guard
    assert i18n.t("mcp.explain.lines_unverified", lines="2") not in result


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("¿Qué importa `App.tsx`?", []),
        ("¿Qué scripts tiene `package.json`?", []),
        ("¿Qué hace `self.port`?", ["port"]),
    ],
)
def test_a_backticked_file_name_is_not_an_identifier(question, expected):
    """Mutant «keep the last part of a file name»: `tsx`/`json` come back."""
    assert line_check.identifiers(question) == expected


def test_the_colon_form_is_linear():
    """Without the lookbehind, a 32 000-letter word with no colon took 21 s (each letter retried
    the word); 16 000 take ~5 s that way and ~1 ms with it."""
    text = "a" * 16_000
    start = time.perf_counter()
    line_check.citations(text, ["focus"], total_lines=365)
    assert time.perf_counter() - start < 1.0
