"""#531: the `N| ` prefix the model copies from its numbered input does not reach the answer.

With `path`, `local_explain_code` shows the model every line as `N| line`. One answer came back
as `98| Sí, la función `summarizable` consulta…`: the prefix is the input's format, not part of
the answer, so it is dropped from lines of prose. Fenced code blocks and echoed lines of the file
(`233| this.focus();`) keep it: there it is a citation, and the line check verifies it. Fake
backend (`_run_chat` doubled), no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from local_delegate import config, i18n, line_check, server

#: Line 98 of the file holds the first `summarizable`, as in the issue.
SUMMARIZABLE_LINE = 98
QUESTION = "¿Consulta summarizable() alguna lista de rutas protegidas?"
ISSUE_BODY = (
    "Sí, la función `summarizable` consulta la lista `PROTECTED` antes de redirigir "
    "a local_summarize."
)


def _source(total: int = 200) -> str:
    rows = []
    for n in range(1, total + 1):
        if n == SUMMARIZABLE_LINE:
            rows.append("def summarizable(path):")
        elif n == SUMMARIZABLE_LINE + 1:
            rows.append("    return path not in PROTECTED")
        else:
            rows.append(f"value_{n} = {n}  # paso {n}")
    return "\n".join(rows) + "\n"


@pytest.fixture
def answer(monkeypatch, tmp_path) -> dict:
    """The fake backend answers `state["text"]` to every call."""
    state = {"text": "", "calls": 0}

    def run_chat(model, system, user, max_tokens, temperature, **_):
        state["calls"] += 1
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
def source(tmp_path: Path) -> Path:
    path = tmp_path / "read_classifier.py"
    path.write_text(_source(), encoding="utf-8")
    return path


def test_the_issue_answer_loses_its_prefix(answer, source):
    """The exact shape of #531. Mutant «no strip»: the `startswith` assert falls."""
    answer["text"] = f"{SUMMARIZABLE_LINE}| {ISSUE_BODY}"
    result = server.local_explain_code(path=str(source), question=QUESTION)
    assert result.startswith(ISSUE_BODY)
    assert f"{SUMMARIZABLE_LINE}|" not in result
    # The check still runs after the strip: the question's identifier gets its exact line.
    line = i18n.t("mcp.explain.occurrences", name="summarizable", lines=str(SUMMARIZABLE_LINE))
    assert result.rstrip().endswith(line)


def test_every_prose_line_loses_its_prefix_and_keeps_its_indent(answer, source):
    answer["text"] = f"98| {ISSUE_BODY}\n\n  12| - Primer punto.\n150| Segundo punto."
    result = server.local_explain_code(path=str(source))
    assert result == f"{ISSUE_BODY}\n\n  - Primer punto.\nSegundo punto."


def test_a_fenced_block_keeps_its_prefixes(answer, source):
    """Inside ``` the prefix is a quoted line of code: untouched, even if it is not the file's."""
    fenced = "```python\n98| def summarizable(path):\n99|     return path not in PROTECTED\n```"
    answer["text"] = f"98| {ISSUE_BODY}\n\n{fenced}\n\n5| Fin."
    result = server.local_explain_code(path=str(source))
    assert result == f"{ISSUE_BODY}\n\n{fenced}\n\nFin."


def test_a_copied_line_of_the_file_keeps_its_prefix(answer, source):
    """`98| def summarizable(path):` outside a fence is the file's line 98: a citation, kept."""
    answer["text"] = f"La definición:\n98| def summarizable(path):\n{ISSUE_BODY}"
    result = server.local_explain_code(path=str(source))
    assert result == answer["text"]


def test_a_normal_answer_comes_back_byte_for_byte(answer, source):
    answer["text"] = f"{ISSUE_BODY}\n\n- `summarizable` (línea 98) | ver tabla 3| no aplica."
    result = server.local_explain_code(path=str(source))
    assert result == answer["text"]


def test_without_path_nothing_is_stripped(answer, source):
    """With `code=` the model never saw a prefix: the text is the model's, byte for byte."""
    answer["text"] = f"98| {ISSUE_BODY}"
    result = server.local_explain_code(code=source.read_text(encoding="utf-8"))
    assert result == answer["text"]


@pytest.mark.parametrize("question", [QUESTION, None])
def test_a_chunked_answer_loses_its_prefix_too(answer, tmp_path, question):
    """The chunked path (3 pieces, 4 passes in the issue), with and without a question."""
    code = _source(total=6_000)
    assert len(code) > config.max_chars_for_role("code")
    path = tmp_path / "big.py"
    path.write_text(code, encoding="utf-8")
    answer["text"] = f"{SUMMARIZABLE_LINE}| {ISSUE_BODY}"
    result = server.local_explain_code(path=str(path), question=question)
    assert answer["calls"] > 2  # guard: it chunked
    assert result.startswith(ISSUE_BODY)


# --- Pure helper --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("98| Sí.", "Sí."),
        ("98|Sí.", "Sí."),
        ("Sí.\n7| No.", "Sí.\nNo."),
        ("~~~\n7| No.\n~~~\n7| No.", "~~~\n7| No.\n~~~\nNo."),
        ("Sin prefijo | con barra.", "Sin prefijo | con barra."),
        ("", ""),
    ],
)
def test_strip_line_prefixes(text, expected):
    assert line_check.strip_line_prefixes(text, _source()) == expected
