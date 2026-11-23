"""#688 and #690: `local_lint_summary` treats the paths of the log exactly.

#688: on a short pytest log in green with one `DeprecationWarning`, the summary gave the warning
twice, under two files: pytest names the file with its relative path in the header of the
`warnings summary` block and with the absolute one in the message line, and the inventory the
program puts in front of the model listed both. It also listed the documentation link of the
footer (`docs.pytest.org/.../capture-warnings.html`, an `.html`) as a file, and every test file of
the progress lines, all of them clean.

#690: a summary that grouped the findings of `knowledge/` and `personal/` under `projects/knowledge/`
and `projects/personal/`, folders that do not exist, got no warning: `invented_files` accepted any
file whose basename the log carries.

Now (`lint_patterns`): an absolute path is one file with the relative path it ends in; what is
inside a URL is not a file; the files that pytest names only in clean progress lines are left out
of the inventory and of the "not mentioned" line; and a path with folders that the summary gives,
or a folder it names alone, must be in the log as it is, at a folder boundary.

The inputs are synthetic, with the shape of the issues. The backend is faked (`_run_chat`).
"""

from __future__ import annotations

import time

import pytest

from local_delegate import config, i18n, lint_patterns, server

RELATIVE = ".venv/Lib/site-packages/starlette/testclient.py"
URL = "https://docs.pytest.org/en/stable/how-to/capture-warnings.html"
CLEAN_FILES = [f"tests/test_mod_{n:02d}.py" for n in range(6)]

#: A pytest run in green with one warning, as in #688.
PYTEST_ONE_WARNING = (
    "============================= test session starts ==============================\n"
    "platform win32 -- Python 3.12.7, pytest-8.3.3, pluggy-1.5.0\n"
    "collected 283 items\n\n"
    + "".join(
        f"{f} {'.' * 40}                              [ {10 * (i + 1)}%]\n"
        for i, f in enumerate(CLEAN_FILES)
    )
    + "\n=============================== warnings summary ===============================\n"
    f"{RELATIVE}:53\n"
    r"  C:\work\proj\.venv\Lib\site-packages\starlette\testclient.py:53: DeprecationWarning: "
    "The 'app' shortcut is now deprecated.\n"
    "    warnings.warn(\n\n"
    f"-- Docs: {URL}\n"
    "======================= 283 passed, 1 warning in 4.21s ========================\n"
)

#: A Markdown linter log over several top-level folders, as in #690.
MARKDOWN_LINT = (
    "projects/alpha/plan.md:3: MD013 Line length\n"
    "projects/alpha/plan.md:9: MD013 Line length\n"
    "projects/beta/notes.md:1: MD041 First line heading\n"
    "knowledge/glossary.md:4: MD013 Line length\n"
    "personal/diary.md:7: MD033 Inline HTML\n"
)


class _Calls(list):
    answer = "- nada"


@pytest.fixture
def captured(monkeypatch, tmp_path) -> _Calls:
    calls = _Calls()

    def run_chat(model, system, user, max_tokens, temperature, **_):
        calls.append({"system": system, "user": user})
        result = server.ChatResult(text=calls.answer, ok=True, finish_reason="stop")
        return result, 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    monkeypatch.delenv("LOCAL_DELEGATE_OUTPUT_LANGUAGE", raising=False)
    i18n.reset()
    yield calls
    i18n.reset()


def _inventory(user: str) -> str:
    """The line of files the program put in front of the log."""
    head = user.split("La lista de arriba")[0]
    return next(line for line in head.splitlines() if line.startswith("Ficheros que nombra"))


# --- #688: one file, no URL, no clean files ------------------------------------------------------


def test_the_absolute_and_the_relative_path_are_one_file():
    """Mutant "no merge": the absolute path is a second entry and the assert fires."""
    files = lint_patterns.files_by_frequency(PYTEST_ONE_WARNING)
    named = [f for f in files if f.lower().endswith("starlette/testclient.py")]
    assert named == [RELATIVE]


def test_a_url_is_not_a_file():
    """Mutant "no URL spans": `docs.pytest.org/.../capture-warnings.html` is listed."""
    files = lint_patterns.files_by_frequency(PYTEST_ONE_WARNING)
    assert set(files) == {*CLEAN_FILES, RELATIVE}


def test_the_clean_files_of_pytest_progress_are_not_reported():
    assert lint_patterns.reported_files(PYTEST_ONE_WARNING) == [RELATIVE]
    # `files_by_frequency` still names them: it says what the log names, nothing more.
    assert set(CLEAN_FILES) <= set(lint_patterns.files_by_frequency(PYTEST_ONE_WARNING))


def test_the_inventory_of_the_issue_names_one_file(captured):
    """The prompt the model gets: one file, the relative path, and nothing else."""
    server.local_lint_summary(text=PYTEST_ONE_WARNING)
    assert len(captured) == 1  # guard: the model ran
    line = _inventory(captured[0]["user"])
    assert RELATIVE in line
    assert line.count("testclient.py") == 1
    assert "capture-warnings" not in line
    assert not [f for f in CLEAN_FILES if f in line]


def test_the_long_call_does_not_list_clean_files_as_not_mentioned(captured, monkeypatch):
    monkeypatch.setattr(config, "LONG_INPUT_CHARS", 10)
    captured.answer = f"**{RELATIVE}**: 1 DeprecationWarning (línea 53)."
    out = server.local_lint_summary(text=PYTEST_ONE_WARNING)
    assert len(captured) == 1
    assert out.startswith(captured.answer)
    assert "test_mod_" not in out
    assert "capture-warnings" not in out.split(captured.answer, 1)[1]
    assert "local-delegate warning" not in out


def test_a_file_with_a_failure_in_its_progress_line_is_kept():
    log = (
        "tests/test_ok.py ....                                                    [ 50%]\n"
        "tests/test_bad.py ..F.                                                   [100%]\n"
        "=========================== short test summary info ============================\n"
        "FAILED tests/test_bad.py::test_x - assert 1 == 2\n"
    )
    assert lint_patterns.reported_files(log) == ["tests/test_bad.py"]


def test_a_clean_file_named_elsewhere_is_kept():
    """Only the files that appear ONLY in clean progress lines go away."""
    log = (
        "tests/test_a.py ....                                                     [100%]\n"
        "tests/test_a.py:12: PytestUnraisableExceptionWarning: boom\n"
        "1 passed, 1 warning in 0.1s\n"
    )
    assert lint_patterns.reported_files(log) == ["tests/test_a.py"]


def test_an_absolute_path_without_its_relative_one_stays():
    log = r"C:\work\proj\src\a.py:1:1: E501 line too long" + "\n"
    assert lint_patterns.files_by_frequency(log) == ["work/proj/src/a.py"]


def test_two_relative_paths_are_not_merged():
    """A relative path that ends in another one is another file (`tests/src/a.py`)."""
    log = "src/a.py:1:1: E501\ntests/src/a.py:2:1: E501\ntests/src/a.py:3:1: E501\n"
    assert lint_patterns.files_by_frequency(log) == ["tests/src/a.py", "src/a.py"]


def test_an_absolute_path_goes_to_its_longest_relative_one():
    log = (
        "pkg/src/a.py:1:1: E501\n"
        "src/a.py:2:1: E501\n"
        "/home/dev/repo/pkg/src/a.py:3:1: E501\n"
        "~/repo/pkg/src/a.py:4:1: E501\n"
    )
    assert lint_patterns.files_by_frequency(log) == ["pkg/src/a.py", "src/a.py"]


def test_a_long_url_is_searched_in_linear_time():
    text = "see https://example.org/" + "a/" * 20_000 + "x.py and src/b.py\n"
    start = time.perf_counter()
    files = lint_patterns.files_by_frequency(text)
    assert time.perf_counter() - start < 1.0
    assert files == ["src/b.py"]


# --- #690: folders the summary makes up -----------------------------------------------------------


def test_a_full_path_with_a_made_up_folder_is_invented():
    """Mutant "match by basename again": `glossary.md` is in the log, so nothing is flagged."""
    answer = "**projects/knowledge/glossary.md**: MD013 (1)"
    assert lint_patterns.invented_files(answer, MARKDOWN_LINT) == ["projects/knowledge/glossary.md"]


def test_a_folder_named_alone_is_checked_too():
    """The shape of #690: the summary groups by folder and lists basenames under it."""
    answer = (
        "### projects/alpha/\n- plan.md: MD013 (2)\n\n"
        "### projects/knowledge/\n- glossary.md: MD013 (1)\n\n"
        "### projects/personal/\n- diary.md: MD033 (1)\n"
    )
    assert lint_patterns.invented_files(answer, MARKDOWN_LINT) == [
        "projects/knowledge/",
        "projects/personal/",
    ]


def test_the_tool_warns_of_the_made_up_folder(captured):
    captured.answer = "### projects/knowledge/\n- glossary.md: MD013 (1)\n"
    out = server.local_lint_summary(text=MARKDOWN_LINT)
    assert len(captured) == 1
    assert "local-delegate warning" in out
    assert "projects/knowledge/" in out.split(captured.answer.rstrip(), 1)[1]


@pytest.mark.parametrize(
    "answer",
    [
        "**knowledge/glossary.md**: MD013 (1)",
        "glossary.md: MD013; plan.md: MD013 (2)",
        "### projects/alpha/\n- plan.md: MD013 (2)\n### knowledge/\n- glossary.md",
        "### projects/\n- alpha/plan.md\n- beta/notes.md",
        "Tipos de error/regla: MD013 y lint/style/noMagicNumbers; y/o MD041.",
        "Ver https://example.org/docs/rules/ y www.example.org/md013.html para la regla.",
        r"`projects\alpha\plan.md`: MD013 (2)",
        "`./knowledge/glossary.md`: MD013",
    ],
    ids=["full", "basenames", "folders", "nested", "slash_words", "urls", "backslashes", "dot"],
)
def test_what_the_log_carries_is_not_flagged(answer):
    """Controls: each passes before and after the fix, so a broader rule cannot sneak in."""
    assert lint_patterns.invented_files(answer, MARKDOWN_LINT) == []


def test_a_path_the_log_gives_absolute_is_not_flagged():
    log = r"C:\vault\knowledge\glossary.md:4: MD013 Line length" + "\n"
    assert lint_patterns.invented_files("knowledge/glossary.md: MD013", log) == []
    assert lint_patterns.invented_files("### knowledge/\n- glossary.md", log) == []


def test_a_folder_must_match_at_a_boundary():
    """`edge/` is not in `knowledge/`: a substring is not a folder."""
    assert lint_patterns.invented_files("### edge/\n- glossary.md", MARKDOWN_LINT) == ["edge/"]
    assert lint_patterns.invented_files("edge/glossary.md", MARKDOWN_LINT) == ["edge/glossary.md"]


# --- #688, live: the model reads the clean files from the log itself -----------------------------
# The inventory no longer lists them, but `gemma3-4b` still gave an entry to each clean file it read
# in the progress lines (live, 2026-11-23). What the program knows (pytest names those files only
# in progress lines without failures) is now checked on the answer, as #641 does for failures.

#: The answer of the live pass, in shape: an entry per clean file, the warning under one of them.
CLEAN_ENTRIES_ANSWER = (
    "- **tests/test_mod_00.py**: 0 errores\n"
    "- **tests/test_mod_01.py**: 1 DeprecationWarning (línea 53)\n"
    f"- **{RELATIVE}**: 1 DeprecationWarning\n"
)


def test_the_tool_warns_of_entries_for_clean_files(captured):
    """Mutant "no clean-entry check": the answer comes back as it was and the assert fires."""
    captured.answer = CLEAN_ENTRIES_ANSWER
    out = server.local_lint_summary(text=PYTEST_ONE_WARNING)
    assert len(captured) == 1  # guard: the model ran
    assert out.startswith(CLEAN_ENTRIES_ANSWER.rstrip())
    tail = out.split(CLEAN_ENTRIES_ANSWER.rstrip(), 1)[1]
    assert "local-delegate warning" in tail
    assert "tests/test_mod_00.py" in tail and "tests/test_mod_01.py" in tail
    # The file the log does report is named as what it reports, not as a clean one.
    assert RELATIVE in tail


def test_an_answer_without_clean_entries_gets_no_warning(captured):
    """Control: an entry only for the reported file passes before and after."""
    captured.answer = f"- **{RELATIVE}**: 1 DeprecationWarning (línea 53)\n"
    out = server.local_lint_summary(text=PYTEST_ONE_WARNING)
    assert len(captured) == 1
    assert "local-delegate warning" not in out


def test_a_clean_file_cited_in_a_sentence_is_not_an_entry():
    answer = f"- **{RELATIVE}**: 1 aviso. Los demás (tests/test_mod_00.py y otros) pasan.\n"
    assert lint_patterns.clean_file_entries(answer, PYTEST_ONE_WARNING) == []


#: The same run with colours (`--color=yes`, what CI writes) and with `-v` and `-v -n 2`.
PYTEST_COLOUR = (
    "\x1b[1m============ test session starts ============\x1b[0m\n"
    "tests/test_a.py \x1b[32m.\x1b[0m\x1b[32m.\x1b[0m\x1b[32m                  [ 50%]\x1b[0m\n"
    "tests/test_b.py \x1b[32m.\x1b[0m\x1b[33ms\x1b[0m\x1b[32m                  [100%]\x1b[0m\n"
    "\x1b[32m============ 3 passed, 1 skipped in 0.10s ============\x1b[0m\n"
)
PYTEST_VERBOSE = (
    "============ test session starts ============\n"
    "tests/test_a.py::test_one PASSED                                     [ 25%]\n"
    "tests/test_a.py::TestX::test_two PASSED                              [ 50%]\n"
    "tests/test_b.py::test_three SKIPPED (no db)                          [ 75%]\n"
    "tests/test_c.py::test_four XFAIL (known)                             [100%]\n"
    "============ 2 passed, 1 skipped, 1 xfailed in 0.10s ============\n"
)
PYTEST_XDIST = (
    "============ test session starts ============\n"
    "[gw0] [ 50%] PASSED tests/test_a.py::test_one \n"
    "[gw1] [100%] PASSED tests\\test_b.py::test_two \n"
    "============ 2 passed in 0.10s ============\n"
)


@pytest.mark.parametrize(
    ("log", "clean"),
    [
        (PYTEST_COLOUR, ["tests/test_a.py", "tests/test_b.py"]),
        (PYTEST_VERBOSE, ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"]),
        (PYTEST_XDIST, ["tests/test_a.py", "tests/test_b.py"]),
    ],
    ids=["colour", "verbose", "xdist"],
)
def test_clean_progress_in_every_pytest_shape(log, clean):
    """Before, only the plain `file ....  [ 10%]` line was clean: colours and `-v` kept them."""
    assert lint_patterns.reported_files(log) == []
    assert sorted(lint_patterns.clean_files(log)) == clean


@pytest.mark.parametrize(
    "line",
    [
        "tests/test_a.py::test_one FAILED                                     [ 50%]",
        "tests/test_a.py::test_one ERROR                                      [ 50%]",
        "tests/test_a.py ..F.                                                 [ 50%]",
        "tests/test_a.py ..E.                                                 [ 50%]",
        "[gw0] [ 50%] FAILED tests/test_a.py::test_one ",
        "tests/test_a.py::test_one XPASS(strict)                              [ 50%]",
        "tests/test_a.py:12: PytestUnraisableExceptionWarning: boom",
    ],
    ids=["v_failed", "v_error", "f_mark", "e_mark", "xdist_failed", "xpass_strict", "warning"],
)
def test_a_line_with_a_problem_keeps_its_file(line):
    """Controls: a failure, an error or a warning is not clean progress."""
    log = f"{line}\n============ 1 failed in 0.10s ============\n"
    assert lint_patterns.reported_files(log) == ["tests/test_a.py"]
    assert lint_patterns.clean_files(log) == []


def test_clean_files_only_on_a_pytest_log():
    """A lint log is not pytest: no file of it is ever called clean by this rule."""
    assert lint_patterns.clean_files("src/a.py .\nsrc/a.py:1:1: E501\n") == []


@pytest.mark.parametrize(
    "line",
    [
        "tests/" + "a" * 200_000 + " " + "." * 200_000,
        # Review of #709: the `.py` branch of the check, and the folder and URL patterns.
        "tests/" + "a" * 200_000 + ".py " + "." * 200_000,
        "x/" * 100_000 + " https://" + "y/" * 100_000,
    ],
    ids=["no_py", "py_branch", "folders_and_url"],
)
def test_the_clean_line_check_is_linear(line):
    log = line + "\n1 passed in 0.1s\n"
    start = time.perf_counter()
    lint_patterns.clean_files(log)
    lint_patterns.reported_files(log)
    lint_patterns.clean_file_entries("- tests/a.py: 0", log)
    lint_patterns.invented_files(line, "src/a.py:1:1: E501\n")
    assert time.perf_counter() - start < 2.0


# --- Review of PR #709 ---------------------------------------------------------------------------


def test_the_long_role_warns_of_entries_for_clean_files(captured, monkeypatch):
    """Mutant "no `_lint_check_clean` in the long postprocess": no warning."""
    monkeypatch.setattr(config, "LONG_INPUT_CHARS", 10)
    captured.answer = CLEAN_ENTRIES_ANSWER
    out = server.local_lint_summary(text=PYTEST_ONE_WARNING)
    assert len(captured) == 1
    tail = out.split(CLEAN_ENTRIES_ANSWER.rstrip(), 1)[1]
    assert "local-delegate warning" in tail and "tests/test_mod_00.py" in tail


def test_the_chunked_path_warns_of_entries_for_clean_files(captured, monkeypatch):
    """Mutant "no `_lint_check_clean` in `_add_not_mentioned`": no warning."""
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 300)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 300)
    captured.answer = CLEAN_ENTRIES_ANSWER
    out = server.local_lint_summary(text=PYTEST_ONE_WARNING)
    assert len(captured) > 2  # guard: the log was chunked
    tail = out.split(CLEAN_ENTRIES_ANSWER.rstrip(), 1)[1]
    assert "tests/test_mod_00.py" in tail.split("local-delegate warning", 1)[1]


#: pytest wraps a long progress line; the failure is in the line without the file.
WRAPPED = (
    "tests/test_big.py ........................................          [ 50%]\n"
    "....F...                                                            [100%]\n"
    "1 failed, 47 passed in 0.5s\n"
)


def test_a_failure_in_a_wrapped_progress_line_keeps_its_file():
    """Before, `tests/test_big.py` was "clean" and the warning blamed a clean file."""
    assert lint_patterns.reported_files(WRAPPED) == ["tests/test_big.py"]
    assert lint_patterns.clean_files(WRAPPED) == []


def test_a_clean_wrapped_progress_line_stays_clean():
    """Control: the wrapped line has only dots, so the file is still clean."""
    log = WRAPPED.replace("....F...", "........").replace("1 failed, 47", "48")
    assert lint_patterns.reported_files(log) == []
    assert lint_patterns.clean_files(log) == ["tests/test_big.py"]


def test_no_clean_warning_when_the_results_line_counts_failures():
    """A failure the program cannot place: it does not call any file clean in the answer."""
    log = "tests/test_a.py ....  [100%]\nsomething odd\n1 failed, 4 passed in 0.5s\n"
    assert lint_patterns.clean_file_entries("- tests/test_a.py: 0 errores", log) == []


def test_a_bare_basename_does_not_own_an_absolute_path():
    log = "conftest.py:3: in f\n/venv/lib/site-packages/pkg/conftest.py:9: W\n"
    files = lint_patterns.files_by_frequency(log)
    assert "conftest.py" in files and len(files) == 2


@pytest.mark.parametrize(
    "answer",
    ["- src/a.py: falla w/ timeout", "Ver github.com/org/repo/ para la regla."],
    ids=["w_slash", "bare_domain"],
)
def test_prose_with_a_slash_is_not_a_made_up_folder(answer):
    assert lint_patterns.invented_files(answer, "src/a.py:1:1: E501\n") == []


def test_overstrike_text_is_not_refused(tmp_path):
    """`man` output saved to a file: a third of the bytes are backspaces, and it is text."""
    path = tmp_path / "man.txt"
    path.write_bytes(b"N\x08NA\x08AM\x08ME\x08E\n" * 50)
    content, _truncated, _raw = server._read_input(None, str(path), server._NO_TRUNCATE)
    assert content.startswith("N\x08N")
