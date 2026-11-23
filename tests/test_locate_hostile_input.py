"""REQ-022 against a hostile file: the index stays linear and never takes the call down.

The file `local_extract` reads is untrusted (a cloned repository, a pull request). Each input here
made the index cost grow with the square of its size, or raise, before it was fixed: a quote that
never closes rescanned its line once per quote, a `/` that opens no regex once per `/`, a heading
copied the list of the later headings, and a long `elif` chain recursed past Python's limit.
"""

from __future__ import annotations

import pytest
from linear_cost import MAX_GROWTH, SIZE_RATIO, cpu_growth

from local_delegate import locate

BACKSLASH = chr(92)

# (name, unit repeated on ONE line, file name)
HOSTILE_UNITS = [
    ("single_quote_escapes", "'" + BACKSLASH, "x.ts"),
    ("double_quote_escapes", '"' + BACKSLASH, "x.js"),
    ("regex_classes_never_closed", "(/[", "x.ts"),
]


@pytest.mark.parametrize(
    ("unit", "name"), [(u, n) for _, u, n in HOSTILE_UNITS], ids=[h[0] for h in HOSTILE_UNITS]
)
def test_a_hostile_line_costs_linearly(unit, name):
    small_size = 5_000
    small_text = unit * (small_size // len(unit))
    big_text = unit * (small_size * SIZE_RATIO // len(unit))
    small, big, growth = cpu_growth(
        lambda: locate.build_index(small_text, name), lambda: locate.build_index(big_text, name)
    )
    assert growth < MAX_GROWTH, (small, big, growth)


def test_many_headings_cost_linearly():
    small_text = "# a\n" * 5_000
    big_text = "# a\n" * (5_000 * SIZE_RATIO)
    index = locate.build_index(small_text, "h.md")
    assert sum(b.kind == "section" for b in index.blocks) == 5_000
    small, big, growth = cpu_growth(
        lambda: locate.build_index(small_text, "h.md"),
        lambda: locate.build_index(big_text, "h.md"),
    )
    assert growth < MAX_GROWTH, (small, big, growth)


def test_sections_still_end_before_the_next_heading_of_same_or_higher_level():
    text = "# A\nx\n## B\ny\n### C\nz\n## D\nw\n# E\nv\n"
    sections = {
        b.name: (b.start, b.end)
        for b in locate.build_index(text, "s.md").blocks
        if b.kind == "section"
    }
    assert sections == {
        "# A": (1, 8),
        "## B": (3, 6),
        "### C": (5, 6),
        "## D": (7, 8),
        "# E": (9, 10),
    }


def test_a_long_elif_chain_keeps_the_index():
    chain = "if a:\n    pass\n" + "elif a:\n    pass\n" * 1_500
    text = chain + "\n\ndef after():\n    return 1\n"
    index = locate.build_index(text, "chain.py")
    assert index.unavailable_reason is None
    lines = text.split("\n")
    start = lines.index("def after():") + 1
    assert [(b.name, b.start, b.end) for b in index.blocks] == [("after", start, start + 1)]
