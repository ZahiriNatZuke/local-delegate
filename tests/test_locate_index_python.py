"""REQ-003 and REQ-022: the Python index of `locate`, by `ast`, with exact lines.

Every expected line is found in the text by a unique marker, never written by hand, so a shifted
index (one more, one less) fails.
"""

from __future__ import annotations

import perf
import pytest

from local_delegate import locate

SOURCE = '''"""Module docstring."""

import functools

LIMIT = 10
first, second = 1, 2
TABLE: dict[str, int] = {
    "a": 1,
}


@functools.cache
@staticmethod
def decorated(x):
    # a comment inside
    return x  # end decorated


async def fetch(url):
    return url  # end fetch


class Outer:
    """Doc."""

    value = 3

    @property
    def name(self):
        return "o"  # end name

    class Inner:
        def deep(self):
            def helper():
                return 1  # end helper

            return helper()  # end deep

    async def run(self):
        pass  # end run


if True:
    def guarded():
        return 0  # end guarded
'''

LINES = SOURCE.split("\n")


def _line(marker: str) -> int:
    hits = [n for n, line in enumerate(LINES, 1) if marker in line]
    assert len(hits) == 1, marker
    return hits[0]


def _blocks():
    index = locate.build_index(SOURCE, "pkg/mod.py")
    assert index.language == "python"
    assert index.unavailable_reason is None
    return index, {b.name: b for b in index.blocks}


def test_functions_classes_and_methods_at_any_depth():
    _, blocks = _blocks()
    expected = {
        "decorated": ("function", "@functools.cache", "# end decorated"),
        "fetch": ("function", "async def fetch", "# end fetch"),
        "Outer": ("class", "class Outer", "# end run"),
        "Outer.name": ("method", "@property", "# end name"),
        "Outer.Inner": ("class", "class Inner", "# end deep"),
        "Outer.Inner.deep": ("method", "def deep", "# end deep"),
        "Outer.Inner.deep.helper": ("function", "def helper", "# end helper"),
        "Outer.run": ("method", "async def run", "# end run"),
        "guarded": ("function", "def guarded", "# end guarded"),
    }
    for name, (kind, first, last) in expected.items():
        block = blocks[name]
        assert (block.kind, block.start, block.end) == (kind, _line(first), _line(last)), name


def test_module_assignments_are_variables():
    _, blocks = _blocks()
    assert (blocks["LIMIT"].kind, blocks["LIMIT"].start, blocks["LIMIT"].end) == (
        "variable",
        _line("LIMIT = 10"),
        _line("LIMIT = 10"),
    )
    assert blocks["first"].start == blocks["second"].start == _line("first, second")
    assert (blocks["TABLE"].start, blocks["TABLE"].end) == (_line("TABLE:"), _line("TABLE:") + 2)
    # a class attribute is not a module assignment
    assert "value" not in blocks and "Outer.value" not in blocks


def test_blocks_are_in_file_order_and_top_level_is_marked():
    index, blocks = _blocks()
    starts = [b.start for b in index.blocks]
    assert starts == sorted(starts)
    assert blocks["decorated"].top_level and blocks["Outer"].top_level
    assert not blocks["Outer.name"].top_level


def test_comment_lines_are_whole_comment_lines_only():
    index, _ = _blocks()
    assert _line("# a comment inside") in index.comment_lines
    assert _line("# end decorated") not in index.comment_lines  # code before the comment
    assert _line('"""Module docstring."""') not in index.comment_lines


def test_syntax_error_gives_no_index():
    index = locate.build_index("def broken(:\n    pass\n", "x.py")
    assert index.language == "python"
    assert index.blocks == ()
    assert index.unavailable_reason == "syntax_error"


@pytest.mark.perf
def test_a_large_module_costs_linearly():
    def module(count: int) -> str:
        return "".join(f"def f{k}(a):\n    return a + {k}\n\n\n" for k in range(count))

    small, big = module(1200), module(12000)
    assert len(big) > 300_000
    assert len(locate.build_index(big, "big.py").blocks) == 12000
    perf.assert_linear(
        lambda: locate.build_index(small, "big.py"),
        lambda: locate.build_index(big, "big.py"),
        size_ratio=10,
    )
