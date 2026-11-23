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

from dataclasses import dataclass
from typing import Literal

from local_delegate import line_check

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
