"""Cross-filled values in a `local_extract` answer (#650).

The model sometimes hands the rows of a table out to the requested keys almost by position: the key
`licensed_user_limits` gets the cells of the row «Custom domains», which belongs to another
requested key, `custom_domain_limits`. This module finds that case deterministically, from the
source and the answer only, so `local_extract` can WARN about it. It never changes a value.

A key A is flagged when all of this holds:

- its value (a string, a number, or the strings and numbers inside a list or an object) is not
  trivial: no null, no boolean, no "no data" marker, no yes/no word, nothing under two characters
  (so no one-digit number);
- the value comes from cells of exactly ONE labelled row or line of the source (a table row in
  HTML, Markdown, CSV or TSV, a top-level key of a JSON object, or a `label: value` / `label =
  value` line): it is a cell give or take a unit, or it is made of that row's cells and nothing
  else but column headers and units; never a piece of a cell or prose around one (`currency` =
  `USD` from «Price: 49 USD», a `summary` that quotes one cell);
- those cells and the value occur only once in the whole source;
- another requested key B fits that row's label (plus the hit cell's column header) better than A does, and B fits it for real: two shared words, or one when one of
  the two holds all the words of the other (`weight` and «Weight (kg)», not `shipping_cost` and
  «Retail cost (USD)»).

A repeated value stays quiet (a `price` of `39` that also sits in the row of `noise_level`), and so
does a cross from a row no requested key fits (B must exist) or a tie.

Deterministic, standard library only; the regular expressions have no nested quantifiers. The words
of a label are matched as they are, so a label in one language and a key in another share none and
nothing is flagged.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from html.parser import HTMLParser
from typing import Any

#: A source longer than this is not scanned: the warning is a cheap check, never a cost.
MAX_SOURCE_CHARS = 400_000

#: Cells times leaves the check may walk before it gives up on the remaining keys.
_BUDGET = 2_000_000

#: A row label longer than this is cut in the warning: it is the source's text, not the program's.
_LABEL_CHARS = 80

_STOPWORDS = frozenset(
    {
        "a", "al", "de", "del", "el", "la", "las", "los", "lo", "y", "o", "u", "en", "por",
        "para", "con", "sin", "un", "una", "the", "of", "and", "or", "in", "on", "per", "for",
        "with", "without", "to", "an", "by", "at", "is",
    }
)  # fmt: skip

#: Words a value may carry besides the cell it comes from (`49 USD` for the cell `49`), as
#: `words()` leaves them (no plural `s`).
_UNITS = frozenset(
    {
        "usd", "eur", "gbp", "us", "kb", "mb", "gb", "tb", "kg", "mg", "lb", "oz", "mm", "cm",
        "km", "ml", "ft", "inch", "sec", "min", "ms", "hr", "hour", "hora", "day", "dia", "week",
        "semana", "month", "mes", "year", "ano", "db", "mah", "mbp", "rpm", "fp", "px",
        "unit", "unidad", "user", "usuario", "seat", "puesto",
    }
)  # fmt: skip

#: The product's "no data" markers (as `server._NO_DATA_MARKERS`) plus yes/no words: a value that
#: is one of them says nothing about where it came from.
_TRIVIAL = frozenset(
    {
        "", "n/a", "n.a", "n/d", "s/d", "null", "none", "undefined", "unknown", "desconocido",
        "desconocida", "no disponible", "not available", "no consta", "not specified",
        "unspecified", "not found", "no aplica", "not applicable", "sin datos", "no data",
        "-", "--", "---", "?", "yes", "no", "si", "true", "false", "verdadero", "falso",
    }
)  # fmt: skip

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_WORD = re.compile(r"[a-z0-9]+")
_DIGIT_GAP = re.compile(r"(?<=\d)[   ,](?=\d{3}(?!\d))")
_DIGIT_UNIT = re.compile(r"(?<=\d)(?=[a-z])")
_SPACES = re.compile(r"\s+")
_KV_SEPARATORS = (" = ", "=", ": ", ":")
_DASHES = "‐‑‒–—−"


def _fold(text: str) -> str:
    """Lower case, no accents, every dash a hyphen."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    for dash in _DASHES:
        text = text.replace(dash, "-")
    return text.lower()


def _norm(text: str) -> str:
    """Folded text with `6 000`/`6,000` as `6000`, `90s` as `90 s` and single spaces."""
    text = _DIGIT_GAP.sub("", _fold(text))
    text = _DIGIT_UNIT.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def words(name: str) -> frozenset[str]:
    """Content words of a key or a label: snake/camel case split, folded, no stopwords, plural
    `s` dropped (`es` after ch/sh/x/ss, `ies` as `y`)."""
    out = set()
    for word in _WORD.findall(_fold(_CAMEL.sub(" ", name))):
        if word in _STOPWORDS or len(word) < 2:
            continue
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 4 and word.endswith(("ches", "shes", "xes", "sses")):
            word = word[:-2]
        elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.add(word)
    return frozenset(out)


def _trivial(text: str) -> bool:
    folded = _norm(text).removesuffix(".").strip()
    return len(folded) < 2 or folded in _TRIVIAL


def _leaves(value: Any) -> list[str]:
    """The strings and numbers of a value; booleans, nulls and trivial values are left out."""
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        # An int is never turned into a float: one of 400 digits would overflow.
        whole_float = isinstance(value, float) and value.is_integer()
        text = str(int(value)) if whole_float else str(value)
        return [] if _trivial(text) else [text]
    if isinstance(value, str):
        return [] if _trivial(value) else [value]
    if isinstance(value, dict):
        return [leaf for item in value.values() for leaf in _leaves(item)]
    if isinstance(value, list):
        return [leaf for item in value for leaf in _leaves(item)]
    return []


class _Html(HTMLParser):
    """Rows of every `<table>` (cells with their `<th>` flag) and the page's whole text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[str, bool]]] = []
        self.text: list[str] = []
        self._row: list[tuple[str, bool]] | None = None
        self._cell: list[str] | None = None
        self._th = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell, self._th = [], tag == "th"
        self.text.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append((_SPACES.sub(" ", "".join(self._cell)).strip(), self._th))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
        self.text.append(" ")

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self._cell is not None:
            self._cell.append(data)


def _grid_rows(grid: list[list[str]], header: list[str] | None) -> list[dict]:
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


def _is_md_rule(line: str) -> bool:
    """A Markdown table rule (`|---|:--:|`, `---|---`, `|-|-|`)."""
    return "-" in line and "|" in line and not line.strip().strip("|:- \t")


def _delimited_rows(lines: list[str]) -> tuple[list[dict], str] | None:
    """A CSV or TSV source: most non-empty lines carry the same number of tabs, or commas. The
    text to count in has its cells apart: a comma between cells is not a decimal comma."""
    filled = [line for line in lines if line.strip()]
    if len(filled) < 2:
        return None
    for delimiter in ("\t", ",", ";"):
        counts = [len(row) for row in csv.reader(filled, delimiter=delimiter)]
        width = max(set(counts), key=counts.count)
        if width >= 2 and counts.count(width) >= 0.8 * len(counts):
            grid = [
                [cell.strip() for cell in row] for row in csv.reader(filled, delimiter=delimiter)
            ]
            plain = "\n".join(" ; ".join(row) for row in grid)
            grid = [row for row in grid if len(row) == width]
            return _grid_rows(grid[1:], grid[0]), plain
    return None


def labelled_rows(source: str) -> tuple[list[dict], str]:
    """Every labelled row or line of the source, `{"label", "cells": [(text, column)]}`, and the
    source's text (an HTML page without its tags) to count occurrences in."""
    stripped = source.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except ValueError:
            data = None
        if isinstance(data, dict):
            rows = []
            for key, value in data.items():
                text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                rows.append({"label": str(key), "cells": [(text, "")]})
            return rows, source
    rows: list[dict] = []
    plain = source
    if "<tr" in source.lower() or "<td" in source.lower():
        parser = _Html()
        parser.feed(source)
        parser.close()
        plain = "".join(parser.text)
        header: list[str] | None = None
        grid: list[list[str]] = []
        for row in parser.rows:
            if all(th for _text, th in row):
                rows.extend(_grid_rows(grid, header))
                header, grid = [text for text, _th in row], []
            else:
                grid.append([text for text, _th in row])
        rows.extend(_grid_rows(grid, header))
    lines = source.split("\n")
    if "|" not in source and "<" not in source:
        delimited = _delimited_rows(lines)
        if delimited is not None:
            return delimited
    header = None
    grid = []
    for index, line in enumerate(lines):
        text = line.strip()
        if "|" in text and text.count("|") >= (1 if not text.startswith("|") else 2):
            following = lines[index + 1].strip() if index + 1 < len(lines) else ""
            if _is_md_rule(text):
                continue
            if header is not None or grid or _is_md_rule(following):
                cells = [cell.strip() for cell in text.strip().strip("|").split("|")]
                if _is_md_rule(following):
                    rows.extend(_grid_rows(grid, header))
                    header, grid = cells, []
                else:
                    grid.append(cells)
                continue
        if grid or header is not None:
            rows.extend(_grid_rows(grid, header))
            header, grid = None, []
        if not text or text.startswith(("<", "#")):
            continue
        for separator in _KV_SEPARATORS:
            label, found, value = text.lstrip("-*• ").partition(separator)
            if found and value.strip() and 0 < len(label) <= 60 and len(label.split()) <= 6:
                rows.append({"label": label.strip(), "cells": [(value.strip(), "")]})
                break
    rows.extend(_grid_rows(grid, header))
    return rows, plain


def _bounded_count(needle: str, haystack: str) -> int:
    """How many times `needle` sits in `haystack`, not glued to a letter, a digit or a decimal."""
    count, start = 0, 0
    while True:
        at = haystack.find(needle, start)
        if at < 0:
            return count
        end = at + len(needle)
        before = haystack[at - 1] if at else " "
        before2 = haystack[at - 2] if at > 1 else " "
        after = haystack[end] if end < len(haystack) else " "
        after2 = haystack[end + 1] if end + 1 < len(haystack) else " "
        glued_before = before.isalnum() or (before in ".," and before2.isdigit())
        glued_after = after.isalnum() or (after in ".," and after2.isdigit())
        if not glued_before and not glued_after:
            count += 1
        start = at + 1


def _cut(haystack: str, needle: str) -> str:
    """`haystack` without its bounded occurrences of `needle`."""
    out, start = [], 0
    while True:
        at = haystack.find(needle, start)
        if at < 0:
            out.append(haystack[start:])
            return " ".join(out)
        if _bounded_count(needle, haystack[max(0, at - 2) : at + len(needle) + 2]):
            out.append(haystack[start:at])
            start = at + len(needle)
        else:
            out.append(haystack[start : at + 1])
            start = at + 1


def _only_units(text: str, allowed: frozenset[str] = frozenset()) -> bool:
    """Whether `text` has nothing left but units, currency signs, punctuation or `allowed` words."""
    if any(ch.isdigit() for ch in text):
        return False
    return all(word in _UNITS or word in allowed for word in words(text))


#: Short forms a label uses for a key's word (`Max load` for `maximum_load`).
_SHORT = {"max": "maximum", "qty": "quantity", "num": "number"}


def _label_words(text: str) -> frozenset[str]:
    return frozenset(_SHORT.get(word, word) for word in words(text))


def _row_hits(value: str, cells: list[tuple[str, str, str]], headers: frozenset[str], item: bool):
    """The `(cell, column)` of one row that `value` comes from, or `[]`.

    - the value is a cell, give or take a unit (`49` and `49 USD`);
    - the value is made of cells of the row and nothing else but the column headers, the row's
      words and units
      (`1-5 (Standard), 1-3 per region (Enterprise)`), never prose around one cell;
    - an item of a list value is one comma-separated item of a cell (`Jira` in `Slack, Jira`).
    """
    v = _norm(value)
    if len(v) < 2:
        return []
    inside = []
    for cell, c, column in cells:
        if v == c:
            return [(cell, column)]
        if len(c) >= 2 and _bounded_count(v, c) and _only_units(_cut(c, v)):
            return [(cell, column)]
        if item and any(part.strip() == v for part in re.split(r"[,;/]", c)):
            return [(cell, column)]
        if len(c) >= 2 and _bounded_count(c, v):
            inside.append((cell, c, column))
    if not inside:
        return []
    rest = v
    for _cell, c, _column in sorted(inside, key=lambda hit: -len(hit[1])):
        rest = _cut(rest, c)
    if not _only_units(rest, headers):
        return []
    return [(cell, column) for cell, _c, column in inside]


def _fits(key: frozenset[str], label: frozenset[str]) -> int:
    """How well a key fits a label: shared words, or 0 when one shared word is a mere accident
    (it counts only if one of the two holds all the words of the other)."""
    shared = len(key & label)
    if shared >= 2 or (shared == 1 and (key <= label or label <= key)):
        return shared
    return 0


def _scan(source: str, fields: list[str], data: dict, skip: frozenset[str]) -> dict[str, dict]:
    rows, plain = labelled_rows(source)
    if not rows:
        return {}
    plain_norm = _norm(plain)
    # Normalized once: the check walks rows x cells x leaves.
    for row in rows:
        row["norm"] = [
            (cell, _norm(cell), column) for cell, column in row["cells"] if not _trivial(cell)
        ]
        # What a value made of this row's cells may carry besides them: the column headers and
        # the words of the row's own cells (`per region` twice where the cell says it once).
        row["headers"] = frozenset(
            w for cell, column in row["cells"] for w in words(column) | words(cell)
        )
    budget = _BUDGET
    names = list(dict.fromkeys(name for name in fields if isinstance(name, str)))
    key_words = {name: _label_words(name) for name in names}
    flagged: dict[str, dict] = {}
    for name in names:
        value = data.get(name)
        leaves = _leaves(value)
        if name in skip or not leaves or not key_words[name]:
            continue
        budget -= len(leaves) * sum(len(row["norm"]) for row in rows)
        if budget < 0:
            break
        item = isinstance(value, (list, dict))
        hit_rows = []
        for row in rows:
            hits = [
                hit for leaf in leaves for hit in _row_hits(leaf, row["norm"], row["headers"], item)
            ]
            if hits:
                hit_rows.append((row, hits))
        if len(hit_rows) != 1:
            continue
        row, hits = hit_rows[0]
        texts = {_norm(cell) for cell, _column in hits} | {_norm(leaf) for leaf in leaves}
        if any(_bounded_count(text, plain_norm) > 1 for text in texts):
            continue
        if any(_bounded_count(_norm(cell), plain_norm) != 1 for cell, _column in hits):
            continue
        # The hit cell's column names it too (`Pro`, `Q2`); a generic one («Value») shares at most
        # one word with a key, which `_fits` does not count.
        label_words = _label_words(row["label"])
        for _cell, column in hits:
            label_words |= _label_words(column)
        mine = len(key_words[name] & label_words)
        best, best_key = mine, None
        for other in names:
            score = _fits(key_words[other], label_words) if other != name else 0
            if score > best:
                best, best_key = score, other
        if best_key is not None:
            label = row["label"]
            if len(label) > _LABEL_CHARS:
                label = label[: _LABEL_CHARS - 1] + "…"
            flagged[name] = {"row": label, "other_key": best_key}
    return flagged


def cross_filled(
    source: str, fields: list[str], data: dict, skip: list[str] | tuple[str, ...] = ()
) -> dict[str, dict]:
    """`{key: {"row": label, "other_key": B}}` for each requested key whose value sits only in
    the row of another requested key. `skip` are keys not to check (the location fields, whose
    `10-14` would hit a cell `14`). Empty when nothing is flagged, the source is too big, or the
    source cannot be read: a warning never breaks the answer."""
    if not source or len(source) > MAX_SOURCE_CHARS or len(fields) < 2:
        return {}
    try:
        return _scan(source, fields, data, frozenset(skip))
    except (ValueError, RecursionError, OverflowError, AssertionError, csv.Error):
        return {}
