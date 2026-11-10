"""#538 (reopened in 0.50.0): a premise of the question confirmed next to real code, unflagged.

Asked where a measurement script «splits by main thread and subagent», the model answered that
«the split by main thread and subagent is done in `by_side`». The script never mentions
subagents: its only split is before/after a hook. No notice came out, for two reasons found by
running the check: «subagente» was not a word the check compares (only nominalizations were),
and the sentence named `by_side` and cited lines that hold it, which counts as anchored. Now
agent nouns like «subagente», «cliente» or «componente» are compared too, and such a noun the
file does not hold that the answer asserts beside real code gets a notice (not the warning: the
code it cites may handle it under another name). A process («partición») does not: code does it
under other names. Also «sesiones» was taken for
absent from a file with `session`: the Spanish single `s` of «sesión» is now matched against the
English double one. Fake backend, no network, log in tmp.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import test_explain_code_premise as first

BACKUP_JS = first.BACKUP_JS
BACKUP_QUESTION = first.QUESTION

from local_delegate import config, i18n, line_check, server

# Like `scripts/measure_adoption.py`: it counts sessions and splits only by the hook's footprint.
MEASURE_PY = '''import json


def hook_side(event, cutoff):
    """Before or after the hook's footprint."""
    return "after" if event["ts"] >= cutoff else "before"


def by_side(events, cutoff):
    sides = {"before": [], "after": []}
    for event in events:
        sides[hook_side(event, cutoff)].append(event)
    return sides


def count_sessions(events):
    return len({e["session"] for e in events})
'''
QUESTION = (
    "¿Dónde se decide qué sesiones se cuentan y cómo se parten por hilo principal y subagente?"
)
#: The answer of the issue, in short: the premise placed in a real function, with right lines.
CONFIRMED = (
    "Las sesiones se cuentan en `count_sessions` (línea 17). "
    "La partición por hilo principal y subagente se realiza en la función `by_side` (línea 9)."
)
#: What it should have said.
DENIED = (
    "Las sesiones se cuentan en `count_sessions` (línea 17). El fichero no separa por hilo "
    "principal y subagente: `by_side` (línea 9) solo parte en antes y después del hook."
)


def _notice(terms: str) -> str:
    return i18n.t("mcp.explain.premise_beside_code", terms=terms)


def test_an_agent_noun_of_the_question_is_a_premise_term():
    """Mutant «only nominalizations» (`_AGENT_NOUN` ignored): «subagente» is not compared."""
    assert line_check.premise_terms(QUESTION, MEASURE_PY) == ["subagente"]


def test_a_spanish_single_s_is_held_by_the_english_double():
    """Mutant «no `sion`→`ssion` variant»: «sesiones» comes back as absent."""
    assert "sesiones" not in line_check.premise_terms(QUESTION, MEASURE_PY)
    assert line_check.premise_terms("¿qué hace la sesión?", "x = 1\n") == ["sesión"]


@pytest.mark.parametrize(
    "question",
    [
        "¿qué hace la función siguiente durante el arranque?",
        "¿cómo responde rápidamente antes de escribir?",
        "¿cuál es la fuente de los datos?",
    ],
)
def test_words_of_asking_ending_like_agent_nouns_are_not_terms(question):
    """Adverbs in -mente and words like «siguiente», «durante», «antes», «fuente» are not."""
    assert line_check.premise_terms(question, MEASURE_PY) == []


def test_an_agent_noun_the_file_holds_is_not_a_term():
    """«cliente» shares `clien` with `client`: held."""
    assert line_check.premise_terms("¿cómo crea el cliente?", "client = make()\n") == []


def test_the_reopened_case_gets_the_notice_and_the_denial_does_not():
    """The data that distinguishes: same file and question, the confirmed premise and the denial.

    The warning stays for unanchored sentences; this sentence is anchored, so it is the notice.
    Mutant «no beside-code branch» (`premises_beside_code` returns []): the first assert falls.
    Mutant «no negation check»: the second falls.
    """
    assert line_check.premises_beside_code(CONFIRMED, QUESTION, MEASURE_PY) == ["subagente"]
    assert line_check.premises_beside_code(DENIED, QUESTION, MEASURE_PY) == []
    # Anchored, so not the warning: the existing contract holds.
    assert line_check.unsupported_premises(CONFIRMED, QUESTION, MEASURE_PY) == []


def test_an_unanchored_premise_gets_the_warning_not_the_notice():
    answer = "La partición por subagente es implícita."
    assert line_check.unsupported_premises(answer, QUESTION, MEASURE_PY) == ["subagente"]
    assert line_check.premises_beside_code(answer, QUESTION, MEASURE_PY) == []


def test_a_premise_the_answer_does_not_name_gets_nothing():
    answer = "Las sesiones se cuentan en `count_sessions` (línea 17)."
    assert line_check.premises_beside_code(answer, QUESTION, MEASURE_PY) == []


#: Live answer of the installed 0.50.0 (2026-11-10), right: `by_side` does split the events.
LIVE_RIGHT = (
    "La función clave `by_side` (línea 9) realiza la partición de los eventos. Inicializa un "
    'diccionario `sides` con dos listas vacías: "before" y "after" (línea 10).'
)
#: Its next sentence, the premise confirmed with nothing behind it.
LIVE_PREMISE = (
    " Esta división permite que el hilo principal y un subagente procesen por separado los "
    "eventos que ocurrieron antes y después del punto de corte."
)
LIVE_QUESTION = (
    "Explica cómo by_side reparte los eventos entre el hilo principal y el subagente, y en qué "
    "líneas se hace esa partición."
)


def test_a_process_done_under_another_name_gets_no_notice():
    """«partición» is a process: `by_side` does it without the word. Only agent nouns get the
    notice; the live check flagged this right answer before that rule. Mutant «every anchored
    term» (no `_is_agent_noun` filter in `premises_beside_code`): this assert falls. The first
    fix's anchored retention stays its known limit, as `test_an_anchored_assertion_is_not_flagged`
    says."""
    assert line_check.premise_terms(LIVE_QUESTION, MEASURE_PY) == ["subagente", "partición"]
    assert line_check.premises_beside_code(LIVE_RIGHT, LIVE_QUESTION, MEASURE_PY) == []
    answer = "`createBackup()` aplica una retención implícita por timestamp."
    assert line_check.premises_beside_code(answer, BACKUP_QUESTION, BACKUP_JS) == []


def test_the_live_premise_gets_the_warning():
    """The live answer of 0.50.0 said nothing; its premise sentence names no code: the warning."""
    answer = LIVE_RIGHT + LIVE_PREMISE
    assert line_check.unsupported_premises(answer, LIVE_QUESTION, MEASURE_PY) == ["subagente"]
    assert line_check.premises_beside_code(answer, LIVE_QUESTION, MEASURE_PY) == []


def test_the_existing_correct_answers_get_no_notice():
    """No new noise on the corpus of the first fix (GOOD, OTHER_GOOD, COGNATES)."""
    for question, answer_text, content in first.GOOD + first.OTHER_GOOD:
        assert line_check.premises_beside_code(answer_text, question, content) == [], answer_text
    for question, answer_text in first.COGNATES:
        assert line_check.premises_beside_code(answer_text, question, first.LOGS_PY) == []


# --- through the tool ---------------------------------------------------------------------------


@pytest.fixture
def answer(monkeypatch, tmp_path) -> dict:
    state = {"text": CONFIRMED}

    def run_chat(model, system, user, max_tokens, temperature, **_):
        result = server.ChatResult(text=state["text"], ok=True, finish_reason="stop")
        return result, 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    monkeypatch.delenv("LOCAL_DELEGATE_OUTPUT_LANGUAGE", raising=False)
    i18n.reset()
    return state


@pytest.fixture
def module(tmp_path: Path) -> Path:
    source = tmp_path / "measure.py"
    source.write_text(MEASURE_PY, encoding="utf-8")
    return source


def test_the_tool_adds_the_notice_on_the_reopened_case(answer, module):
    """Mutant «`_verified_lines` without the beside-code branch»: this assert falls."""
    result = server.local_explain_code(path=str(module), question=QUESTION)
    assert result.startswith(CONFIRMED)  # the prose is not rewritten
    assert _notice("«subagente»") in result


def test_the_tool_adds_nothing_on_the_denial(answer, module):
    answer["text"] = DENIED
    result = server.local_explain_code(path=str(module), question=QUESTION)
    assert _notice("«subagente»") not in result
    assert server.WARNING_MARKER not in result


def test_the_notice_comes_in_english_too(answer, module, monkeypatch):
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    i18n.reset()
    result = server.local_explain_code(path=str(module), question=QUESTION)
    assert _notice("«subagente»") in result
    assert "does not" in result
