"""Does a text carry a table, and of which format? The rule that sends a small input to `long`.

`local_extract` (#586) and `local_summarize` (#650) send a small input with a table to the long
role. Measured on 22 small inputs: the mechanical model answered with the value of another row in
8 of the 16 that carry a table, and in none of the 6 without one. So the rule is "the input has a
table", nothing about how many fields are asked for or how alike they are. `local_summarize` also
judges the figures of a summary only on an input with a table (#630).

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
  blank, the way prose writes them, and then no delimiter at the end of the line either (the
  cut of a wrapped list); and with semicolons, no `;` at the end of the line (a statement).

The text is looked at as it is: a JSON is not parsed, so a `<tr` inside one of its strings counts,
and so does a tag inside a code block or a diff. The error falls on the side of going up.

What it does not see, on purpose and pinned by tests: a CSV of two columns (one comma per line
is every other line of prose), a CSV whose rows have quoted cells that span lines, a TSV row
whose first cell is empty (it starts with a tab, like indented code), a CSV written with a blank
after each comma whose last cell is empty (`pro, 20,`, the cut of a wrapped list), tables
aligned with spaces, and `<div>` grids that only say so with class names
(`row`, `cell`, `grid`): those names also lay out pages that hold no table.

No regular expression and linear in the text's length: the input is not trusted, and the repo
does not let a pattern that can backtrack run on it. Pure, with no import from the package, so it
loads without `server`.
"""

from __future__ import annotations

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


def has_table(text: str) -> bool:
    """`True` if `text` carries a table of any of the formats of `table_format`."""
    return table_format(text) is not None


def table_format(text: str) -> str | None:
    """The format of the first kind of table found (`html`, `aria`, `markdown`, `csv`, `tsv`)."""
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
    """`_MIN_ROWS` consecutive lines that are rows with the same number of `delimiter`."""
    if not any(delimiter in line for line in lines):
        return False
    run = 0
    previous: int | None = None
    for line in lines:
        count = _row_delimiters(line, delimiter, fewest) if delimiter in line else None
        if count is None:
            run, previous = 0, None
            continue
        run = run + 1 if count == previous else 1
        previous = count
        if run >= _MIN_ROWS:
            return True
    return False


def _row_delimiters(line: str, delimiter: str, fewest: int) -> int | None:
    """How many `delimiter` a row has outside double quotes, or `None` if the line is not a row.

    One pass over the line: the quote state, the delimiters, the words of the current cell and
    the marks of code or prose.
    """
    line = line.rstrip("\r")
    if not line or line[0] in " \t" or line.startswith(_LINE_MARKERS) or _is_numbered(line):
        return None
    # Trailing blanks go, but not a trailing tab: it is the empty last cell of a TSV row.
    line = line.rstrip(" ") if delimiter == "\t" else line.rstrip()
    last = len(line) - 1
    count = 0
    spaced = True
    quoted = False
    words = 0
    most_words = 0
    in_word = False
    previous = ""
    for index, char in enumerate(line):
        if char == '"':
            quoted = not quoted
        elif quoted:
            pass
        elif char == delimiter:
            count += 1
            if index < last:
                spaced = spaced and line[index + 1] == " "
            most_words = max(most_words, words)
            words, in_word = 0, False
            previous = char
            continue
        elif _is_code_mark(char, line[index + 1 : index + 2], previous, delimiter):
            return None
        if not quoted and not char.isspace():
            if not in_word:
                words += 1
                in_word = True
        elif not quoted:
            in_word = False
        previous = char
    if quoted or count < fewest:
        return None
    prose = delimiter != "\t" and spaced
    if (prose or delimiter == ";") and line.endswith(delimiter):
        # A wrapped list of prose (`a, b, c,` cut after a comma) or a statement that ends in `;`.
        return None
    most_words = max(most_words, words)
    cap = _MAX_CELL_WORDS_SPACED if prose else _MAX_CELL_WORDS
    if most_words > cap:
        return None
    return count


def _is_code_mark(char: str, following: str, previous: str, delimiter: str) -> bool:
    """Outside quotes, a mark of code or prose: `{ } [ ] ; =`, `: ` or a `(` glued to a word."""
    if char in _CODE_CHARS:
        return True
    if char == ":":
        return following == " "
    return char == "(" and bool(previous) and not previous.isspace() and previous != delimiter


def _is_numbered(line: str) -> bool:
    """A numbered list item: digits, then `. ` or `) `."""
    index = 0
    while index < len(line) and line[index].isdigit():
        index += 1
    return 0 < index and line[index : index + 2] in (". ", ") ")
