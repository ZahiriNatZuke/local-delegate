"""Does a text carry a table? The rule that sends a small `local_extract` input to `long` (#586).

Measured on 22 small inputs: the mechanical model answered with the value of another row in 8 of
the 16 that carry a table, and in none of the 6 without one. So the rule is "the input has a
table", nothing about how many fields are asked for or how alike they are.

A text has a table when it carries:

- an HTML `<table` or `<tr` tag (any case) followed by a blank, `>` or `/`, so `<track>` and
  `<tablet>` are not tables; or
- a line with two or more `|` followed by a separator line: only `|`, `:`, `-` and blanks, with
  `--` somewhere (a Markdown table).

The text is looked at as it is: a JSON is not parsed, so a `<tr` inside one of its strings counts,
and so does a tag inside a code block or a diff. The error falls on the side of going up.

What it does not see, on purpose and pinned by tests: CSV, TSV, a GFM table without outer pipes
(one `|` per line), the separator `|-|-|` (no `--`) and grids made of `<div>`.

No regular expression and linear in the text's length: the input is not trusted, and the repo
does not let a pattern that can backtrack run on it. Pure, with no import from the package, so it
loads without `server` and can serve `local_summarize` too when that is measured (decision D3).
"""

from __future__ import annotations

__all__ = ["has_table"]

#: The HTML tags that make a table. `<td`/`<th` are left out: they never come without a `<tr`.
_TAGS = ("<table", "<tr")

#: What may follow one of `_TAGS` for it to be that tag and not a longer name (`<track>`).
_TAG_ENDS = frozenset(">/")

#: The characters of a Markdown separator line, besides blanks.
_SEPARATOR_CHARS = "|:-"


def has_table(text: str) -> bool:
    """`True` if `text` carries an HTML table tag or a Markdown table with its separator line."""
    if not text:
        return False
    return _has_tag(text.lower()) or _has_pipe_table(text)


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


def _has_pipe_table(text: str) -> bool:
    """A line with two or more `|` followed by a separator line (only `|:-` and blanks, with `--`)."""
    lines = text.split("\n")
    for index in range(len(lines) - 1):
        if lines[index].count("|") >= 2 and _is_separator(lines[index + 1]):
            return True
    return False


def _is_separator(line: str) -> bool:
    """A Markdown separator line: `--` in it and nothing but `|`, `:`, `-` and blanks."""
    stripped = line.strip()
    if "--" not in stripped:
        return False
    return not stripped.strip(_SEPARATOR_CHARS + " \t")
