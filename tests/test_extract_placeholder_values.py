"""#586: `local_extract` turns "no data" markers into null and counts a JSON input's lists.

The model answered `"N/A"` for fields the text does not hold (not null, so not in `missing_keys`
and no warning), and counted the 2 reviews as the comments of `"comments": []`. Backend faked
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


#: The shape of the issue's input: `gh pr view --json body,comments,reviews`.
_PR_JSON = json.dumps(
    {
        "body": "## Qué cambia\n\n- Arreglo.\n- **Tras la revisión**: se ajustó el test.\n",
        "comments": [],
        "reviews": [
            {"author": {"login": "bot"}, "body": ""},
            {"author": {"login": "bot"}, "body": ""},
        ],
    }
)


# --- REQ-001 / REQ-003: what is a marker ------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "N/A",
        "n/a",
        " N/A. ",
        "n.a.",
        "NULL",
        "unknown",
        "Unknown.",
        "desconocido",
        "No disponible",
        "no consta",
        "not specified",
        "-",
        "—",
        "?",
        "…",
        "",
        "   ",
        "Sin información",
    ],
)
def test_markers(value):
    assert server._is_no_data_marker(value)


@pytest.mark.parametrize(
    "value",
    [
        "none",
        "None",
        "ninguno",
        "NA",
        "0",
        "false",
        "N/A en Windows",
        "unknown host",
        "a",
        0,
        False,
        None,
        ["N/A"],
        {"x": "N/A"},
        1.5,
        ".",
        " . ",
        "--",
        "...",
    ],
)
def test_legitimate_values_are_not_markers(value):
    assert not server._is_no_data_marker(value)


# --- REQ-001 / REQ-002: end to end ------------------------------------------------------------


def test_markers_become_null_and_missing(backend):
    """The issue's first case: three "N/A" that passed for values, with no warning."""
    _calls, state = backend
    state["answer"] = lambda call: _ok(
        '{"review_verdict": "N/A", "closes_issue": "#586", "review_location": "unknown",'
        ' "adjustments": ""}'
    )
    fields = ["review_verdict", "closes_issue", "review_location", "adjustments"]
    data = server.local_extract(fields=fields, text="texto")
    meta = data.pop("_local_delegate")
    assert data == {
        "review_verdict": None,
        "closes_issue": "#586",
        "review_location": None,
        "adjustments": None,
    }
    assert meta["missing_keys"] == ["review_verdict", "review_location", "adjustments"]
    assert meta["placeholder_keys"] == {
        "review_verdict": "N/A",
        "review_location": "unknown",
        "adjustments": "",
    }
    assert meta["warning"] == i18n.t(
        "mcp.warning.extract_placeholder_keys",
        fields="review_verdict, review_location, adjustments",
    )


def test_omitted_and_marker_keys_in_request_order(backend, monkeypatch):
    """`missing_keys` has both kinds; the "left out" warning names only the omitted one."""
    _calls, state = backend
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    state["answer"] = lambda call: _ok('{"b": "N/A", "c": "x"}')
    data = server.local_extract(fields=["a", "b", "c"], text="texto")
    meta = data.pop("_local_delegate")
    assert data == {"a": None, "b": None, "c": "x"}
    assert meta["missing_keys"] == ["a", "b"]
    assert meta["warning"] == (
        i18n.t("mcp.warning.extract_missing_keys", fields="a")
        + "; "
        + i18n.t("mcp.warning.extract_placeholder_keys", fields="b")
    )


def test_marker_on_a_renamed_key(backend, monkeypatch):
    """A key spelled another way is mapped first, then its marker is null."""
    _calls, state = backend
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    state["answer"] = lambda call: _ok('{"Review_Verdict": "N/A"}')
    data = server.local_extract(fields=["review_verdict"], text="texto")
    meta = data.pop("_local_delegate")
    assert data == {"review_verdict": None}
    assert meta["renamed_keys"] == {"Review_Verdict": "review_verdict"}
    assert meta["placeholder_keys"] == {"review_verdict": "N/A"}
    assert meta["missing_keys"] == ["review_verdict"]


def test_legitimate_values_pass_untouched(backend):
    _calls, state = backend
    answer = {
        "breaking": "none",
        "code": "NA",
        "n": 0,
        "ok": False,
        "list": ["N/A"],
        "t": "N/A en Mac",
    }
    state["answer"] = lambda call: _ok(json.dumps(answer))
    data = server.local_extract(fields=list(answer), text="texto")
    assert "_local_delegate" not in data
    assert data == answer


# --- REQ-004: chunked fill skips markers ------------------------------------------------------


def test_fill_from_partials_skips_a_marker():
    data = {"a": None, "b": "N/A"}
    partials = ['{"a": "N/A", "b": "-"}', '{"a": "real", "b": "otro"}']
    server._fill_nulls_from_partials(data, ["a", "b"], partials)
    assert data == {"a": "real", "b": "otro"}


def test_fill_from_partials_keeps_a_real_value():
    data = {"a": "del reduce"}
    server._fill_nulls_from_partials(data, ["a"], ['{"a": "de un trozo"}'])
    assert data == {"a": "del reduce"}


# --- REQ-006: counts of a top-level list ------------------------------------------------------


def test_the_issue_comment_case(backend):
    """`number_of_comments: 2` over `"comments": []` (copied from `reviews`) is 0."""
    _calls, state = backend
    state["answer"] = lambda call: _ok(
        '{"review_verdict": "N/A", "number_of_comments": 2, "number_of_reviews": 2}'
    )
    fields = ["review_verdict", "number_of_comments", "number_of_reviews"]
    data = server.local_extract(fields=fields, text=_PR_JSON)
    meta = data.pop("_local_delegate")
    assert data == {"review_verdict": None, "number_of_comments": 0, "number_of_reviews": 2}
    assert meta["recounted_keys"] == {
        "number_of_comments": {"model": 2, "count": 0, "source": "comments"}
    }
    assert meta["missing_keys"] == ["review_verdict"]
    assert meta["warning"] == (
        i18n.t("mcp.warning.extract_placeholder_keys", fields="review_verdict")
        + "; "
        + i18n.t("mcp.warning.extract_recounted_keys", pairs="number_of_comments = 0 (comments)")
    )


@pytest.mark.parametrize(
    "name", ["commentCount", "comments_count", "num_comments", "count_comments"]
)
def test_count_key_spellings(backend, name):
    _calls, state = backend
    state["answer"] = lambda call: _ok(json.dumps({name: "N/A"}))
    data = server.local_extract(fields=[name], text=_PR_JSON)
    meta = data.pop("_local_delegate")
    assert data == {name: 0}
    assert meta["recounted_keys"] == {name: {"model": "N/A", "count": 0, "source": "comments"}}
    # Recounted, so neither missing nor a marker any more.
    assert "missing_keys" not in meta
    assert "placeholder_keys" not in meta


def test_an_omitted_count_is_filled_and_not_missing(backend, monkeypatch):
    _calls, state = backend
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    state["answer"] = lambda call: _ok("{}")
    data = server.local_extract(fields=["number_of_reviews"], text=_PR_JSON)
    meta = data.pop("_local_delegate")
    assert data == {"number_of_reviews": 2}
    assert "missing_keys" not in meta
    assert meta["recounted_keys"]["number_of_reviews"] == {
        "model": None,
        "count": 2,
        "source": "reviews",
    }


@pytest.mark.parametrize(
    ("text", "fields", "answer"),
    [
        # Not JSON: no count.
        ("comments: ninguno", ["number_of_comments"], {"number_of_comments": 2}),
        # A JSON list, not an object.
        ("[1, 2]", ["number_of_comments"], {"number_of_comments": 2}),
        # The key is not a list.
        ('{"comments": 5}', ["number_of_comments"], {"number_of_comments": 2}),
        # Nested list: only the top level counts.
        ('{"data": {"comments": []}}', ["number_of_comments"], {"number_of_comments": 2}),
        # Two top-level keys match (`comment` and `comments`): ambiguous.
        ('{"comment": [], "comments": [1]}', ["comment_count"], {"comment_count": 7}),
        # Not a count key.
        ('{"comments": []}', ["comments_summary"], {"comments_summary": "algo"}),
        # The model's count is right, as an int or a numeric string.
        ('{"comments": [1, 2]}', ["number_of_comments"], {"number_of_comments": 2}),
        ('{"comments": [1, 2]}', ["number_of_comments"], {"number_of_comments": "2"}),
        ('{"comments": [1, 2]}', ["number_of_comments"], {"number_of_comments": 2.0}),
        # The JSON already holds the count (a page of a longer list): the document's figure wins.
        ('{"comments": [1, 2], "comment_count": 57}', ["comment_count"], {"comment_count": 57}),
        (
            '{"items": [1], "total_count": 125, "count_items": 125}',
            ["count_items"],
            {"count_items": 125},
        ),
        # (a) A legitimate total under another name, at the top level or in a top-level object.
        (
            '{"comments": [1, 2], "total_comments": 57}',
            ["comment_count"],
            {"comment_count": 57},
        ),
        (
            '{"comments": [1, 2], "commentCount": 57}',
            ["number_of_comments"],
            {"number_of_comments": 57},
        ),
        (
            '{"comments": [1, 2], "comments_total": 57}',
            ["num_comments"],
            {"num_comments": 57},
        ),
        ('{"files": ["a"], "meta": {"file_count": 9}}', ["file_count"], {"file_count": 9}),
        (
            '{"total_count": 125, "items": [' + ", ".join(["1"] * 30) + "]}",
            ["item_count"],
            {"item_count": 125},
        ),
        # (b) A figure smaller than the list's length is the model's, not corrected.
        ('{"comments": [1, 2, 3]}', ["number_of_comments"], {"number_of_comments": 2}),
        # An integer longer than Python's 4300-digit limit: no count, and no exception.
        (
            '{"comments": [], "n": ' + "9" * 5000 + "}",
            ["number_of_comments"],
            {"number_of_comments": 3},
        ),
    ],
)
def test_no_recount(backend, text, fields, answer):
    _calls, state = backend
    state["answer"] = lambda call: _ok(json.dumps(answer))
    data = server.local_extract(fields=fields, text=text)
    assert "_local_delegate" not in data
    assert data == answer


def test_a_json_with_bom_is_recounted(backend):
    _calls, state = backend
    state["answer"] = lambda call: _ok('{"number_of_comments": 2}')
    bom = chr(0xFEFF)
    data = server.local_extract(fields=["number_of_comments"], text=bom + _PR_JSON)
    meta = data.pop("_local_delegate")
    assert meta["recounted_keys"]["number_of_comments"]["count"] == 0
    assert data == {"number_of_comments": 0}


# --- Warnings and chunks, end to end ----------------------------------------------------------


def test_an_earlier_warning_keeps_its_text_and_the_marker_one_follows(backend):
    """#455: the truncation warning keeps its exact text; the marker notice goes after `; `."""
    _calls, state = backend
    state["answer"] = lambda call: _ok('{"a": "N/A"}', finish="length")
    data = server.local_extract(fields=["a"], text="texto")
    meta = data.pop("_local_delegate")
    assert meta["truncated"] is True  # guard: the cut call really happened
    assert meta["warning"] == (
        server._truncated_calls_notice(1, 1)
        + "; "
        + i18n.t("mcp.warning.extract_placeholder_keys", fields="a")
    )


def test_chunked_reduce_marker_is_replaced_by_a_chunk_value(backend):
    """#473 + #586: the reduce says "N/A", one chunk found the value: the value wins."""
    calls, state = backend

    def answer(call):
        if "Combina los objetos parciales" in call["system"]:
            return _ok('{"a": "N/A"}')
        return _ok('{"a": "ZZZ"}' if "a = ZZZ" in call["user"] else '{"a": "N/A"}')

    state["answer"] = answer
    text = "Línea de relleno sin datos útiles.\n" * 1800 + "a = ZZZ\n"
    data = server.local_extract(fields=["a"], text=text)
    # Guard: chunked, and the reduce was really asked.
    assert any("Combina los objetos parciales" in c["system"] for c in calls)
    meta = data.pop("_local_delegate", {})
    assert "placeholder_keys" not in meta
    assert data == {"a": "ZZZ"}


def test_a_numbered_marker_is_null(backend, tmp_path):
    """#568 numbering: the model copied the line prefix too (`"3| N/A"`); still a marker."""
    calls, state = backend
    source = tmp_path / "notes.txt"
    source.write_text("uno\ndos\ntres\n", encoding="utf-8")
    state["answer"] = lambda call: _ok('{"owner": "3| N/A", "start_line": 2}')
    data = server.local_extract(fields=["owner", "start_line"], path=str(source))
    assert "3| tres" in calls[0]["user"]  # guard: the input really was numbered
    meta = data.pop("_local_delegate")
    assert data == {"owner": None, "start_line": 2}
    assert meta["placeholder_keys"] == {"owner": "3| N/A"}
    assert meta["missing_keys"] == ["owner"]
