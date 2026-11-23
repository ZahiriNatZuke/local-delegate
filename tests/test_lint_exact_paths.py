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
    assert not [f for f in files if "pytest.org" in f or "capture-warnings" in f]


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
    assert "pytest.org" not in line
    assert not [f for f in CLEAN_FILES if f in line]


def test_the_long_call_does_not_list_clean_files_as_not_mentioned(captured, monkeypatch):
    monkeypatch.setattr(config, "LONG_INPUT_CHARS", 10)
    captured.answer = f"**{RELATIVE}**: 1 DeprecationWarning (línea 53)."
    out = server.local_lint_summary(text=PYTEST_ONE_WARNING)
    assert len(captured) == 1
    assert out.startswith(captured.answer)
    assert "test_mod_" not in out
    assert "pytest.org" not in out.split(captured.answer, 1)[1]
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
