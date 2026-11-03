"""`local_extract` returns exactly the requested keys, whatever the model answered.

In free mode (`LOCAL_DELEGATE_JSON_SCHEMA=off`, or `auto` after the backend refused the schema)
nothing forces the model to the requested keys. A key it left out comes back as null and is
named in `_local_delegate.missing_keys`; a key it added is dropped and named in `dropped_keys`,
with a readable `warning`. Backend faked (`_run_chat` doubled), no network.
"""

from __future__ import annotations

import pytest

from local_delegate import config, i18n, server


def _ok(text: str, finish: str = "stop"):
    return server.ChatResult(text=text, ok=True, finish_reason=finish)


@pytest.fixture
def backend(monkeypatch):
    calls: list[dict] = []
    state = {"answer": lambda call: _ok("{}")}

    def run_chat(model, system, user, max_tokens, temperature, **kwargs):
        call = {"system": system, "user": user, "response_format": kwargs.get("response_format")}
        calls.append(call)
        return state["answer"](call), 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    return calls, state


def _big_text(final: str = "") -> str:
    return "Línea de relleno sin datos útiles.\n" * 1800 + final


def test_free_mode_missing_and_extra_keys_are_normalized(backend, monkeypatch):
    """The case of the security review: `age` missing, `made_up` extra, nothing said."""
    calls, state = backend
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    state["answer"] = lambda call: _ok('{"name": "x", "made_up": 1}')
    data = server.local_extract(fields=["name", "age"], text="name: x")
    assert calls[0]["response_format"] is None  # guard: free mode really
    meta = data.pop("_local_delegate")
    assert data == {"name": "x", "age": None}
    assert meta["missing_keys"] == ["age"]
    assert meta["dropped_keys"] == ["made_up"]
    assert meta["warning"] == (
        i18n.t("mcp.warning.extract_missing_keys", fields="age")
        + "; "
        + i18n.t("mcp.warning.extract_dropped_keys", fields="made_up")
    )


def test_free_mode_only_extra_key(backend, monkeypatch):
    _calls, state = backend
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    state["answer"] = lambda call: _ok('{"a": 1, "b": 2, "zz": 3}')
    data = server.local_extract(fields=["a", "b"], text="a=1 b=2")
    meta = data.pop("_local_delegate")
    assert data == {"a": 1, "b": 2}
    assert meta == {
        "dropped_keys": ["zz"],
        "warning": i18n.t("mcp.warning.extract_dropped_keys", fields="zz"),
    }


def test_a_model_made_up_reserved_key_is_dropped_and_named(backend, monkeypatch):
    """The model cannot smuggle its own `_local_delegate` past the normalization."""
    _calls, state = backend
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    state["answer"] = lambda call: _ok('{"a": 1, "_local_delegate": {"fake": true}}')
    data = server.local_extract(fields=["a"], text="a=1")
    meta = data["_local_delegate"]
    assert "fake" not in meta
    assert meta["dropped_keys"] == ["_local_delegate"]


def test_schema_mode_with_matching_keys_has_no_notice(backend, monkeypatch):
    calls, state = backend
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "auto")
    state["answer"] = lambda call: _ok('{"name": "x", "age": 3}')
    data = server.local_extract(fields=["name", "age"], text="name: x, age: 3")
    assert calls[0]["response_format"] is not None  # guard: the schema was asked for
    assert data == {"name": "x", "age": 3}


def test_duplicated_requested_fields_are_listed_once(backend, monkeypatch):
    _calls, state = backend
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    state["answer"] = lambda call: _ok("{}")
    data = server.local_extract(fields=["a", "a"], text="nothing")
    assert data["a"] is None
    assert data["_local_delegate"]["missing_keys"] == ["a"]


def test_chunked_extra_key_is_dropped_and_chunked_warning_keeps_its_text(backend, monkeypatch):
    calls, state = backend
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    state["answer"] = lambda call: _ok('{"a": null, "extra": "x"}')
    data = server.local_extract(fields=["a"], text=_big_text())
    pieces = len(calls)
    assert pieces > 1  # guard: it chunked
    meta = data.pop("_local_delegate")
    assert data == {"a": None}
    assert meta["dropped_keys"] == ["extra"]
    assert "missing_keys" not in meta
    assert meta["chunked"]["null_fields"] == ["a"]
    # The chunked notice came first and keeps its exact text.
    assert meta["warning"] == meta["chunked"]["notice"]


def test_chunked_key_missing_everywhere_is_null_and_named(backend, monkeypatch):
    calls, state = backend
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    state["answer"] = lambda call: _ok('{"a": "AAA"}' if "a = AAA" in call["user"] else "{}")
    data = server.local_extract(fields=["a", "b"], text=_big_text("a = AAA\n"))
    assert len(calls) > 1
    meta = data.pop("_local_delegate")
    assert data == {"a": "AAA", "b": None}
    assert meta["missing_keys"] == ["b"]
    assert meta["chunked"]["null_fields"] == ["b"]


def test_error_path_is_unchanged(backend, monkeypatch):
    """A non-JSON answer still degrades to `error`/`raw`, with no normalized keys."""
    _calls, state = backend
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    state["answer"] = lambda call: _ok("not json")
    data = server.local_extract(fields=["a"], text="x")
    assert set(data) == {"_local_delegate"}
    assert data["_local_delegate"]["raw"] == "not json"
