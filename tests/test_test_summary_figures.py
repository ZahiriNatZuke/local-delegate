"""#714: the figures of a test output, by program, in `local_summarize` and `local_lint_summary`.

Two failures seen live on 2026-11-23 with 0.53.0:

- the #684 warning («the summary denies …») fired over faithful summaries: a comma did not end the
  negation, a figure in words did not count as a figure, and `failed` and `errors` were one
  category («1 falló, sin errores» over `1 failed`);
- the model rewrote figures the program can read: «Python 3.11.5» for 3.11.15, «Veintiocho»
  tests for 216, «dos» and then «tres» skipped.

The totals and the versions are read from the input and written by the program, in a fixed line;
a summary naming another Python version gets a warning. The inputs are synthetic.
"""

from __future__ import annotations

import json
import time

import backend_mock
import httpx2
import pytest

from local_delegate import config, runner_totals, server

#: A pytest output with the shape of the day: header, progress, totals (216 passed, 3 skipped).
PYTEST_LOG = (
    "============================= test session starts =============================\n"
    "platform win32 -- Python 3.11.15, pytest-8.3.4, pluggy-1.5.0\n"
    "rootdir: C:\\work\\proj\n"
    "collected 219 items\n\n"
    + "".join(f"tests/test_m{i}.py {'.' * 24}s [{10 * (i + 1):3d}%]\n" for i in range(3))
    + "".join(f"tests/test_n{i}.py {'.' * 48} [{40 + 10 * i:3d}%]\n" for i in range(3))
    + "======================= 216 passed, 3 skipped in 12.34s =======================\n"
)

#: What the model wrote that day: another version, another total, two different skip counts.
BAD_SUMMARY = (
    "La suite corrió con Python 3.11.5 y pytest 8.3.4. Veintiocho pruebas pasaron y dos se "
    "omitieron; más abajo, tres omitidas en total."
)

#: A log the lint tool summarizes (a failure keeps it off the «no findings» answer).
PYTEST_FAILING_LOG = (
    "============================= test session starts =============================\n"
    "platform linux -- Python 3.12.7, pytest-8.3.4, pluggy-1.5.0\n"
    "collected 219 items\n\n"
    "tests/test_a.py ....F....s [ 50%]\n"
    "tests/test_b.py .........ss [100%]\n\n"
    "=================================== FAILURES ===================================\n"
    "___________________________________ test_x ___________________________________\n"
    "tests/test_a.py:12: in test_x\n"
    "    assert 1 == 2\n"
    "E   assert 1 == 2\n"
    "=========================== short test summary info ============================\n"
    "FAILED tests/test_a.py::test_x - assert 1 == 2\n"
    "================== 1 failed, 215 passed, 3 skipped in 9.87s ===================\n"
)


def _short(totals: str) -> str:
    return f"....\n=== {totals} in 1.00s ===\n"


# --- The #684 warning without false positives -------------------------------------------------------


def test_a_comma_ends_the_negation():
    log = _short("10 passed, 4 skipped")
    assert runner_totals.denied("Sin fallos, cuatro pruebas omitidas.", log) == []
    # Only the comma cuts here (no figure, no conjunction); without it the negation reaches.
    assert runner_totals.denied("Sin fallos, con pruebas omitidas.", log) == []
    found = runner_totals.denied("Sin fallos con pruebas omitidas.", log)
    assert [(c, n) for c, _clause, n in found] == [(runner_totals.SKIPS, 4)]


@pytest.mark.parametrize(
    "summary",
    ["No se reportaron fallos, saltos ni errores.", "No failures, skips or errors were reported."],
)
def test_a_comma_inside_a_list_of_categories_does_not_end_the_negation(summary):
    """Review H1: the comma of a list keeps the negation of the list (it warned on main too)."""
    found = runner_totals.denied(summary, _short("10 passed, 2 skipped"))
    assert [(c, n) for c, _clause, n in found] == [(runner_totals.SKIPS, 2)]


def test_a_figure_in_words_ends_the_negation():
    log = _short("10 passed, 2 skipped")
    assert runner_totals.denied("No hubo fallos salvo dos omitidas.", log) == []
    assert runner_totals.denied("No failures except two skipped tests.", log) == []
    # Positive controls: without the figure, and with an article that is not one, it is flagged.
    for summary in ("No hubo fallos ni omitidas.", "No hubo ni un salto."):
        found = runner_totals.denied(summary, log)
        assert [c for c, _clause, _n in found] == [runner_totals.SKIPS], summary


def test_errors_are_their_own_category():
    failed = _short("1 failed, 10 passed")
    assert runner_totals.denied("1 falló, sin errores.", failed) == []
    assert runner_totals.denied("One test failed, no errors.", failed) == []
    errored = _short("1 error, 10 passed")
    found = runner_totals.denied("Todo bien, sin errores.", errored)
    assert [(c, n) for c, _clause, n in found] == [(runner_totals.ERRORS, 1)]
    # «fallos» keeps its broad reach: failures and errors, as before.
    found = runner_totals.denied("Todo bien, sin fallos.", errored)
    assert [(c, n) for c, _clause, n in found] == [(runner_totals.FAILURES, 1)]


def test_the_new_negation_cuts_stay_linear_on_hostile_input():
    hostile = "no " * 50_000 + "dos " * 50_000 + ", " * 50_000 + "errores"
    start = time.perf_counter()
    runner_totals.denied(hostile, _short("1 error"))
    header = "platform x -- Python 3.11.15, pytest-8.3.4, " + "1." * 150 + "\n"
    assert len(header) < 400  # reaches the header pattern, not the length guard
    runner_totals.python_versions("Python 3." * 200_000, header + "Python 3." * 200_000)
    runner_totals.pytest_header(("platform x -- Python " + "1." * 150 + "\n") * 5_000)
    assert time.perf_counter() - start < 5


# --- The figures, by program --------------------------------------------------------------------------


def test_the_totals_parts_and_versions_are_read():
    found = runner_totals.totals(PYTEST_LOG)
    assert found.parts == ["216 passed, 3 skipped"]
    assert runner_totals.pytest_header(PYTEST_LOG) == ("3.11.15", "8.3.4")
    assert runner_totals.pytest_header("no header here\n216 passed in 1s\n") is None


def test_another_python_version_is_read_by_program():
    assert runner_totals.python_versions(BAD_SUMMARY, PYTEST_LOG) == ["3.11.5"]
    assert runner_totals.python_versions("Con Python 3.11.15.", PYTEST_LOG) == []
    assert runner_totals.python_versions("Con Python 3.11, sin más.", PYTEST_LOG) == []
    assert runner_totals.python_versions("Python 3.11.5", "sin cabecera\n") == []


# --- The tools, with a fake backend -------------------------------------------------------------------


@backend_mock.mock
def _call(monkeypatch, tmp_path, tool, answer: str, **kwargs):
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
    return tool(**kwargs)


def _result(output: str) -> str:
    return json.loads(output)["result"] if output.startswith("{") else output


def _program_line(result: str) -> str:
    marker = "216 passed, 3 skipped"
    assert marker in result, result
    start = result.rindex("\n", 0, result.index(marker)) + 1
    return result[start : result.index("\n", start) if "\n" in result[start:] else None]


def test_summarize_adds_the_program_line(monkeypatch, tmp_path):
    result = _result(
        _call(monkeypatch, tmp_path, server.local_summarize, BAD_SUMMARY, text=PYTEST_LOG)
    )
    assert result.startswith(BAD_SUMMARY)  # the summary is not changed
    line = _program_line(result)
    assert "Python 3.11.15" in line
    assert "pytest 8.3.4" in line
    assert not line.startswith(server.WARNING_MARKER)


def test_another_python_version_is_flagged(monkeypatch, tmp_path):
    result = _result(
        _call(monkeypatch, tmp_path, server.local_summarize, BAD_SUMMARY, text=PYTEST_LOG)
    )
    warning = result[result.index(server.WARNING_MARKER) :]
    assert "3.11.5" in warning
    assert "3.11.15" in warning
    faithful = BAD_SUMMARY.replace("3.11.5", "3.11.15")
    result = _result(
        _call(monkeypatch, tmp_path, server.local_summarize, faithful, text=PYTEST_LOG)
    )
    assert server.WARNING_MARKER not in result
    assert "Python 3.11.15" in _program_line(result)


def test_without_a_totals_line_the_summary_is_as_before(monkeypatch, tmp_path):
    text = "Un documento sin salida de tests. Habla de Python 3.11.5 y de nada más.\n" * 3
    result = _result(_call(monkeypatch, tmp_path, server.local_summarize, "Resumen.", text=text))
    assert "passed" not in result
    assert server.WARNING_MARKER not in result


def test_an_answer_with_the_totals_gets_no_line(monkeypatch, tmp_path):
    answer = "Python 3.11.15: 216 passed, 3 skipped en 12,34 s."
    result = _result(_call(monkeypatch, tmp_path, server.local_summarize, answer, text=PYTEST_LOG))
    assert result.count("216 passed, 3 skipped") == 1
    assert server.WARNING_MARKER not in result
    # Control: the same answer with another version gets the line and the warning.
    other = answer.replace("3.11.15", "3.11.5")
    result = _result(_call(monkeypatch, tmp_path, server.local_summarize, other, text=PYTEST_LOG))
    assert result.count("216 passed, 3 skipped") == 2
    assert server.WARNING_MARKER in result


def test_the_warning_cites_the_line_that_counts(monkeypatch, tmp_path):
    # The line that counts the skips goes second: neither the first nor the last line would do.
    log = (
        "....\n=== 3 passed in 2.00s ===\n....\n=== 2 skipped, 5 passed in 1.00s ===\n"
        "....\n=== 4 passed in 3.00s ===\n"
    )
    result = _result(
        _call(monkeypatch, tmp_path, server.local_summarize, "Todo bien, sin saltos.", text=log)
    )
    warning = result[result.index(server.WARNING_MARKER) :]
    assert "2 skipped, 5 passed in 1.00s" in warning
    assert "3 passed in 2.00s" not in warning
    assert "4 passed in 3.00s" not in warning


@pytest.mark.parametrize("role", ["mechanical", "long"])
def test_lint_summary_adds_the_program_line(monkeypatch, tmp_path, role):
    monkeypatch.setattr(server, "_role_for_size", lambda _n: (role, f"model-{role}"))
    answer = "tests/test_a.py: 1 fallo (test_x). Python 3.11.5. Veintiocho pruebas pasaron."
    result = _result(
        _call(monkeypatch, tmp_path, server.local_lint_summary, answer, text=PYTEST_FAILING_LOG)
    )
    assert result.startswith(answer)
    assert "1 failed, 215 passed, 3 skipped" in result
    assert "Python 3.12.7" in result
    assert "3.11.5" in result[result.index(server.WARNING_MARKER) :]


def test_lint_summary_chunked_adds_the_program_line(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "_role_for_size", lambda _n: ("long", "model-long"))
    monkeypatch.setattr(config, "max_chars_for_role", lambda _role: 400)
    answer = "tests/test_a.py: 1 fallo (test_x)."
    result = _result(
        _call(monkeypatch, tmp_path, server.local_lint_summary, answer, text=PYTEST_FAILING_LOG)
    )
    assert "1 failed, 215 passed, 3 skipped" in result
    assert "Python 3.12.7" in result


def test_another_version_named_by_the_input_is_not_flagged():
    """Review H3: a version the input names elsewhere (a warning, another tox session) is real."""
    log = PYTEST_LOG + "  DeprecationWarning: removed in Python 3.14\n"
    assert runner_totals.python_versions("Avisa de que se quita en Python 3.14.", log) == []
    sessions = PYTEST_LOG + PYTEST_LOG.replace("3.11.15", "3.12.7")
    assert runner_totals.python_versions("Corrió en Python 3.12.7 y 3.11.15.", sessions) == []
    assert runner_totals.python_versions("Corrió en Python 3.13.1.", sessions) == ["3.13.1"]


def test_cargo_parts_keep_their_separator():
    """Review H4: the parts read as the runner wrote them."""
    line = "test result: ok. 5 passed; 0 failed; 2 ignored; 0 measured; 0 filtered out; finished in 0.01s"
    assert runner_totals.totals(line + "\n").parts == [
        "5 passed; 0 failed; 2 ignored; 0 measured; 0 filtered out"
    ]


def test_more_than_three_totals_lines_are_capped(monkeypatch, tmp_path):
    log = "".join(f"....\n=== {n} passed in 1.00s ===\n" for n in range(1, 6))
    result = _result(_call(monkeypatch, tmp_path, server.local_summarize, "Resumen.", text=log))
    assert "1 passed | 2 passed | 3 passed" in result
    assert "4 passed" not in result
    assert "(y 2 líneas de totales más)" in result


def test_go_output_gets_no_program_line(monkeypatch, tmp_path):
    log = "=== RUN   TestA\n--- FAIL: TestA (0.00s)\nFAIL\nok  \tpkg\t0.01s\n"
    result = _result(_call(monkeypatch, tmp_path, server.local_summarize, "Resumen.", text=log))
    assert "Totales de la salida de tests" not in result
