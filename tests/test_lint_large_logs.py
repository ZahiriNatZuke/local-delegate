"""Wave lint-large-logs: the chunked lint of very large logs, bounded and with program counts.

Born of backlog §1.8 (`evidence/B2e/live.md`): with logs of 150-210 k characters the final step of
the chunked lint wrote one entry per file (50-130 files), 6-8 k characters, and ended in `length`;
the map steps counted tests per file chunk by chunk and got them wrong. Now each map answers in a
terse format with no figures and an entry only for the most named files of its chunk, the final
step an entry only for the `LINT_TOP_FILES` most named files of the log, with the counts of the
program, and the program adds how many files are left out. Map and final steps have larger caps.

`lint_patterns.per_file_code_counts` gives the program the count per file in the formats that put
the file and the code on the same diagnostic (ruff concise and full, tsc). The per-file counts in
the mechanical call (iterations 1 and 2 of the wave) were measured and not adopted; a control test
checks that the call is as in the base.

The backend is faked (`_run_chat`): no network, no GPU. Each test names the mutant that makes it
fail (`evidence/lint-large-logs/mutants.json`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_delegate import config, i18n, lint_patterns, server

BASE = "Resume la siguiente salida de linter/tests:\n\n"

#: Three files with different counts per file: F401 is 1 + 2 = 3 in the whole log.
THREE_FILES = (
    "app/main.py:12:101: E501 Line too long\n"
    "app/main.py:40:105: E501 Line too long\n"
    "app/main.py:7:8: F401 `os` imported but unused\n"
    "app/util.py:3:8: F401 `sys` imported but unused\n"
    "app/util.py:9:8: F401 `re` imported but unused\n"
    "app/util.py:55:120: E501 Line too long\n"
    "app/util.py:70:5: W291 Trailing whitespace\n"
    "app/cli.py:88:101: E501 Line too long\n"
    "Found 8 errors.\n"
)


class _Calls(list):
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


def _pytest_log(files: int, tests: int) -> str:
    return (
        "".join(
            f"tests/test_mod_{f:02d}.py::test_case_{t}\n"
            for f in range(files)
            for t in range(tests)
        )
        + f"{files * tests} tests collected\n"
    )


def _ruff_log(files: int, per_file: int) -> str:
    rules = ["CPY001 Missing copyright notice", "D401 First line of docstring", "S603 subprocess"]
    return (
        "".join(
            f"src/pkg/mod_{f:02d}.py:{n + 1}:1: {rules[(f + n) % 3]}\n"
            for f in range(files)
            for n in range(per_file + f % 4)
        )
        + "Found many errors.\n"
    )


# --- per-file counts: the program -------------------------------------------------------------


def test_per_file_counts_of_the_countable_formats():
    """ruff concise, ruff full and tsc give the count of each code in each file; most first."""
    assert lint_patterns.per_file_code_counts(THREE_FILES) == {
        "app/util.py": {"F401": 2, "E501": 1, "W291": 1},
        "app/main.py": {"E501": 2, "F401": 1},
        "app/cli.py": {"E501": 1},
    }
    full = (
        "D101 Missing docstring in public class\n --> src/a.py:3:7\n"
        "E501 Line too long (120 > 88)\n --> src/a.py:9:89\n"
        "D101 Missing docstring in public class\n --> src/b.py:1:7\n"
    )
    assert lint_patterns.per_file_code_counts(full) == {
        "src/a.py": {"D101": 1, "E501": 1},
        "src/b.py": {"D101": 1},
    }
    tsc = (
        "src/x.ts(3,5): error TS2345: Argument of type 'string'.\n"
        "src/x.ts(9,1): error TS2345: Argument of type 'string'.\n"
        "src/y.ts(1,1): error TS2532: Object is possibly 'undefined'.\n"
    )
    assert lint_patterns.per_file_code_counts(tsc) == {
        "src/x.ts": {"TS2345": 2},
        "src/y.ts": {"TS2532": 1},
    }


def test_formats_that_do_not_say_the_file_of_each_code_give_no_per_file_counts():
    """eslint stylish (the file on its own line), pytest (no codes), prose: `None`."""
    eslint = "/repo/src/a.ts\n  12:7  error  'x' is unused  no-unused-vars\n"
    assert lint_patterns.per_file_code_counts(eslint) is None
    assert lint_patterns.per_file_code_counts(_pytest_log(3, 2)) is None
    assert lint_patterns.per_file_code_counts("Todo en orden.\n") is None


# --- the mechanical call: not touched (iterations 1 and 2 did not reach the criterion) --------


def test_the_mechanical_call_keeps_the_counts_of_the_whole_log(captured):
    """Control: the per-file counts of iterations 1 and 2 were not adopted (`plan.md`); the
    mechanical call keeps the inventory of the base, with the count of each code in the log."""
    server.local_lint_summary(text=THREE_FILES)
    (call,) = captured
    head = call["user"].partition(BASE)[0]
    assert head.startswith("Ficheros que nombra el log") and "F401: 3" in head


# --- problem 1: the chunked lint ---------------------------------------------------------------


@pytest.fixture
def chunked(monkeypatch) -> None:
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 1200)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 1200)


def test_the_chunked_lint_bounds_the_entries_and_counts_the_rest(captured, chunked):
    """Mutant "one entry per file" (`_lint_final_inventory` without the rule and
    `_lint_other_files` returning the answer): the final prompt does not limit the entries and
    the answer has no line with the files left out."""
    log = _ruff_log(30, 3)
    out = server.local_lint_summary(text=log)
    maps, final = captured[:-1], captured[-1]
    assert len(maps) > 1  # guard: the log was chunked
    assert "Escribe una entrada solo para los 10 ficheros de la lista" in final["user"]
    assert "(de 30), con su número de diagnósticos contado por el programa:" in final["user"]
    per = lint_patterns.per_file_code_counts(log)
    top = lint_patterns.files_by_frequency(log)[0]
    assert f"{top} {sum(per[top].values())}" in final["user"]
    assert "nunca dentro de la entrada de un fichero" in final["user"]
    assert "Ninguna entrada más tras el último." in final["user"]
    assert "Y otros 20 ficheros que nombra el log no tienen entrada en el resumen." in out


def test_the_map_steps_give_no_figures_per_file(captured, chunked):
    """Mutant "map of before" (`_build` of B2e back in the map): no map prompt forbids figures."""
    server.local_lint_summary(text=_pytest_log(40, 3))
    maps = captured[:-1]
    assert len(maps) > 1  # guard: the log was chunked
    for call in maps:
        assert call["user"].startswith("Esto es un trozo de un log mayor. Responde en formato")
        assert "sin explicarlos y sin cifras" in call["user"]


def test_a_map_with_many_files_names_only_the_most_named(captured, chunked):
    """A chunk naming more than `LINT_TOP_FILES` files lists the ones that get an entry."""
    server.local_lint_summary(text=_pytest_log(60, 1))
    first = captured[0]["user"]
    assert "ficheros: da entrada solo a estos, los más nombrados, y a ningún otro:" in first
    listed = first.split("y a ningún otro: ", 1)[1].split(".\n", 1)[0]
    assert len(listed.split(", ")) == server.LINT_TOP_FILES


def test_a_chunked_log_without_per_file_counts_forbids_them(captured, chunked):
    """pytest: the program cannot give a count per file, so the final step must give none.
    Mutant "no prohibition": the final prompt lacks the rule."""
    out = server.local_lint_summary(text=_pytest_log(40, 3))
    final = captured[-1]["user"]
    assert "Los 10 ficheros más nombrados del log (de 40):" in final
    assert "El log no da cifras por fichero: no pongas ninguna en las entradas." in final
    assert "Y otros 30 ficheros" in out


def test_a_chunked_log_with_few_files_has_no_line_of_the_rest(captured, chunked):
    """Control: with `LINT_TOP_FILES` files or fewer every file gets an entry and no line."""
    out = server.local_lint_summary(text=_ruff_log(6, 20))
    assert len(captured) > 2  # guard: the log was chunked
    final = captured[-1]["user"]
    assert "Escribe una entrada solo para los 6 ficheros de la lista, en ese orden." in final
    assert "Y otros" not in out


def test_the_line_of_the_rest_in_english(captured, chunked, monkeypatch):
    """The line comes from the catalog: in English with `LOCAL_DELEGATE_LANG=en`."""
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    i18n.reset()
    out = server.local_lint_summary(text=_pytest_log(40, 3))
    assert "And 30 other files named by the log have no entry in the summary." in out
