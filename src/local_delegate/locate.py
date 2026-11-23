"""Lines of the location fields of `local_extract`, computed by program (#692-#698).

The model never writes a line number. A field that asks for lines (`line_check.is_location_field`)
is answered here from an index of the file (Python by `ast`, TS/JS by `locate_ts`, Markdown, a
unified diff, literal ids such as `REQ-012`), or from what the model chose: names of that index,
or a literal piece of one line of the content (an "anchor") that is searched for exactly. Pure
program: no network, no model, no execution of the content (`ast.parse`, never `compile`), and
linear regular expressions only, because the file is untrusted input.

Lines are counted from 1, both ends included, splitting only on `\\n`, like `Read`: to read an
item, `offset=start` and `limit=end-start+1`.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import chain, pairwise
from pathlib import PurePath
from typing import Literal

from local_delegate import line_check, locate_ts, sections

Category = Literal["files", "hunks", "declarations", "sections", "ids"]

#: The languages whose index is of code (they mark comment lines and route to the `code` role).
CODE_LANGUAGES: frozenset[str] = frozenset({"python", "typescript"})


@dataclass(frozen=True)
class Block:
    """One entry of a file index: what it is and the lines it covers."""

    name: str  # "Class.method", path of a diff, "## Title", "REQ-012"
    kind: str  # "function" | "class" | "method" | "function_property" | "property"
    # | "variable" | "type" (function_property: arrow, function, computed, signal, effect)
    # | "section" | "file" | "hunk" | "id" | "table" | "list_item" | "fence"
    start: int  # 1-based, inclusive
    end: int  # 1-based, inclusive
    hunks: tuple[tuple[int, int], ...] = ()
    top_level: bool = False  # where a piece may be cut (REQ-013)


@dataclass(frozen=True)
class FileIndex:
    """The index of one file: its blocks in file order and its whole comment lines."""

    language: str | None  # "python" | "typescript" | "markdown" | "diff" | None
    blocks: tuple[Block, ...]
    comment_lines: frozenset[int]  # whole comment lines (code)
    unavailable_reason: str | None = None  # "syntax_error" | "unbalanced" | None


@dataclass(frozen=True)
class FieldRequest:
    """What a location field name asks for (REQ-008)."""

    name: str
    categories: frozenset[Category]
    kinds: frozenset[str]  # `Block.kind`s asked by `declarations`; empty = every kind
    singular: bool  # the categories appeared only in the singular (REQ-009, REQ-010)
    hunks: bool  # the field asks for the hunks of a diff (REQ-002)
    ids: tuple[str, ...]  # ids named in the field, normalized: "REQ-012"
    residual: tuple[str, ...]  # words left over (REQ-008)


@dataclass(frozen=True)
class Item:
    """One element of a location value, located or not."""

    name: str
    start: int | None
    end: int | None
    hunks: tuple[tuple[int, int], ...] = ()
    reason: str | None = None  # "not_found" | "ambiguous" | "too_short" | "in_comment"
    # | "not_in_index" | None
    candidates: tuple[int, ...] = ()
    source: str = "program"  # "program" | "selection" | "anchor" -> located[field].by
    index: str | None = None  # "python" | "typescript" | "markdown" | "diff" | "ids" | None
    conflict: bool = False  # name and anchor in different places (REQ-011)
    anchor_end_ignored: bool = False


# --- REQ-008: what a field name asks for, by presence --------------------------------------------

#: Closed vocabulary of each category, folded (lower case, no accents), es and en. The value says
#: whether the word is singular (`True`), plural (`False`) or both (`None`: `computed`).
_FILE_WORDS: dict[str, bool | None] = {
    "fichero": True, "ficheros": False, "archivo": True, "archivos": False,
    "file": True, "files": False, "ruta": True, "rutas": False, "path": True, "paths": False,
}  # fmt: skip
_HUNK_WORDS: dict[str, bool | None] = {"hunk": True, "hunks": False}
_SECTION_WORDS: dict[str, bool | None] = {
    "seccion": True, "secciones": False, "section": True, "sections": False,
    "heading": True, "headings": False, "titulo": True, "titulos": False,
    "title": True, "titles": False, "encabezado": True, "encabezados": False,
    "header": True, "headers": False, "cabecera": True, "cabeceras": False,
    "apartado": True, "apartados": False, "chapter": True, "chapters": False,
    "capitulo": True, "capitulos": False,
}  # fmt: skip
_ID_WORDS: dict[str, bool | None] = {
    "id": True, "ids": False, "identificador": True, "identificadores": False,
    "identifier": True, "identifiers": False, "requisito": True, "requisitos": False,
    "requirement": True, "requirements": False,
}  # fmt: skip
#: `declarations` subtypes: word -> (singular, the `Block.kind`s it asks for; empty = all).
_FUNCTION_KINDS = frozenset({"function", "method", "function_property"})
_DECLARATION_WORDS: dict[str, tuple[bool | None, frozenset[str]]] = {
    **dict.fromkeys(("funcion", "function", "metodo", "method", "handler", "manejador",
                     "signal", "senal"), (True, _FUNCTION_KINDS)),
    **dict.fromkeys(("funciones", "functions", "metodos", "methods", "handlers",
                     "manejadores", "signals", "senales", "computeds"), (False, _FUNCTION_KINDS)),
    "computed": (None, _FUNCTION_KINDS),
    "clase": (True, frozenset({"class"})), "class": (True, frozenset({"class"})),
    "clases": (False, frozenset({"class"})), "classes": (False, frozenset({"class"})),
    **dict.fromkeys(("tipo", "type", "interfaz", "interface", "enum"), (True, frozenset({"type"}))),
    **dict.fromkeys(("tipos", "types", "interfaces", "enums"), (False, frozenset({"type"}))),
    **dict.fromkeys(("variable", "constante", "constant"), (True, frozenset({"variable"}))),
    **dict.fromkeys(("variables", "constantes", "constants"), (False, frozenset({"variable"}))),
    **dict.fromkeys(("declaracion", "declaration", "simbolo", "symbol", "definicion",
                     "definition"), (True, frozenset())),
    **dict.fromkeys(("declaraciones", "declarations", "simbolos", "symbols", "definiciones",
                     "definitions"), (False, frozenset())),
}  # fmt: skip
_CATEGORY_WORDS: tuple[tuple[Category, dict[str, bool | None]], ...] = (
    ("files", _FILE_WORDS),
    ("hunks", _HUNK_WORDS),
    ("sections", _SECTION_WORDS),
    ("ids", _ID_WORDS),
)
#: Quantifiers, dropped from the residual: they say how many, not what.
_QUANTIFIER_WORDS = frozenset(
    {
        "lista", "listas", "list", "lists", "listado", "todos", "todas", "todo", "toda",
        "all", "every", "each", "cada", "sus", "their", "its",
    }
)  # fmt: skip
#: Words that, beside a category, do not narrow it: every file of a diff changes
#: (`ficheros_que_cambian_con_sus_lineas`, `changed_files_with_lines`). Dropped from the residual.
_NEUTRAL_WORDS = frozenset(
    {
        "diff", "patch", "parche", "changed", "modified", "touched", "cambiado", "cambiados",
        "cambiada", "cambiadas", "modificado", "modificados", "modificada", "modificadas",
        "tocado", "tocados", "cambian", "cambia", "cambiaron", "change", "changes",
    }
)  # fmt: skip
#: Words of 3 letters or fewer never stay in the residual (`y`, `con`, `de`, `sus`).
_SHORT_WORD_MAX = 3


def _id_tokens(words: list[str]) -> tuple[list[str], set[int]]:
    """REQ-007 (a): the ids of a field name (`D7_linea`, `REQ_012_linea`) and the word positions
    they take. One word of letters then digits, or a word of letters followed by one of digits.
    """
    ids: list[str] = []
    used: set[int] = set()
    for k, word in enumerate(words):
        if k in used:
            continue
        letters = word.rstrip("0123456789")
        digits = word[len(letters) :]
        if letters.isalpha() and digits and len(letters) <= 6:
            ids.append(f"{letters.upper()}-{digits}")
            used.add(k)
        elif (
            word.isalpha()
            and len(word) <= 6
            and k + 1 < len(words)
            and words[k + 1].isdigit()
            and word not in _CATEGORY_VOCABULARY
        ):
            ids.append(f"{word.upper()}-{words[k + 1]}")
            used.update((k, k + 1))
    return ids, used


_CATEGORY_VOCABULARY = frozenset(
    {w for _, vocabulary in _CATEGORY_WORDS for w in vocabulary} | set(_DECLARATION_WORDS)
)


def _field_words(name: str) -> list[str]:
    return line_check._FIELD_WORD.findall(
        line_check._fold(line_check._CAMEL_BOUNDARY.sub(" ", name))
    )


def classify_field(name: str) -> FieldRequest:
    """REQ-008: the categories a location field name asks for, by presence, and what is left.

    The name is split into words like `line_check.is_location_field` does. First the ids of the
    name (REQ-007 a) and the words of each category's closed vocabulary are taken, before any
    short word is dropped (`ids_con_lineas`). Then the location words
    (`line_check._LOCATION_NAME_WORDS`), the quantifiers, the words that do not narrow a category
    and every word of 3 letters or fewer are dropped from the rest: what is left is the
    residual. An unknown word never cancels a category, it only goes to the residual. Meant for
    names where `is_location_field(name)` holds.
    """
    words = _field_words(name)
    ids, used = _id_tokens(words)
    categories: set[Category] = set()
    kinds: set[str] = set()
    every_kind = False
    numbers: list[bool | None] = []
    taken = set(used)
    for k, word in enumerate(words):
        if k in taken:
            continue
        for category, vocabulary in _CATEGORY_WORDS:
            if word in vocabulary:
                categories.add(category)
                numbers.append(vocabulary[word])
                taken.add(k)
                break
        else:
            if word in _DECLARATION_WORDS:
                number, word_kinds = _DECLARATION_WORDS[word]
                categories.add("declarations")
                numbers.append(number)
                if word_kinds:
                    kinds.update(word_kinds)
                else:
                    every_kind = True
                taken.add(k)
    if ids:
        categories.add("ids")
        numbers.append(len(ids) == 1)
    residual = tuple(
        word
        for k, word in enumerate(words)
        if k not in taken
        and len(word) > _SHORT_WORD_MAX
        and word not in line_check._LOCATION_NAME_WORDS
        and word not in _QUANTIFIER_WORDS
        and word not in _NEUTRAL_WORDS
        and not word.isdigit()
    )
    return FieldRequest(
        name=name,
        categories=frozenset(categories),
        kinds=frozenset() if every_kind else frozenset(kinds),
        singular=bool(numbers) and all(n is True for n in numbers),
        hunks="hunks" in categories,
        ids=tuple(dict.fromkeys(ids)),
        residual=residual,
    )


# --- REQ-002: the value of a location field ------------------------------------------------------


def to_value(req: FieldRequest, items: list[Item]) -> list[dict] | None:
    """REQ-002: the items as a list of `{"name", "start", "end"}` (+ `hunks` when the field asks
    for them), located ones in file order (by `start`, then `end`), unlocated ones last in the
    order they came; `None` when there is no item.
    """
    if not items:
        return None
    located = sorted(
        (it for it in items if it.start is not None and it.end is not None),
        key=lambda it: (it.start, it.end),
    )
    unlocated = [it for it in items if it.start is None or it.end is None]
    out: list[dict] = []
    for it in [*located, *unlocated]:
        start, end = (
            (it.start, it.end) if it.start is not None and it.end is not None else (None, None)
        )
        entry: dict = {"name": it.name, "start": start, "end": end}
        if req.hunks:
            entry["hunks"] = [[a, b] for a, b in it.hunks]
        out.append(entry)
    return out


# --- REQ-003 to REQ-007: the index of a file ----------------------------------------------------

_PYTHON_SUFFIXES = frozenset({".py", ".pyi"})
_TS_SUFFIXES = frozenset({".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"})
_MARKDOWN_SUFFIXES = frozenset({".md", ".markdown", ".mdx"})
#: #665: read as a diff even when it does not open with a patch header; any other file is a diff
#: only by its start (`sections.is_unified_diff`).
_DIFF_SUFFIXES = frozenset({".patch", ".diff"})
#: The kinds an ANCHOR line can fall inside (REQ-011); never offered to the model by name.
_CONTAINER_KINDS = frozenset({"table", "list_item", "fence"})
_DECLARATION_KINDS = frozenset(
    {"function", "class", "method", "function_property", "property", "variable", "type"}
)
#: The longest name a table row, a list item or a fence gets (its first line, stripped).
_LABEL_MAX = 80


def _lines(content: str) -> list[str]:
    """The lines of `content` as `Read` counts them: split only on `\\n`, without the empty one
    after a final newline."""
    lines = content.split("\n")
    if len(lines) > 1 and lines[-1] == "":
        lines.pop()
    return lines


def _ordered(blocks: list[Block]) -> tuple[Block, ...]:
    return tuple(sorted(blocks, key=lambda b: (b.start, -b.end)))


def build_index(content: str, path: str) -> FileIndex:
    """The index of `content`, read from `path` (its suffix, or its start for a diff).

    Python (`ast`) and TS/JS (`locate_ts`) give declarations; Markdown, sections, tables, list
    items, fenced blocks and ids; a unified diff, its files and hunks; any other text, its tables,
    list items, fenced blocks and ids. A Python `SyntaxError` or TS/JS braces that do not balance
    give an empty index with `unavailable_reason` (REQ-022); it never raises.
    """
    suffix = PurePath(path).suffix.lower() if path else ""
    if suffix in _PYTHON_SUFFIXES:
        return _python_index(content)
    if suffix in _TS_SUFFIXES:
        entries, comment_lines, reason = locate_ts.index_typescript(content)
        blocks = [Block(n, k, s, e, top_level=top) for n, k, s, e, top in entries]
        return FileIndex("typescript", _ordered(blocks), comment_lines, reason)
    if suffix in _DIFF_SUFFIXES or (
        suffix not in _MARKDOWN_SUFFIXES and sections.is_unified_diff(content)
    ):
        blocks = [
            Block(file_path, "file", first, last, hunks=tuple(hunks), top_level=True)
            for first, last, file_path, hunks in line_check.diff_file_hunks(content)
        ]
        return FileIndex("diff", _ordered(blocks), frozenset())
    markdown = suffix in _MARKDOWN_SUFFIXES
    lines = _lines(content)
    blocks = _text_blocks(lines, headings=markdown)
    blocks += _id_blocks(lines, blocks)
    return FileIndex("markdown" if markdown else None, _ordered(blocks), frozenset())


# Python -----------------------------------------------------------------------------------------


def _python_index(content: str) -> FileIndex:
    """REQ-003: functions, `async def`, classes and methods at any depth (`Class.method`) and
    module assignments, each from its first decorator to its `end_lineno`."""
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return FileIndex("python", (), frozenset(), "syntax_error")
    blocks: list[Block] = []

    def first_line(node: ast.stmt) -> int:
        decorators = getattr(node, "decorator_list", [])
        return min([node.lineno, *(d.lineno for d in decorators)])

    # depth first with a stack of its own, in the same order as a recursive walk: a long `elif`
    # chain nests one `If` per branch in `orelse`, and recursion would end in a `RecursionError`
    # on a file that `ast.parse` accepted (REQ-022)
    stack: list[tuple[Iterator[ast.stmt], str, str]] = [(iter(tree.body), "", "module")]
    while stack:
        body, prefix, scope = stack[-1]
        node = next(body, None)
        if node is None:
            stack.pop()
            continue
        top = scope == "module"
        end = node.end_lineno or node.lineno
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = prefix + node.name
            kind = "method" if scope == "class" else "function"
            blocks.append(Block(name, kind, first_line(node), end, top_level=top))
            stack.append((iter(node.body), name + ".", "function"))
        elif isinstance(node, ast.ClassDef):
            name = prefix + node.name
            blocks.append(Block(name, "class", first_line(node), end, top_level=top))
            stack.append((iter(node.body), name + ".", "class"))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            if scope != "module":
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for name in _assigned_names(targets):
                blocks.append(Block(name, "variable", node.lineno, end, top_level=True))
        else:  # if, try, with, for, while, match: their bodies keep the scope
            inner = [getattr(node, attr, None) for attr in ("body", "orelse", "finalbody")]
            parts = [*getattr(node, "handlers", []), *getattr(node, "cases", [])]
            bodies = [b for b in inner if isinstance(b, list)] + [part.body for part in parts]
            stack.append((chain.from_iterable(bodies), prefix, scope))
    return FileIndex("python", _ordered(blocks), _python_comment_lines(content))


def _assigned_names(targets: list[ast.expr]) -> list[str]:
    names: list[str] = []
    for target in targets:
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            names += _assigned_names(list(target.elts))
    return names


def _python_comment_lines(content: str) -> frozenset[int]:
    """The lines that hold only a `# comment` (a `#` inside a string is not one)."""
    out: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(content).readline):
            if tok.type == tokenize.COMMENT and not tok.line[: tok.start[1]].strip():
                out.add(tok.start[0])
    except (tokenize.TokenError, SyntaxError):
        # `ast.parse` accepted the file, so this is the tokenizer giving up near its end (an
        # unclosed bracket or string at EOF): the comment lines read so far are still right
        return frozenset(out)
    return frozenset(out)


# Markdown and plain text ------------------------------------------------------------------------

_LIST_ITEM = re.compile(r"[ \t]*(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)")
_TABLE_ROW = re.compile(r"[ \t]*\|")


def _indent(line: str) -> int:
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip(" "))


def _label(line: str) -> str:
    return line.strip()[:_LABEL_MAX]


def _trim_blank_end(lines: list[str], start: int, end: int) -> int:
    while end > start and not lines[end - 1].strip():
        end -= 1
    return end


def _heading_level(line: str) -> int:
    marks = line.lstrip(" ")
    return len(marks) - len(marks.lstrip("#"))


def _text_blocks(lines: list[str], headings: bool) -> list[Block]:
    """REQ-005: sections (when `headings`), tables, list items and fenced blocks of `lines`.

    A section ends on the line before the next heading of the same or a higher level (or at the
    end), a list item on the line before the next non-blank line indented as much or less (or a
    heading), both without their trailing blank lines. A table is a run of lines that start with
    `|`; a fenced block goes from its opening fence to its closing one (or to the end).
    """
    total = len(lines)
    blocks: list[Block] = []
    fence_start: int | None = None
    table_start: int | None = None
    found_headings: list[tuple[int, int]] = []  # (line, level)
    items: list[int] = []

    def close_table(last: int) -> None:
        nonlocal table_start
        if table_start is not None:
            blocks.append(Block(_label(lines[table_start - 1]), "table", table_start, last))
            table_start = None

    for number, line in enumerate(lines, 1):
        if line_check._FENCE.match(line):
            close_table(number - 1)
            if fence_start is None:
                fence_start = number
            else:
                blocks.append(Block(_label(lines[fence_start - 1]), "fence", fence_start, number))
                fence_start = None
            continue
        if fence_start is not None:
            continue
        if _TABLE_ROW.match(line):
            if table_start is None:
                table_start = number
            continue
        close_table(number - 1)
        if headings and line_check._ATX_HEADING.match(line):
            found_headings.append((number, _heading_level(line)))
        elif _LIST_ITEM.match(line):
            items.append(number)
    close_table(total)
    if fence_start is not None:
        blocks.append(Block(_label(lines[fence_start - 1]), "fence", fence_start, total))
    heading_lines = {number for number, _ in found_headings}
    # a section ends before the next heading of the same or a higher level: one pass with the
    # open sections on a stack, never a scan of the later headings for each one (REQ-022)
    section_end = [total] * len(found_headings)
    open_sections: list[int] = []  # positions in `found_headings`, levels strictly growing
    for k, (number, level) in enumerate(found_headings):
        while open_sections and found_headings[open_sections[-1]][1] >= level:
            section_end[open_sections.pop()] = number - 1
        open_sections.append(k)
    for k, (number, _level) in enumerate(found_headings):
        end = _trim_blank_end(lines, number, section_end[k])
        blocks.append(Block(_label(lines[number - 1]), "section", number, end, top_level=True))
    for number in items:
        width = _indent(lines[number - 1])
        end = total
        for later in range(number + 1, total + 1):
            text = lines[later - 1]
            if text.strip() and (_indent(text) <= width or later in heading_lines):
                end = later - 1
                break
        end = _trim_blank_end(lines, number, end)
        blocks.append(Block(_label(lines[number - 1]), "list_item", number, end))
    return blocks


# Ids --------------------------------------------------------------------------------------------

#: REQ-007 (b): an id of strict form, two or more capitals, `-` or `_`, two or more digits. The
#: look-behind lets a match start only at the start of a run of capitals, so it stays linear.
_STRICT_ID = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2,})[-_](\d{2,})(?![A-Za-z0-9])")
#: What comes before an id that DEFINES it: a list marker, a heading or the first table cell,
#: with up to three emphasis or link marks (`- **REQ-012** — …`).
_DEFINITION_PREFIX = re.compile(
    r"(?:[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+| {0,3}#{1,6}[ \t]+|[ \t]*\|[ \t]*)[*_`\[]{0,3}"
)
_DEFINITION_PREFIX_MAX = 40
#: The most candidates an ambiguous item lists.
MAX_CANDIDATES = 5


def _id_occurrences(
    letters: str, lines: list[str], wanted: frozenset[str] | None = None
) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    """REQ-007: in ONE pass, the lines where each id with the prefix `letters` appears, and the
    lines where it is defined, keyed by its digits. The prefix matches as a whole word, in any
    case, with `-`, `_` or no separator (`REQ-012`, `req_012`, `REQ012`)."""
    pattern = re.compile(
        r"(?<![A-Za-z0-9])" + re.escape(letters) + r"[-_]?(\d+)(?![A-Za-z0-9])", re.IGNORECASE
    )
    seen: dict[str, list[int]] = {}
    defined: dict[str, list[int]] = {}
    for number, line in enumerate(lines, 1):
        for m in pattern.finditer(line):
            digits = m.group(1)
            if wanted is not None and digits not in wanted:
                continue
            places = seen.setdefault(digits, [])
            if not places or places[-1] != number:
                places.append(number)
            if _is_definition(line, m.start()):
                definitions = defined.setdefault(digits, [])
                if not definitions or definitions[-1] != number:
                    definitions.append(number)
    return seen, defined


def _is_definition(line: str, at: int) -> bool:
    prefix = line[:at]
    return (
        len(prefix) <= _DEFINITION_PREFIX_MAX and _DEFINITION_PREFIX.fullmatch(prefix) is not None
    )


def _by_start(blocks: list[Block] | tuple[Block, ...]) -> dict[int, Block]:
    """The list item or section that starts at each line (a section wins over a list item)."""
    out: dict[int, Block] = {}
    for block in blocks:
        if block.kind == "section" or (block.kind == "list_item" and block.start not in out):
            out[block.start] = block
    return out


def _id_item(name: str, seen: list[int], defined: list[int], by_start: dict[int, Block]) -> Item:
    """One id: the block of its definition, the only line it appears on, or why not (REQ-007).

    A definition opens a list item, a heading or the first cell of a table row; its range is the
    list item, the section or the row. Several candidate lines give `ambiguous`, none `not_found`.
    """
    places = defined or seen
    if not places:
        return Item(name, None, None, reason="not_found", index="ids")
    if len(places) > 1:
        return Item(
            name,
            None,
            None,
            reason="ambiguous",
            candidates=tuple(places[:MAX_CANDIDATES]),
            index="ids",
        )
    start = end = places[0]
    block = by_start.get(start) if defined else None
    if block is not None:
        end = block.end
    return Item(name, start, end, index="ids")


def _named_id_items(
    names: tuple[str, ...], lines: list[str], blocks: list[Block] | tuple[Block, ...]
) -> list[Item]:
    """REQ-007 (a): the ids named in a field (`REQ-012`), one pass per prefix."""
    by_start = _by_start(blocks)
    by_prefix: dict[str, set[str]] = {}
    for name in names:
        letters, _, digits = name.partition("-")
        by_prefix.setdefault(letters, set()).add(digits)
    found = {
        letters: _id_occurrences(letters, lines, frozenset(digits))
        for letters, digits in by_prefix.items()
    }
    items = []
    for name in names:
        letters, _, digits = name.partition("-")
        seen, defined = found[letters]
        items.append(_id_item(name, seen.get(digits, []), defined.get(digits, []), by_start))
    return items


def _strict_id_items(lines: list[str], blocks: list[Block] | tuple[Block, ...]) -> list[Item]:
    """REQ-007 (b): the strict ids of `lines` (`_STRICT_ID`) that have the most frequent prefix,
    in file order (`REQ_012` and `REQ-012` are one id)."""
    found: dict[tuple[str, str], None] = {}
    for line in lines:
        for m in _STRICT_ID.finditer(line):
            found.setdefault((m.group(1), m.group(2)), None)
    if not found:
        return []
    counts: dict[str, int] = {}
    for prefix, _ in found:
        counts[prefix] = counts.get(prefix, 0) + 1
    top = max(counts, key=lambda prefix: counts[prefix])  # the first one on a tie
    digits_in_order = [digits for prefix, digits in found if prefix == top]
    seen, defined = _id_occurrences(top, lines, frozenset(digits_in_order))
    by_start = _by_start(blocks)
    items = [
        _id_item(f"{top}-{digits}", seen.get(digits, []), defined.get(digits, []), by_start)
        for digits in digits_in_order
    ]
    # file order: by the line of each id, the ones without a line last (a stable sort)
    return sorted(items, key=lambda it: (it.start is None, it.start or 0))


def _id_blocks(lines: list[str], blocks: list[Block]) -> list[Block]:
    """The ids of REQ-007 (b) that have one place, as blocks of kind `id` (for selection)."""
    return [
        Block(item.name, "id", item.start, item.end)
        for item in _strict_id_items(lines, blocks)
        if item.start is not None and item.end is not None
    ]


def _structure(index: FileIndex, lines: list[str]) -> list[Block] | tuple[Block, ...]:
    """The blocks to find id definitions in: the index of a text file, the text blocks of code."""
    if index.language in ("markdown", None):
        return index.blocks
    return _text_blocks(lines, headings=False)


# --- REQ-009 and REQ-010: what the index answers, and what the model may choose ----------------

#: The languages whose index holds each category (`ids` is found in any text).
_CATEGORY_LANGUAGES: dict[str, frozenset[str]] = {
    "files": frozenset({"diff"}),
    "hunks": frozenset({"diff"}),
    "sections": frozenset({"markdown"}),
    "declarations": CODE_LANGUAGES,
}
#: The kinds that may be chosen by name (REQ-010) and go into the catalogue (REQ-012).
_SELECTABLE_KINDS = _DECLARATION_KINDS | {"section", "file", "id"}


def _category_blocks(req: FieldRequest, index: FileIndex) -> list[Block] | None:
    """The blocks of `index` that the categories of `req` ask for; None if one of them has no
    index in this file (`funciones_con_lineas` over a Markdown)."""
    if index.unavailable_reason is not None or not req.categories:
        return None
    chosen: list[Block] = []
    for category in sorted(req.categories):
        if category == "ids":
            chosen += [b for b in index.blocks if b.kind == "id"]
            continue
        if index.language not in _CATEGORY_LANGUAGES[category]:
            return None
        if category in ("files", "hunks"):
            chosen += [b for b in index.blocks if b.kind == "file"]
        elif category == "sections":
            chosen += [b for b in index.blocks if b.kind == "section"]
        else:
            kinds = req.kinds or _DECLARATION_KINDS
            chosen += [b for b in index.blocks if b.kind in kinds]
    unique = {(b.name, b.start, b.end): b for b in chosen}
    return list(_ordered(list(unique.values())))


def answer_by_program(req: FieldRequest, index: FileIndex, content: str) -> list[Item] | None:
    """REQ-009: the items of a field the index answers alone, or None if it needs the model.

    An id named in the field (`REQ_012_linea`) is always answered, from the content (REQ-007 a).
    Otherwise the field must have a category in the PLURAL, no residual and an index of that
    category: then every entry of the category (or of its kinds: `funciones_con_lineas` gives
    functions, methods and function properties, not classes nor constants). A singular category
    never gets the whole index (it goes to a choice by the model). Ids without a name
    (`requisitos_con_lineas`) are the strict ids of the content (REQ-007 b).
    """
    lines = _lines(content)
    if req.ids:
        return _named_id_items(req.ids, lines, _structure(index, lines))
    if not req.categories or req.residual or req.singular:
        return None
    if req.categories == {"ids"}:
        if index.unavailable_reason is not None:
            return None
        return _strict_id_items(lines, _structure(index, lines))
    blocks = _category_blocks(req, index)
    if blocks is None or (not blocks and req.categories & {"files", "hunks"}):
        return None  # a `.patch` where the program found no file: the model's turn (#665)
    language = index.language
    return [
        Item(b.name, b.start, b.end, hunks=b.hunks, source="program", index=language)
        for b in blocks
    ]


def selectable_names(req: FieldRequest, index: FileIndex) -> list[str]:
    """REQ-010: the names the model may choose from for `req` (for the schema `enum`), in file
    order; `[]` when there is no choice (no category, or no index of it here)."""
    blocks = _category_blocks(req, index)
    if not blocks:
        return []
    return list(dict.fromkeys(b.name for b in blocks))


def catalogue(index: FileIndex, budget_chars: int) -> str:
    """REQ-012: kind and name of each entry of the index that may be chosen, one per line and
    without any line number; "" if there is none or the text is longer than `budget_chars`."""
    entries = [f"- {b.kind}: {b.name}" for b in index.blocks if b.kind in _SELECTABLE_KINDS]
    if not entries:
        return ""
    text = "\n".join(entries)
    return text if len(text) <= budget_chars else ""


# --- REQ-011 and REQ-013: names and anchors that the model gave ---------------------------------

#: An anchor needs at least this many characters that are not blanks.
ANCHOR_MIN_CHARS = 6
_LINE_BREAK = re.compile(r"[\n\r]")


def _normalize(text: str) -> str:
    """Blanks as one space, ends trimmed; cut at the first line break (REQ-011)."""
    return " ".join(_LINE_BREAK.split(text, maxsplit=1)[0].split())


_HEADING_MARKS = re.compile(r"^\s*#+\s*")


def _heading_text(heading: str) -> str:
    """A heading (`## Title`) without its `#` marks."""
    return _HEADING_MARKS.sub("", heading)


def _bare_name(name: str) -> str:
    return name.strip().removesuffix("()").strip()


def _match_name(name: str, index: FileIndex) -> tuple[Block | None, list[Block]]:
    """REQ-010: the block of the index named `name` (full name, a heading without its `#`, an id
    in any case or separator, or the last segment when only one block has it), else the
    candidates when several have it."""
    wanted = _bare_name(name)
    if not wanted:
        return None, []
    pool = [b for b in index.blocks if b.kind in _SELECTABLE_KINDS]

    def unique(hits: list[Block]) -> tuple[Block | None, list[Block]] | None:
        if len(hits) == 1:
            return hits[0], []
        if hits:
            return None, hits
        return None

    exact = unique([b for b in pool if b.name == wanted])
    if exact:
        return exact
    heading = _heading_text(wanted)
    titled = unique([b for b in pool if b.kind == "section" and _heading_text(b.name) == heading])
    if titled:
        return titled
    id_key = _id_key(wanted)
    if id_key:
        by_id = unique([b for b in pool if b.kind == "id" and _id_key(b.name) == id_key])
        if by_id:
            return by_id
    last = wanted.rsplit(".", 1)[-1]
    segment = unique([b for b in pool if b.name.rsplit(".", 1)[-1] == last])
    if segment:
        return segment
    return None, []


_ID_KEY = re.compile(r"([A-Za-z]{1,12})[-_]?(\d{1,9})")


def _id_key(name: str) -> tuple[str, str] | None:
    m = _ID_KEY.fullmatch(name.strip())
    return (m.group(1).upper(), m.group(2)) if m else None


@dataclass(frozen=True)
class _Anchored:
    start: int | None
    end: int | None
    reason: str | None = None
    candidates: tuple[int, ...] = ()
    end_ignored: bool = False


class _Lines:
    """The lines of the content, with their blanks normalized once (REQ-011)."""

    def __init__(self, content: str) -> None:
        self.lines = _lines(content)
        normalized = [" ".join(line.split()) for line in self.lines]
        # one string with the normalized lines and the offset where each starts: `str.find` over
        # it costs one pass in C per anchor, where a per-line `in` costs one Python step per line
        self.joined = "\n".join(normalized)
        self.starts = [0] * len(normalized)
        offset = 0
        for n, line in enumerate(normalized):
            self.starts[n] = offset
            offset += len(line) + 1

    def hits(self, text: str, first: int, last: int) -> list[int]:
        """The lines from `first` to `last` (1-based) whose normalized text holds `text`."""
        if "\n" in text or first > last or not self.starts:
            return []  # no line holds a line break: a match across two lines is no hit
        joined, starts = self.joined, self.starts
        stop = starts[last] - 1 if last < len(starts) else len(joined)
        out: list[int] = []
        at = joined.find(text, starts[first - 1], stop)
        while at != -1:
            line = bisect_right(starts, at)  # 1-based number of the line that holds `at`
            out.append(line)
            # the next hit can only count on a later line
            at = joined.find(text, starts[line], stop) if line < len(starts) else -1
        return out


class _BlockSpans:
    """The blocks of an index sorted for `_anchor_block`, built once per call to `resolve`: the
    containers apart, and the widest other block that starts at each line (the first on a tie)."""

    def __init__(self, index: FileIndex) -> None:
        self.containers = [b for b in index.blocks if b.kind in _CONTAINER_KINDS]
        self.widest: dict[int, Block] = {}
        for b in index.blocks:
            if b.kind in _CONTAINER_KINDS:
                continue
            current = self.widest.get(b.start)
            if current is None or b.end > current.end:
                self.widest[b.start] = b


def _anchor_block(spans: _BlockSpans, line: int) -> tuple[int, int]:
    """REQ-011 without `anchor_end`: the table, list item or fenced block that holds `line` (the
    innermost), else the declaration or section that starts at it (the widest), else the line."""
    holding = [b for b in spans.containers if b.start <= line <= b.end]
    if holding:
        block = min(holding, key=lambda b: (b.end - b.start, -b.start))
        return block.start, block.end
    widest = spans.widest.get(line)
    if widest is not None:
        return widest.start, widest.end
    return line, line


def _resolve_anchor(
    anchor: str,
    anchor_end: str | None,
    lines: _Lines,
    index: FileIndex,
    piece_range: tuple[int, int] | None,
    spans: _BlockSpans,
) -> _Anchored:
    text = _normalize(anchor)
    if len(text.replace(" ", "")) < ANCHOR_MIN_CHARS:
        return _Anchored(None, None, reason="too_short")
    total = len(lines.lines)
    hits: list[int] = []
    if piece_range is not None:
        first, last = max(piece_range[0], 1), min(piece_range[1], total)
        hits = lines.hits(text, first, last)
    if not hits:
        hits = lines.hits(text, 1, total)
    if not hits:
        return _Anchored(None, None, reason="not_found")
    if len(hits) > 1:
        return _Anchored(None, None, reason="ambiguous", candidates=tuple(hits[:MAX_CANDIDATES]))
    line = hits[0]
    if index.language in CODE_LANGUAGES and line in index.comment_lines:
        return _Anchored(None, None, reason="in_comment")
    ignored = False
    if anchor_end is not None and _normalize(anchor_end):
        closing = lines.hits(_normalize(anchor_end), line + 1, total)
        if closing:
            return _Anchored(line, closing[0])
        ignored = True
    start, end = _anchor_block(spans, line)
    return _Anchored(start, end, end_ignored=ignored)


def _entry_text(entry: dict, key: str) -> str | None:
    value = entry.get(key)
    return value if isinstance(value, str) and value.strip() else None


def resolve(
    req: FieldRequest,
    entries: list[dict],
    index: FileIndex,
    content: str,
    piece_range: tuple[int, int] | None = None,
) -> list[Item]:
    """REQ-011, REQ-013: the items of what the model gave (`{"name", "anchor", "anchor_end"}`).

    A name is matched first against the index of the whole file (`_match_name`): when it holds,
    its block gives the lines, and an anchor that points outside that block only counts a
    conflict. Otherwise the anchor is searched as a substring of ONE line, blanks normalized,
    case and accents kept: inside `piece_range` first (one hit there wins, several are
    `ambiguous`), then in the whole file. No hit is `not_found`, several `ambiguous` with up to
    `MAX_CANDIDATES` lines, fewer than `ANCHOR_MIN_CHARS` non-blank characters `too_short`, a whole
    comment line of code `in_comment`; all with null lines. A number the model wrote never
    reaches an item: only the index and the anchor give lines.
    """
    lines = _Lines(content)
    spans = _BlockSpans(index)
    out: list[Item] = []
    language = index.language
    for raw in entries:
        entry = {"name": raw} if isinstance(raw, str) else raw
        if not isinstance(entry, dict):
            continue
        name = _entry_text(entry, "name") or ""
        anchor = _entry_text(entry, "anchor")
        anchor_end = _entry_text(entry, "anchor_end")
        if not name and not anchor:
            continue
        block, candidates = _match_name(name, index) if name else (None, [])
        anchored = (
            _resolve_anchor(anchor, anchor_end, lines, index, piece_range, spans)
            if anchor
            else None
        )
        if block is not None:
            conflict = (
                anchored is not None
                and anchored.start is not None
                and not block.start <= anchored.start <= block.end
            )
            out.append(
                Item(
                    block.name,
                    block.start,
                    block.end,
                    hunks=block.hunks,
                    source="selection",
                    index=language,
                    conflict=conflict,
                )
            )
        elif anchored is not None:
            out.append(
                Item(
                    name or _normalize(anchor or "")[:_LABEL_MAX],
                    anchored.start,
                    anchored.end,
                    reason=anchored.reason,
                    candidates=anchored.candidates,
                    source="anchor",
                    index=language if anchored.start is not None else None,
                    anchor_end_ignored=anchored.end_ignored,
                )
            )
        elif candidates:
            out.append(
                Item(
                    name,
                    None,
                    None,
                    reason="ambiguous",
                    candidates=tuple(b.start for b in candidates[:MAX_CANDIDATES]),
                    source="selection",
                )
            )
        else:
            out.append(Item(name, None, None, reason="not_in_index", source="selection"))
    return out


def merge(items_lists: list[list[Item]]) -> list[Item]:
    """REQ-013: the items of several pieces as one list, by `(name, start, end)` without repeats,
    located ones in file order; an unlocated item is dropped when its name was located elsewhere
    or it came already (same name and reason)."""
    located: dict[tuple[str, int, int], Item] = {}
    for items in items_lists:
        for item in items:
            if item.start is not None and item.end is not None:
                located.setdefault((item.name, item.start, item.end), item)
    names = {name for name, _, _ in located}
    unlocated: dict[tuple[str, str | None], Item] = {}
    for items in items_lists:
        for item in items:
            if (item.start is None or item.end is None) and item.name not in names:
                unlocated.setdefault((item.name, item.reason), item)
    ordered = sorted(located.values(), key=lambda it: (it.start, it.end))
    return [*ordered, *unlocated.values()]


# --- REQ-013: pieces cut at the blocks ---------------------------------------------------------


def split_at_blocks(
    content: str, index: FileIndex, budget: int
) -> list[tuple[str, tuple[int, int]]]:
    """REQ-013: `content` in pieces of at most `budget` characters, each with its absolute range
    of lines. Cuts go before the top-level blocks of the index (or before paragraphs, without an
    index); a block longer than `budget` is cut before its inner blocks, then by lines."""
    lines = _lines(content)
    total = len(lines)
    if not content or total == 0:
        return []
    sizes = [len(line) + 1 for line in lines]
    prefix = [0]
    for size in sizes:
        prefix.append(prefix[-1] + size)

    def size_of(first: int, last: int) -> int:
        return prefix[last] - prefix[first - 1]

    top = sorted({b.start for b in index.blocks if b.top_level and 1 < b.start <= total})
    if not top:
        top = [n for n in range(2, total + 1) if lines[n - 1].strip() and not lines[n - 2].strip()]
    starts = sorted({b.start for b in index.blocks})

    def segments(first: int, last: int, cuts: list[int]) -> list[tuple[int, int]]:
        bounds = [first, *[c for c in cuts if first < c <= last], last + 1]
        return [(a, b - 1) for a, b in pairwise(bounds) if a <= b - 1]

    ranges: list[tuple[int, int]] = []

    def pack(parts: list[tuple[int, int]], depth: int) -> None:
        current: tuple[int, int] | None = None
        for first, last in parts:
            if size_of(first, last) > budget:
                if current is not None:
                    ranges.append(current)
                    current = None
                inner = [s for s in starts if first < s <= last] if depth == 0 else []
                if inner:
                    pack(segments(first, last, inner), 1)
                elif last > first:
                    pack([(n, n) for n in range(first, last + 1)], 2)
                else:  # one line longer than the budget: alone
                    ranges.append((first, last))
                continue
            if current is None:
                current = (first, last)
            elif size_of(current[0], last) <= budget:
                current = (current[0], last)
            else:
                ranges.append(current)
                current = (first, last)
        if current is not None:
            ranges.append(current)

    pack(segments(1, total, top), 0)
    return [("\n".join(lines[a - 1 : b]), (a, b)) for a, b in ranges]


# --- REQ-018: #633, items that are only the ranges of their sections ---------------------------

#: #633: a word that names one block whose range is the answer (`tabla_de_mutantes`).
_BLOCK_WORDS = frozenset({"tabla", "table", "bloque", "block", "diagrama", "diagram"})
#: How far after its heading a range may start and still be the section (its blank line, and one
#: more: `line_check.TOLERANCE`).
_SECTION_SLACK = 2 + line_check.TOLERANCE


def section_only(req: FieldRequest, items: list[Item], index: FileIndex) -> bool:
    """#633: whether a field that asks for items got only the ranges of the sections that hold
    them. It asks for items when its residual has a plural word and no block word and it does not
    ask for sections; the items are only sections when every located one is a range that starts
    at a heading or just after it."""
    if "sections" in req.categories:
        return False
    subject = set(req.residual)
    if subject & _BLOCK_WORDS or not any(word.endswith("s") for word in subject):
        return False
    headings = sorted(b.start for b in index.blocks if b.kind == "section")
    located = [it for it in items if it.start is not None and it.end is not None]
    if not located or not headings:
        return False
    for item in located:
        before = [h for h in headings if h <= item.start]
        if item.end <= item.start or not before or item.start - before[-1] > _SECTION_SLACK:
            return False
    return True
