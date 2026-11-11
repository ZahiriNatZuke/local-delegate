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
from local_delegate.table_detect import has_table, table_format

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


# --- #650: the shapes the #586 rule did not see, now seen, with their format -----------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("plan,seats,price\nbasic,5,9\npro,20,29\n", "csv"),
        ("plan,seats,price\nbasic,,9\npro,20,29\n", "csv"),  # an empty cell (#650)
        ('plan,note,price\nbasic,"5 seats, 1 domain",9\npro,"20, 3",29\n', "csv"),
        ("plan, seats, price\nbasic, 5, 9\npro, 20, 29\n", "csv"),  # blanks after the commas
        ("producto;talla;precio\nCamiseta;M;24,90\nPantalón;L;39,90\n", "csv"),  # `;`, `,` decimal
        ("plan\tseats\tprice\nbasic\t5\t9\npro\t20\t29\n", "tsv"),
        ("plan\tseats\nbasic\t5\npro\t20\n", "tsv"),  # two columns of TSV
        ("plan\tseats\tprice\nbasic\t5\t\npro\t20\t29\n", "tsv"),  # empty last cell (review)
        ("plan,seats,price\nbasic,5,\npro,20,29\n", "csv"),  # empty last cell of a CSV
        ("nombre;precio;nota\nCafé;1,50;\nTé;1,20;\nMate;0,90;\n", "csv"),  # Excel es, last empty
        ("plan,seats,price\r\nbasic,5,9\r\npro,20,29\r\n", "csv"),
        ("Seats | Domains\n--- | ---\n5 | 1\n", "markdown"),  # GFM without outer pipes
        ("| Plan | Seats |\n|-|-|\n| Basic | 5 |\n", "markdown"),  # the compact separator
        ("Plan|Seats\n:-|-:\nBasic|5\n", "markdown"),
        ('<div role="table"><div role="row"><div role="cell">5</div></div></div>', "aria"),
        ("<div role='row'>", "aria"),
        ("<DIV ROLE=GRID>", "aria"),
        ("<table><tr><td>5</td></tr></table>", "html"),
    ],
    ids=[
        "csv",
        "csv-empty-cell",
        "csv-quoted-commas",
        "csv-spaced",
        "csv-semicolon",
        "tsv",
        "tsv-two-columns",
        "tsv-empty-last-cell",
        "csv-empty-last-cell",
        "csv-semicolon-empty-last-cell",
        "csv-crlf",
        "gfm-without-outer-pipes",
        "single-dash-separator",
        "gfm-aligned-no-blanks",
        "aria-table",
        "aria-row-single-quote",
        "aria-grid-unquoted",
        "html",
    ],
)
def test_the_shapes_of_650_are_seen_with_their_format(text, expected):
    assert table_format(text) == expected
    assert has_table(text) is True


@pytest.mark.parametrize(
    "text",
    [
        # `<div>` grids by class names: the same names lay out pages without a table.
        '<div class="row"><div class="cell">Seats</div><div class="cell">5</div></div>',
        '<div class="grid"><div class="col-6">Plans</div><div class="col-6">FAQ</div></div>',
        "plan,seats\nbasic,5\npro,20\n",  # a CSV of two columns
        "plan    seats  price\nbasic   5      9\npro     20     29\n",  # aligned with spaces
        "plan,seats,price\nbasic,5,9\n",  # two lines are not three rows
        '<div role="rowgroup">',  # a role that is not one of the table ones on its own
        "<p role=rowdy>",
        "\tseats\tprice\nbasic\t5\t9\npro\t20\t29\n",  # a TSV header whose first cell is empty
        "plan, seats, price\nbasic, 5,\npro, 20, 29\n",  # spaced CSV with an empty last cell
    ],
    ids=[
        "div-grid-classes",
        "div-bootstrap-grid",
        "csv-two-columns",
        "space-aligned",
        "csv-two-lines",
        "aria-rowgroup",
        "aria-longer-word",
        "tsv-empty-first-cell",
        "csv-spaced-empty-last-cell",
    ],
)
def test_the_shapes_the_rule_does_not_see_stay_false(text):
    assert has_table(text) is False


# --- #650: prose, code, logs, YAML and JSON are not CSV or TSV --------------------------------

_NOT_TABLES = {
    "prose-commas": (
        "The team met on Monday, reviewed the plan, and agreed on the budget.\n"
        "After lunch, the designers, writers and testers shared their notes.\n"
        "On Friday, everyone signed off, and the release went out on time.\n"
    ),
    "prose-wrapped": (
        "Each team, as the plan says, keeps its own backlog and its own board, and\n"
        "the leads, once a week, meet to compare them, so nothing falls between\n"
        "two teams, which happened twice last year, and it cost us a release.\n"
    ),
    "wrapped-file-list": (
        "en scripts/price_watcher.py, ci_gate.py, measure_cooldown.py,\n"
        "analyze_benchmark.py, pair_sheet.py, build_corpus.py,\n"
        "check_install_e2e.py, measure_adoption.py, dev/affinity_batch.py,\n"
    ),
    "python-calls": "foo(a, b, c)\nbar(d, e, f)\nbaz(g, h, i)\n",
    "python-indented": "    x = f(a, b)\n    y, z = 1, 2\n    return x, y, z\n",
    "python-imports": "import os, sys, re\nfrom a import b, c, d\nfrom e import f, g, h\n",
    "js-statements": "let a = 1; let b = 2; let c = 3;\nfoo(); bar(); baz();\nx++; y++; z++;\n",
    "c-defines": "#define A\t1\n#define B\t2\n#define C\t3\n",
    "makefile": "build:\n\tcc -o a a.c\n\tcc -o b b.c\n\tcc -o c c.c\n",
    "go-indented-tabs": "func f() {\n\ta := 1\t// one\n\tb := 2\t// two\n\tc := 3\t// three\n}\n",
    "yaml": "name: demo\ntags: [a, b, c]\nmatrix:\n  os: [linux, mac, win]\nenv: a, b, c\n",
    "json": '{\n  "a": [1, 2, 3],\n  "b": [4, 5, 6],\n  "c": [7, 8, 9]\n}\n',
    "json-lines": '{"a": 1, "b": 2, "c": 3}\n{"a": 4, "b": 5, "c": 6}\n{"a": 7, "b": 8, "c": 9}\n',
    "python-log": (
        "2026-11-11 10:00:00,123 INFO started\n"
        "2026-11-11 10:00:01,456 INFO loaded\n"
        "2026-11-11 10:00:02,789 INFO done\n"
    ),
    "pytest-log": (
        "FAILED tests/a.py::test_x[1, 2, 3] - AssertionError: a, b, c\n"
        "FAILED tests/a.py::test_y[4, 5, 6] - AssertionError: d, e, f\n"
        "FAILED tests/a.py::test_z[7, 8, 9] - AssertionError: g, h, i\n"
    ),
    "markdown-list": "- apples, pears, plums\n- figs, dates, limes\n- kiwis, mangos, melons\n",
    "numbered-list": "1. apples, pears, plums\n2. figs, dates, limes\n3. kiwis, mangos, melons\n",
    "powershell": (
        "Step 'a' @('plugin', 'validate', $mkt, '--json')\n"
        "Step 'b' @('plugin', 'validate', $one, '--json')\n"
        "Step 'c' @('plugin', 'validate', $two, '--json')\n"
    ),
    "prose-semicolons": (
        "We tried the first plan; it failed; we tried again.\n"
        "The second one was slower; it worked; nobody complained.\n"
        "The third one was the best; it shipped; we celebrated.\n"
    ),
    "prose-decimal-commas-es": (
        "La mediana bajó de 4,2 s a 2,9 s, y el p95 quedó en 7 s.\n"
        "El modelo largo tardó 1,8 s más, y el mecánico 0,4 s menos.\n"
        "Con la tabla el error bajó a 0,5 por fila, y sin ella a 1,2.\n"
    ),
    "prose-thousands-en": (
        "Processed 1,234,567 rows in 3.2 s and wrote them all.\n"
        "Processed 2,345,678 rows in 4.1 s and wrote them all.\n"
        "Processed 3,456,789 rows in 5.0 s and wrote them all.\n"
    ),
    "python-log-asctime-with-comma": (
        "2026-11-11 10:00:00,123 INFO lote 1 listo, 100 filas\n"
        "2026-11-11 10:00:01,456 INFO lote 2 listo, 200 filas\n"
        "2026-11-11 10:00:02,789 INFO lote 3 listo, 300 filas\n"
    ),
    "setext-heading-with-pipe": "cat file | grep x\n---\n\nmore text\n",
    "horizontal-rule": "a | b\n\n---\n",
}


@pytest.mark.parametrize("name", sorted(_NOT_TABLES))
def test_prose_code_logs_yaml_and_json_are_not_tables(name):
    assert table_format(_NOT_TABLES[name]) is None


def test_short_spaced_enumerations_go_up_on_purpose():
    """The known error of the CSV rule, on the side of going up: short cells after `, `."""
    text = "Red, green, blue and pink.\nOne, two, three and four.\nSix, seven, eight and nine.\n"
    assert table_format(text) == "csv"


def test_without_delimited_csv_and_tsv_are_not_looked_for():
    assert table_format("plan,seats,price\nbasic,5,9\npro,20,29\n", delimited=False) is None
    assert table_format("Plan | Seats\n--- | ---\nBasic | 5\n", delimited=False) == "markdown"


def test_the_python_and_markdown_sources_of_the_repo_are_not_csv_or_tsv():
    """A broad negative control: no source or wiki page of the repo reads as CSV or TSV."""
    files = sorted((REPO / "src").rglob("*.py")) + sorted((REPO / "docs").rglob("*.md"))
    files += sorted((REPO / "tests").glob("test_*.py"))
    assert len(files) > 100
    seen = {
        str(file.relative_to(REPO)): found
        for file in files
        if (found := table_format(file.read_text(encoding="utf-8"))) in ("csv", "tsv")
    }
    assert not seen, seen


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
    # #650: the CSV/TSV, GFM and ARIA rules.
    "commas-one-line": "',' * 1_000_000",
    "quotes-one-line": "'\"' * 1_000_000",
    "tsv-rows-never-three": "'a\\tb\\na\\tb\\tc\\n' * 100_000",
    "csv-rows-never-three": "'a,b,c\\na,b\\n' * 100_000",
    "csv-counts-change-each-line": "'a,b,c\\na,b,c,d\\n' * 71_429",
    "one-line-read-by-every-pass": "'a,b\\t\"c;\"' * 125_000",
    "equal-counts-cells-too-long": "'a,b,c d e f g h i j k\\n' * 45_455",
    "equal-counts-calls": "'f(a,b,c)\\n' * 111_112",
    "gfm-cells-mismatch": "'a|b\\n-|-|-\\n' * 100_000",
    "role-repeated": "'role=' * 200_000",
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
