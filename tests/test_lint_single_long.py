"""B2f: the single `local_lint_summary` call of the `long` role keeps the rule codes (front B).

Born of the live measurement of B2-affinity (`evidence/B2-affinity/live.md`) and of the check on
`main` of `evidence/B2f/live.md`: with the hardened language order `gemma4-26b-a4b`, the model of
the `long` role, describes each rule in words and leaves out its code ("Línea demasiado larga"
instead of `E501`). The single call of that role now gets what the chunked lint got in B2e: the
inventory of files and codes of the log in front of it, computed by the program and without
counts, and the "not mentioned" line after the answer. The `mechanical` role is not touched.

The backend is faked (`_run_chat`): no network. Each block names the mutant that makes it fail
(recorded in `evidence/B2f/mutants.json`).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from local_delegate import config, i18n, lint_patterns, server

BASE = "Resume la siguiente salida de linter/tests:\n\n"


def _ruff_log(files: int, per_file: int) -> str:
    rules = ["CPY001 Missing copyright notice", "D401 First line of docstring", "S603 subprocess"]
    return (
        "".join(
            f"src/pkg/mod_{f:02d}.py:{n + 1}:1: {rules[n % 3]}\n"
            for f in range(files)
            for n in range(per_file)
        )
        + f"Found {files * per_file} errors.\n"
    )


class _Calls(list):
    """The captured calls, and the text the fake model answers (`answer`)."""

    answer = "- nota"


@pytest.fixture
def captured(monkeypatch, tmp_path) -> _Calls:
    """`_run_chat` doubled; the fake model answers `calls.answer` ("- nota" names nothing)."""
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


@pytest.fixture
def long_role(monkeypatch) -> None:
    """Small logs go to the `long` role (as a log of 6-48 k characters does), in one call."""
    monkeypatch.setattr(config, "LONG_INPUT_CHARS", 100)


def _rows(tmp_path: Path) -> list[dict]:
    return [
        json.loads(line)
        for file in sorted(tmp_path.glob("*.jsonl"))
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.mark.parametrize("product", ["es", "en"])
def test_the_single_long_lint_call_gets_the_inventory_in_front_of_the_log(
    monkeypatch, captured, long_role, tmp_path, product
):
    """Mutant "the prompt of before" (`_lint_single_user` returns `base` for every role): the
    inventory asserts fail, not the guards that it was ONE call of the long role."""
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", product)
    i18n.reset()
    log = _ruff_log(4, 3)
    server.local_lint_summary(text=log)
    (call,) = captured  # guard: a single call, no chunking
    (row,) = _rows(tmp_path)
    assert row["model"] == config.models_by_role()["long"]  # guard: the long role
    assert call["system"] == server._lint_system(200)  # the system is not touched
    # Mutant "the cap of before" (factor 1): this assert fails, not the guards above.
    assert call["max_tokens"] == 2 * server._lint_max_tokens(200) == 1456  # rule (2) of B2f
    head, sep, rest = call["user"].partition(BASE)
    assert sep and rest == log  # the log goes as before, after the inventory
    assert "src/pkg/mod_00.py" in head and "CPY001" in head and "S603" in head
    assert head.startswith("Ficheros que nombra el log")
    # Wave lint-counts: each code carries its count in the whole log (4 files x 1 of each rule),
    # and the prompt says to copy it. Mutant "inventory without counts" (`with_counts=False` in
    # `_lint_single_user`): these asserts fail, not the ones above.
    assert "CPY001: 4, D401: 4, S603: 4" in head
    assert server._LINT_COUNTS_CLAUSE.strip() in head
    figures = re.sub(r"\b[A-Z]{1,5}\d{2,5}: \d+", " ", head)
    names = lint_patterns.RULE.sub(" ", lint_patterns.FILE.sub(" ", figures))
    assert not re.search(r"\d", names), head  # no other figure than the counts of the codes


def test_the_counts_of_the_single_long_call_come_from_the_log(captured, long_role):
    """Wave lint-counts: the counts are the log's, not a constant. Positive control: a log with
    different counts per code gives different figures (5, 2, 1), in that order; a code inside a
    file name (`test_E501.py`) is not counted. Mutant "count each code once" (`code_counts`
    returns 1 for every code): the first assert fails."""
    log = (
        "".join(f"a.py:{n}:1: D101 Missing docstring\n" for n in range(1, 6))
        + "b.py:1:1: E501 Line too long\nb.py:9:1: E501 Line too long\n"
        + "tests/test_E501.py:3:1: F401 unused import\n"
        + "Found 8 errors.\n"
    )
    server.local_lint_summary(text=log)
    (call,) = captured
    assert "D101: 5, E501: 2, F401: 1" in call["user"]
    assert "E501: 3" not in call["user"]


@pytest.mark.parametrize(("product", "label"), [("es", "Sin mencionar"), ("en", "Not mentioned")])
def test_the_single_long_lint_answer_lists_what_it_does_not_mention(
    monkeypatch, captured, long_role, product, label
):
    """Mutant "no fallback" (no `postprocess` in the single call): the line is missing and this
    assert fails, not the guard that it was one call. The fake model names nothing."""
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", product)
    i18n.reset()
    out = server.local_lint_summary(text=_ruff_log(4, 3))
    assert len(captured) == 1  # guard: a single call
    (line,) = [ln for ln in out.splitlines() if ln.startswith(label)]
    assert "src/pkg/mod_00.py" in line and "CPY001" in line and "S603" in line
    assert not re.search(r"\d", lint_patterns.RULE.sub(" ", lint_patterns.FILE.sub(" ", line)))


def test_a_long_answer_that_names_everything_gets_no_line(captured, long_role):
    """Positive control of the fallback: what the model names is not listed again."""
    captured.answer = (
        "mod_00.py, mod_01.py, mod_02.py y mod_03.py: CPY001, D401 y S603. Found 12 errors."
    )
    out = server.local_lint_summary(text=_ruff_log(4, 3))
    assert len(captured) == 1
    assert "Sin mencionar" not in out
    assert "CPY001, D401 y S603" in out  # guard: the answer of the model is there


def test_the_mechanical_single_call_gets_the_inventory_and_keeps_the_rest(captured, tmp_path):
    """Affinity by language: the `mechanical` role gets the inventory with counts too (the 26B
    of the affinity cell answers with this prompt), and keeps its cap and no "not mentioned"
    line. Mutant "the long role only" (`_lint_single_user` returns `base` for `mechanical`): the
    inventory assert fails, not the guard of the role. One file: with several files and a
    countable format the mechanical call gets the counts per file instead (wave lint-large-logs,
    `tests/test_lint_large_logs.py`)."""
    log = _ruff_log(1, 12)
    out = server.local_lint_summary(text=log)
    (call,) = captured
    (row,) = _rows(tmp_path)
    assert row["model"] == config.models_by_role()["mechanical"]  # guard: the mechanical role
    head, sep, rest = call["user"].partition(BASE)
    assert sep and rest == log
    assert head.startswith("Ficheros que nombra el log") and "CPY001: 4, D401: 4, S603: 4" in head
    assert call["max_tokens"] == server._lint_max_tokens(200) == 728  # its cap of before
    assert "Sin mencionar" not in out


def test_a_long_log_without_files_or_codes_keeps_the_prompt_of_before(captured, long_role):
    """Control: with nothing to list there is no inventory and no line (B34 and A11 of set 3)."""
    log = "Todo en orden.\nComprobaciones superadas: todas.\n" * 4
    out = server.local_lint_summary(text=log)
    (call,) = captured
    assert call["user"] == BASE + log
    assert "Sin mencionar" not in out
