"""Issue #525: `local_lint_summary` with nothing to summarize no longer makes up diagnostics.

Live on 0.47.1, a 3-byte `[]` (the JSON of a clean linter run) came back as errors and warnings
in `src/main.js`, `tests/main.test.js` and `webpack.config.js`, with no warning. The same with an
empty file, only whitespace, `{}`, `[]\\n` and a pytest log where every test passed. Two parts:

- the program answers the inputs it recognises as clean before the model
  (`lint_patterns.clean_verdict`), with a fixed sentence and no usage event;
- for the rest, the summary gets a visible warning when it names files the input does not carry
  (`lint_patterns.invented_files`), in every role and also chunked.

The prompts are not touched: the system prompt is the footprint of the measured affinity cells of
lint, and `test_a_long_log_without_files_or_codes_keeps_the_prompt_of_before` guards the user one.

The backend is faked (`_run_chat`): no network. Each block names the mutant that makes it fail.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_delegate import config, i18n, lint_patterns, server

NO_FINDINGS_ES = (
    "Sin hallazgos: la entrada no trae errores, avisos ni pruebas fallidas que resumir."
)
NO_FINDINGS_EN = "No findings: the input carries no errors, warnings or failed tests to summarize."
#: What the model answered live to `[]` (issue #525), files that the input does not carry.
INVENTED = (
    "**Archivo: src/main.js**\n- Errores: 2\n\n**Archivo: tests/main.test.js**\n- Errores: 1\n\n"
    "**Archivo: webpack.config.js**\n- Avisos: 1"
)

ESLINT_CLEAN = json.dumps(
    [
        {
            "filePath": r"C:\proj\src\app.js",
            "messages": [],
            "suppressedMessages": [],
            "errorCount": 0,
            "fatalErrorCount": 0,
            "warningCount": 0,
            "fixableErrorCount": 0,
            "fixableWarningCount": 0,
        }
    ]
)
PYTEST_PASSED = (
    "============================= test session starts ==============================\n"
    "platform win32 -- Python 3.12.7, pytest-8.3.3, pluggy-1.5.0\n"
    "collected 42 items\n\n"
    "tests/test_a.py ..........                                              [ 23%]\n"
    "tests/test_b.py ................................                        [100%]\n\n"
    "============================== 42 passed in 3.21s ==============================\n"
)

#: Every clean form of the issue and the brief, with the line the answer quotes ("" for none).
CLEAN_FORMS = [
    ("brackets", "[]", ""),
    ("empty", "", ""),
    ("spaces", "   \n\t\n  ", ""),
    ("object", "{}", ""),
    ("brackets_newline", "[]\n", ""),
    ("null", "null", ""),
    ("eslint_clean", ESLINT_CLEAN, ""),
    ("semgrep_clean", '{"results": [], "errors": [], "paths": {"scanned": ["a.py"]}}', ""),
    ("biome_clean", '{"summary": {"errors": 0, "warnings": 0}, "diagnostics": []}', ""),
    ("stylelint_clean", '[{"source": "a.css", "errored": false, "warnings": []}]', ""),
    ("zero_problems", "0 problems\n", "0 problems"),
    ("no_problems", "\u2714 No problems found\n", "\u2714 No problems found"),
    ("ruff", "All checks passed!\n", "All checks passed!"),
    ("zero_errors", "0 errors\n", "0 errors"),
    ("pyright", "0 errors, 0 warnings, 0 informations \n", "0 errors, 0 warnings, 0 informations"),
    (
        "mypy",
        "Success: no issues found in 12 source files\n",
        "Success: no issues found in 12 source files",
    ),
    ("ansi", "\x1b[32mAll checks passed!\x1b[0m\n", "All checks passed!"),
    ("pytest_passed", PYTEST_PASSED, "42 passed in 3.21s"),
    ("pytest_quiet", "....\n4 passed, 1 skipped in 0.12s\n", "4 passed, 1 skipped in 0.12s"),
]

#: Inputs that look close to a clean one and do carry something: they go to the model.
DIRTY_FORMS = [
    ("ruff_error", "src/a.py:1:1: E501 Line too long\nFound 1 error.\n"),
    ("errors_and_warnings", "0 errors, 3 warnings\n"),
    ("found_errors", "Found 2 errors.\n"),
    ("eslint_message", '[{"filePath": "a.js", "messages": [{"ruleId": "no-undef"}]}]'),
    ("eslint_count", '[{"filePath": "a.js", "messages": [], "errorCount": 1}]'),
    ("stylelint_errored", '[{"source": "a.css", "errored": true, "warnings": []}]'),
    ("unknown_object", '{"foo": 1}'),
    ("list_of_numbers", "[1]"),
    ("list_of_strings", '["a.py:1: E501"]'),
    ("invalid_json", "[{]"),
    ("pytest_warning", "== 3 passed, 1 warning in 1.0s =="),
    ("pytest_failed", "== 1 failed, 3 passed in 1.0s =="),
    ("pytest_failed_line", "FAILED tests/test_a.py::test_x\n== 3 passed in 1.0s ==\n"),
    ("clean_line_and_more", "All checks passed!\nsrc/a.py:1:1: E501 Line too long\n"),
]


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


def _rows(tmp_path: Path) -> list[dict]:
    return [
        json.loads(line)
        for file in sorted(tmp_path.glob("*.jsonl"))
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# --- the program tells a clean input apart ----------------------------------------------------
@pytest.mark.parametrize(
    ("log", "line"), [f[1:] for f in CLEAN_FORMS], ids=[f[0] for f in CLEAN_FORMS]
)
def test_clean_verdict_recognises_each_clean_form(log, line):
    """Mutant "`clean_verdict` always returns None": no form is recognised."""
    assert lint_patterns.clean_verdict(log) == line


@pytest.mark.parametrize("log", [f[1] for f in DIRTY_FORMS], ids=[f[0] for f in DIRTY_FORMS])
def test_clean_verdict_leaves_any_content_to_the_model(log):
    """Mutant "`clean_verdict` always returns \"\"": every dirty input would be called clean."""
    assert lint_patterns.clean_verdict(log) is None


# --- the tool answers without the model ------------------------------------------------------
@pytest.mark.parametrize(
    ("log", "line"), [f[1:] for f in CLEAN_FORMS], ids=[f[0] for f in CLEAN_FORMS]
)
def test_a_clean_input_is_answered_without_the_model(captured, tmp_path, log, line):
    """Mutant "no short-circuit in `local_lint_summary`": the fake model is called and its
    answer comes back instead of the fixed sentence."""
    captured.answer = INVENTED
    out = server.local_lint_summary(text=log)
    assert captured == []
    if line:
        assert out == NO_FINDINGS_ES[:-1] + f" (el log dice: «{line}»)."
    else:
        assert out == NO_FINDINGS_ES
    assert "src/main.js" not in out
    # No model ran, so no delegation is logged (as with the open backend breaker).
    assert _rows(tmp_path) == []


def test_the_short_circuit_answers_in_english(captured, monkeypatch):
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    i18n.reset()
    assert server.local_lint_summary(text="[]") == NO_FINDINGS_EN
    assert server.local_lint_summary(text="All checks passed!") == (
        NO_FINDINGS_EN[:-1] + ' (the log says: "All checks passed!").'
    )
    assert captured == []


def test_a_clean_file_by_path_carries_the_usual_receipt(captured, monkeypatch, tmp_path):
    """The read was made server-side: the answer keeps the receipt of the other paths."""
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", True)
    log = tmp_path / "empty-lint.json"
    log.write_text("[]\n", encoding="utf-8")
    out = server.local_lint_summary(path=str(log))
    assert captured == []
    assert out.startswith(NO_FINDINGS_ES)
    assert "leído server-side: 3 chars" in out


def test_the_short_circuit_still_checks_the_path(captured, tmp_path):
    """The path guard and the missing-file error come before the verdict."""
    with pytest.raises(ValueError):
        server.local_lint_summary(path=str(tmp_path / "missing.json"))
    assert captured == []


@pytest.mark.parametrize("log", [f[1] for f in DIRTY_FORMS], ids=[f[0] for f in DIRTY_FORMS])
def test_an_input_with_content_still_goes_to_the_model(captured, log):
    """Control: the short-circuit does not take what the model has to summarize."""
    out = server.local_lint_summary(text=log)
    assert len(captured) == 1
    assert out.startswith("- nota")


# --- the net for what reaches the model ------------------------------------------------------
def test_the_prompts_of_the_tool_are_not_touched(captured):
    """The system prompt is the footprint of the affinity cells: it stays as `_lint_system`."""
    log = "src/a.py:1:1: E501 Line too long\n"
    server.local_lint_summary(text=log)
    assert captured[0]["system"] == server._lint_system(200)
    assert "Sin hallazgos" not in captured[0]["system"] + captured[0]["user"]


WARNING_ES = (
    "[local-delegate warning: el resumen nombra ficheros que no aparecen en la entrada y pueden "
    "ser inventados: src/main.js, tests/main.test.js, webpack.config.js]"
)


def test_invented_files_lists_what_the_log_does_not_name():
    log = r"C:\proj\src\app.js:1:1: no-undef" + "\nsrc/a.py:2:1: E501\n"
    assert lint_patterns.invented_files(INVENTED, log) == [
        "src/main.js",
        "tests/main.test.js",
        "webpack.config.js",
    ]
    # By path or by basename, as `mentions` matches.
    assert lint_patterns.invented_files("`src/app.js`, app.js y src/a.py", log) == []


def test_the_mechanical_call_warns_of_invented_files(captured):
    """Mutant "mechanical role without `_lint_invented` in the postprocess": the answer comes
    back without the warning (the assert on `WARNING_ES` fires)."""
    captured.answer = INVENTED
    out = server.local_lint_summary(text="src/a.py:1:1: E501 Line too long\n")
    assert len(captured) == 1  # guard: the model ran, in a single call
    assert out.startswith(INVENTED)
    assert out.endswith(WARNING_ES)


def test_a_summary_of_the_files_of_the_log_has_no_warning(captured):
    """Control: naming the files of the log is not flagged."""
    captured.answer = "**src/a.py**: E501 (1)"
    out = server.local_lint_summary(text="src/a.py:1:1: E501 Line too long\n")
    assert "local-delegate warning" not in out


def test_the_long_call_warns_of_invented_files(captured, monkeypatch):
    """Mutant "long role without `_lint_invented`"."""
    monkeypatch.setattr(config, "LONG_INPUT_CHARS", 10)
    captured.answer = INVENTED
    out = server.local_lint_summary(text="src/a.py:1:1: E501 Line too long\n")
    assert len(captured) == 1
    assert WARNING_ES in out


def test_the_chunked_lint_warns_of_invented_files(captured, monkeypatch):
    """Mutant "chunked `_add_not_mentioned` without `_lint_invented`"."""
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 1200)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 1200)
    log = "".join(
        f"src/pkg/mod_{f:02d}.py:{n + 1}:1: E501 Line too long\n"
        for f in range(30)
        for n in range(3)
    )
    captured.answer = INVENTED
    out = server.local_lint_summary(text=log)
    assert len(captured) > 2  # guard: the log was chunked
    assert WARNING_ES in out
