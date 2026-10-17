"""B2d-3: `local_lint_summary` asks for a count only when the log gives it or it can be counted.

In the live measurement of B2d-2 (`evidence/B2d-2/live.md`, point 6) `fidelity_total` went from 9
to 12 over the 10 logs of set 3: per-item counts in parentheses ("Claude Code Client (3)") that the
log does not carry. The format asked for "the count per error type/rule" with no condition. The
prompt now says where a count may come from (`server._lint_count_clause`), in the single call and
in every step of the chunking, in both languages of the product.

The prompts are captured with a fake backend (`_run_chat` doubled), with no network: what is
tested is the prompt sent, not what a real model does with it (that is the live measurement of
`evidence/B2d-3/measure.md`).
"""

from __future__ import annotations

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
