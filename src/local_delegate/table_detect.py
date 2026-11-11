"""Does a text carry a table, and of which format? The rule that sends a small input to `long`.

`local_extract` (#586) and `local_summarize` (#650) send a small input with a table to the long
role. Measured on 22 small inputs: the mechanical model answered with the value of another row in
8 of the 16 that carry a table, and in none of the 6 without one. So the rule is "the input has a
table", nothing about how many fields are asked for or how alike they are. `local_summarize` also
judges the figures of a summary only on an input with an HTML, ARIA or Markdown table (#630; a
CSV or TSV, such as a CI log with tabs, does not open that check).

A text has a table, and `table_format` names it, when it carries:

- `html`: an HTML `<table` or `<tr` tag (any case) followed by a blank, `>` or `/`, so `<track>`
  and `<tablet>` are not tables;
- `aria`: an ARIA table role, `role="table"`, `"grid"`, `"treegrid"` or `"row"` (any quote or
  none, any case): the `<div>` grids that say they are a table;
- `markdown`: a line with two or more `|` followed by a separator line (only `|`, `:`, `-` and
  blanks, with `--` somewhere); or a GFM table: a header line with a `|` followed by a delimiter
  row with a `|`, whose cells are all `-` with an optional `:` at either end and as many as the
  header's, two or more. So `a | b` over `--- | ---` and the compact `|-|-|` are tables;
- `csv` or `tsv`: three or more consecutive lines that each have the same number of commas or
  semicolons (two or more) or tabs (one or more) outside double quotes, and look like rows, not
  like prose or code: no leading blank; no list, quote or comment marker at the start; none of
  `{ } [ ] ; =` (but the delimiter); no `: `; no `(` glued to what comes before it (a call,
  `@(`); no cell with more than 8 words, or 3 when every comma or semicolon is followed by a
  blank, the way prose writes them (a comma between two digits, `4,2` or `1,234`, does not
  count either way), and then no delimiter at the end of the line either (the cut of a wrapped
  list).

The text is looked at as it is: a JSON is not parsed, so a `<tr` inside one of its strings counts,
and so does a tag inside a code block or a diff, or a page that only names `role="row"`. The
error falls on the side of going up; so does a short enumeration of prose on three lines
(`Red, green, blue and pink.`).

What it does not see, on purpose and pinned by tests: a CSV of two columns (one comma per line
is every other line of prose), a CSV whose rows have quoted cells that span lines, a TSV row
whose first cell is empty (it starts with a tab, like indented code), a CSV written with a blank
after each comma whose last cell is empty (`pro, 20,`, the cut of a wrapped list), a CSV cell
with `=`, `[` or `: ` outside quotes (a URL with `?id=5`), a GFM table behind `> ` or a diff's
`+`, `role = "row"` with blanks around `=`, tables aligned with spaces, and `<div>` grids that
only say so with class names (`row`, `cell`, `grid`): those names also lay out pages that hold
no table.

No regular expression and linear in the text's length: the input is not trusted, and the repo
does not let a pattern that can backtrack run on it. Pure, with no import from the package, so it
loads without `server`.
"""

from __future__ import annotations

from itertools import pairwise

__all__ = ["has_table", "table_format"]

#: The HTML tags that make a table. `<td`/`<th` are left out: they never come without a `<tr`.
_TAGS = ("<table", "<tr")

#: What may follow one of `_TAGS` for it to be that tag and not a longer name (`<track>`).
_TAG_ENDS = frozenset(">/")

#: The ARIA roles that make a table (`role="cell"` never comes without a `role="row"`).
_ARIA_ROLES = frozenset({"table", "grid", "treegrid", "row"})

#: The longest role name read after `role=`: a longer word is not one of `_ARIA_ROLES`.
_ARIA_MAX = 8

#: The characters of a Markdown separator line, besides blanks.
_SEPARATOR_CHARS = "|:-"

#: How many consecutive rows make a CSV or TSV: a header and two rows.
_MIN_ROWS = 3

#: (format, delimiter, fewest delimiters per row).
_DELIMITED = (("csv", ",", 2), ("csv", ";", 2), ("tsv", "\t", 1))

#: Outside quotes, any of these makes a line code or data, not a row.
_CODE_CHARS = frozenset("{}[];=")

#: A line that starts with one of these is a list item, a quote, a comment or a heading.
_LINE_MARKERS = ("- ", "* ", "+ ", "> ", "#", "//", "--")

#: The most words a cell may have; when every comma is followed by a blank, the prose cap.
_MAX_CELL_WORDS = 8
_MAX_CELL_WORDS_SPACED = 3

#: The most delimiters a row may have: more is a long line of data or prose, not a row.
_MAX_CELLS = 256


def has_table(text: str) -> bool:
    """`True` if `text` carries a table of any of the formats of `table_format`."""
    return table_format(text) is not None


def table_format(text: str, *, delimited: bool = True) -> str | None:
    """The format of the first kind of table found (`html`, `aria`, `markdown`, `csv`, `tsv`).

    `delimited=False` skips CSV and TSV, the slowest passes, for a caller that does not want them.
    """
    if not text:
        return None
    low = text.lower()
    if _has_tag(low):
        return "html"
    if _has_aria_role(low):
        return "aria"
    lines = text.split("\n")
    if _has_pipe_table(lines):
        return "markdown"
    if not delimited:
        return None
    for name, delimiter, fewest in _DELIMITED:
        if _has_delimited_rows(lines, delimiter, fewest):
            return name
    return None


def _has_tag(low: str) -> bool:
    """An HTML table tag in the lowercased text, followed by a blank, `>` or `/`.

    Each search resumes after the previous match, so the whole scan reads every character a
    bounded number of times: `<tr` repeated a million times is still one pass.
    """
    size = len(low)
    for tag in _TAGS:
        start = low.find(tag)
        while start != -1:
            end = start + len(tag)
            if end < size and (low[end] in _TAG_ENDS or low[end].isspace()):
                return True
            start = low.find(tag, end)
    return False


def _has_aria_role(low: str) -> bool:
    """`role=` followed by one of `_ARIA_ROLES`, quoted or not, and then a quote, blank, `>`, `/`.

    Reads at most `_ARIA_MAX` + 2 characters after each `role=`, and resumes after it: linear.
    """
    size = len(low)
    start = low.find("role=")
    while start != -1:
        index = start + len("role=")
        if index < size and low[index] in "\"'":
            index += 1
        end = index
        while end < size and end - index <= _ARIA_MAX and "a" <= low[end] <= "z":
            end += 1
        closed = end >= size or low[end] in "\"'>/" or low[end].isspace()
        if closed and low[index:end] in _ARIA_ROLES:
            return True
        start = low.find("role=", start + 1)
    return False


def _has_pipe_table(lines: list[str]) -> bool:
    """A Markdown table: the rule of #586 (two `|` and a `--` separator) or a GFM delimiter row."""
    for index in range(len(lines) - 1):
        header, separator = lines[index], lines[index + 1]
        if header.count("|") >= 2 and _is_separator(separator):
            return True
        # The cheap tests first: most lines with a `|` are not over a delimiter row.
        cheap = "-" in separator and "|" in separator and "|" in header
        if cheap and _is_gfm_delimiter(separator, _cell_count(header)):
            return True
    return False


def _is_separator(line: str) -> bool:
    """A Markdown separator line: `--` in it and nothing but `|`, `:`, `-` and blanks."""
    stripped = line.strip()
    if "--" not in stripped:
        return False
    return not stripped.strip(_SEPARATOR_CHARS + " \t")


def _cell_count(line: str) -> int:
    """The cells of a GFM row: its `|` not escaped, without one leading and one trailing `|`."""
    stripped = _strip_outer_pipes(line.strip())
    return stripped.count("|") - stripped.count("\\|") + 1


def _strip_outer_pipes(stripped: str) -> str:
    stripped = stripped.removeprefix("|")
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]
    return stripped


def _is_gfm_delimiter(line: str, header_cells: int) -> bool:
    """A GFM delimiter row: a `|`, and as many cells as the header (two or more) of `-` with `:`."""
    stripped = line.strip()
    if "|" not in stripped or "-" not in stripped or header_cells < 2:
        return False
    cells = _strip_outer_pipes(stripped).split("|")
    if len(cells) != header_cells:
        return False
    for cell in cells:
        body = cell.strip().removeprefix(":").removesuffix(":")
        if not body or body.strip("-"):
            return False
    return True


def _has_delimited_rows(lines: list[str], delimiter: str, fewest: int) -> bool:
    """`_MIN_ROWS` consecutive lines that are rows with the same number of `delimiter`.

    Two steps, so a long text costs C-speed work per line: the raw count of `delimiter` picks
    the runs of lines with the same count, and only the lines of such a run are read as rows
    (each line once). A line with quotes is read at once: its quoted delimiters do not count.
    """
    if not any(delimiter in line for line in lines):
        return False
    checked: dict[int, int | None] = {}

    def row(index: int) -> int | None:
        if index not in checked:
            checked[index] = _row_delimiters(lines[index], delimiter, fewest)
        return checked[index]

    window: list[int] = []
    previous: int | None = None
    for index, line in enumerate(lines):
        if delimiter not in line:
            window, previous = [], None
            continue
        count = row(index) if '"' in line else line.count(delimiter)
        if count is None or count < fewest:
            window, previous = [], None
            continue
        if count != previous:
            window = []
        window.append(index)
        previous = count
        if len(window) >= _MIN_ROWS:
            # Read the run as rows; keep only what follows the last line that is not one.
            bad = [position for position, at in enumerate(window) if row(at) != count]
            if not bad:
                return True
            window = window[bad[-1] + 1 :]
    return False


def _row_delimiters(line: str, delimiter: str, fewest: int) -> int | None:
    """How many `delimiter` a row has outside double quotes, or `None` if the line is not a row.

    The quoted parts are replaced by one word (`Q`), so the rest is read with `str` methods that
    run in C: the delimiters, the marks of code or prose and the words of each cell.
    """
    line = line.rstrip("\r")
    if not line or line[0] in " \t" or line.startswith(_LINE_MARKERS) or _is_numbered(line):
        return None
    # Trailing blanks go, but not a trailing tab: it is the empty last cell of a TSV row.
    line = line.rstrip(" ") if delimiter == "\t" else line.rstrip()
    if '"' in line:
        parts = line.split('"')
        if len(parts) % 2 == 0:
            return None  # a quote left open: a cell that spans lines, or not a row
        line = "Q".join(parts[0::2])
    count = line.count(delimiter)
    if count < fewest or count > _MAX_CELLS:
        return None
    if any(mark in line for mark in _CODE_CHARS if mark != delimiter) or ": " in line:
        return None
    if _has_glued_paren(line, delimiter):
        return None
    cells = line.split(delimiter)
    spaced = True
    for before, cell in pairwise(cells):
        following = cell[:1]
        # A comma between two digits (`4,2`, `1,234`, `10:00:00,123`) says nothing of style.
        numeric = before[-1:].isdigit() and following.isdigit()
        if following and not numeric:
            spaced = spaced and following == " "
    prose = delimiter != "\t" and spaced
    if prose and line.endswith(delimiter):
        # A wrapped list of prose (`a, b, c,` or `a; b;` cut after the delimiter).
        return None
    cap = _MAX_CELL_WORDS_SPACED if prose else _MAX_CELL_WORDS
    if any(len(cell.split()) > cap for cell in cells):
        return None
    return count


def _has_glued_paren(line: str, delimiter: str) -> bool:
    """A `(` glued to what comes before it (a call, `@(`), not after a blank or the delimiter."""
    if line.count("(") > _MAX_CELLS:
        return True
    start = line.find("(")
    while start != -1:
        if start > 0 and not line[start - 1].isspace() and line[start - 1] != delimiter:
            return True
        start = line.find("(", start + 1)
    return False


def _is_numbered(line: str) -> bool:
    """A numbered list item: digits, then `. ` or `) `."""
    rest = line.lstrip("0123456789")
    return len(rest) < len(line) and rest[:2] in (". ", ") ")
