"""#473: a chunked `local_extract` never returns a null field in silence.

A document larger than the role's window is processed in chunks (map/reduce). When a field stays
null in every chunk, the final null may mean "not seen" rather than "absent": `_local_delegate`
says so, with the number of chunks and the fields, both for `text` and `path`. Backend faked
(`_run_chat` doubled), no network.
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
        call = {"system": system, "user": user}
        calls.append(call)
        return state["answer"](call), 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    return calls, state


def _big_text(final: str = "") -> str:
    return "Línea de relleno sin datos útiles.\n" * 1800 + final


def _notice(pieces: int, fields: list[str]) -> str:
    return i18n.t("mcp.warning.extract_null_in_chunks", pieces=pieces, fields=", ".join(fields))


def test_all_null_in_every_chunk_is_flagged_with_text(backend):
    """The case of the issue: every chunk answers null and nothing said so."""
    calls, state = backend
    state["answer"] = lambda call: _ok('{"a": null, "b": null}')
    data = server.local_extract(fields=["a", "b"], text=_big_text())
    pieces = len(calls)
    assert pieces > 1  # guard: it chunked
    assert data["a"] is None and data["b"] is None
    meta = data["_local_delegate"]
    notice = _notice(pieces, ["a", "b"])
    assert meta["chunked"] == {"pieces": pieces, "null_fields": ["a", "b"], "notice": notice}
    assert meta["warning"] == notice
    assert "truncated" not in meta, "the input is not truncated: `truncated` keeps its meaning"


def test_all_null_in_every_chunk_is_flagged_with_path(backend, tmp_path, monkeypatch):
    """Same with `path`, next to `read_server_side` (the exact shape of the report)."""
    calls, state = backend
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", True)
    state["answer"] = lambda call: _ok('{"a": null}')
    doc = tmp_path / "schema.json"
    doc.write_text(
        json.dumps({"$defs": {f"Rule{i}": {"type": "string"} for i in range(3000)}}, indent=2),
        encoding="utf-8",
    )
    data = server.local_extract(fields=["a"], path=str(doc))
    meta = data["_local_delegate"]
    assert "read_server_side" in meta
    assert meta["chunked"]["pieces"] == len(calls) > 1
    assert meta["chunked"]["null_fields"] == ["a"]
    assert meta["warning"] == _notice(len(calls), ["a"])


def test_only_the_fields_null_everywhere_are_named(backend):
    """A value found in one chunk wins over the nulls of the others; only `b` is named."""
    _calls, state = backend
    state["answer"] = lambda call: _ok(
        '{"a": "ZZZ", "b": null}' if "a = ZZZ" in call["user"] else '{"a": null, "b": null}'
    )
    data = server.local_extract(fields=["a", "b"], text=_big_text("a = ZZZ\n"))
    assert data["a"] == "ZZZ"
    assert data["_local_delegate"]["chunked"]["null_fields"] == ["b"]


def test_a_chunked_extraction_with_every_value_has_no_notice(backend):
    calls, state = backend
    state["answer"] = lambda call: _ok(
        '{"a": "ZZZ"}' if "a = ZZZ" in call["user"] else '{"a": null}'
    )
    data = server.local_extract(fields=["a"], text=_big_text("a = ZZZ\n"))
    assert len(calls) > 1
    assert "_local_delegate" not in data


def test_a_single_call_null_is_not_flagged(backend):
    """One call saw the whole input: its null is a real "absent"."""
    calls, state = backend
    state["answer"] = lambda call: _ok('{"a": null}')
    data = server.local_extract(fields=["a"], text="nothing here")
    assert len(calls) == 1
    assert data == {"a": None}


def test_a_truncation_warning_keeps_its_text_and_the_detail_goes_to_chunked(backend):
    calls, state = backend
    state["answer"] = lambda call: _ok('{"a": null}', "length" if len(calls) <= 3 else "stop")
    data = server.local_extract(fields=["a"], text=_big_text())
    meta = data["_local_delegate"]
    assert meta["truncated"] is True
    assert meta["warning"].startswith(
        i18n.t("mcp.warning.output_truncated_calls", truncated=1, calls=len(calls))
    )
    chunked = meta["chunked"]
    assert chunked["null_fields"] == ["a"]
    assert chunked["notice"] == _notice(chunked["pieces"], ["a"])


# --- The reduce never drops a value a partial had (#473) ---------------------------------------


def _two_values_answer(reduce_text: str):
    """`a` only in the chunk with `a = AAA`, `b` only in the one with `b = BBB`."""

    def answer(call):
        if "Combina" in call["system"]:
            return _ok(reduce_text)
        has_a, has_b = "a = AAA" in call["user"], "b = BBB" in call["user"]
        return _ok(json.dumps({"a": "AAA" if has_a else None, "b": "BBB" if has_b else None}))

    return answer


def _two_values_text() -> str:
    return "b = BBB\n" + _big_text("a = AAA\n")


def test_a_null_left_by_the_reduce_takes_the_partial_value(backend):
    calls, state = backend
    state["answer"] = _two_values_answer('{"a": null, "b": null}')
    data = server.local_extract(fields=["a", "b"], text=_two_values_text())
    assert any("Combina" in c["system"] for c in calls)  # guard: the model reduced
    assert data["a"] == "AAA" and data["b"] == "BBB"
    assert "_local_delegate" not in data


def test_a_non_null_value_of_the_reduce_is_never_overwritten(backend):
    _calls, state = backend
    state["answer"] = _two_values_answer('{"a": "merged", "b": null}')
    data = server.local_extract(fields=["a", "b"], text=_two_values_text())
    assert data["a"] == "merged"
    assert data["b"] == "BBB"


def test_the_first_partial_value_wins_in_chunk_order():
    data = {"a": None}
    server._fill_nulls_from_partials(
        data, ["a"], ['{"a": null}', "not json", '{"a": "first"}', '{"a": "second"}']
    )
    assert data == {"a": "first"}


def test_a_field_null_in_the_reduce_and_every_partial_is_still_listed(backend):
    _calls, state = backend
    state["answer"] = _two_values_answer('{"a": null, "b": null, "c": null}')
    data = server.local_extract(fields=["a", "b", "c"], text=_two_values_text())
    assert data["a"] == "AAA" and data["b"] == "BBB" and data["c"] is None
    assert data["_local_delegate"]["chunked"]["null_fields"] == ["c"]
