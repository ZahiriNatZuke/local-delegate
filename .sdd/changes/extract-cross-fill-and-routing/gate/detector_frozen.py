"""Prototype of the cross-fill detector for `local_extract` (#586). Research only: not in `src/`.

Question it answers, per requested key A with a non-null value V: does V sit, literally, in a
labelled row/line of the source that belongs to ANOTHER requested key rather than to A?

Three variants, measured side by side in `evaluate.py`:

- `strict`  (the proposal): V is found only in rows whose label fits another requested key B better
  than it fits A (more shared words), and in no row where A is a best fit.
- `loose`:  V is found only in rows whose label shares no word with A, whether or not another
  requested key fits them (catches a neighbour row nobody asked for; flags synonyms too).
- `partial`: `strict`, plus rows that fit A only in part both ways (A has words the label lacks
  and the label has words A lacks) when A has no fully fitting row.

Deterministic, standard library only; the regular expressions have no nested quantifiers.
"""

from __future__ import annotations

import json
import re
import unicodedata
from html.parser import HTMLParser
from typing import Any

STOPWORDS = frozenset(
    "a al de del el la las los lo y o u en por para con sin un una "
    "the of and or in on per for with without to an by at is".split()
)

#: The product's "no data" markers (server.py `_NO_DATA_MARKERS`), so a proxy answer is read as the
#: product would return it.
NO_DATA_MARKERS = frozenset(
    {
        "", "n/a", "n.a", "n/d", "s/d", "null", "undefined", "unknown", "desconocido", "desconocida",
        "no disponible", "not available", "no consta", "no especificado", "no especificada",
        "not specified", "unspecified", "no mencionado", "no mencionada", "not mentioned",
        "not found", "no encontrado", "no encontrada", "no aplica", "not applicable", "sin datos",
        "sin dato", "no data", "sin información", "sin informacion", "no information", "-", "---",
        "—", "–", "?", "…",
    }
)  # fmt: skip

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_WORD = re.compile(r"[a-z0-9]+")
_DIGIT_GAP = re.compile(r"(?<=\d)[   ,](?=\d{3}(?!\d))")
_DIGIT_UNIT = re.compile(r"(?<=\d)(?=[a-z])")
_SPACES = re.compile(r"\s+")
_KV_SEPARATORS = (" = ", "=", ": ", ":")

#: A cell longer than this is prose (the `body` of a JSON, a sentence after a colon), not the value
#: of a row: an answer that is a piece of it (`#412` inside a PR body) is not a hit. Added after
#: the first run flagged exactly that case; `None` turns the guard off, to measure without it.
LONG_CELL_CHARS: int | None = 60


def fold(text: str) -> str:
    """Lower case, no accents, every dash a hyphen."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    for dash in "‐‑‒–—−":
        text = text.replace(dash, "-")
    return text.lower()


def norm_value(text: str) -> str:
    """Folded text with `6 000`/`6,000` as `6000`, `90s` as `90 s` and single spaces."""
    text = fold(text)
    text = _DIGIT_GAP.sub("", text)
    text = _DIGIT_UNIT.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def _is_md_separator(line: str) -> bool:
    """A Markdown table rule (`|---|:--:|`): only pipes, colons, hyphens and blanks, with `--`."""
    return "--" in line and not line.strip().strip("|:- 	")


def is_marker(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip().casefold()
    text = text.removesuffix(".").rstrip() or text
    return text in NO_DATA_MARKERS


def words(name: str) -> frozenset[str]:
    """Content words of a key or of a label: split, folded, no stopwords, plural `s` dropped."""
    out = set()
    for word in _WORD.findall(fold(_CAMEL.sub(" ", name))):
        if word in STOPWORDS or len(word) < 2:
            continue
        if len(word) > 3 and word.endswith("s"):
            word = word[:-1]
        out.add(word)
    return frozenset(out)


class _Tables(HTMLParser):
    """Rows of every `<table>`: a list of (text, is_header_cell) per `<tr>`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[str, bool]]] = []
        self._row: list[tuple[str, bool]] | None = None
        self._cell: list[str] | None = None
        self._th = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell, self._th = [], tag == "th"

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append((_SPACES.sub(" ", "".join(self._cell)).strip(), self._th))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _table_rows(grid: list[list[str]], header: list[str] | None) -> list[dict]:
    rows = []
    for cells in grid:
        if len(cells) < 2:
            continue
        rows.append(
            {
                "label": cells[0],
                "cells": [
                    (text, header[i + 1] if header and i + 1 < len(header) else "")
                    for i, text in enumerate(cells[1:])
                ],
            }
        )
    return rows


def labelled_rows(source: str) -> list[dict]:
    """Every labelled row or line of the source: `{"label", "cells": [(text, column_label)]}`."""
    rows: list[dict] = []
    # A JSON object: each top-level key labels its value.
    stripped = source.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except ValueError:
            data = None
        if isinstance(data, dict):
            for key, value in data.items():
                text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                rows.append({"label": str(key), "cells": [(text, "")]})
            return rows
    # HTML tables.
    if "<tr" in source.lower():
        parser = _Tables()
        parser.feed(source)
        header: list[str] | None = None
        grid: list[list[str]] = []
        for row in parser.rows:
            if all(th for _text, th in row):
                rows.extend(_table_rows(grid, header))
                header, grid = [text for text, _th in row], []
            else:
                grid.append([text for text, _th in row])
        rows.extend(_table_rows(grid, header))
    # Markdown tables and `label: value` / `label = value` lines.
    header = None
    grid = []
    lines = source.split("\n")
    for index, line in enumerate(lines):
        text = line.strip()
        if text.startswith("|") and text.count("|") >= 2:
            cells = [cell.strip() for cell in text.strip("|").split("|")]
            if _is_md_separator(text):
                continue
            following = lines[index + 1].strip() if index + 1 < len(lines) else ""
            if _is_md_separator(following) and "|" in following:
                rows.extend(_table_rows(grid, header))
                header, grid = cells, []
            else:
                grid.append(cells)
            continue
        if grid or header:
            rows.extend(_table_rows(grid, header))
            header, grid = None, []
        if not text or text.startswith(("<", "#", "|")):
            continue
        for separator in _KV_SEPARATORS:
            label, found, value = text.partition(separator)
            if found and value.strip() and 0 < len(label) <= 60 and len(label.split()) <= 6:
                rows.append({"label": label.strip(), "cells": [(value.strip(), "")]})
                break
    rows.extend(_table_rows(grid, header))
    return rows


def _bounded(needle: str, haystack: str) -> bool:
    """`needle` inside `haystack`, not glued to a letter, a digit or a decimal on either side."""
    start = 0
    while True:
        at = haystack.find(needle, start)
        if at < 0:
            return False
        before = haystack[at - 1] if at else " "
        after = haystack[at + len(needle)] if at + len(needle) < len(haystack) else " "
        after2 = haystack[at + len(needle) + 1] if at + len(needle) + 1 < len(haystack) else " "
        before2 = haystack[at - 2] if at > 1 else " "
        glued_before = before.isalnum() or (before in ".," and before2.isdigit())
        glued_after = after.isalnum() or (after in ".," and after2.isdigit())
        if not glued_before and not glued_after:
            return True
        start = at + 1


def _leaves(value: Any) -> list[str]:
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [str(int(value)) if float(value).is_integer() else str(value)]
    if isinstance(value, str):
        return [] if is_marker(value) else [value]
    if isinstance(value, dict):
        return [leaf for item in value.values() for leaf in _leaves(item)]
    if isinstance(value, list):
        return [leaf for item in value for leaf in _leaves(item)]
    return []


def value_hits_cell(value: str, cell: str) -> bool:
    """Whether the answer `value` carries the text of `cell`, or is a piece of it."""
    v, c = norm_value(value), norm_value(cell)
    if not v or not c or is_marker(cell):
        return False
    if v == c:
        return True
    numeric_cell = c.replace(".", "").isdigit()
    if (len(c) >= 2 or numeric_cell) and _bounded(c, v):
        return True
    numeric_value = v.replace(".", "").isdigit()
    short_cell = LONG_CELL_CHARS is None or len(c) <= LONG_CELL_CHARS
    if len(v) >= 3 and short_cell and _bounded(v, c):
        return True
    return numeric_value and c.startswith(v + " ")


def detect(source: str, fields: list[str], data: dict) -> dict[str, dict]:
    """`{variant: {key: {"row": label, "other_key": B | None}}}` for the keys each variant flags."""
    rows = labelled_rows(source)
    key_words = {name: words(name) for name in fields}
    flagged: dict[str, dict] = {"strict": {}, "loose": {}, "partial": {}}
    for name in fields:
        leaves = _leaves(data.get(name))
        if not leaves:
            continue
        own = False  # V sits in a row where A is a best fit
        any_mine = False  # V sits in a row whose label shares a word with A
        full = False  # ... and that row's label is covered by A, or covers A
        zero_rows: list[str] = []  # rows V sits in whose label shares no word with A
        foreign: list[tuple[str, str]] = []  # (row label, the key that fits it better)
        partial_rows: list[str] = []
        for row in rows:
            for cell, column in row["cells"]:
                if not any(value_hits_cell(leaf, cell) for leaf in leaves):
                    continue
                label_words = words(row["label"]) | words(column)
                mine = len(key_words[name] & label_words)
                best_other, best_key = 0, None
                for other in fields:
                    if other == name:
                        continue
                    score = len(key_words[other] & label_words)
                    if score > best_other:
                        best_other, best_key = score, other
                if mine == 0:
                    zero_rows.append(row["label"])
                else:
                    any_mine = True
                if best_other > mine:
                    foreign.append((row["label"], best_key))
                elif mine > 0:
                    own = True
                    row_words = words(row["label"])
                    if key_words[name] <= label_words or row_words <= key_words[name]:
                        full = True
                    else:
                        partial_rows.append(row["label"])
        if foreign and not own:
            flagged["strict"][name] = {"row": foreign[0][0], "other_key": foreign[0][1]}
            flagged["partial"][name] = flagged["strict"][name]
        elif partial_rows and not full:
            flagged["partial"][name] = {"row": partial_rows[0], "other_key": None}
        if name in flagged["strict"]:
            flagged["loose"][name] = flagged["strict"][name]
        elif zero_rows and not any_mine:
            flagged["loose"][name] = {"row": zero_rows[0], "other_key": None}
    return flagged
