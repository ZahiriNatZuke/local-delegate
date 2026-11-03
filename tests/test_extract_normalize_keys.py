"""`local_extract` returns exactly the requested keys, whatever the model answered.

In free mode (`LOCAL_DELEGATE_JSON_SCHEMA=off`, or `auto` after the backend refused the schema)
nothing forces the model to the requested keys. A key it left out comes back as null and is
named in `_local_delegate.missing_keys`; a key it added is dropped and named in `dropped_keys`,
with a readable `warning`. Backend faked (`_run_chat` doubled), no network.
"""

from __future__ import annotations

import json

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
    assert meta["dropped"] == {"made_up": 1}  # dropped from the data, not lost
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
        "dropped": {"zz": 3},
        "warning": i18n.t("mcp.warning.extract_dropped_keys", fields="zz"),
    }


# --- A key spelled another way is mapped, not lost --------------------------------------------


@pytest.mark.parametrize(
    ("requested", "answered"),
    [
        ("Name", "name"),
        ("endDate", "end_date"),
        ("start_date", "Start-Date"),
        ("start date", "startDate"),
    ],
)
def test_a_key_written_another_way_keeps_its_value(backend, monkeypatch, requested, answered):
    _calls, state = backend
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    state["answer"] = lambda call: _ok(json.dumps({answered: "x"}))
    data = server.local_extract(fields=[requested], text="x")
    meta = data.pop("_local_delegate")
    assert data == {requested: "x"}
    assert meta == {
        "renamed_keys": {answered: requested},
        "warning": i18n.t("mcp.warning.extract_renamed_keys", pairs=f"{answered} -> {requested}"),
    }


def test_an_ambiguous_shape_is_not_mapped_and_its_values_are_kept(backend, monkeypatch):
    """Two answered keys with the shape of one requested key: no guess; both kept in `dropped`."""
    _calls, state = backend
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    state["answer"] = lambda call: _ok('{"name": "x", "NAME": "y"}')
    data = server.local_extract(fields=["Name"], text="x")
    meta = data.pop("_local_delegate")
    assert data == {"Name": None}
    assert "renamed_keys" not in meta
    assert meta["missing_keys"] == ["Name"]
    assert meta["dropped"] == {"name": "x", "NAME": "y"}


def test_a_shape_shared_by_two_requested_keys_is_not_mapped(backend, monkeypatch):
    _calls, state = backend
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    state["answer"] = lambda call: _ok('{"Start-Date": "x"}')
    data = server.local_extract(fields=["start_date", "startDate"], text="x")
    meta = data.pop("_local_delegate")
    assert data == {"start_date": None, "startDate": None}
    assert meta["dropped"] == {"Start-Date": "x"}


def test_a_present_requested_key_is_never_overwritten_by_a_lookalike(backend, monkeypatch):
    _calls, state = backend
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    state["answer"] = lambda call: _ok('{"Name": "right", "name": "other"}')
    data = server.local_extract(fields=["Name"], text="x")
    meta = data.pop("_local_delegate")
    assert data == {"Name": "right"}
    assert meta["dropped"] == {"name": "other"}


# --- Arguments and the reserved name -----------------------------------------------------------


@pytest.mark.parametrize("fields", [[], [""], ["  ", "\t"]])
def test_no_field_to_extract_is_rejected_before_the_backend(backend, fields):
    calls, _state = backend
    with pytest.raises(ValueError, match="fields"):
        server.local_extract(fields=fields, text="x")
    assert calls == []


def test_a_requested_reserved_name_is_not_filled_with_null(backend, monkeypatch):
    """As before this change: no `"_local_delegate": null` appears out of nowhere."""
    _calls, state = backend
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    state["answer"] = lambda call: _ok('{"a": 1}')
    data = server.local_extract(fields=["a", "_local_delegate"], text="a=1")
    assert data == {"a": 1}


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
