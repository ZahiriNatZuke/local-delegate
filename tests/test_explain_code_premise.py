"""#538: `local_explain_code` confirmed a premise of the question that the code does not meet.

Asked «¿cómo gestiona los backups y su retención?» about an installer module that creates
timestamped backups and never deletes one, the model answered there was an «implicit retention»,
with no warning. Now, with `path` and a question, a word of the question that the file does not
hold (by its first letters, without accents) and that the answer asserts in a sentence that
neither negates it nor stands on the code (a verified cited line, or a code identifier that is in
the file) gets a warning. The answer that denies the premise passes. Fake backend (`_run_chat`
doubled), no network, log in tmp.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from local_delegate import config, i18n, line_check, server

# A JS installer module: timestamped backups, created and listed, never deleted.
BACKUP_JS = """const fs = require('fs');
const path = require('path');

const BACKUP_DIR = path.join(__dirname, 'backups');

function stamp() {
  return new Date().toISOString().replace(/[:.]/g, '-');
}

function createBackup(file) {
  fs.mkdirSync(BACKUP_DIR, { recursive: true });
  const target = path.join(BACKUP_DIR, `${path.basename(file)}.${stamp()}.bak`);
  fs.copyFileSync(file, target);
  return target;
}

function listBackups() {
  return fs.readdirSync(BACKUP_DIR).filter((name) => name.endsWith('.bak'));
}

function install(file, contents) {
  if (fs.existsSync(file)) {
    createBackup(file);
  }
  fs.writeFileSync(file, contents);
}

module.exports = { createBackup, listBackups, install };
"""
QUESTION = "¿cómo gestiona los backups y su retención?"

# Answers that say what the code does: none may warn.
GOOD = [
    (QUESTION, "No hay retención: el módulo nunca borra backups; `createBackup()` (línea 10) copia el fichero con un timestamp.", BACKUP_JS),
    (QUESTION, "Crea los backups en `createBackup()` (línea 10) con la fecha en el nombre. No implementa ninguna política de retención.", BACKUP_JS),
    (QUESTION, "Los backups se guardan en `BACKUP_DIR` con la fecha en el nombre.", BACKUP_JS),
    (QUESTION, "There is no retention logic: backups are never deleted.", BACKUP_JS),
    (QUESTION, "La retención no existe en este código.", BACKUP_JS),
    (QUESTION, "Sin retención: los ficheros .bak se acumulan en la carpeta.", BACKUP_JS),
    (QUESTION, "Antes de escribir, `install` llama a `createBackup` si el fichero existe (línea 22).\n\nNada se ocupa de la retención: ningún código borra los .bak.", BACKUP_JS),
    ("How does it handle backup retention?", "It does not prune anything; retention is unbounded because no code deletes old backups.", BACKUP_JS),
]  # fmt: skip
# Answers that assert the premise with nothing in the code behind it: all must warn.
BAD = [
    (QUESTION, "El módulo aplica una retención implícita: los backups se acumulan con su timestamp y los antiguos quedan como histórico.", BACKUP_JS),
    (QUESTION, "La retención de los backups es implícita, basada en el timestamp del nombre.", BACKUP_JS),
    (QUESTION, "Gestiona la retención conservando solo los backups más recientes.", BACKUP_JS),
    ("How does it handle backup retention?", "Retention is implicit: old backups are rotated by their timestamp.", BACKUP_JS),
]  # fmt: skip
# Correct answers to other questions about English code: a question word the file does not hold
# («teclado», «puerto», «entrada») is anchored by a cited line or an identifier.
TS = """export class Form {
  validateInput(value: string): boolean {
    return value.trim().length > 0;
  }

  onKeyDown(event: KeyboardEvent) {
    if (event.key === 'Enter') {
      this.submit();
    }
  }
}
"""
OTHER_GOOD = [
    ("¿cómo valida la entrada del usuario?", "Valida la entrada con `validateInput()` (línea 2), que rechaza cadenas vacías.", TS),
    ("¿cómo valida la entrada del usuario?", "La entrada se valida en validateInput: recorta espacios y exige longitud mayor que cero.", TS),
    ("¿cómo maneja el teclado?", "El teclado se maneja en onKeyDown (línea 6): con Enter envía el formulario.", TS),
    ("¿qué tecla envía el formulario?", "La tecla Enter, en la línea 7, llama a submit().", TS),
    ("¿qué pasa si el usuario pulsa Escape?", "Nada: onKeyDown solo reacciona a Enter; Escape no tiene efecto.", TS),
    # Right and without any anchor: they warned (5 of 6) before only nominalizations counted.
    ("¿cómo valida la entrada del usuario?", "Recorta los espacios de la entrada y exige que quede algo.", TS),
    ("¿cómo valida la entrada del usuario?", "Comprueba que la entrada tenga longitud mayor que cero.", TS),
    ("¿qué hace al pulsar Enter?", "Al pulsar Enter envía el formulario.", TS),
    ("¿dónde guarda las copias?", "Guarda las copias en la carpeta backups junto al módulo.", BACKUP_JS),
    ("¿cómo nombra las copias?", "Cada copia lleva el nombre del fichero, la fecha ISO y la extensión .bak.", BACKUP_JS),
    ("¿qué pasa si el fichero no existe al instalar?", "Si no existe, escribe el contenido directamente sin copia.", BACKUP_JS),
    # A nominalization the code holds as a cognate: «validación» shares `valid` with validateInput.
    ("¿cómo hace la validación?", "La validación recorta espacios y exige longitud mayor que cero.", TS),
]  # fmt: skip


def test_the_issue_case_warns_and_the_correct_answer_does_not():
    """The data that distinguishes: same file and question, the invented answer and the true one.

    Mutant «no negation check» (`_NEGATION` never matches): the correct answer warns too.
    Mutant «no premise check» (`unsupported_premises` returns []): the invented one stops warning.
    """
    assert line_check.unsupported_premises(BAD[0][1], QUESTION, BACKUP_JS) == ["retención"]
    assert line_check.unsupported_premises(GOOD[0][1], QUESTION, BACKUP_JS) == []


@pytest.mark.parametrize(("question", "answer_text", "content"), GOOD + OTHER_GOOD)
def test_correct_answers_do_not_warn(question, answer_text, content):
    assert line_check.unsupported_premises(answer_text, question, content) == []


@pytest.mark.parametrize(("question", "answer_text", "content"), BAD)
def test_asserted_premises_warn(question, answer_text, content):
    assert line_check.unsupported_premises(answer_text, question, content)


def test_the_premise_terms_skip_words_of_asking_and_words_in_the_file():
    """Only nominalizations count: «gestiona» and «backups» are not; «retención» is, and the file
    does not hold it. Mutant «every word counts» (no `_NOMINALIZATION` filter): «entrada» and
    «usuario» come back for the second question."""
    assert line_check.premise_terms(QUESTION, BACKUP_JS) == ["retención"]
    assert line_check.premise_terms("¿cómo valida la entrada del usuario?", TS) == []
    assert line_check.premise_terms("¿Hay rotaciones o caducidades?", BACKUP_JS) == [
        "rotaciones",
        "caducidades",
    ]
    assert line_check.premise_terms("¿Qué opciones y qué función tiene?", BACKUP_JS) == []
    # A file that talks about retention (a comment, a name) holds the word: nothing to check.
    assert line_check.premise_terms(QUESTION, BACKUP_JS + "// retention: keep all\n") == []


LOGS_PY = """import logging
from logging.handlers import TimedRotatingFileHandler


class Service:
    def __init__(self):
        self.handler = TimedRotatingFileHandler("app.log", when="midnight")
        self.ready = True

    def run(self, start, end):
        duration = end - start
        return create_report(duration)
"""
# Cognates whose Spanish `ci` is an English `ti`: the file holds them, the answer is right.
COGNATES = [
    ("¿cómo hace la rotación de los logs?", "La rotación de los logs ocurre cada medianoche."),
    ("¿qué hace la inicialización?", "La inicialización deja el servicio listo."),
    ("¿cómo calcula la duración?", "La duración se calcula restando el inicio al final."),
    ("¿qué pasa tras la creación del informe?", "La creación del informe recibe la duración."),
]  # fmt: skip


@pytest.mark.parametrize(("question", "answer_text"), COGNATES)
def test_cognates_with_a_soft_c_are_held_by_the_file(question, answer_text):
    """rotación/TimedRotatingFileHandler, inicialización/__init__, duración/duration,
    creación/create_report. Mutant «no `ci`→`ti` variant» (`_held` only compares the stem as
    written): the four warn."""
    assert line_check.premise_terms(question, LOGS_PY) == []
    assert line_check.unsupported_premises(answer_text, question, LOGS_PY) == []


def test_the_cognate_variant_does_not_hide_a_real_premise():
    """Control: the variant is not a blanket pass; «retención» is still absent from LOGS_PY."""
    question = "¿cómo gestiona la retención de los logs?"
    answer_text = "La retención de los logs es implícita."
    assert line_check.unsupported_premises(answer_text, question, LOGS_PY) == ["retención"]


def test_a_truncated_answer_does_not_judge_its_last_line():
    """The answer was cut by `max_tokens`: «línea 2» may be the start of «línea 22». As in
    `check`, the last line is not judged. Mutant «`_verified_lines` does not pass `truncated`»:
    the second assert falls."""
    question = "¿Dónde hace `install` la comprobación?"
    cut = "`install` escribe el fichero.\nLa comprobación está en la línea 2"
    assert line_check.unsupported_premises(cut, question, BACKUP_JS) == ["comprobación"]
    assert line_check.unsupported_premises(cut, question, BACKUP_JS, truncated=True) == []
    result = server._verified_lines(cut, question, BACKUP_JS, truncated=True)
    assert server.WARNING_MARKER not in result


def test_an_anchored_assertion_is_not_flagged():
    """Known limit, by design: a sentence that names a real identifier counts as anchored.
    Mutant «nothing anchors» (`_anchored` always False): this assert falls."""
    answer = "`createBackup()` aplica una retención implícita por timestamp."
    assert line_check.unsupported_premises(answer, QUESTION, BACKUP_JS) == []


def test_a_verified_cited_line_anchors_and_a_wrong_one_does_not():
    """«La comprobación» (absent from the file) stands on line 22 when that line is where
    `install` checks; cited on line 4 it stands on nothing."""
    question = "¿Dónde hace `install` la comprobación?"
    assert line_check.premise_terms(question, BACKUP_JS) == ["comprobación"]
    right = "La comprobación está en la línea 22."
    wrong = "La comprobación está en la línea 4."
    assert line_check.unsupported_premises(right, question, BACKUP_JS) == []
    assert line_check.unsupported_premises(wrong, question, BACKUP_JS) == ["comprobación"]


def test_fenced_code_is_not_prose():
    answer = "Copia el fichero (línea 13).\n\n```js\n// retención implícita\n```"
    assert line_check.unsupported_premises(answer, QUESTION, BACKUP_JS) == []


# --- through the tool ---------------------------------------------------------------------------


@pytest.fixture
def answer(monkeypatch, tmp_path) -> dict:
    """The fake backend answers `state["text"]` to every call."""
    state = {"text": BAD[0][1]}

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
    source = tmp_path / "backups.js"
    source.write_text(BACKUP_JS, encoding="utf-8")
    return source


def _warning(terms: str) -> str:
    return f"{server.WARNING_MARKER}{i18n.t('mcp.explain.premise_unsupported', terms=terms)}]"


def test_the_tool_warns_on_the_issue_case(answer, module):
    """Mutant «`_verified_lines` without the premise branch»: this assert falls."""
    result = server.local_explain_code(path=str(module), question=QUESTION)
    assert result.startswith(BAD[0][1])  # the prose is not rewritten
    assert _warning("«retención»") in result


def test_the_tool_does_not_warn_on_the_correct_answer(answer, module):
    answer["text"] = GOOD[0][1]
    result = server.local_explain_code(path=str(module), question=QUESTION)
    assert "premisa" not in result
    assert server.WARNING_MARKER not in result


def test_without_path_nothing_is_added(answer, module):
    """Inline code has no file to check against: byte for byte, as before."""
    code = module.read_text(encoding="utf-8")
    assert server.local_explain_code(code=code, question=QUESTION) == BAD[0][1]


def test_the_warning_comes_in_english_too(answer, module, monkeypatch):
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    i18n.reset()
    result = server.local_explain_code(path=str(module), question=QUESTION)
    assert _warning("«retención»") in result
    assert "premise" in result
