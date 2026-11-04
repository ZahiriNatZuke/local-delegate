"""Estructura de un documento Markdown para `local_summarize` (SDD `resumen-por-secciones`).

Por qué existe: en el piloto de T5 del SDD `subagente-lector-local`, Claude pidió resúmenes de
450–600 palabras y la tool nombró entre el 0 % y el 27 % de los títulos del documento. El prompt
pedía «prosa clara» y el modelo aplanaba la estructura; Claude, sin saber qué secciones había,
volvía a leer el fichero. Aquí vive todo lo que no le pedimos al modelo porque se puede calcular:

- **detectar** las secciones (títulos ATX y setext, fuera de bloques de código y del front matter);
- **emparejar** la salida del modelo con los títulos esperados y **completar** los que falten, para
  que «no omite ninguna» no dependa de que el modelo obedezca;
- **trocear** un documento largo por esas secciones, sin cortar dentro de una valla de código.

Todo es puro (sin red ni disco): lo prueban `tests/test_structured_summary.py` y lo usa también
`scripts/measure_structured_summary.py`, que mide con estas mismas funciones.
"""

from __future__ import annotations

import functools
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import pairwise

from . import i18n

# --- Detección -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Heading:
    text: str
    level: int
    start: int  # posición del primer carácter de la línea del título en el texto analizado


@dataclass(frozen=True)
class Structure:
    level: int
    headings: tuple[Heading, ...]

    @property
    def texts(self) -> list[str]:
        return [t.text for t in self.headings]


_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_ATX_CLOSING = re.compile(r"(?:^|[ \t]+)#+[ \t]*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def _lines(text: str) -> list[tuple[int, str]]:
    """(posición, línea sin su salto). Acepta `\\n` y `\\r\\n` sin cambiar las posiciones."""
    out: list[tuple[int, str]] = []
    pos = 0
    for line in text.splitlines(keepends=True):
        out.append((pos, line.rstrip("\r\n")))
        pos += len(line)
    return out


def _is_paragraph(line: str) -> bool:
    """¿Puede esta línea ser el texto de un título setext?"""
    if not line.strip():
        return False
    if _ATX.match(line) or _SETEXT.match(line) or _FENCE.match(line):
        return False
    if _LIST_ITEM.match(line) or line.lstrip().startswith(("|", ">")):
        return False
    return not line.startswith(("    ", "\t"))  # bloque de código indentado


def markdown_headings(text: str) -> list[Heading]:
    """Todos los títulos del documento, en orden, sin los de dentro de vallas ni front matter."""
    lines = _lines(text)
    headings: list[Heading] = []
    i = 0
    # Front matter YAML: `---` en la primera línea hasta el siguiente `---` o `...`. Si no se
    # cierra, no es front matter y se analiza como texto.
    if lines and lines[0][1].strip() == "---":
        for j in range(1, len(lines)):
            if lines[j][1].strip() in {"---", "..."}:
                i = j + 1
                break
    fence: str | None = None
    previous: tuple[int, str] | None = None  # línea previa candidata a texto de un setext
    while i < len(lines):
        pos, line = lines[i]
        i += 1
        if fence is not None:
            closing = _FENCE.match(line)
            if (
                closing
                and closing.group(1)[0] == fence[0]
                and len(closing.group(1)) >= len(fence)
                and not line.strip().strip(fence[0])
            ):
                fence = None
            continue
        opening = _FENCE.match(line)
        if opening:
            fence = opening.group(1)
            previous = None
            continue
        atx = _ATX.match(line)
        if atx:
            heading_text = _ATX_CLOSING.sub("", atx.group(2) or "").strip()
            if heading_text:
                headings.append(Heading(heading_text, len(atx.group(1)), pos))
            previous = None
            continue
        setext = _SETEXT.match(line)
        if setext and previous is not None:
            level = 1 if setext.group(1)[0] == "=" else 2
            headings.append(Heading(previous[1].strip(), level, previous[0]))
            previous = None
            continue
        # Solo la ÚLTIMA línea de un párrafo puede ser el texto de un setext: una línea en
        # blanco rompe la candidatura, y por eso `---` tras una línea vacía es una regla.
        previous = (pos, line) if _is_paragraph(line) else None
    return headings


# #499: the hunk header every unified diff carries (`@@@` with two `-` ranges in a combined diff),
# and the first lines that open a patch.
_HUNK = re.compile(r"^(@@@?) (?:-\d+(?:,\d+)? )+\+\d+(?:,\d+)? \1", re.MULTILINE)
_GIT_DIFF = re.compile(r"^diff --(?:git|cc|combined) ")
_GIT_COMMIT = re.compile(r"^commit [0-9a-f]{40}\b")  # `git show`, `git log -p`
_FORMAT_PATCH = re.compile(r"^From [0-9a-f]{40} ")  # `git format-patch`
_SVN_INDEX = re.compile(r"^Index: \S+$")
_SVN_RULE = re.compile(r"^=+$")


def _opens_a_patch(lines: list[str]) -> bool:
    """¿Abren estas líneas (sin las vacías del principio) un parche? Cada forma exige su pareja.

    Sin la pareja, una primera línea suelta (`--- draft ---`, `Index: list of topics`, prosa que
    empieza por `diff -`) bastaba para que un Markdown con un hunk en una valla perdiera sus
    secciones.
    """
    first = lines[0]
    second = lines[1] if len(lines) > 1 else ""
    if _GIT_DIFF.match(first) or _FORMAT_PATCH.match(first):
        return True
    if _GIT_COMMIT.match(first):
        return any(_GIT_DIFF.match(line) for line in lines)
    if first.startswith("--- "):
        return second.startswith("+++ ")
    if _SVN_INDEX.match(first):
        return bool(_SVN_RULE.match(second))
    if first.startswith("diff -"):  # `diff -u`, `diff -ru`
        return second.startswith("--- ")
    return False


def is_unified_diff(text: str) -> bool:
    """¿Es el texto un diff unificado? Empieza por una cabecera de parche y trae algún hunk `@@`.

    Se mira el PRINCIPIO, no cualquier línea: un Markdown que enseña un diff dentro de una valla
    sigue siendo un documento con sus títulos. Se saltan el BOM, las líneas vacías y las
    `Only in …` con que `diff -r` abre a veces su salida.
    """
    lines = [line.rstrip("\r") for line in text.lstrip("\ufeff").splitlines()]
    lines = [line for line in lines if line.strip()]
    while lines and lines[0].startswith("Only in "):
        lines.pop(0)
    return bool(lines) and _opens_a_patch(lines) and _HUNK.search(text) is not None


def detect(text: str) -> Structure | None:
    """Nivel estructural (el más alto con al menos dos títulos) y sus títulos, o None.

    Un diff unificado no tiene estructura de documento (#499): sus líneas de contexto de un
    `.md` (` ## [0.46.0]`, con un espacio delante) parecían títulos, y el resumen estructurado
    metía los hunks de los ficheros siguientes dentro de esa «sección».
    """
    if is_unified_diff(text):
        return None
    headings = markdown_headings(text)
    for level in range(1, 7):
        at_level = tuple(t for t in headings if t.level == level)
        if len(at_level) >= 2:
            return Structure(level, at_level)
    return None


# --- Lines that are data, not structure (#539) ----------------------------------------------------
#
# A code file that builds a Markdown document inside a string literal (a JS template literal, a
# Python triple-quoted string) carries lines that look like headings and are data. When the model
# turns one of them into a heading of the summary, the structure of the summary comes from a test
# fixture. These helpers find those lines so the server can say so.

_INTERPOLATION = re.compile(r"\$\{[^}\n]*\}")
_TRIPLE_QUOTES = ('"""', "'''")
#: What may come right before a string literal that is DATA: an assignment, an argument, an
#: element, a concatenation, a ternary branch or `return`. In Markdown prose a backtick follows a
#: word and a space (`use \`x\``), so a stray one never opens a literal there; and a Python
#: docstring (a triple-quoted string alone at the start of a statement) is documentation of the
#: code, whose sections a summary may well use as its own.
_LITERAL_OPENERS = ("=", "(", ",", ":", "[", "{", "+", "?", "return", "=>")
_OPENER_WINDOW = max(len(o) for o in _LITERAL_OPENERS)
#: Where the scanner has to stop in each state; everything in between is skipped by the regex, so
#: the scan is linear in the size of the text.
_NEXT_IN_CODE = re.compile(r"[\n`'\"#/]")
_NEXT_IN_STRING = {
    "`": re.compile(r"[\n\\`]"),
    "'": re.compile(r"[\n\\']"),
    '"': re.compile(r'[\n\\"]'),
    '"""': re.compile(r'[\n\\]|"""'),
    "'''": re.compile(r"[\n\\]|'''"),
}
_MULTILINE = frozenset({"`", *_TRIPLE_QUOTES})


def _opens_literal(text: str, line_start: int, at: int, *, alone: bool = True) -> bool:
    """Is the literal that starts at `at` data, by what comes before it on its line?

    `alone` is the answer when nothing but blanks precedes it: a template that continues an
    assignment from the line above, yes; a triple-quoted string that opens a statement, no (a
    docstring). Only the last non-blank characters are looked at (a fixed window), so a line full
    of literals is still scanned in linear time (#539 review: copying the line up to each
    backtick made a 2.4 MB one-line input take 73 s).
    """
    end = at
    while end > line_start and text[end - 1] in " \t":
        end -= 1
    if end == line_start:
        return alone
    return text[max(line_start, end - _OPENER_WINDOW) : end].endswith(_LITERAL_OPENERS)


def _literal_lines(text: str, *, prose: bool = False) -> list[tuple[int, str]]:
    """(position, line) of each line covered by a multi-line string literal that is data.

    A light scanner, not a parser: single and double quotes and comments close at the end of the
    line, a backslash escapes the next character inside a string, a run of two or more backticks
    (a Markdown fence or double-backtick code) is not a template delimiter, and a literal counts
    only after an opener (`_opens_literal`), so docstrings and stray prose backticks do not. Only
    the lines the literal covers from start to end count (not the line that opens it nor the one
    that closes it), so the code around the literal is never taken for its content.

    With `prose` (a Markdown or text file) a literal never crosses a line outside a fenced block:
    an unclosed `` `x `` in a paragraph does not swallow the headings below it.
    """
    inside: list[tuple[int, str]] = []
    state: str | None = None  # "`", '"""', "'''", "'", '"' or "comment"
    counted = False  # does the open multi-line literal count as data?
    in_fence = False  # prose only: inside a ``` block
    i, n = 0, len(text)
    line_start = 0
    line_opened_inside = False
    while i < n:
        if state == "comment":
            found = text.find("\n", i)
            i = n if found < 0 else found
            if i == n:
                break
        elif state is None:
            m = _NEXT_IN_CODE.search(text, i)
            if m is None:
                break
            i = m.start()
        else:
            m = _NEXT_IN_STRING[state].search(text, i)
            if m is None:
                break
            i = m.start()
        c = text[i]
        if c == "\n":
            if line_opened_inside and state in _MULTILINE and counted:
                inside.append((line_start, text[line_start:i].rstrip("\r")))
            if state in {"'", '"', "comment"} or (prose and state in _MULTILINE and not in_fence):
                state = None
            i += 1
            line_start = i
            line_opened_inside = state in _MULTILINE
            continue
        if state is not None:
            if c == "\\":
                # The escaped character is skipped, but never a line break: the line still ends.
                i += 1 if text.startswith("\n", i + 1) else 2
            elif state in _TRIPLE_QUOTES:
                state = None
                i += 3
            else:  # closes "`", "'" or '"'
                state = None
                i += 1
            continue
        if text.startswith(_TRIPLE_QUOTES, i):
            counted = _opens_literal(text, line_start, i, alone=False)
            state = text[i : i + 3]
            i += 3
        elif c == "`":
            run = i
            while run < n and text[run] == "`":
                run += 1
            if run - i >= 2:  # a fence, or an empty template / Markdown double-backtick code
                if run - i >= 3 and _opens_literal(text, line_start, i):
                    in_fence = not in_fence
                i = run
                continue
            counted = _opens_literal(text, line_start, i)
            if counted or not prose:
                state = "`"
            i += 1
        elif c in "'\"":
            state = c
            i += 1
        elif c == "#" or text.startswith("//", i):
            state = "comment"
            i += 1
        else:  # a lone `/`
            i += 1
    return inside


def string_literal_lines(text: str, *, prose: bool = False) -> list[str]:
    """The lines that lie inside a multi-line string literal that is data (`_literal_lines`)."""
    return [line for _pos, line in _literal_lines(text, prose=prose)]


def _source_heading_text(line: str) -> str:
    """The comparable form of a source line, without the `#`s of an ATX heading."""
    atx = _ATX.match(line)
    if atx:
        return normalize_heading(_ATX_CLOSING.sub("", atx.group(2) or ""))
    return normalize_heading(line)


def string_literal_headings(output: str, source: str, *, kind: str = "unknown") -> list[str]:
    """Headings of `output` that copy a line of a string literal of `source`, in output order.

    `kind` is what the source is, by the extension of its file: "code", "prose" (Markdown, text)
    or "unknown" (inline text, another extension). A heading counts when its normalized text
    equals the normalized text of a line inside a multi-line string literal (`_literal_lines`).
    Outside a code file, a heading the document also has as a real heading (outside any literal)
    does not count: a `## Usage` in a fenced example does not make the document's own `## Usage`
    data. In a code file a heading with an unresolved `${...}` that appears verbatim in the source
    counts too: that interpolation only exists inside a template. Headings are returned as the
    model wrote them, once each.
    """
    code_file = kind == "code"
    covered = _literal_lines(source, prose=kind == "prose")
    literal = {_source_heading_text(line) for _pos, line in covered}
    literal.discard("")
    if not code_file and literal:
        in_literal = {pos for pos, _line in covered}
        literal -= {
            normalize_heading(h.text)
            for h in markdown_headings(source)
            if h.start not in in_literal
        }
    found: list[str] = []
    lines = output.split("\n")
    for index, normalized in heading_lines(output):
        raw = lines[index].strip().lstrip("#").strip().strip("*_").rstrip(":").strip()
        copied = normalized in literal or (
            code_file and _INTERPOLATION.search(raw) is not None and raw in source
        )
        if copied and raw not in found:
            found.append(raw)
    return found


# --- Normalización y emparejamiento --------------------------------------------------------------

_NUMBERING = re.compile(r"^\s*(?:\d+|[ivxlc]+)[.)]\s+", re.IGNORECASE)
_OUTPUT_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_OUTPUT_BOLD = re.compile(r"^\s*(\*\*|__)(.+?)\1\s*:?\s*$")


def normalize_heading(text: str) -> str:
    """La forma comparable de un título: sin tildes, mayúsculas, signos ni numeración inicial."""
    unmarked = "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )
    unnumbered = _NUMBERING.sub("", unmarked.lower())
    return " ".join(re.sub(r"[\W_]+", " ", unnumbered).split())


def _matches(expected: str, candidate: str) -> bool:
    """Igual, o la candidata empieza por el esperado y sigue una palabra nueva."""
    return bool(expected) and (candidate == expected or candidate.startswith(expected + " "))


def heading_lines(output: str) -> list[tuple[int, str]]:
    """(índice de línea, texto normalizado) de cada línea de título de una salida del modelo."""
    found: list[tuple[int, str]] = []
    for index, line in enumerate(output.split("\n")):
        m = _OUTPUT_HEADING.match(line) or _OUTPUT_BOLD.match(line)
        if m:
            found.append((index, normalize_heading(m.group(m.lastindex or 1))))
    return found


@dataclass
class Matching:
    """Resultado de emparejar la salida con los títulos esperados (índices sobre esperados)."""

    pairs: dict[int, int] = field(default_factory=dict)  # esperado -> índice de línea
    missing: list[int] = field(default_factory=list)
    out_of_order: list[int] = field(default_factory=list)
    empty: list[int] = field(default_factory=list)
    # Expected index -> line index of a heading the model wrote in another language (also in
    # `pairs`). Only filled with `positional=True` (B2d-fix).
    translated: dict[int, int] = field(default_factory=dict)


def _words(text: str) -> int:
    return len(re.findall(r"\w+", text))


_ATX_LEVEL = re.compile(r"^\s{0,3}(#{1,6})\s")


def _pair_translated(output: str, expected: list[str], result: Matching) -> None:
    """Pairs a missing heading with the one the model wrote in its slot in another language.

    The prompt asks for every heading verbatim, but with a response language different from the
    document's the model sometimes translates one ("Introducción" -> "Introduction"). Text
    matching then sees an expected heading missing and an unknown one, and `complete` inserted the
    expected one again: the section came out twice, once summarized and once "(not summarized)"
    (live sample of B2d). The rescue is positional and narrow, so a heading the model invented is
    not taken for a section: between the same two paired neighbours there must be exactly ONE
    missing expected heading and exactly ONE unpaired ATX line, at the level of the paired ones
    (2 when nothing paired), that matches no expected heading. Bold lines never count.
    """
    lines = output.split("\n")
    normalized = [normalize_heading(e) for e in expected]
    level_of: dict[int, int] = {}
    for index, line in enumerate(lines):
        m = _ATX_LEVEL.match(line)
        if m:
            level_of[index] = len(m.group(1))
    paired_levels = {level_of[line] for line in result.pairs.values() if line in level_of}
    levels = paired_levels or {2}
    used = set(result.pairs.values())
    free = [
        (index, text)
        for index, text in heading_lines(output)
        if index not in used
        and level_of.get(index) in levels
        and not any(_matches(n, text) for n in normalized)
    ]
    for k in list(result.missing):
        before = max((line for e, line in result.pairs.items() if e < k), default=-1)
        after = min((line for e, line in result.pairs.items() if e > k), default=len(lines))
        low = max((e for e in result.pairs if e < k), default=-1)
        high = min((e for e in result.pairs if e > k), default=len(expected))
        missing_here = [e for e in result.missing if low < e < high]
        candidates = [index for index, _text in free if before < index < after]
        if missing_here == [k] and len(candidates) == 1:
            result.pairs[k] = result.translated[k] = candidates[0]
            result.missing.remove(k)


def match_headings(
    output: str, expected: list[str], *, min_content: int = 3, positional: bool = False
) -> Matching:
    """Subsecuencia común más larga entre los títulos esperados y las líneas de título.

    Uno a uno y en orden: un título duplicado necesita dos apariciones, y una mención en la prosa
    no cuenta. Un esperado sin pareja que sí aparece en una línea de título libre está **fuera de
    orden** (existe, pero no donde tocaba); si no aparece en ninguna, **falta**. Una sección
    emparejada es **vacía** si tiene menos de `min_content` palabras hasta la siguiente
    línea emparejada: los subtítulos y negritas que el modelo pone dentro cuentan como contenido.

    With `positional=True` (what `complete` uses) a missing heading is also paired with the one
    the model translated in its slot (`_pair_translated`). The measurement script keeps the
    default: it measures text matching, as when its baseline was frozen.
    """
    normalized = [normalize_heading(e) for e in expected]
    candidates = heading_lines(output)
    n, m = len(normalized), len(candidates)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if _matches(normalized[i], candidates[j][1]):
                table[i][j] = table[i + 1][j + 1] + 1
            else:
                table[i][j] = max(table[i + 1][j], table[i][j + 1])
    result = Matching()
    used: set[int] = set()
    i = j = 0
    while i < n and j < m:
        if _matches(normalized[i], candidates[j][1]) and table[i][j] == table[i + 1][j + 1] + 1:
            result.pairs[i] = candidates[j][0]
            used.add(j)
            i += 1
            j += 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1
    unused = [c for k, c in enumerate(candidates) if k not in used]
    for k in range(n):
        if k in result.pairs:
            continue
        if any(_matches(normalized[k], c[1]) for c in unused):
            result.out_of_order.append(k)
        else:
            result.missing.append(k)
    if positional:
        _pair_translated(output, expected, result)
    lines = output.split("\n")
    order = sorted(result.pairs.items(), key=lambda par: par[1])
    for pos, (k, line) in enumerate(order):
        end = order[pos + 1][1] if pos + 1 < len(order) else len(lines)
        body = "\n".join(lines[line + 1 : end])
        if _words(body) < min_content:
            result.empty.append(k)
    return result


# --- Completitud ---------------------------------------------------------------------------------


def not_summarized() -> str:
    """El texto que va bajo el título de una sección que el modelo no resumió, en el idioma vigente."""
    return i18n.t("mcp.sections.not_summarized")


#: Sus dos formas, para quien lee salidas ya escritas en cualquiera de los dos idiomas (REQ-033).
NOT_SUMMARIZED_FORMS = frozenset(
    i18n.t_lang(language, "mcp.sections.not_summarized") for language in i18n.LANGUAGES
)

#: El marcador de aviso (REQ-010, desde la 0.36.0; antes `[local-delegate aviso: `). Lo comparte
#: `server`: valor de máquina que no cambia con el idioma.
WARNING_MARKER = "[local-delegate warning: "

#: #580: the end of a sentence: terminal punctuation, the marks that may close it (a parenthesis,
#: quotes, the end of a bold or italic span), then whitespace or the end of the text. A dot followed
#: by a digit or a letter (`0.36.0`, `server.py`) is not one.
_SENTENCE_END = re.compile(r"[.!?…][)\]\"'»”*_]*(?=\s|$)")
#: #580: the line that opens or closes a fenced code block.
_FENCE_LINE = re.compile(r"(?m)^[ \t]*(?:```|~~~)")
#: #580: what precedes the dot of an ordered list marker (`1.`, `  12.`).
_LIST_NUMBER = re.compile(r"[ \t]*\d+")


def _announces(line: str) -> bool:
    """#580: a line that introduces what follows (heading, bold label, line ending in `:`)."""
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("#"):
        return True
    if stripped.startswith("**") and stripped.endswith("**"):
        return True
    return stripped.strip("*_ ").endswith(":")


def _close_structure(text: str) -> str:
    """#580: drop an unclosed code block and the lines left announcing content that never came."""
    fences = list(_FENCE_LINE.finditer(text))
    if len(fences) % 2:
        text = text[: fences[-1].start()]
    lines = text.rstrip().split("\n")
    while lines and (not lines[-1].strip() or _announces(lines[-1])):
        lines.pop()
    return "\n".join(lines).rstrip()


def trim_to_last_sentence(text: str) -> str | None:
    """#580: a cut answer up to its last complete sentence, with its Markdown left closed.

    The answer ended by `max_tokens`: every line but the last one is complete (the model wrote its
    line break), and the last one stops wherever the cap fell, often inside a word. The cut goes
    after the last sentence end of that line whose inline code and bold spans are closed, or else
    at the end of the previous line; then an unclosed code block is dropped, and so are the
    headings, bold labels and `…:` lines that would be left introducing nothing (a list whose items
    never came). `None` when there is nothing complete to keep or nothing to remove: the caller
    then returns the answer as it came.
    """
    head, newline, last = text.rpartition("\n")
    candidates = [
        head + newline + last[: m.end()]
        for m in reversed(list(_SENTENCE_END.finditer(last)))
        if last[: m.end()].count("`") % 2 == 0
        and last[: m.end()].count("**") % 2 == 0
        # The `1.` of an ordered list item is its marker, not a sentence.
        and not _LIST_NUMBER.fullmatch(last[: m.start()])
    ]
    if newline:
        candidates.append(head)
    for candidate in candidates:
        cut = _close_structure(candidate)
        if cut.strip():
            return cut if cut != text.rstrip() else None
    return None


@dataclass
class Completion:
    text: str
    missing: int
    empty: int
    out_of_order: int


def _is_cut_heading(line: str, expected: list[str]) -> bool:
    """Is this last line of a truncated output a heading cut in the middle? (B2d-2)

    Only if it is a heading line no longer than the longest expected heading: a cut heading cannot
    be longer than a whole one. Before, any line that started with `#` was dropped, and a model
    that wrote the body of a section on the same line as a `###` lost the whole body (the probable
    httpcore2 case of set 3: 2112 tokens generated, 752 chars delivered, `## Changelog` empty).
    """
    found = heading_lines(line)
    if not found:
        return False
    longest = max((len(normalize_heading(e)) for e in expected), default=0)
    return len(found[0][1]) <= longest


def complete(
    output: str,
    expected: list[str],
    *,
    truncated: bool = False,
    empty_in_document: frozenset[int] = frozenset(),
) -> Completion:
    """Inserta en su sitio los títulos que el modelo no puso, y avisa de cuántos quedaron sin resumir.

    Con `truncated` (la salida acabó por `length`), una última línea que es un título a medias
    (`_is_cut_heading`) se quita antes de emparejar, y el título entero vuelve a entrar como
    faltante.

    `empty_in_document` are the indices of the expected sections that have no content in the
    document itself (B2d-2, httpx2: `## Release Information` followed directly by `## 2.13.1`).
    The model does well leaving them empty, so they are not reported as not summarized; if the
    model left one out, its heading goes back without the "not summarized" placeholder.
    """
    lines = output.rstrip("\n").split("\n")
    if truncated and lines and _is_cut_heading(lines[-1], expected):
        lines = lines[:-1]
    text = "\n".join(lines)
    emp = match_headings(text, expected, positional=True)
    # A heading the model translated goes back to the document's wording, so it can be searched
    # in the document; its level (the `#`s) is kept.
    for k, index in emp.translated.items():
        hashes = _ATX_LEVEL.match(lines[index])
        lines[index] = f"{hashes.group(1) if hashes else '##'} {expected[k]}"
    insertions: dict[int, list[str]] = {}
    placeholder = not_summarized()
    for k in emp.missing:
        next_line = min((line for e, line in emp.pairs.items() if e > k), default=len(lines))
        body = "" if k in empty_in_document else f"\n{placeholder}"
        insertions.setdefault(next_line, []).append(f"## {expected[k]}{body}\n")
    if insertions:
        new_lines: list[str] = []
        for index in range(len(lines) + 1):
            for block in insertions.get(index, []):
                if new_lines and new_lines[-1].strip():
                    new_lines.append("")
                new_lines.extend(block.rstrip("\n").split("\n"))
                new_lines.append("")
            if index < len(lines):
                new_lines.append(lines[index])
        text = "\n".join(new_lines).rstrip("\n")
    elif emp.translated:
        text = "\n".join(lines)
    missing = [k for k in emp.missing if k not in empty_in_document]
    empty = [k for k in emp.empty if k not in empty_in_document]
    left_out = len(missing) + len(empty)
    if left_out:
        key = (
            "mcp.warning.sections_not_summarized_one"
            if left_out == 1
            else "mcp.warning.sections_not_summarized"
        )
        notice = i18n.t(key, n=left_out)
        text += f"\n\n{WARNING_MARKER}{notice}]"
    return Completion(text, len(missing), len(empty), len(emp.out_of_order))


# --- Secciones del resumen (v3: subsecciones, introducción y tamaño) -----------------------------
#
# La etapa 2 de la v2 dio 3/9: con el nivel `##` solo, un documento con subsecciones perdía justo
# esas partes (el modelo repartía el presupuesto a partes iguales y las `###` se quedaban fuera), y
# el texto anterior al primer título —la introducción— no estaba en la lista. Claude releía ambas.


def introduction() -> str:
    """El título de la sección sintética con el texto anterior al primer título.

    It is a heading the MODEL writes, not one of the document's, so it goes in the response
    language (REQ-028) when the catalog has it, and in the product language otherwise. In the
    B2d live sample it went in the product language ("Introducción") while the model was told to
    answer in English: it wrote "Introduction" and the server added "Introducción" again as not
    summarized.
    """
    response = i18n.response_language().value.lower().replace("_", "-").split("-")[0]
    if response in i18n.LANGUAGES:
        return i18n.t_lang(response, "mcp.sections.introduction")
    return i18n.t("mcp.sections.introduction")


#: Sus dos formas, para quien lee salidas o planes ya escritos (REQ-033).
INTRODUCTION_FORMS = frozenset(
    i18n.t_lang(language, "mcp.sections.introduction") for language in i18n.LANGUAGES
)
MIN_INTRO_WORDS = 20


@dataclass(frozen=True)
class Section:
    heading: str
    start: int
    end: int
    subheadings: tuple[str, ...] = ()
    synthetic: bool = False  # la «Introducción»: no es un título del documento
    # Characters of the section WITHOUT its own heading line (B2d-2); None: not measured, `size`.
    body_size: int | None = None

    @property
    def size(self) -> int:
        return self.end - self.start

    @property
    def content_size(self) -> int:
        """What the word budget is shared by: the body, without the heading (B2d-2).

        Measured with the heading, a section with nothing under it (httpx2's `## Release
        Information`) was asked for ~23 words, which invites the model to invent them.
        """
        return self.size if self.body_size is None else self.body_size

    @property
    def empty(self) -> bool:
        """The section has no content in the document itself."""
        return self.body_size == 0


def _words_outside_headings(text: str) -> int:
    return sum(_words(line) for _pos, line in _lines(text) if not _ATX.match(line))


def _body_size(text: str, start: int, end: int) -> int:
    """Characters of the span `[start, end)` after its heading line(s); 0 if it has no words.

    The heading is one line (ATX) or two (setext: the text and its underline). Subheadings do not
    count as content: a section that only holds headings has nothing to summarize of its own.
    """
    span = text[start:end]
    lines = span.splitlines(keepends=True)
    skip = 1 if lines and _ATX.match(lines[0].rstrip("\r\n")) else 2
    body = "".join(lines[skip:])
    return len(body.strip()) if _words_outside_headings(body) else 0


def _is_introduction(heading: str) -> bool:
    """Is this document heading the one the product adds, in either language? (B2d-2)"""
    return normalize_heading(heading) in {normalize_heading(f) for f in INTRODUCTION_FORMS}


def sections_for_summary(text: str, structure: Structure) -> list[Section]:
    """Las secciones que se piden al modelo, en orden, con su tramo del texto y sus subsecciones.

    Las subsecciones son los títulos del nivel siguiente al estructural que caen dentro de cada
    sección (fuera de vallas, porque salen de `markdown_headings`). La introducción es el texto
    anterior a la primera sección, si tiene contenido de verdad y no solo un título `#`.
    """
    all_headings = markdown_headings(text)
    top_level = list(structure.headings)
    next_level = [t.text for t in all_headings if t.level == structure.level + 1]
    # Si los subtítulos se repiten (menos de la mitad distintos) son categorías, no temas: el
    # CHANGELOG tiene 103 que son 5 etiquetas (`Added`, `Fixed`…). Listarlas duplicaba el
    # resumen (1124 palabras para un tope de 500) sin decir nada de cada versión.
    are_topics = len(set(next_level)) * 2 >= len(next_level)
    sections_: list[Section] = []
    first = top_level[0].start
    # B2d-2: a document with its own "Introduction" (pycparser, set 3) got the product's one too,
    # and the summary came out with that section twice. Its own one is enough.
    own_introduction = any(_is_introduction(t.text) for t in top_level)
    if not own_introduction and _words_outside_headings(text[:first]) >= MIN_INTRO_WORDS:
        sections_.append(Section(introduction(), 0, first, synthetic=True))
    for i, heading in enumerate(top_level):
        end = top_level[i + 1].start if i + 1 < len(top_level) else len(text)
        subs = tuple(
            t.text
            for t in all_headings
            if are_topics and t.level == structure.level + 1 and heading.start < t.start < end
        )
        body = _body_size(text, heading.start, end)
        sections_.append(Section(heading.text, heading.start, end, subs, body_size=body))
    return sections_


def allocate_by_size(sizes: list[int], total: int, *, minimum: int) -> list[int]:
    """Reparte `total` en proporción a `sizes`, sin pasar nunca de `total`.

    El mínimo solo se aplica si cabe para todos (`minimum × n ≤ total`); si no, el reparto es
    proporcional puro (y al menos 1 a cada uno). A size of 0 (a section with no content in the
    document, B2d-2) gets 0 words and does not count for the minimum.
    """
    if not sizes:
        return []
    size_sum = sum(sizes) or 1
    sized = sum(1 for t in sizes if t > 0)
    base = minimum if minimum * sized <= total else 0
    remainder = total - base * sized
    return [max(1, base + (remainder * t) // size_sum) if t > 0 else 0 for t in sizes]


# --- Troceado por secciones ----------------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    text: str
    start: int
    sections: tuple[Section, ...]  # las que EMPIEZAN dentro del trozo
    continues_from: str | None  # si el trozo empieza a mitad de una sección, su título
    words: int = 0

    @property
    def headings(self) -> tuple[str, ...]:
        return tuple(s.heading for s in self.sections)


def _section_at(sections_: list[Section], pos: int) -> str | None:
    """El título de la sección que contiene la posición `pos` (None: antes de la primera)."""
    inside = [s for s in sections_ if s.start <= pos]
    return inside[-1].heading if inside else None


def chunks_by_sections(
    text: str,
    sections_: list[Section],
    budget: int,
    split: Callable[[str, int], list[str]],
    *,
    from_pos: int = 0,
    to_pos: int | None = None,
) -> list[Chunk]:
    """Corta `text[from_pos:to_pos]` SOLO al principio de las secciones y empaqueta secciones enteras
    hasta el presupuesto.

    Cortar por las posiciones ya detectadas —y no por cualquier `#`— es lo que impide partir
    dentro de una valla de código o en un subtítulo. Una sección mayor que el presupuesto se parte
    con `split` (el troceado genérico); sus partes siguientes son continuaciones de esa sección.
    Las palabras se reparten después, con `allocate_words`.
    """
    to_pos = len(text) if to_pos is None else to_pos
    cuts = [s.start for s in sections_ if from_pos < s.start < to_pos]
    bounds = [from_pos, *cuts, to_pos]
    segments: list[tuple[int, str]] = [(a, text[a:b]) for a, b in pairwise(bounds) if b > a]
    starts = {s.start for s in sections_}

    def _chunk(start: int, chunk_text: str) -> Chunk:
        end = start + len(chunk_text)
        inside = tuple(s for s in sections_ if start <= s.start < end)
        continued = None if start in starts else _section_at(sections_, start)
        return Chunk(chunk_text, start, inside, continued)

    chunks: list[Chunk] = []
    current: tuple[int, str] | None = None
    for start, segment_text in segments:
        if len(segment_text) > budget:
            if current is not None:
                chunks.append(_chunk(*current))
                current = None
            pos = start
            for part in split(segment_text, budget):
                chunks.append(_chunk(pos, part))
                pos += len(part)
            continue
        if current is None:
            current = (start, segment_text)
        elif len(current[1]) + len(segment_text) <= budget:
            current = (current[0], current[1] + segment_text)
        else:
            chunks.append(_chunk(*current))
            current = (start, segment_text)
    if current is not None:
        chunks.append(_chunk(*current))
    return chunks


def allocate_words(chunks: list[Chunk], max_words: int, *, minimum: int = 40) -> list[Chunk]:
    """Reparte `max_words` entre trozos en proporción a su tamaño, sin pasar nunca del total."""
    allocation = allocate_by_size([len(t.text) for t in chunks], max_words, minimum=minimum)
    return [
        Chunk(t.text, t.start, t.sections, t.continues_from, words)
        for t, words in zip(chunks, allocation, strict=True)
    ]


def split_chunk(
    chunk: Chunk,
    text: str,
    sections_: list[Section],
    split: Callable[[str, int], list[str]],
) -> list[Chunk]:
    """Parte en dos (aprox.) un trozo que no cupo, con las posiciones del documento entero.

    Es el reintento por desborde en modo por secciones: usar aquí el troceado genérico volvería a
    cortar en los `#` de las vallas de código. Las palabras del trozo se reparten entre las partes.
    """
    budget = max(1, len(chunk.text) // 2)
    parts = chunks_by_sections(
        text,
        sections_,
        budget,
        split,
        from_pos=chunk.start,
        to_pos=chunk.start + len(chunk.text),
    )
    return allocate_words(parts, chunk.words, minimum=20)


# --- Enfoque --------------------------------------------------------------------------------------

FOCUS_MAX = 200
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def sanitize_focus(focus: str | None) -> str | None:
    """Una línea, sin caracteres de control ni comillas angulares, 200 caracteres como mucho.

    `focus` va al prompt de sistema: un texto de varias líneas o con instrucciones ganaría
    autoridad de sistema. Colapsarlo a una línea y delimitarlo lo deja como un dato.
    """
    if focus is None:
        return None
    clean = " ".join(_CONTROL.sub(" ", focus).replace("«", '"').replace("»", '"').split())
    return clean[:FOCUS_MAX].rstrip() or None


# #558: the focus reached the system prompt of every call and the model still left out the section
# that treats it. What can be computed is computed: the significant words of the focus, the
# sections of the input that hold them (named to the model) and whether the summary mentions any.

#: Words that say nothing about what the caller wants (es/en), folded (no accents); with them every
#: section would match.
_FOCUS_EMPTY_WORDS_TEXT = (
    "los las del que con por para una uno unos unas sus este esta estos estas ese esa eso esto "
    "todo toda todos todas como cual sobre entre sin hay mas muy pero sino "
    "the and for with from about into what how which that this these those its are was were "
    "not but all any"
)
_FOCUS_EMPTY_WORDS = frozenset(_FOCUS_EMPTY_WORDS_TEXT.split())
_FOCUS_WORD = re.compile(r"\w+")
#: Sections named to the model at most: a focus that matches more does not single any out.
FOCUS_MAX_SECTIONS = 8


def _fold(text: str) -> str:
    """Lower case and without accents, so «configuración» and «Configuracion» are one word."""
    folded = text.casefold()
    if folded.isascii():
        return folded
    decomposed = unicodedata.normalize("NFKD", folded)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def focus_terms(focus: str | None) -> list[str]:
    """The significant words of `focus`, folded, in order and once: 3+ characters, no empty word."""
    terms: list[str] = []
    for word in _FOCUS_WORD.findall(_fold(focus or "")):
        if len(word) >= 3 and word not in _FOCUS_EMPTY_WORDS and word not in terms:
            terms.append(word)
    return terms


#: A focus token the model copies as it is instead of translating it: a digit, `_`, `.` or `/`
#: inside (`cp1252`, `utf8`, `config.json`), camelCase (`readFile`) or all capitals (`UTF`, `API`).
_LITERAL_TOKEN = re.compile(r"\d|\w[_./]\w|[a-z][A-Z]|^[^a-z]*[A-Z][^a-z]*[A-Z][^a-z]*$")


def literal_focus_terms(focus: str | None) -> set[str]:
    """The terms of `focus` (as `focus_terms` folds them) that come from a literal token."""
    literal: set[str] = set()
    for token in (focus or "").split():
        if _LITERAL_TOKEN.search(token):
            literal.update(_FOCUS_WORD.findall(_fold(token)))
    return literal


def _stem(term: str) -> str:
    # A prefix, so «riesgos» matches «riesgo»; never under 4 characters (all of a short term). An
    # English plural in «-ies» goes back to «-y» first, so «policies» and «policy» share «poli».
    if term.endswith("ies") and len(term) > 4:
        term = term[:-3] + "y"
    return term[: max(4, len(term) - 2)]


@functools.lru_cache(64)
def _stems_pattern(stems: tuple[str, ...]) -> re.Pattern[str]:
    # One pass over the text: a word that starts with any stem. Escaped literals as flat
    # choices, longest first; `\w*` after it is a single greedy run, with no backtracking.
    choices = "|".join(re.escape(s) for s in sorted(set(stems), key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{choices})\w*")


def focus_terms_in(text: str, terms: list[str]) -> list[str]:
    """The `terms` that start a word of `text` (folded, by their stem), in the order given."""
    if not terms:
        return []
    stems = {term: _stem(term) for term in terms}
    pending = set(stems.values())
    found_stems: set[str] = set()
    for match in _stems_pattern(tuple(stems.values())).finditer(_fold(text)):
        word = match.group()
        hits = {s for s in pending if word.startswith(s)}
        found_stems |= hits
        pending -= hits
        if not pending:
            break
    return [term for term in terms if stems[term] in found_stems]


def focus_sections(text: str, terms: list[str]) -> list[str]:
    """Headings of `text` whose title or body holds a term; none if more than `FOCUS_MAX_SECTIONS`.

    The body of a heading runs to the next heading of any level, so a nested section is named by
    its own title and not by its parent's.
    """
    if not terms:
        return []
    headings = markdown_headings(text)
    found: list[str] = []
    for i, heading in enumerate(headings):
        end = headings[i + 1].start if i + 1 < len(headings) else len(text)
        if focus_terms_in(text[heading.start : end], terms):
            found.append(heading.text)
    return found if len(found) <= FOCUS_MAX_SECTIONS else []
