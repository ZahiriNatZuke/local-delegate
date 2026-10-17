"""B2d-3: `local_lint_summary` asks for a count only when the log gives it or it can be counted.

In the live measurement of B2d-2 (`evidence/B2d-2/live.md`, point 6) `fidelity_total` went from 9
to 12 over the 10 logs of set 3: per-item counts in parentheses ("Claude Code Client (3)") that the
log does not carry. The format asked for "the count per error type/rule" with no condition. The
prompt now says where a count may come from (`server._lint_count_clause`), in the single call and
in every step of the chunking, in both languages of the product. Step 1b: a total line of the log
("Found 10 errors.") is copied as it is; the live measurement of step 1 lost them.

The prompts are captured with a fake backend (`_run_chat` doubled), with no network: what is
tested is the prompt sent, not what a real model does with it (that is the live measurement of
`evidence/B2d-3/measure.md`).
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from local_delegate import config, i18n, server

OUTPUT = "LOCAL_DELEGATE_OUTPUT_LANGUAGE"
#: (product language, output variable): the two batches of the live measurement.
BATCHES = [("es", "en"), ("en", "es")]

#: A log with no figures at all: any count in the answer would be invented.
LOG_WITHOUT_FIGURES = (
    "Claude Code Client: falta la credencial\n"
    "Claude Code Client: no se encuentra el fichero de ajustes\n"
    "Servicios: el daemon no responde\n"
)
#: A log whose figures are real: the control.
LOG_WITH_FIGURES = (
    "src/a.py:1:1: E501 Line too long (120 > 88)\n"
    "src/b.py:3:5: F401 `os` imported but unused\n"
    "Found 12 errors.\n"
    "[*] 4 fixable with the `--fix` option.\n"
)
INVENTED = "**Claude Code Client (3)**: missing credential and settings file."

RULE_SOURCE = " La cantidad sale solo del contenido:"
RULE_NO_NUMBER = (
    "Si el contenido no la da y no se puede contar, no pongas ningún número: nada de recuentos "
    "entre paréntesis."
)
OLD_FORMAT = "con el conteo por tipo de error/regla y los más relevantes primero"
#: Step 1b: the total line of the log, copied as it is.
RULE_TOTAL_LINE = (
    " Si el contenido trae una línea de total (la que dice cuántos errores, avisos o tests hay, "
    "como «Found … errors.» o «… passed»), cópiala tal cual, con sus cifras; si no la trae, no "
    "inventes ninguna."
)


@pytest.fixture
def captured(monkeypatch) -> list[dict]:
    """Every call to the backend, answered with an invented count in parentheses."""
    calls: list[dict] = []

    def run_chat(model, system, user, max_tokens, temperature, **_):
        calls.append({"system": system, "user": user})
        result = server.ChatResult(text=INVENTED, ok=True, finish_reason="stop")
        return result, 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    return calls


def _tag(n: int) -> str:
    """A name with no digit for the `n`-th copy (`aa`, `ab`, …): a figure would be a count."""
    letters = "abcdefghijklmnopqrstuvwxyz"
    return letters[n // 26 % 26] + letters[n % 26]


def _spread(log: str, copies: int) -> str:
    """`copies` copies of `log`, each line under its own file: long enough to chunk, and B2d-4 does
    not compact it (a line with a file location never groups), as `log * copies` would."""
    return "".join(
        f"pkg-{_tag(n)}/run.log: {line}\n" for n in range(copies) for line in log.splitlines()
    )


def _languages(monkeypatch, product: str, output: str) -> None:
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", product)
    monkeypatch.setenv(OUTPUT, output)
    i18n.reset()


def _assert_count_rule(system: str) -> None:
    assert RULE_SOURCE in system, system[-700:]
    assert RULE_NO_NUMBER in system, system[-700:]
    assert OLD_FORMAT not in system, "the unconditional count of before stayed in the format"


@pytest.mark.parametrize(("product", "output"), BATCHES)
def test_a_log_without_figures_gets_the_count_rule(monkeypatch, captured, product, output):
    """Mutant "`_lint_system` without `_lint_count_clause`": fails at `RULE_SOURCE in system`.

    The fake model answers "(3)", as gemma4 did on `doctor` with the home empty: the rule is what
    the prompt can do about it, and it has to be in the prompt sent, in both batches.
    """
    _languages(monkeypatch, product, output)
    out = server.local_lint_summary(text=LOG_WITHOUT_FIGURES)
    (call,) = captured
    assert INVENTED in out  # guard: the fake model was really called
    assert LOG_WITHOUT_FIGURES.strip() in call["user"]
    _assert_count_rule(call["system"])
    # The language order still closes the prompt: the rule goes before it, not after.
    assert call["system"].endswith(server._lint_language_clause())


@pytest.mark.parametrize(("product", "output"), BATCHES)
def test_the_count_rule_is_in_every_step_of_the_chunking(monkeypatch, captured, product, output):
    """Map and reduce: the reduce does not use `system`, the rule goes in `reduce_extra` too.

    Mutant "`reduce_extra` without the rule": fails at `RULE_SOURCE` in the last step.
    """
    _languages(monkeypatch, product, output)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 1200)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 1200)
    server.local_lint_summary(text=_spread(LOG_WITHOUT_FIGURES, 40))
    assert len(captured) > 2  # guard: it really chunked
    assert "Resume la siguiente salida" not in captured[-1]["user"]  # guard: the last one reduces
    for step in captured:
        _assert_count_rule(step["system"])


@pytest.mark.parametrize(("product", "output"), BATCHES)
def test_control_a_log_with_real_figures_keeps_them(monkeypatch, captured, product, output):
    """Control: the rule removes invented counts, not the real ones.

    The log reaches the model untouched, with its figures, and the format still asks for the count
    when it can be known: a rule that said "no numbers" would pass the two tests above and fail
    here.
    """
    _languages(monkeypatch, product, output)
    server.local_lint_summary(text=LOG_WITH_FIGURES)
    (call,) = captured
    assert LOG_WITH_FIGURES.strip() in call["user"]
    for figure in ("Found 12 errors.", "4 fixable", "(120 > 88)"):
        assert figure in call["user"]
    assert "con la cantidad por tipo de error/regla cuando se pueda saber" in call["system"]
    assert "la que el contenido escribe (una línea de total o un recuento)" in call["system"]
    assert "la que cuentas tú con las líneas que el contenido repite" in call["system"]


# --- Step 1b: the total line of the log is copied as it is --------------------------------------


@pytest.mark.parametrize(("product", "output"), BATCHES)
@pytest.mark.parametrize("chunked", [False, True], ids=["single", "chunked"])
def test_the_total_line_is_copied_as_it_is(monkeypatch, captured, product, output, chunked):
    """In the live measurement of step 1 the `ruff` answers lost "Found 10 errors." and "Found 7
    errors." (`evidence/B2d-3/live.md`). Mutant "without the sentence of step 1b": fails at
    `RULE_TOTAL_LINE in system`, in the single call and in every step of the chunking; the rule
    against invented counts still holds (`_assert_count_rule`)."""
    _languages(monkeypatch, product, output)
    if chunked:
        monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 1200)
        monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 1200)
    server.local_lint_summary(text=LOG_WITH_FIGURES * (40 if chunked else 1))
    assert len(captured) > 2 if chunked else len(captured) == 1  # guard: the path asked for
    for step in captured:
        assert RULE_TOTAL_LINE in step["system"], step["system"][-700:]
        _assert_count_rule(step["system"])
        # The language order still closes the prompt, after the total line.
        assert step["system"].index(RULE_TOTAL_LINE) < step["system"].rindex(
            server._lint_language_clause()
        )


def test_the_total_line_rule_gives_the_model_no_figure_to_copy():
    """The examples of the rule carry no digit: a "Found 10 errors." in the prompt would be a
    figure the model could copy into a log that has none."""
    assert RULE_TOTAL_LINE in server._lint_count_clause()
    assert not any(ch.isdigit() for ch in server._lint_count_clause())


# --- The control of the live measurement (`evidence/B2d-3/check_controls.py`) -------------------

CONTROLS_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".sdd/changes/english-names-bilingual-output/evidence/B2d-3/check_controls.py"
)


def _controls():
    spec = importlib.util.spec_from_file_location("b2d3_check_controls", CONTROLS_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_control_takes_a_figure_that_ends_the_sentence():
    """B31 of the step 1 said "Pruebas superadas: 57." and came out as not kept. Mutant "the
    regex of before" (lookahead without a digit or a dot): the first assert fails."""
    controls = _controls()
    assert controls.kept("Pruebas superadas: 57.", "57")
    assert controls.kept("57 passed in 3.2s", "57")
    assert not controls.kept("ratio 0.57 of the run", "57")
    assert not controls.kept("157 passed", "57")
    assert not controls.kept("57.3 seconds", "57")


def test_the_control_reads_the_repetitions_of_a_version(tmp_path):
    """`<id>-r<k>.txt`: a case is kept in a version when the majority of its repetitions keep it."""
    controls = _controls()
    for rep, text in (("1", "Pruebas superadas: 57."), ("2", "ratio 0.57"), ("3", "57 passed")):
        (tmp_path / f"B31-r{rep}.txt").write_text(text, encoding="utf-8")
    (tmp_path / "B32-r1.txt").write_text("Found 17 errors.", encoding="utf-8")
    result = controls.check_version(tmp_path)
    rows = {r["id"]: r for r in result["rows"]}
    assert (rows["B31"]["kept_reps"], rows["B31"]["runs"], rows["B31"]["ok"]) == (2, 3, True)
    assert (rows["B32"]["kept_reps"], rows["B32"]["ok"]) == (0, False)
    assert rows["A15"]["missing_answer"]
    assert result["cases_kept"] == ["B31"]


# --- B2d-4: a dense block of lines with the same problem is compacted by the program -----------

#: The first round of B2d-4 had a sentence of its own in the count rule about the marker; the
#: second round takes it out (the model of A12 counted the lines it saw instead of copying N).
MARKER_WORDS = "líneas más como las anteriores"
#: How many equal items the synthetic log carries (B35 had 45 and 40).
MANY = 60


def _marker(more: int, size: int) -> str:
    """The marker of a compacted block, with the two figures the program counts."""
    return f"… y {more} {MARKER_WORDS} ({size} en total)"


def _many_equal_items(copies: int = MANY) -> tuple[str, list[str]]:
    """A log like B35: a header, `copies` items with the same problem, and an `ok` line."""
    names = [f"item-{_tag(n)}" for n in range(copies)]
    body = "".join(
        f"  · {name}: system cambio con los prompts (frontera declarada)\n" for name in names
    )
    return f"idioma del corpus: es\n{body}ok\n", names


@pytest.mark.parametrize(("product", "output"), BATCHES)
def test_many_equal_items_reach_the_model_compacted(monkeypatch, captured, product, output):
    """B35 was cut by `max_tokens` in the 3 repetitions of step 1b: the model named the 80-odd
    `commit-…` items one by one. Mutant "`local_lint_summary` without `compact_repeated_lines`":
    fails at the first assert (the marker with the program's N is not in the prompt sent). Mutant
    "the marker without the total": the same assert fails (the `(60 en total)` is missing)."""
    _languages(monkeypatch, product, output)
    log, names = _many_equal_items()
    server.local_lint_summary(text=log)
    (call,) = captured
    more = MANY - server.LINT_REPEAT_KEEP
    assert _marker(more, MANY) in call["user"], call["user"][-400:]
    kept = [name for name in names if f"{name}:" in call["user"]]
    assert kept == names[: server.LINT_REPEAT_KEEP]  # the first ones, in their place
    assert "idioma del corpus: es" in call["user"] and call["user"].rstrip().endswith("ok")
    assert MARKER_WORDS not in call["system"], call["system"][-700:]
    _assert_count_rule(call["system"])


@pytest.mark.parametrize(("product", "output"), BATCHES)
def test_the_marker_reaches_a_step_of_the_chunking(monkeypatch, captured, product, output):
    """The block is compacted before the size check, so the marker with both figures reaches a
    map step, and every step keeps the count rule of step 1b and nothing about the marker.
    Mutant "the sentence of the first round back in `_lint_count_clause`": fails at
    `MARKER_WORDS not in` in the first step."""
    _languages(monkeypatch, product, output)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 1200)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 1200)
    log, _names = _many_equal_items()
    server.local_lint_summary(text=_spread(LOG_WITH_FIGURES, 20) + log)
    assert len(captured) > 2  # guard: it really chunked
    assert "Resume la siguiente salida" not in captured[-1]["user"]  # guard: the last one reduces
    for step in captured:
        assert MARKER_WORDS not in step["system"], step["system"][-700:]
        assert RULE_TOTAL_LINE in step["system"], step["system"][-700:]
        _assert_count_rule(step["system"])
    more = MANY - server.LINT_REPEAT_KEEP
    assert any(_marker(more, MANY) in step["user"] for step in captured[:-1])


def test_the_count_rule_is_the_one_of_step_1b():
    """Second round of B2d-4: the count rule goes back to step 1b, word for word (the marker is a
    count the content writes). Mutant "the sentence of the first round back": the `==` fails."""
    assert server._lint_count_clause() == RULE_SOURCE + (
        " la que el contenido escribe (una línea de total o un recuento) o la que cuentas tú con "
        "las líneas que el contenido repite. " + RULE_NO_NUMBER + RULE_TOTAL_LINE
    )


EVIDENCE = (
    Path(__file__).resolve().parents[1] / ".sdd/changes/english-names-bilingual-output/evidence"
)
DOCS_3 = EVIDENCE / "B2d-fix/docs-3"


def _log(name: str) -> str:
    content, _truncated, _raw = server._read_input(None, str(DOCS_3 / name), server._NO_TRUNCATE)
    return content


def test_n_is_counted_from_the_log_of_b35():
    """N against the log, counted here by a regex of its own, not by the function under test."""
    log = _log("es-log-B2d-fix_corpus-affinity-check.txt")
    system_lines = len(re.findall(r"^  \S+ \S+: system cambio ", log, re.MULTILINE))
    max_tokens_lines = len(re.findall(r"^  \S+ \S+: max_tokens cambio ", log, re.MULTILINE))
    assert (system_lines, max_tokens_lines) == (45, 40)  # guard: the log is the one of B35
    compacted, groups = server.compact_repeated_lines(log)
    assert groups == sorted([system_lines, max_tokens_lines])
    keep = server.LINT_REPEAT_KEEP
    assert _marker(system_lines - keep, system_lines) in compacted
    assert _marker(max_tokens_lines - keep, max_tokens_lines) in compacted
    assert len(compacted.splitlines()) == len(log.splitlines()) - (85 - 2 * keep) + 2
    # The lines out of the blocks stay, in order.
    assert compacted.splitlines()[0] == log.splitlines()[0]
    assert compacted.splitlines()[-1] == "ok"


@pytest.mark.parametrize(
    "name",
    [
        "en-log-biome-lint-nest.txt",  # A14: the same hint under each diagnostic, far apart
        "en-log-ruff-concise-build-site.txt",  # A15: the same rule in many files
        "es-log-check-llamaswap-pre-b10909.txt",  # A11
        "es-log-doctor-empty-home.txt",  # A13
    ],
)
def test_control_logs_without_a_dense_block_reach_the_model_untouched(name):
    """Control: the compaction does not touch a lint log by file nor the cases of the control of
    the live measurement. A rule that compacted every repeated line would pass the tests above and
    fail here (A14 repeats its hints 13 to 20 times)."""
    log = _log(name)
    assert server.compact_repeated_lines(log) == (log, [])


def test_control_the_same_rule_in_many_files_is_not_compacted():
    """Forty E501 in forty files: every file and line reaches the model."""
    log = "".join(f"src/m_{_tag(n)}.py:1:1: E501 Line too long (120 > 88)\n" for n in range(40))
    assert server.compact_repeated_lines(log) == (log, [])
    tied = "".join(f"  → {_tag(n)}: falla igual\n" for n in range(9))
    assert server.compact_repeated_lines(tied) == (tied, [])  # under LINT_REPEAT_MIN


def test_the_fidelity_counter_allows_the_programs_n_and_no_other():
    """The counter of the live measurement accepts the N the tool wrote in the prompt (and the
    block size) as a count the log supports, and still flags a made-up one."""
    spec = importlib.util.spec_from_file_location(
        "score_lint_fidelity",
        Path(__file__).resolve().parents[1] / "scripts/score_lint_fidelity.py",
    )
    assert spec is not None and spec.loader is not None
    scorer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scorer)
    log, _names = _many_equal_items()
    more = MANY - server.LINT_REPEAT_KEEP
    assert scorer.count_inventions(f"item-aa, item-ab, item-ac y {more} más.", log)["total"] == 0
    assert scorer.count_inventions(f"Los {MANY} elementos fallan igual.", log)["total"] == 0
    assert scorer.count_inventions(f"item-aa y {more + 4} más.", log)["total"] == 1
    assert (
        scorer.count_inventions(f"item-aa y {more} más ({MANY + 1} en total).", log)["total"] == 1
    )
