"""`table_detect.has_table`: the rule that sends a small `local_extract` input to `long` (#586).

REQ-007 to REQ-010 of the SDD change `extract-cross-fill-and-routing`. The cases are the invented
inputs of its research (`tests/fixtures/extract_table_routing/`), annotated by hand with whether
they carry a table; the hostile inputs run in a child process with a hard cap, so a rule that
backtracks fails the test instead of hanging the suite.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import local_delegate
from local_delegate.table_detect import has_table

FIXTURES = Path(__file__).parent / "fixtures" / "extract_table_routing"
REPO = Path(__file__).resolve().parent.parent
_SRC = str(Path(local_delegate.__file__).resolve().parent.parent)

#: The hard cap of a child process: a backtracking rule takes far longer than this.
_CHILD_CAP_S = 10.0
#: REQ-009: each hostile input of 1 000 000 characters is resolved in less than this.
_HOSTILE_LIMIT_S = 1.0


def _cases() -> list[dict]:
    return json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))["cases"]


def _source(case: dict) -> str:
    return (FIXTURES / case["file"]).read_text(encoding="utf-8")


def _small_cases() -> list[dict]:
    return [case for case in _cases() if not case.get("large")]


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = _SRC + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


# --- The fixtures: the count the plan asks for (T2) --------------------------------------------


def test_the_fixtures_hold_the_research_set():
    cases = _cases()
    small = _small_cases()
    assert len(cases) == 26
    assert sum(len(case["fields"]) for case in cases) == 130
    assert len(small) == 22
    assert sum(1 for case in small if case["has_table"]) == 16
    for case in cases:
        assert (FIXTURES / case["file"]).is_file(), case["file"]


# --- REQ-008: what is a table -----------------------------------------------------------------


@pytest.mark.parametrize("case", _small_cases(), ids=lambda case: case["id"])
def test_the_small_cases_split_sixteen_with_table_and_six_without(case):
    assert has_table(_source(case)) is case["has_table"]


def test_the_split_is_sixteen_and_six():
    verdicts = [has_table(_source(case)) for case in _small_cases()]
    assert verdicts.count(True) == 16
    assert verdicts.count(False) == 6


def test_a_markdown_table_is_a_table():
    case = next(case for case in _cases() if case["id"] == "06-limits-table-es")
    assert has_table(_source(case)) is True
    assert has_table("| Plan | Seats |\n| --- | --- |\n| Basic | 5 |\n") is True
    assert has_table("Plan | Seats | Price\n:--|--:|:-:\nBasic | 5 | 9\n") is True


def test_a_markdown_table_with_crlf_lines_is_a_table():
    assert has_table("| Plan | Seats |\r\n| --- | --- |\r\n| Basic | 5 |\r\n") is True


def test_a_pipe_without_separator_line_is_not_a_table():
    assert has_table("a | b | c") is False
    assert has_table("cat file | grep x | sort\nls -la\n") is False
    assert has_table("| a | b |\n| c | d |\n") is False


def test_table_is_a_table_in_any_case():
    assert has_table("<TABLE><TR><TD>5</TD></TR></TABLE>") is True
    assert has_table("<Table class='x'>") is True
    assert has_table("<TR>") is True


@pytest.mark.parametrize("text", ["<table>", "<table class='p'>", "<table\n>", "<tr/>", "<tr\t>"])
def test_a_table_tag_followed_by_blank_gt_or_slash_is_a_table(text):
    assert has_table(text) is True


@pytest.mark.parametrize("text", ["<track src='a.vtt'>", "<tablet>", "<trace>", "<table", "<tr"])
def test_track_and_tablet_are_not_tables(text):
    assert has_table(text) is False


def test_an_empty_text_is_not_a_table():
    assert has_table("") is False


# --- REQ-008: «Lo que la regla de la tabla no ve», pinned so a change of the rule is visible ----


@pytest.mark.parametrize(
    "text",
    [
        "plan,seats,price\nbasic,5,9\npro,20,29\n",  # CSV
        "plan\tseats\tprice\nbasic\t5\t9\npro\t20\t29\n",  # TSV
        "Seats | Domains\n--- | ---\n5 | 1\n",  # GFM without outer pipes: one `|` per line
        "| Plan | Seats |\n|-|-|\n| Basic | 5 |\n",  # the separator `|-|-|` (no `--`)
        '<div class="row"><div class="cell">Seats</div><div class="cell">5</div></div>',
    ],
    ids=["csv", "tsv", "gfm-without-outer-pipes", "single-dash-separator", "div-grid"],
)
def test_the_shapes_the_rule_does_not_see_stay_false(text):
    assert has_table(text) is False


@pytest.mark.parametrize(
    "text",
    [
        '{"html": "<tr><td>5</td></tr>"}',  # a JSON string: the text is looked at as it is
        "```html\n<table>\n</table>\n```",  # a code block
        "-<tr>\n+<tr class='x'>\n",  # a diff
    ],
    ids=["json-string", "code-block", "diff"],
)
def test_a_tag_inside_json_code_or_diff_counts_on_the_side_of_going_up(text):
    assert has_table(text) is True


# --- REQ-007: the frozen corpus case keeps its declared role ----------------------------------


def test_the_frozen_toml_source_of_the_corpus_has_no_table():
    source = REPO / "benchmarks" / "catalogo-2026-09" / "fuentes" / "extraer-toml-2k.toml"
    assert has_table(source.read_text(encoding="utf-8")) is False


# --- REQ-009: no regular expression, linear cost ----------------------------------------------

#: Each one of 1 000 000 characters, built in the child from this expression.
_HOSTILE = {
    "lt-repeated": "'<' * 1_000_000",
    "tr-repeated-unclosed": "'<tr' * 333_334",
    "pipes-one-line": "'|' * 1_000_000",
    "one-pipe-per-line": "'|\\n' * 500_000",
    "endless-separator": "'| a | b |\\n|' + '-' * 999_989",
}


@pytest.mark.parametrize("name", sorted(_HOSTILE))
def test_a_hostile_input_ends_in_less_than_a_second(name):
    script = (
        "import json, time\n"
        "from local_delegate.table_detect import has_table\n"
        f"text = {_HOSTILE[name]}\n"
        "assert len(text) >= 1_000_000, len(text)\n"
        "started = time.perf_counter()\n"
        "result = has_table(text)\n"
        "print(json.dumps({'elapsed': time.perf_counter() - started, 'result': result}))\n"
    )
    try:
        done = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=_CHILD_CAP_S,
            env=_child_env(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{name}: has_table did not end within {_CHILD_CAP_S} s")
    assert done.returncode == 0, done.stderr
    report = json.loads(done.stdout.strip().splitlines()[-1])
    assert report["elapsed"] < _HOSTILE_LIMIT_S, f"{name}: {report['elapsed']:.2f} s"


def test_the_module_uses_no_regular_expression():
    source = (Path(_SRC) / "local_delegate" / "table_detect.py").read_text(encoding="utf-8")
    assert "import re" not in source
    assert "from re " not in source
    assert "regex" not in source.replace("regular expression", "")


# --- REQ-010: its own module, loaded without `server`; `server` calls it ----------------------


def test_the_module_imports_without_loading_the_server():
    script = (
        "import sys\n"
        "import local_delegate.table_detect\n"
        "loaded = sorted(m for m in sys.modules if m.startswith('local_delegate'))\n"
        "print(','.join(loaded))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=_CHILD_CAP_S,
        env=_child_env(),
        check=False,
    )
    assert done.returncode == 0, done.stderr
    loaded = done.stdout.strip().split(",")
    assert "local_delegate.table_detect" in loaded
    assert "local_delegate.server" not in loaded
    assert loaded == ["local_delegate", "local_delegate.table_detect"], loaded
