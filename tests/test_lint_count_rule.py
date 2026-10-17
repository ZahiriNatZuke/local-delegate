"""B2d-3: `local_lint_summary` asks for a count only when the log gives it or it can be counted.

In the live measurement of B2d-2 (`evidence/B2d-2/live.md`, point 6) `fidelity_total` went from 9
to 12 over the 10 logs of set 3: per-item counts in parentheses ("Claude Code Client (3)") that the
log does not carry. The format asked for "the count per error type/rule" with no condition. The
prompt now says where a count may come from (`server._lint_count_clause`), in the single call and
in every step of the chunking, in both languages of the product. Step 1b: a total line of the log
("Found 10 errors.") is copied as it is; the live measurement of step 1 lost them. Step 1c: items
with the same problem go in one line; in the live measurement of step 1b a log with no total line
came out cut by `max_tokens`, one block per item with the same sentence.

The prompts are captured with a fake backend (`_run_chat` doubled), with no network: what is
tested is the prompt sent, not what a real model does with it (that is the live measurement of
`evidence/B2d-3/measure.md`).
"""

from __future__ import annotations

import importlib.util
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
#: Step 1c: items with the same problem, in one line that names them together.
RULE_GROUPING = (
    " Si varios elementos tienen el mismo problema, aunque sean de archivos distintos, ponlos en "
    "una sola línea que los nombre juntos, en vez de repetir el mismo texto por cada uno; si el "
    "contenido no dice cuántos son, nómbralos sin poner número."
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
    server.local_lint_summary(text=LOG_WITHOUT_FIGURES * 40)
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


# --- Step 1c: items with the same problem go in one line -----------------------------------------

#: A log with no total line and the same problem in several items, like B35 of set 3.
LOG_SAME_PROBLEM = "".join(
    f"commit-trampa-{name}: system cambio con los prompts de la 0.36.0\n"
    for name in ("uno", "dos", "tres", "cuatro", "cinco", "seis")
)


@pytest.mark.parametrize(("product", "output"), BATCHES)
@pytest.mark.parametrize("chunked", [False, True], ids=["single", "chunked"])
def test_items_with_the_same_problem_go_in_one_line(
    monkeypatch, captured, product, output, chunked
):
    """In the live measurement of step 1b, B35 (no total line) came out cut by `max_tokens` in its
    3 repetitions: one block per item, all with the same sentence (`evidence/B2d-3/live.md`).
    Mutant "without the sentence of step 1c": fails at `RULE_GROUPING in step["system"]`, in the
    single call and in every step of the chunking; the rules of step 1 and 1b still hold."""
    _languages(monkeypatch, product, output)
    if chunked:
        monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 1200)
        monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 1200)
    server.local_lint_summary(text=LOG_SAME_PROBLEM * (20 if chunked else 1))
    assert len(captured) > 2 if chunked else len(captured) == 1  # guard: the path asked for
    for step in captured:
        system = step["system"]
        assert RULE_GROUPING in system, system[-900:]
        assert RULE_TOTAL_LINE in system
        _assert_count_rule(system)
        # After the total line and before the language order, which still closes the prompt.
        assert system.index(RULE_TOTAL_LINE) < system.index(RULE_GROUPING)
        assert system.index(RULE_GROUPING) < system.rindex(server._lint_language_clause())


def test_the_grouping_rule_does_not_clash_with_the_count_rule():
    """With no figure in the log the grouped items carry no number: the grouping must not ask for
    "how many" when the log does not say it. Mutant "without the sentence of step 1c": fails at
    `RULE_GROUPING in clause`; the rule against counts in parentheses stays, with no digit."""
    clause = server._lint_count_clause()
    assert RULE_GROUPING in clause
    assert "si el contenido no dice cuántos son, nómbralos sin poner número" in clause
    assert RULE_NO_NUMBER in clause
    assert not any(ch.isdigit() for ch in clause)


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
