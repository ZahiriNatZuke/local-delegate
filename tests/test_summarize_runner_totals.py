"""#684: `local_summarize` warns when its summary denies a category a test runner counted.

The issue: over a short `pytest -q` output ending in `750 passed, 2 skipped in 81.33s` the
mechanical model wrote «omitiendo 2» and, a sentence later, «No se reportaron fallos ni saltos»,
with no warning. The check is by program, after the answer: the totals line of the runner is read
from the input and a negated mention of a category counted above zero gets a warning. The summary
is not changed. The input is synthetic, with the shape of the issue.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import backend_mock
import httpx2
import pytest

from local_delegate import config, i18n, runner_totals, server

#: A short `pytest -q` output with the shape of the issue (about 1.6 KB, mechanical role).
PYTEST_LOG = (
    "".join(f"{'.' * 70} [{min(100, 10 * (i + 1)):3d}%]\n" for i in range(10))
    + "=============================== warnings summary ===============================\n"
    + "tests/test_cli.py::test_help\n"
    + "  DeprecationWarning: a function is deprecated\n"
    + "-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html\n"
    + "750 passed, 2 skipped in 81.33s (0:01:21)\n"
)

#: What the model wrote in the issue: the skips counted, then denied.
BAD_SUMMARY = (
    "La suite de pytest completó con éxito 750 casos, omitiendo 2, en 81,33 s. "
    "No se reportaron fallos ni saltos."
)

#: A faithful summary: it says the skips and denies the failures, which the runner did not count.
GOOD_SUMMARY = (
    "La suite de pytest pasó 750 casos y saltó 2 en 81,33 s; no hubo fallos ni errores. "
    "Hay un aviso de deprecación en tests/test_cli.py."
)


# --- The totals, as a pure function ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("log", "failures", "skips"),
    [
        ("750 passed, 2 skipped in 81.33s", 0, 2),
        ("==== 3 failed, 10 passed, 1 error in 2.01s ====", 4, 0),
        ("1 failed, 5 passed, 1 skipped, 3 warnings, 1 xfailed in 0.5s", 1, 1),
        ("Tests:       1 failed, 2 skipped, 10 passed, 13 total", 1, 2),
        (
            (
                "test result: FAILED. 5 passed; 1 failed; 2 ignored; 0 measured; 0 filtered out;"
                " finished in 0.00s"
            ),
            1,
            2,
        ),
        ("=== RUN   TestA\n--- FAIL: TestA (0.00s)\n    --- SKIP: TestA/sub (0.00s)\nFAIL", 1, 1),
    ],
)
def test_the_totals_of_each_runner_are_read(log, failures, skips):
    found = runner_totals.totals("some output\n" + log + "\n")
    assert found
    assert found.counts.get(runner_totals.FAILURES, 0) == failures
    assert found.counts.get(runner_totals.SKIPS, 0) == skips


@pytest.mark.parametrize(
    "text",
    [
        "La suite pasó entera: 750 passed, 2 skipped.",  # no duration: prose, not a totals line
        "Se corrió en 2 skipped steps in 3s de prisa",  # a part that is not `N outcome`
        "no tests ran in 0.01s",
        "",
    ],
)
def test_prose_is_not_a_totals_line(text):
    assert not runner_totals.totals(text)


def test_the_issue_summary_is_denied_on_skips_only():
    found = runner_totals.denied(BAD_SUMMARY, PYTEST_LOG)
    assert [(category, count) for category, _clause, count in found] == [(runner_totals.SKIPS, 2)]
    assert "ni saltos" in found[0][1]


@pytest.mark.parametrize(
    ("summary", "category"),
    [
        ("No failures or skips were reported.", runner_totals.SKIPS),
        ("Todo pasó, sin saltos.", runner_totals.SKIPS),
        ("Ningún test fue omitido.", runner_totals.SKIPS),
        ("All green, with 0 skipped tests.", runner_totals.SKIPS),
        ("Without any skipped test the run ended.", runner_totals.SKIPS),
    ],
)
def test_a_denial_is_found_in_both_languages(summary, category):
    found = runner_totals.denied(summary, PYTEST_LOG)
    assert [c for c, _clause, _count in found] == [category]


@pytest.mark.parametrize(
    "summary",
    [
        GOOD_SUMMARY,
        "750 passed and 2 skipped; no failures.",
        "Pasaron 750 y se saltaron 2; sin fallos.",
        "No hubo fallos, pero 2 casos se saltaron.",
        "Sin errores. 2 saltados.",
        "No se ve nada raro: 2 saltos y 750 aciertos.",
    ],
)
def test_a_faithful_summary_is_not_flagged(summary):
    assert runner_totals.denied(summary, PYTEST_LOG) == []


def test_without_a_totals_line_nothing_is_flagged():
    assert runner_totals.denied(BAD_SUMMARY, "Un documento sin salida de tests.\n") == []


def test_a_failure_denied_while_the_runner_failed_is_flagged():
    log = "F.....\n1 failed, 5 passed in 0.20s\n"
    found = runner_totals.denied("Todo pasó y no hubo fallos.", log)
    assert [(c, n) for c, _clause, n in found] == [(runner_totals.FAILURES, 1)]


def test_the_check_is_linear_on_hostile_input():
    hostile = ("1 passed, " * 20_000) + "\n" + ("--- " * 50_000) + "\n" + "no " * 50_000
    start = time.perf_counter()
    runner_totals.denied("no " * 50_000 + "saltos", hostile)
    assert time.perf_counter() - start < 5


# --- The tool, with a fake backend -----------------------------------------------------------------


@backend_mock.mock
def _summarize(monkeypatch, tmp_path, answer: str, **kwargs):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(server, "_summary_language", lambda: "es")
    monkeypatch.setattr(config, "SUMMARIZE_TABLE_LONG", False)

    def _handler(request: httpx2.Request) -> httpx2.Response:
        json.loads(request.content)
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": answer}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    return server.local_summarize(**kwargs)


def _write(tmp_path, text: str):
    path = tmp_path / "pytest.log"
    path.write_bytes(text.encode("utf-8"))
    return path


def _result(output: str) -> str:
    return json.loads(output)["result"] if output.startswith("{") else output


def test_the_fixture_goes_to_the_mechanical_role_like_the_issue():
    assert len(PYTEST_LOG) < config.LONG_INPUT_CHARS


def test_the_summary_of_the_issue_comes_with_one_warning(monkeypatch, tmp_path):
    path = _write(tmp_path, PYTEST_LOG)
    output = _summarize(
        monkeypatch,
        tmp_path,
        BAD_SUMMARY,
        path=str(path),
        focus="resultado final, fallos, saltos y avisos",
        max_words=60,
    )
    result = _result(output)
    # The summary is kept as it came; the warning goes after it.
    assert BAD_SUMMARY in result
    assert result.count(server.WARNING_MARKER) == 1
    warning = result[result.index(server.WARNING_MARKER) :]
    assert "ni saltos" in warning
    assert "750 passed, 2 skipped in 81.33s" in warning
    assert "local_lint_summary" in warning
    assert warning.index(server.WARNING_MARKER) < warning.index("leído server-side")


def test_a_faithful_summary_comes_without_a_warning(monkeypatch, tmp_path):
    path = _write(tmp_path, PYTEST_LOG)
    output = _summarize(monkeypatch, tmp_path, GOOD_SUMMARY, path=str(path), max_words=60)
    assert server.WARNING_MARKER not in _result(output)


def test_the_inline_text_is_checked_too(monkeypatch, tmp_path):
    output = _summarize(monkeypatch, tmp_path, BAD_SUMMARY, text=PYTEST_LOG, max_words=60)
    assert _result(output).count(server.WARNING_MARKER) == 1


@pytest.mark.parametrize("language", ["es", "en"])
def test_the_warning_is_in_both_catalogs(language):
    catalog = json.loads(
        (Path(i18n.__file__).parent / "resources" / "i18n" / language / "mcp.json").read_text(
            encoding="utf-8"
        )
    )
    for key in (
        "mcp.warning.summary_denies_test_totals",
        "mcp.warning.denied_failures",
        "mcp.warning.denied_skips",
    ):
        assert catalog[key]
