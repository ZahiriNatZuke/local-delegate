"""Issue #641: on a pytest log, `local_lint_summary` counts only the tests that fail.

Live on 0.49.0 and 0.50.0, with the output of a pytest run of 24 files (1 failed, 660 passed) the
summary gave a second failure in `tests/test_metrics_own_repo.py`, a file that only appears CITED in
the assertion message of the one failure, and then one "no errors" line per clean file until
`max_tokens` cut it. Confirmed by running the tool with the backend faked: the inventory the program
puts in front of the log lists the 24 files plus the cited one, the cited one FIRST (it is the most
named), and nothing checked the answer against the log.

Now the program reads the failures from the log (`lint_patterns.pytest_failures`: the `FAILED` and
`ERROR` lines of the short summary and the `file:line` of each traceback) and:

- gives them to the model as facts, instead of the list of every file the log names;
- checks the answer against them (`lint_patterns.failure_mismatch`) and adds one visible warning
  when it gives an entry to a file without failures, leaves out a failing file or counts its
  failures wrong. A faithful answer comes back as it was.

Logs of other tools (ruff, ESLint) and pytest logs without failures keep everything as before.
The backend is faked (`_run_chat`): no network. Each block names the mutant that makes it fail.
"""

from __future__ import annotations

import time

import pytest

from local_delegate import config, i18n, lint_patterns, server

BASE = "Resume la siguiente salida de linter/tests:\n\n"
FAILING = "tests/test_detect_spanish_names.py"
CITED = "tests/test_metrics_own_repo.py"
NODE = f"{FAILING}::test_no_spanish_names_in_own_code"
CLEAN_FILES = [f"tests/test_mod_{i:02d}.py" for i in range(1, 23)]


def _issue_log() -> str:
    """The shape of the log of the issue, with made-up names: 24 files, 1 failed, 660 passed.

    The only failure is in `FAILING`; its message lists three locations of `CITED`, so `CITED` is
    named more times than `FAILING` and comes first in `files_by_frequency`.
    """
    lines = ["created: 2/2 workers", "2 workers [661 items]", ""]
    for i, name in enumerate([*CLEAN_FILES, FAILING, CITED]):
        dots = "." * 26 + ("F" if name == FAILING else ".")
        lines.append(f"{name} {dots:<50} [{(i + 1) * 4:3d}%]")
    lines += [
        "",
        "=" * 35 + " FAILURES " + "=" * 35,
        "_" * 22 + " test_no_spanish_names_in_own_code " + "_" * 22,
        "[gw1] win32 -- Python 3.13.1 C:\\proj\\.venv\\Scripts\\python.exe",
        "",
        "    def test_no_spanish_names_in_own_code():",
        '        """Every identifier of the repo is in English (rule of 2026-10-07)."""',
        "        offenders = det.scan_repo(ROOT, exclude=EXCLUDED)",
        "        offenders = [o for o in offenders if o.word not in ALLOWED]",
        ">       assert offenders == [], _format(offenders)",
        "E       AssertionError: Spanish names in the code:",
        f"E           {CITED}:41: propias",
        f"E           {CITED}:58: medicion",
        f"E           {CITED}:77: ventana",
        f"E       assert [Offender(path='{CITED}', line=41, word='propias'), ...] == []",
        "E         Left contains 3 more items, first extra item: Offender(...)",
        "E         Use -v to get more diff",
        "",
        f"{FAILING}:210: AssertionError",
        "=" * 25 + " short test summary info " + "=" * 25,
        f"FAILED {NODE} - AssertionError: Spanish names in the code:",
        "1 failed, 660 passed in 48.17s",
    ]
    return "\n".join(lines) + "\n"


ISSUE_LOG = _issue_log()
#: The shape of the answer of the issue: the failure, a phantom one in the cited file, and one line
#: per clean file.
ISSUE_ANSWER = (
    f"- `{FAILING}`: 1 fallo (AssertionError): nombres en español `propias`, `medicion`, "
    "`ventana`.\n"
    f"- `{CITED}`: 1 fallo.\n"
    + "".join(f"- `{name}`: No se reportan errores.\n" for name in CLEAN_FILES)
    + "\nTotal: 1 failed, 660 passed in 48.17s"
)
#: The comment of the issue (0.50.0): the right failure moved to the cited file and multiplied.
COMMENT_ANSWER = f"**{CITED}**: 6 errores (AssertionError, nombres en español)."
#: What a faithful summary of `ISSUE_LOG` says: the failure in its file, the cited one as context
#: (also in a top-level sentence that does not start with it).
FAITHFUL_ANSWER = (
    f"- `{FAILING}`: 1 fallo en `test_no_spanish_names_in_own_code` (línea 210, "
    f"AssertionError): nombres en español en `{CITED}` (`propias`, `medicion`, `ventana`).\n"
    f"Las tres palabras están en `{CITED}`.\n"
    "\nTotal: 1 failed, 660 passed in 48.17s"
)
#: What `gemma3-4b` answered live (2026-11-10) to the prompt of this fix over `ISSUE_LOG`: right,
#: with a second figure ("3 errores", the three words) that is not the count of failures.
LIVE_ANSWER = (
    "**Resumen de Problemas por Archivo:**\n\n"
    f"*   **{FAILING}:** 1 fallo. El fallo se debe a la presencia de nombres en español en el "
    f"código, específicamente en `{CITED}`. Se identificaron 3 errores: `propias`, `medicion` y "
    "`ventana`."
)

#: Several failures, an error in a fixture and a collection error, with `--tb=short`.
MANY_LOG = (
    "============================= test session starts ==============================\n"
    "collected 40 items / 1 error\n\n"
    "tests/test_api.py ..F.F.....                                             [ 25%]\n"
    "tests/test_db.py ....E.....                                              [ 50%]\n"
    "tests/test_cli.py ....................                                   [100%]\n\n"
    "==================================== ERRORS ====================================\n"
    "____________________ ERROR collecting tests/test_broken.py _____________________\n"
    "tests/test_broken.py:3: in <module>\n"
    "    import missing_module\n"
    "E   ModuleNotFoundError: No module named 'missing_module'\n"
    "_______________________ ERROR at setup of test_connect ________________________\n"
    "tests/conftest.py:18: in database\n"
    "    raise RuntimeError('no db')\n"
    "E   RuntimeError: no db\n"
    "=================================== FAILURES ===================================\n"
    "____________________________ TestUsers.test_create _____________________________\n"
    "tests/test_api.py:31: in test_create\n"
    "    assert response.status == 201\n"
    "E   assert 500 == 201\n"
    "E    +  where 500 = <Response>.status\n"
    "E   log: FAILED tests/test_other.py::test_q - a FAILED line inside a message\n"
    "_____________________________ test_delete[admin] ______________________________\n"
    "tests/test_api.py:57: in test_delete\n"
    "    check(src/app/users.py)\n"
    "src/app/users.py:12: in check\n"
    "    raise PermissionError(name)\n"
    "E   PermissionError: admin\n"
    "=========================== short test summary info ============================\n"
    "FAILED tests/test_api.py::TestUsers::test_create - assert 500 == 201\n"
    "FAILED tests/test_api.py::test_delete[admin] - PermissionError: admin\n"
    "ERROR tests/test_db.py::test_connect - RuntimeError: no db\n"
    "ERROR tests/test_broken.py\n"
    "============== 2 failed, 36 passed, 2 errors in 1.92s ===============\n"
)

RUFF_LOG = (
    "src/app/main.py:12:101: E501 Line too long (104 > 100)\n"
    "src/app/main.py:7:8: F401 [*] `os` imported but unused\n"
    "tests/test_main.py:3:1: D100 Missing docstring in public module\n"
    "Found 3 errors.\n"
    "[*] 1 fixable with the `--fix` option.\n"
)
ESLINT_LOG = (
    "/home/dev/proj/src/app.js\n"
    "  12:5  error    'x' is assigned a value but never used  no-unused-vars\n"
    "  20:1  warning  Unexpected console statement            no-console\n\n"
    "/home/dev/proj/src/util.js\n"
    "  3:10  error  'fs' is defined but never used  no-unused-vars\n\n"
    "\u2716 3 problems (2 errors, 1 warning)\n"
)
#: A pytest log with no failure but a warning: not clean (#525 sends it to the model), no facts.
PYTEST_WARNING_LOG = (
    "tests/test_a.py ....                                                     [ 50%]\n"
    "tests/test_b.py ....                                                     [100%]\n\n"
    "=============================== warnings summary ===============================\n"
    "tests/test_b.py::test_old\n"
    "  tests/test_b.py:9: DeprecationWarning: old() is deprecated\n\n"
    "======================== 8 passed, 1 warning in 0.31s =========================\n"
)


class _Calls(list):
    """The captured calls, and the text the fake model answers (`answer`)."""

    answer = "- nota"


@pytest.fixture
def captured(monkeypatch, tmp_path) -> _Calls:
    calls = _Calls()

    def run_chat(model, system, user, max_tokens, temperature, **_):
        calls.append({"model": model, "system": system, "user": user, "max_tokens": max_tokens})
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


def _warning(out: str) -> str:
    """The line of the warning of #641 in `out`, or "" if there is none."""
    lines = [ln for ln in out.splitlines() if "no cuadra con los fallos" in ln]
    assert len(lines) <= 1, out
    return lines[0] if lines else ""


# --- The program reads the failures --------------------------------------------------------------


def test_the_failure_of_the_issue_is_one_and_in_its_own_file():
    """Mutant "every file the log names fails" (`pytest_failures` from `files_by_frequency`): the
    list has 25 entries and the first assert fails. Mutant "no location" (`location=None`): the
    last one fails."""
    failures = lint_patterns.pytest_failures(ISSUE_LOG)
    assert [f.node for f in failures] == [NODE]
    (failure,) = failures
    assert failure.kind == "FAILED" and failure.file == FAILING
    assert failure.location == f"{FAILING}:210"


def test_several_failures_errors_and_a_collection_error():
    """Each node once, in the order of the summary, with the line of its own file (not the one of
    `src/app/users.py` or `conftest.py` where the exception was raised, when the node's file is in
    the traceback). Mutant "last location of the section": `test_delete[admin]` gets
    `src/app/users.py:12` and the location assert fails. Mutant "FAILED anywhere in the line"
    (`_summary_entry` without the prefix check): the `FAILED` inside an `E` message adds a third
    failure, the cross-check with `2 failed` gives `[]` and the first assert fails."""
    failures = lint_patterns.pytest_failures(MANY_LOG)
    assert [(f.kind, f.node) for f in failures] == [
        ("FAILED", "tests/test_api.py::TestUsers::test_create"),
        ("FAILED", "tests/test_api.py::test_delete[admin]"),
        ("ERROR", "tests/test_db.py::test_connect"),
        ("ERROR", "tests/test_broken.py"),
    ]
    assert [f.file for f in failures] == [
        "tests/test_api.py",
        "tests/test_api.py",
        "tests/test_db.py",
        "tests/test_broken.py",
    ]
    assert [f.location for f in failures] == [
        "tests/test_api.py:31",
        "tests/test_api.py:57",
        "tests/conftest.py:18",  # the node's file is not in its traceback: where it was raised
        "tests/test_broken.py:3",
    ]


def test_windows_paths_and_the_verbose_xdist_prefix():
    log = (
        "[gw0] [ 50%] FAILED tests\\unit\\test_a.py::test_x \n"
        "[gw1] [100%] PASSED tests\\unit\\test_b.py::test_y \n"
        "=================================== FAILURES ===================================\n"
        "____________________________________ test_x ____________________________________\n"
        "C:\\proj\\tests\\unit\\test_a.py:7: in test_x\n"
        "    assert 1 == 2\n"
        "E   assert 1 == 2\n"
        "=========================== short test summary info ============================\n"
        "FAILED tests\\unit\\test_a.py::test_x - assert 1 == 2\n"
        "========================= 1 failed, 1 passed in 0.20s =========================\n"
    )
    (failure,) = lint_patterns.pytest_failures(log)
    assert failure.node == "tests/unit/test_a.py::test_x"
    assert failure.file == "tests/unit/test_a.py"
    assert failure.location == "tests/unit/test_a.py:7"


@pytest.mark.parametrize(
    "log",
    [
        RUFF_LOG,
        ESLINT_LOG,
        PYTEST_WARNING_LOG,
        "ERROR: could not open tests/test_a.py\n",
        "ERROR tests/test_a.py - could not be read\nbuild stopped\n",
    ],
    ids=["ruff", "eslint", "pytest_warning", "error_line_of_another_tool", "no_pytest_summary"],
)
def test_logs_without_pytest_failures_give_none(log):
    """Mutant "no pytest marker" (`pytest_failures` without the results line or short summary
    check): `no_pytest_summary` gives one failure."""
    assert lint_patterns.pytest_failures(log) == []


def test_a_summary_that_disagrees_with_the_count_gives_no_facts():
    """A cut log (two failures counted, one `FAILED` line left) is not a complete list: no facts,
    so nothing is said to be "the only failures". Mutant "no cross-check": one failure comes back."""
    log = (
        "FAILED tests/test_a.py::test_x - assert 1 == 2\n"
        "============== 2 failed, 3 passed in 0.50s ==============\n"
    )
    assert lint_patterns.pytest_failures(log) == []


def test_reading_the_failures_is_linear_on_hostile_input():
    """The input is not trusted (ReDoS antecedent in `lint_patterns`): long runs without breaks."""
    n = 200_000
    for text in (
        "FAILED " + "a/" * (n // 2),
        "FAILED tests/t.py::" + ":" * n,
        "_" * n + "\n" + "a.py:" * (n // 5),
        "1 failed, " * (n // 10) + " in 1s",
        "- " + "a.py" * (n // 4) + ": " + "1 fallo " * (n // 8),
    ):
        start = time.perf_counter()
        lint_patterns.pytest_failures(text)
        lint_patterns.failure_mismatch(text, lint_patterns.pytest_failures(MANY_LOG))
        assert time.perf_counter() - start < 2.0


# --- The model gets them as facts ----------------------------------------------------------------


def test_the_model_gets_the_failure_as_a_fact_and_not_the_list_of_files(captured):
    """Mutant "prompt of before" (`_lint_single_user` without the facts): the first assert fails.
    Mutant "facts plus the file list": the last one fails (the cited and clean files are listed
    again as files of the log)."""
    server.local_lint_summary(text=ISSUE_LOG, max_words=150)
    (call,) = captured
    head, sep, rest = call["user"].partition(BASE)
    assert sep and rest == ISSUE_LOG  # guard: the log goes whole after the head
    assert f"{NODE} ({FAILING}:210)" in head
    assert "no son fallos propios" in head or "no es un fallo propio" in head
    assert call["system"] == server._lint_system(150)  # the system prompt is not touched
    assert CITED not in head and CLEAN_FILES[0] not in head


@pytest.mark.parametrize("log", [RUFF_LOG, ESLINT_LOG, PYTEST_WARNING_LOG])
def test_other_logs_keep_the_prompt_of_before(captured, log):
    server.local_lint_summary(text=log)
    (call,) = captured
    assert call["user"] == server._lint_single_user(log, log, "mechanical")
    assert call["user"].startswith("Ficheros que nombra el log")  # the inventory of before
    assert "Fallos reales" not in call["user"]


# --- The answer is checked against them ----------------------------------------------------------


def test_the_answer_of_the_issue_gets_the_warning(captured):
    """Mutant "no check" (`_lint_check_failures` returns the answer): `_warning` is empty."""
    captured.answer = ISSUE_ANSWER
    out = server.local_lint_summary(text=ISSUE_LOG, max_words=150)
    warning = _warning(out)
    assert warning.startswith(server.WARNING_MARKER)
    assert f"{NODE} ({FAILING}:210)" in warning  # the real failure, read by the program
    assert "(1 en total" in warning
    assert CITED in warning  # the phantom failure is named
    assert "y 18 más" in warning  # 23 files without failures: 5 named, the rest counted
    assert out.startswith(ISSUE_ANSWER)  # additive: the answer is there as it was


def test_the_answer_of_the_comment_gets_the_warning(captured):
    """The failure moved to the cited file (`6 errores`) and the failing file left out."""
    captured.answer = COMMENT_ANSWER
    warning = _warning(server.local_lint_summary(text=ISSUE_LOG))
    assert CITED in warning and "sin fallos" in warning
    assert f"No nombra estos ficheros con fallos: {FAILING}" in warning


def test_a_wrong_count_in_the_right_file_gets_the_warning(captured):
    """Mutant "no count check" (`miscounted` always empty): `_warning` is empty."""
    captured.answer = f"- `{FAILING}`: 6 fallos (AssertionError)."
    warning = _warning(server.local_lint_summary(text=ISSUE_LOG))
    assert f"Cuenta mal los fallos de: {FAILING}" in warning


def test_a_faithful_answer_comes_back_as_it_was(captured):
    """Positive control: the cited file inside the entry of the failure, or in a sentence that
    does not start with it, is context, not an entry. Mutant "any file of the line is an entry"
    (`_entry_file` takes the first file wherever it is): the faithful answer gets a warning and
    this assert fails."""
    captured.answer = FAITHFUL_ANSWER
    out = server.local_lint_summary(text=ISSUE_LOG)
    assert out == FAITHFUL_ANSWER


@pytest.mark.parametrize(
    "answer", [LIVE_ANSWER, f"*   **{FAILING}:** 1 fallo, con 3 errores de nombres."]
)
def test_only_the_first_figure_of_an_entry_is_its_count(captured, answer):
    """The live answer of the fix: "1 fallo ... 3 errores". Mutant "every figure of the entry"
    (`failure_mismatch` compares all of them): `_warning` gives "Cuenta mal los fallos"."""
    captured.answer = answer
    assert _warning(server.local_lint_summary(text=ISSUE_LOG)) == ""


def test_cited_files_as_sub_items_are_context(captured):
    """Mutant "indented lines are entries" (`_entry_file` strips the indentation): the second
    sub-item, without a line number, gives a phantom entry and `_warning` is not empty."""
    captured.answer = (
        f"- `{FAILING}`: 1 fallo (AssertionError) por nombres en español:\n"
        f"  - `{CITED}:41`: propias\n"
        f"  - `{CITED}`: medicion, ventana\n"
    )
    assert _warning(server.local_lint_summary(text=ISSUE_LOG)) == ""


def test_several_failures_counted_per_file(captured):
    captured.answer = (
        "- tests/test_api.py: 2 fallos (assert 500 == 201; PermissionError).\n"
        "- tests/test_db.py: 1 error en el setup (RuntimeError: no db).\n"
        "- tests/test_broken.py: error de colección (ModuleNotFoundError).\n"
    )
    assert _warning(server.local_lint_summary(text=MANY_LOG)) == ""
    captured.answer = captured.answer.replace("2 fallos", "3 fallos")
    assert "Cuenta mal los fallos de: tests/test_api.py" in _warning(
        server.local_lint_summary(text=MANY_LOG)
    )


@pytest.mark.parametrize("log", [RUFF_LOG, ESLINT_LOG, PYTEST_WARNING_LOG])
def test_other_logs_get_no_failure_warning(captured, log):
    captured.answer = "- `src/app/main.py`: E501, F401.\n- `tests/test_main.py`: D100."
    assert _warning(server.local_lint_summary(text=log)) == ""


def test_the_warning_in_english(captured, monkeypatch):
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    i18n.reset()
    captured.answer = COMMENT_ANSWER
    out = server.local_lint_summary(text=ISSUE_LOG)
    (line,) = [ln for ln in out.splitlines() if "does not match the failures" in ln]
    assert NODE in line and CITED in line


def test_the_all_passed_log_of_525_still_skips_the_model(captured):
    log = "tests/test_a.py ....                [100%]\n\n==== 4 passed in 0.12s ====\n"
    out = server.local_lint_summary(text=log)
    assert captured == [] and out.startswith("Sin hallazgos")


# --- The long role and the chunked path ----------------------------------------------------------


def test_the_long_role_does_not_list_clean_files_as_not_mentioned(captured, monkeypatch):
    """The line "Sin mencionar" of the long role listed the files of the log the summary leaves
    out: on a pytest log, the clean ones, which a good summary leaves out on purpose. Mutant
    "not_mentioned over every file": the clean files come back in that line."""
    monkeypatch.setattr(config, "LONG_INPUT_CHARS", 100)
    captured.answer = FAITHFUL_ANSWER
    out = server.local_lint_summary(text=ISSUE_LOG)
    assert len(captured) == 1  # guard: one call
    assert CLEAN_FILES[0] not in out
    assert out == FAITHFUL_ANSWER


def test_the_chunked_final_step_gets_the_facts_and_is_checked(captured, monkeypatch):
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 1200)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 1200)
    captured.answer = COMMENT_ANSWER
    out = server.local_lint_summary(text=ISSUE_LOG)
    final = captured[-1]
    assert len(captured) > 2  # guard: the log was chunked
    assert f"{NODE} ({FAILING}:210)" in final["user"]
    assert CLEAN_FILES[0] not in final["user"].split("Estos son resúmenes parciales")[0]
    assert CITED in _warning(out)
    assert "Y otros" not in out  # the clean files are not "files left out"
