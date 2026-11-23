"""#717: `local_lint_summary` gives the counts per file and per code by program.

In the smoke test of 0.54.0 the model gave `core.py` the F401 of `util.py` and per-file counts that
added up to 5 over `Found 4 errors`, with no warning: the files and the code were in the log, so
nothing else had a word to say. What the program can count is not asked of the model: for the
formats `lint_patterns.per_file_code_counts` reads (ruff/flake8 concise, ruff full, tsc) the answer
ends with a line of the program, and a warning names each figure of the summary that is not the
log's. The data tells them apart: the smoke case (a foreign code and a wrong total), a right
summary full of line and column numbers (no warning), tsc and ruff full, and the formats with no
per-file counts (the default eslint format, pytest), which stay as they were.
"""

from __future__ import annotations

import pytest

from local_delegate import config, i18n, lint_patterns, server

#: The smoke case of 0.54.0: 4 warnings in two files.
SMOKE = (
    "pkg/core.py:10:89: E501 Line too long (101 > 88)\n"
    "pkg/core.py:22:89: E501 Line too long (95 > 88)\n"
    "pkg/core.py:31:5: E741 Ambiguous variable name: `l`\n"
    "pkg/util.py:3:8: F401 [*] `sys` imported but unused\n"
    "Found 4 errors.\n"
    "[*] 1 fixable with the `--fix` option.\n"
)

#: What the model wrote, in the shape of the smoke test: F401 in `core.py`, 5 in all.
WRONG = (
    "- `pkg/core.py`: 3 errores\n"
    "  - E501 (2): líneas 10 y 22, línea demasiado larga\n"
    "  - F401 (1): `sys` importado sin usar\n"
    "- `pkg/util.py`: 2 errores\n"
    "  - F401 (1): import sin usar\n"
)

#: Right figures, among line and column numbers and the `Found 4 errors` of the log.
RIGHT = (
    "- `pkg/core.py` — 3 avisos\n"
    "  - E501 ×2 (líneas 10:89 y 22:89, 101 > 88)\n"
    "  - E741 en la línea 31\n"
    "- `pkg/util.py` — 1 aviso\n"
    "  - F401: 1 (`sys` sin usar, 3:8)\n"
    "- Por código: E501: 2, E741: 1, F401: 1 (Found 4 errors).\n"
)

WARNING = "[local-delegate warning: el resumen da otras cifras que el log"


class _Calls(list):
    answer = "- nota"


@pytest.fixture
def captured(monkeypatch, tmp_path) -> _Calls:
    calls = _Calls()

    def run_chat(model, system, user, max_tokens, temperature, **_):
        calls.append({"user": user})
        result = server.ChatResult(text=calls.answer, ok=True, finish_reason="stop")
        return result, 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.delenv("LOCAL_DELEGATE_DUMP_CHUNK_NOTES", raising=False)
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    monkeypatch.delenv("LOCAL_DELEGATE_OUTPUT_LANGUAGE", raising=False)
    i18n.reset()
    return calls


# --- the program: the mismatches -----------------------------------------------------------------


def test_the_smoke_case_names_the_foreign_code_and_the_wrong_total():
    per_file = lint_patterns.per_file_code_counts(SMOKE)
    found = lint_patterns.count_mismatches(WRONG, per_file)
    assert lint_patterns.CountMismatch("pkg/core.py", "F401", None, 0) in found
    assert lint_patterns.CountMismatch("pkg/util.py", None, 2, 1) in found
    # Control: what the summary got right is not a mismatch.
    assert not [m for m in found if m.code == "E501"]
    assert len(found) == 2


def test_right_figures_among_line_numbers_give_no_mismatch():
    per_file = lint_patterns.per_file_code_counts(SMOKE)
    assert lint_patterns.count_mismatches(RIGHT, per_file) == []


def test_a_wrong_figure_for_a_code_inside_and_outside_the_entries():
    per_file = lint_patterns.per_file_code_counts(SMOKE)
    inside = "### core.py\n- E501: 3 líneas largas\n- E741 ×1\n"
    assert lint_patterns.count_mismatches(inside, per_file) == [
        lint_patterns.CountMismatch("pkg/core.py", "E501", 3, 2)
    ]
    outside = "- `pkg/util.py`: 1 aviso (F401)\n\nPor código:\n- E501 ×4\n- F401 (1)\n"
    assert lint_patterns.count_mismatches(outside, per_file) == [
        lint_patterns.CountMismatch(None, "E501", 4, 2)
    ]


def test_a_line_that_names_another_file_is_not_the_entry_of_this_one():
    per_file = lint_patterns.per_file_code_counts(SMOKE)
    answer = "- `pkg/core.py`: 3 errores\n  - E501 ×2, E741 ×1; el F401 es de `pkg/util.py`\n"
    assert lint_patterns.count_mismatches(answer, per_file) == []


def test_tsc_and_ruff_full_are_checked_too():
    tsc = (
        "src/x.ts(3,5): error TS2345: Argument of type 'string'.\n"
        "src/x.ts(9,1): error TS2345: Argument of type 'string'.\n"
        "src/y.ts(1,1): error TS2532: Object is possibly 'undefined'.\n"
    )
    per_file = lint_patterns.per_file_code_counts(tsc)
    assert lint_patterns.count_mismatches("- src/x.ts: TS2345 ×3\n", per_file) == [
        lint_patterns.CountMismatch("src/x.ts", "TS2345", 3, 2)
    ]
    assert lint_patterns.count_mismatches("- src/x.ts: TS2345 ×2\n", per_file) == []
    full = (
        "D101 Missing docstring in public class\n --> src/a.py:3:7\n"
        "D101 Missing docstring in public class\n --> src/b.py:1:7\n"
    )
    per_file = lint_patterns.per_file_code_counts(full)
    assert lint_patterns.count_mismatches("- src/a.py: 2 errores (D101)\n", per_file) == [
        lint_patterns.CountMismatch("src/a.py", "D101", 2, 1)
    ]
    assert lint_patterns.count_mismatches("- src/a.py: 2 errores, todos D101\n", per_file) == [
        lint_patterns.CountMismatch("src/a.py", None, 2, 1)
    ]


# --- the tool: the line and the warning -----------------------------------------------------------


def test_the_smoke_case_gets_the_line_of_the_program_and_the_warning(captured):
    captured.answer = WRONG
    out = server.local_lint_summary(text=SMOKE)
    assert out.startswith(WRONG.rstrip())
    assert (
        "Recuentos del log (leídos por programa, mandan sobre el texto): "
        "pkg/core.py 3 (E501 2, E741 1) | pkg/util.py 1 (F401 1) · por código: "
        "E501 2, E741 1, F401 1." in out
    )
    warning = out[out.index(WARNING) :]
    assert "«pkg/core.py»: F401 (el log no lo tiene en ese fichero)" in warning
    assert "«pkg/util.py»: 2 en total (el log: 1)" in warning


def test_a_right_summary_gets_the_line_and_no_warning(captured):
    captured.answer = RIGHT
    out = server.local_lint_summary(text=SMOKE)
    assert "Recuentos del log (leídos por programa" in out
    assert "warning" not in out


def test_the_long_role_gets_them_too(captured, monkeypatch):
    monkeypatch.setattr(config, "LONG_INPUT_CHARS", 0)
    captured.answer = WRONG
    out = server.local_lint_summary(text=SMOKE)
    assert "Recuentos del log (leídos por programa" in out
    assert "«pkg/core.py»: F401" in out[out.index(WARNING) :]


def test_the_chunked_summary_gets_them_too(captured, monkeypatch):
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 1200)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 1200)
    log = "".join(f"pkg/core.py:{n}:89: E501 Line too long ({n} > 88)\n" for n in range(1, 41))
    log += "pkg/util.py:3:8: F401 `sys` imported but unused\nFound 41 errors.\n"
    captured.answer = "- `pkg/core.py`: 41 errores (E501)\n- `pkg/util.py`: 1 aviso (F401)\n"
    out = server.local_lint_summary(text=log)
    assert len(captured) > 1  # it was chunked
    assert "pkg/core.py 40 (E501 40) | pkg/util.py 1 (F401 1)" in out
    assert "«pkg/core.py»: E501 41 (el log: 40)" in out[out.index(WARNING) :]


def test_many_files_are_listed_up_to_ten_and_the_rest_counted(captured):
    log = "".join(f"src/m{f:02d}.py:1:1: F401 unused\n" for f in range(13))
    out = server.local_lint_summary(text=log)
    assert "src/m09.py 1 (F401 1) (y 3 ficheros más) · por código: F401 13." in out
    assert "src/m10.py 1" not in out


def test_the_line_in_english(captured, monkeypatch):
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    i18n.reset()
    captured.answer = WRONG
    out = server.local_lint_summary(text=SMOKE)
    assert "Counts of the log (read by the program, they hold over the text): " in out
    assert "the summary gives other figures than the log" in out


@pytest.mark.parametrize(
    "log",
    [
        "/repo/src/a.ts\n  12:7  error  'x' is unused  no-unused-vars\n\n1 problem (1 error)\n",
        (
            "tests/test_a.py::test_one FAILED\nFAILED tests/test_a.py::test_one - assert 1 == 2\n"
            "1 failed, 3 passed in 0.12s\n"
        ),
    ],
    ids=["eslint-default", "pytest"],
)
def test_formats_without_per_file_counts_stay_as_they_were(captured, log):
    captured.answer = "- `src/a.ts`: 3 errores (no-unused-vars)\n"
    out = server.local_lint_summary(text=log)
    assert "Recuentos del log" not in out
    assert "otras cifras que el log" not in out


def test_what_the_program_cannot_tell_gives_no_warning():
    """Review of #717: a total of two files, the figure of a code next to the total word, a list
    of lines after a code and a basename two files share are not mismatches."""
    per_file = lint_patterns.per_file_code_counts(SMOKE)
    assert (
        lint_patterns.count_mismatches("- `pkg/core.py` y `pkg/util.py`: 4 avisos\n", per_file)
        == []
    )
    assert (
        lint_patterns.count_mismatches("- `pkg/core.py`: 2 errores E501 y 1 E741\n", per_file) == []
    )
    assert lint_patterns.count_mismatches("- `pkg/core.py`: E501 (10, 22), E741\n", per_file) == []
    # Control: the same shapes with a wrong figure still warn.
    assert lint_patterns.count_mismatches("- `pkg/core.py`: 5 avisos\n", per_file) == [
        lint_patterns.CountMismatch("pkg/core.py", None, 5, 3)
    ]
    assert lint_patterns.count_mismatches("- `pkg/core.py`: E501 (3), E741\n", per_file) == [
        lint_patterns.CountMismatch("pkg/core.py", "E501", 3, 2)
    ]
    twins = "a/core.py:1:1: E501 long\nb/core.py:1:1: F401 unused\nb/core.py:2:1: F401 unused\n"
    twins_per_file = lint_patterns.per_file_code_counts(twins)
    assert lint_patterns.count_mismatches("- core.py: 2 errores (F401)\n", twins_per_file) == []
    assert lint_patterns.count_mismatches("- b/core.py: 3 errores\n", twins_per_file) == [
        lint_patterns.CountMismatch("b/core.py", None, 3, 2)
    ]


def test_a_bold_line_under_heading_entries_is_not_part_of_the_last_one():
    """Second judge, L1: `**Por código:** …` after `### file` entries is the summary per code."""
    per_file = lint_patterns.per_file_code_counts(SMOKE)
    answer = (
        "### pkg/core.py\n- E501 ×2\n- E741 ×1\n\n### pkg/util.py\n- F401 ×1\n\n"
        "**Por código:** E501 ×2, E741 ×1, F401 ×1\n"
    )
    assert lint_patterns.count_mismatches(answer, per_file) == []
    # Control: a wrong figure on that line is checked against the whole log.
    wrong = answer.replace("E501 ×2, E741", "E501 ×5, E741")
    assert lint_patterns.count_mismatches(wrong, per_file) == [
        lint_patterns.CountMismatch(None, "E501", 5, 2)
    ]


def test_a_total_word_followed_by_a_code_is_the_figure_of_that_code():
    """Second judge, L2: `2 errores de E501 y 1 de E741` and `2 avisos (E501)` count E501."""
    per_file = lint_patterns.per_file_code_counts(SMOKE)
    for answer in (
        "- `pkg/core.py`: 2 errores de E501 y 1 de E741\n",
        "- `pkg/core.py`: 2 avisos (E501), 1 aviso (E741)\n",
        "- `pkg/core.py`: E501 (10 y 22), E501 (10-22), E741\n",
    ):
        assert lint_patterns.count_mismatches(answer, per_file) == [], answer
    assert lint_patterns.count_mismatches("- `pkg/core.py`: 3 errores de E501\n", per_file) == [
        lint_patterns.CountMismatch("pkg/core.py", "E501", 3, 2)
    ]


#: A code in two files: the figure of one file is not the total of the log.
SHARED = "pkg/a.py:1:1: E501 long\npkg/a.py:2:1: E501 long\npkg/b.py:1:1: E501 long\n"


def test_a_paragraph_of_a_file_is_not_judged_against_the_whole_log():
    """Review of #717, R7: a paragraph without indent under a heading entry, or a line that names a
    file in the middle, speaks of that file: it is not a figure of the whole log."""
    per_file = lint_patterns.per_file_code_counts(SHARED)
    for answer in (
        "### pkg/a.py\nTiene E501 ×2, en las líneas 1 y 2.\n",
        "El fichero `pkg/b.py` tiene E501 ×1.\n",
        "### pkg/a.py\n- E501 ×2\n\n### pkg/b.py\nSolo E501 ×1.\n",
    ):
        assert lint_patterns.count_mismatches(answer, per_file) == [], answer
    # Control: a wrong figure in the entry, and a figure of the whole log, still warn.
    assert lint_patterns.count_mismatches("### pkg/a.py\n- E501 ×3\n", per_file) == [
        lint_patterns.CountMismatch("pkg/a.py", "E501", 3, 2)
    ]
    closed = "### pkg/a.py\n- E501 ×2\n\nPor código:\n- E501 ×5\n"
    assert lint_patterns.count_mismatches(closed, per_file) == [
        lint_patterns.CountMismatch(None, "E501", 5, 3)
    ]
    assert lint_patterns.count_mismatches("Por código: E501 ×2\n", per_file) == [
        lint_patterns.CountMismatch(None, "E501", 2, 3)
    ]


def test_the_lines_of_the_program_go_together_before_the_warnings(captured):
    """Review of #717, R6: the totals of the tests (#715) and the counts of the lint go right
    after the summary, in that order, and the warnings close the answer."""
    log = SMOKE + "1 failed, 3 passed in 0.12s\n"
    captured.answer = "- `pkg/core.py`: 3 errores\n- `pkg/ghost.py`: 1 error\n"
    out = server.local_lint_summary(text=log)
    tests_line = out.index("Totales de la salida de tests")
    lint_line = out.index("Recuentos del log")
    first_warning = out.index(server.WARNING_MARKER)
    assert out.index("pkg/core.py") < tests_line < lint_line < first_warning


def test_bullets_after_a_paragraph_of_a_heading_entry_are_not_given_to_that_file():
    """Second review of #717 (H1): a paragraph without `:` under `### b.py` leaves its bullets
    to nobody: they are not the file's, and the program cannot tell they are the log's."""
    per_file = lint_patterns.per_file_code_counts(SHARED)
    answer = "### pkg/b.py\n- E501 ×1\n\nEn total por código\n- E501 ×3\n"
    assert lint_patterns.count_mismatches(answer, per_file) == []
    # Control: a heading closes that state and its entry is judged again.
    again = answer + "\n### pkg/a.py\n- E501 ×4\n"
    assert lint_patterns.count_mismatches(again, per_file) == [
        lint_patterns.CountMismatch("pkg/a.py", "E501", 4, 2)
    ]


def test_a_line_that_names_files_warns_when_its_figure_is_neither_theirs_nor_the_log_s():
    """Second review of #717 (H2): `E501: 7 (core.py)` is wrong for the file and for the log."""
    per_file = lint_patterns.per_file_code_counts(SMOKE)
    assert lint_patterns.count_mismatches("Por código:\n- E501: 7 (core.py)\n", per_file) == [
        lint_patterns.CountMismatch(None, "E501", 7, 2)
    ]
    shared = lint_patterns.per_file_code_counts(SHARED)
    # The figure of the named file, or of the whole log, is fair.
    assert lint_patterns.count_mismatches("- E501 ×1 en `pkg/b.py`\n", shared) == []
    assert lint_patterns.count_mismatches("- E501 ×3, sobre todo en `pkg/a.py`\n", shared) == []
