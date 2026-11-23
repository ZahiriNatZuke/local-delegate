"""The fidelity counter finds files and pytest node ids in linear time, with the regex's result.

`scripts/score_lint_fidelity.py` searched a log with `FILE.findall` and a pytest node regex: both
quadratic on a long run without spaces (a `unittest` progress line). At 5 000 dots `log_facts`
took 5 s and `count_inventions` 11 s here. It now goes through `lint_patterns.file_spans` and its
own `pytest_nodes`; a differential fuzz holds `pytest_nodes` equal to the regex.

Each time cap fails on the old code by its time assert: at 20 000 chars it took over a minute.
"""

from __future__ import annotations

import importlib.util
import random
import re
import sys
from pathlib import Path

import perf
import pytest

from local_delegate import lint_patterns

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "score_lint_fidelity.py"
CAP_SECONDS = 2.0
N = 20_000

#: The definition `pytest_nodes` must match (the regex the script used before).
_PYTEST_NODE = re.compile(r"((?:[\w.~-]+[/\\])*[\w.-]+\.py)::(\S+)")


def _load():
    spec = importlib.util.spec_from_file_location("score_lint_fidelity_linear", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


counter = _load()

LONG_RUNS = {
    "dots": lambda n: "." * n,
    "word_dot": lambda n: "a." * (n // 2),
    "dirs_no_extension": lambda n: "dir.v1/" * (n // 7) + "x.pyz",
    "dirs_then_separator": lambda n: "d/" * (n // 2) + "::",
    "word_then_colon": lambda n: "a.py:" * (n // 5),
}


def _score(run: str) -> tuple[dict, dict]:
    log = f"Ran 3 tests\n{run}\nFAILED tests/test_x.py::test_a - E501 line\n"
    facts = counter.log_facts(log)
    return facts, counter.count_inventions("tests/test_x.py fails 1 test " + run, log)


@pytest.mark.perf
@pytest.mark.parametrize("name", sorted(LONG_RUNS))
def test_a_long_run_is_scored_in_linear_time(name):
    small, big = LONG_RUNS[name](N // 10), LONG_RUNS[name](N)
    facts, result = _score(big)
    assert "tests/test_x.py" in facts["files"]
    assert result["invented_files"] == []
    perf.assert_linear(lambda: _score(small), lambda: _score(big), size_ratio=10)


_PIECES = list("ab_9é.-~/\\: \n") + [
    ".py", ".PY", ".pyi", "::", ":::", "py", "/x.", "..", "//", "~/", "a.py::t", "[p]",
]  # fmt: skip


def test_pytest_nodes_are_what_the_regex_finds():
    rng = random.Random(611)
    checked = 0
    for _ in range(30_000):
        text = "".join(rng.choice(_PIECES) for _ in range(rng.randint(0, 24)))
        expected = _PYTEST_NODE.findall(text)
        assert counter.pytest_nodes(text) == expected, text
        checked += bool(expected)
    # Guard: the fuzz reached many texts that do hold a node id.
    assert checked > 5_000


def test_files_in_and_strip_files_are_what_the_regex_gives():
    rng = random.Random(612)
    pieces = list("ab_9.-~/\\: \n") + [".py", ".ts", ".md", "//", "x.json"]
    for _ in range(5_000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 24)))
        assert counter.files_in(text) == lint_patterns.FILE.findall(text), text
        assert counter.strip_files(text) == lint_patterns.FILE.sub(" ", text), text
