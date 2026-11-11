"""#650: a small `local_summarize` input that carries a table goes to the `long` role.

The same rule as `local_extract` (#586, `tests/test_extract_table_routing.py`), with the same
detector (`table_detect.table_format`): the mechanical model filled an empty CSV cell with its
neighbour's. Every test runs the real tool against a fake backend (`server._post_chat` replaced),
with the default configuration reloaded from the environment; every log row goes to the test's
directory and nothing calls a real backend.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_delegate import backend_params as bp
from local_delegate import config, i18n, server

MECHANICAL = "gemma3-4b"
LONG = "gemma4-26b-a4b"
VARIABLE = "LOCAL_DELEGATE_SUMMARIZE_TABLE_LONG"
TEXT_KEY = "mcp.warning.summarize_role_reason_table"
ROOT = Path(__file__).resolve().parents[1]

CSV = "plan,seats,price\nbasic,,9\npro,20,29\nteam,50,79\n"
PROSE = "The release went out on Friday. The team met on Monday to plan the next one.\n"


class Backend:
    """The fake backend: records the model of every real call and answers a summary."""

    def __init__(self) -> None:
        self.models: list[str] = []

    def __call__(self, model: str, payload: dict) -> server.ChatResult:
        self.models.append(model)
        return server.ChatResult(text="A short summary.", ok=True, finish_reason="stop")


@pytest.fixture
def backend(reload_config, monkeypatch, tmp_path):
    reload_config()
    bp._forget()
    fake = Backend()
    monkeypatch.setattr(server, "_post_chat", fake)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    yield fake
    bp._forget()


def _rows(tmp_path: Path, tool: str = "local_summarize") -> list[dict]:
    rows: list[dict] = []
    for file in sorted(tmp_path.glob("usage*.jsonl")):
        rows += [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()]
    return [row for row in rows if row.get("tool") == tool]


def _notice(fmt: str) -> str:
    return i18n.t(TEXT_KEY, format=fmt)


@pytest.mark.parametrize(
    ("text", "fmt"),
    [
        (CSV, "csv"),
        ("plan\tseats\tprice\nbasic\t5\t9\npro\t20\t29\n", "tsv"),
        ("Plan | Seats\n--- | ---\nBasic | 5\n", "markdown"),
        ("| Plan | Seats |\n|-|-|\n| Basic | 5 |\n", "markdown"),
        ("<table><tr><td>Basic</td><td>5</td></tr></table>", "html"),
        ('<div role="table"><div role="row">Basic 5</div></div>', "aria"),
    ],
    ids=["csv", "tsv", "gfm", "compact-separator", "html", "aria"],
)
def test_a_small_table_goes_to_the_long_model_and_says_its_format(backend, tmp_path, text, fmt):
    output = server.local_summarize(text=text)

    assert backend.models == [LONG], "the small table goes to the long model"
    assert _notice(fmt) in output, "the summary says why, with the format"
    assert f"({fmt})" in _notice(fmt)
    assert [row.get("role_reason") for row in _rows(tmp_path)] == ["table"]
    assert [row["model"] for row in _rows(tmp_path)] == [LONG]


def test_a_small_table_by_path_goes_to_long(backend, tmp_path):
    source = tmp_path / "plans.csv"
    source.write_text(CSV, encoding="utf-8")

    output = server.local_summarize(path=str(source))

    assert backend.models == [LONG]
    assert _notice("csv") in output


def test_without_a_table_it_stays_on_the_mechanical_model(backend, tmp_path):
    output = server.local_summarize(text=PROSE)

    assert backend.models == [MECHANICAL], "the negative control: prose stays on mechanical"
    assert server.WARNING_MARKER not in output
    rows = _rows(tmp_path)
    assert len(rows) == 1 and "role_reason" not in rows[0], rows


def test_a_large_table_is_long_by_size_with_no_reason(backend, tmp_path):
    text = CSV + "\n".join(f"plan{n},{n},{n * 3}" for n in range(1, 800)) + "\n"
    assert len(text) > config.LONG_INPUT_CHARS

    output = server.local_summarize(text=text)

    assert set(backend.models) == {LONG}
    assert _notice("csv") not in output, "by size there is no role_reason"
    assert all("role_reason" not in row for row in _rows(tmp_path))


def test_the_switch_turns_it_off(backend, reload_config, tmp_path):
    reload_config(**{VARIABLE: "0"})
    assert config.SUMMARIZE_TABLE_LONG is False

    output = server.local_summarize(text=CSV)

    assert backend.models == [MECHANICAL]
    assert _notice("csv") not in output
    rows = _rows(tmp_path)
    assert len(rows) == 1 and "role_reason" not in rows[0], rows


def test_the_switch_is_on_by_default_and_registered(backend):
    assert config.SUMMARIZE_TABLE_LONG is True
    assert VARIABLE in config.ENVIRONMENT_VARIABLES


def test_extract_switch_does_not_turn_off_summarize(backend, reload_config):
    reload_config(LOCAL_DELEGATE_EXTRACT_TABLE_LONG="0")

    server.local_summarize(text=CSV)

    assert backend.models == [LONG], "each tool has its own switch"


def test_a_raised_small_input_keeps_the_single_call(backend, monkeypatch):
    """With the structured summary on, only the size opens it: the raised input is one call."""
    monkeypatch.setattr(config, "STRUCTURED_SUMMARY", True)
    text = "# Plans\n\nIntro.\n\n## Prices\n\n| Plan | Seats |\n| --- | --- |\n| Basic | 5 |\n"
    called: list[bool] = []
    monkeypatch.setattr(server.sections, "detect", lambda *_a, **_k: called.append(True))

    server.local_summarize(text=text)

    assert backend.models == [LONG]
    assert called == [], "the structured path is not tried for an input the table raised"


def test_the_reason_does_not_leak_to_the_next_operation(backend, tmp_path):
    server.local_summarize(text=CSV)

    assert server._ROLE_REASON.get() is None
    server.local_summarize(text=PROSE)

    rows = _rows(tmp_path)
    assert [row.get("role_reason") for row in rows] == ["table", None]


def test_the_docstring_names_the_rule_and_its_switch():
    doc = server.local_summarize.__doc__ or ""
    assert VARIABLE in doc
    assert "table" in doc and "CSV" in doc


def test_a_failed_call_still_logs_the_reason(backend, monkeypatch, tmp_path):
    """The backend fails after the rule raised the role: every row of the operation says why."""
    models: list[str] = []

    def failing(model: str, payload: dict) -> server.ChatResult:
        models.append(model)
        return server.ChatResult(text="", ok=False, error="http_500", error_class="model")

    monkeypatch.setattr(server, "_post_chat", failing)

    server.local_summarize(text=CSV)

    assert models and models[0] == LONG, "the first try is the long model"
    rows = _rows(tmp_path)
    assert rows and all(row.get("role_reason") == "table" for row in rows), rows


def test_the_docs_name_format_and_the_recipe_names_the_rule():
    for relative in ("docs/wiki/Tools.md", "docs/wiki/Configuration.md", "CHANGELOG.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert '"format"' in text or "`format`" in text, relative
        assert "TSV" in text and "ARIA" in text, relative
    recipe = (ROOT / "docs" / "recipes" / "claude-code-integration.md").read_text(encoding="utf-8")
    line = next(line for line in recipe.splitlines() if line.startswith("| `local_summarize` |"))
    assert "tabla" in line


@pytest.mark.parametrize(
    "relative",
    [
        "README.md",
        "CHANGELOG.md",
        "docs/wiki/Tools.md",
        "docs/wiki/Configuration.md",
        "docs/wiki/Architecture.md",
        "docs/wiki/Savings-and-metrics.md",
    ],
)
def test_each_surface_names_the_switch(relative):
    path = ROOT / relative
    if not path.is_file():
        pytest.skip(f"{relative} is not in the tree")
    assert VARIABLE in path.read_text(encoding="utf-8"), relative


@pytest.mark.parametrize("language", ["es", "en"])
def test_the_text_key_exists_in_both_languages(language):
    catalog = ROOT / "src" / "local_delegate" / "resources" / "i18n" / language / "mcp.json"
    texts = json.loads(catalog.read_text(encoding="utf-8"))
    assert VARIABLE + "=0" in texts[TEXT_KEY]
    assert "{format}" in texts[TEXT_KEY]
