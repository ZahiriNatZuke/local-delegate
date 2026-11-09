"""#586: `local_extract` asks the model for null where the input has no data, in every call.

The model filled keys the input has no data for: a verdict with no review in it, a PR body as its
comments, the custom-domain row of a table as the licensed-user limits. Only the map of a chunked
input said "null"; the single call and the reduce did not. Now every call carries the rule, and an
empty list the schema made the model write as the text "[]" comes back as []. Backend faked
(`_run_chat` doubled), no network.
"""

from __future__ import annotations

import json

import pytest

from local_delegate import config, i18n, server

RULE = (
    "Si el contenido no trae el dato de una clave, pon null en vez de inventarlo, y no la "
    "rellenes con el dato de otra clave ni de otra fila de una tabla o lista. Sigue "
    "valiendo resumir, contar, clasificar o deducir lo que el contenido permite (por "
    "ejemplo, false si no menciona algo), y tomar lo que va dentro de una ruta o de un "
    "nombre."
)


def _ok(text: str):
    return server.ChatResult(text=text, ok=True, finish_reason="stop")


@pytest.fixture
def backend(monkeypatch, tmp_path):
    calls: list[dict] = []
    state = {"answer": lambda call: _ok("{}")}

    def run_chat(model, system, user, max_tokens, temperature, **_):
        calls.append({"system": system, "user": user})
        return state["answer"](calls[-1]), 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    i18n.reset()
    yield calls, state
    i18n.reset()


# --- The rule in every call -------------------------------------------------------------------


def test_the_single_call_asks_null_and_no_fill(backend):
    calls, _state = backend
    server.local_extract(fields=["review_verdict"], text="Un PR sin revisiones.")
    assert len(calls) == 1
    assert RULE in calls[0]["system"]
    # After the frozen format order, before anything else.
    assert calls[0]["system"].index("Nada fuera del formato.") < calls[0]["system"].index(RULE)


def test_with_line_numbers_the_rule_is_kept(backend, tmp_path):
    calls, _state = backend
    path = tmp_path / "doc.md"
    path.write_text("# Título\n\nTexto.\n", encoding="utf-8")
    server.local_extract(fields=["intro_heading_line"], path=str(path))
    assert RULE in calls[0]["system"]
    assert "Cada línea del contenido" in calls[0]["system"]


def test_every_map_piece_and_the_reduce_carry_the_rule(backend, monkeypatch):
    calls, state = backend
    monkeypatch.setattr(config, "max_chars_for_role", lambda role: 2_000)
    # Two pieces that disagree, so the reduce is the model's and not the program's shortcut.
    answers = iter(['{"a": "uno"}', '{"a": "dos"}'])
    state["answer"] = lambda call: _ok(next(answers, '{"a": "uno"}'))
    text = "\n".join(f"Línea {i} del documento con algo de texto." for i in range(200))
    server.local_extract(fields=["a"], text=text)
    assert len(calls) >= 3
    assert all(RULE in call["system"] for call in calls)


# --- "[]" written as text is an empty list ----------------------------------------------------


@pytest.mark.parametrize("text", ["[]", " [] ", "\n[]\n"])
def test_an_empty_list_as_text_is_an_empty_list(backend, text):
    _calls, state = backend
    state["answer"] = lambda call: _ok(json.dumps({"comments_authors_and_gist": text}))
    data = server.local_extract(fields=["comments_authors_and_gist"], text='{"comments": []}')
    meta = data.pop("_local_delegate", {})
    assert data == {"comments_authors_and_gist": []}
    assert meta.get("decoded_keys") == {"comments_authors_and_gist": text}
    assert "warning" not in meta


# `[ ]` is an unchecked Markdown task box (`- [ ] migrar`): a value, not an empty list.
@pytest.mark.parametrize("value", ["[1]", "[] y más", "{}", "none", "", "x", "[ ]", "[\n]"])
def test_other_texts_are_not_decoded(backend, value):
    _calls, state = backend
    state["answer"] = lambda call: _ok(json.dumps({"k": value}))
    data = server.local_extract(fields=["k"], text="texto")
    assert data.get("k") != []
    assert "decoded_keys" not in data.get("_local_delegate", {})


def test_an_empty_list_with_a_copied_line_prefix_is_an_empty_list(backend, tmp_path):
    """With numbered input (#568) the model may copy the `N| ` of a line before the value."""
    _calls, state = backend
    path = tmp_path / "doc.md"
    path.write_text("# Título\n\nSin comentarios.\n", encoding="utf-8")
    state["answer"] = lambda call: _ok(json.dumps({"intro_heading_line": 1, "comments": "3| []"}))
    data = server.local_extract(fields=["intro_heading_line", "comments"], path=str(path))
    assert data["comments"] == []
    assert data["_local_delegate"]["decoded_keys"] == {"comments": "3| []"}


def test_an_unchecked_task_box_is_kept(backend):
    """The review's case: `estado_tarea` over `- [ ] migrar` is the box itself, not a list."""
    _calls, state = backend
    state["answer"] = lambda call: _ok(json.dumps({"estado_tarea": "[ ]"}))
    data = server.local_extract(fields=["estado_tarea"], text="- [ ] migrar\n")
    assert data == {"estado_tarea": "[ ]"}
