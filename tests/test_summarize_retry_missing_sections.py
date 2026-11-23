"""#691: a chunked `local_summarize` retries once the sections the model left out.

Before, `sections.complete` put each missing heading back with «(sin resumir)» under it, and a
heading the model had written another way came out twice. Now the missing (or empty) sections are
asked again in one call of the same operation; what is still missing is named once, in the notice,
and never padded into the body.

The data tells the cases apart: a model that leaves two sections out the first time and summarizes
them the second; one that leaves them out both times; one whose retry fails in the backend; one
that leaves a heading empty; and an obedient one, that must get no retry at all.
"""

from __future__ import annotations

import json

import backend_mock
import httpx2

from local_delegate import config, sections, server

LEFT_OUT = ("Sección 5", "Sección 17")


def _long_doc(sections_: int = 30, chars: int = 2200) -> str:
    return "# Doc\n\nintro\n\n" + "".join(
        f"## Sección {i}\n\n" + ("palabra " * (chars // 8)) + "\n\n" for i in range(sections_)
    )


def _listed(user: str) -> list[str]:
    """The headings of the list a call asks for (the format of `server._section_list`)."""
    if "Secciones, en orden:\n" not in user:
        return []
    block = user.split("Secciones, en orden:\n", 1)[1].split("\n\n", 1)[0]
    return [line[2:].rsplit(" (unas ", 1)[0] for line in block.split("\n") if line.startswith("- ")]


@backend_mock.mock
def _summarize(monkeypatch, tmp_path, respond, **kwargs):
    monkeypatch.setattr(config, "LONG_INPUT_CHARS", 0)
    monkeypatch.setattr(config, "STRUCTURED_SUMMARY", True)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    seen: list[dict] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.content)
        seen.append(payload)
        status, text, end = respond(payload, len(seen))
        if status != 200:
            return httpx2.Response(status, text="boom")
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": text}, "finish_reason": end}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    text = _long_doc()
    assert len(text) > config.max_chars_for_role("long")
    return server.local_summarize(text=text, max_words=600), seen


def _events(tmp_path) -> list[dict]:
    return [
        json.loads(line)
        for file in sorted(tmp_path.glob("*.jsonl"))
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _is_retry(payload) -> bool:
    return tuple(_listed(payload["messages"][1]["content"])) == LEFT_OUT


def _model(*, retry: str, empty: bool = False):
    """Leaves `LEFT_OUT` out of the chunk calls (or empty, with `empty`); `retry` says what then."""

    def _respond(payload, _n):
        listed = _listed(payload["messages"][1]["content"])
        if not listed:
            return 200, "Continuación de la sección.", "stop"
        if _is_retry(payload):
            if retry == "ok":
                return 200, "\n\n".join(f"## {t}\nResumen nuevo de {t}." for t in listed), "stop"
            if retry == "error":
                return 500, "", "stop"
            return 200, "\n\n".join(f"## {t}\n" for t in listed), "stop"  # empty again
        parts = []
        for t in listed:
            if t in LEFT_OUT:
                if empty:
                    parts.append(f"## {t}\n")
                continue
            parts.append(f"## {t}\nResumen de {t}.")
        return 200, "\n\n".join(parts), "stop"

    return _respond


def test_left_out_the_first_time_and_summarized_the_second(monkeypatch, tmp_path):
    output, seen = _summarize(monkeypatch, tmp_path, _model(retry="ok"))
    retries = [p for p in seen if _is_retry(p)]
    assert len(retries) == 1
    # The retry asks only for those sections, with their own text.
    assert "palabra" in retries[0]["messages"][1]["content"]
    for title in LEFT_OUT:
        assert output.count(f"## {title}\n") == 1
        assert f"## {title}\nResumen nuevo de {title}." in output
    order = [output.index(f"## Sección {i}\n") for i in range(30)]
    assert order == sorted(order)
    assert not any(form in output for form in sections.NOT_SUMMARIZED_FORMS)
    assert "sin resumir por el límite" not in output
    (event,) = _events(tmp_path)
    # One operation: the retry is one more call of the same event.
    assert event["chunks"] == len(seen) == len(event["steps"])
    assert [s["kind"] for s in event["steps"]].count("sections_retry") == 1


def test_left_out_twice_is_named_once_in_the_notice(monkeypatch, tmp_path):
    output, seen = _summarize(monkeypatch, tmp_path, _model(retry="again"))
    assert len([p for p in seen if _is_retry(p)]) == 1
    assert not any(form in output for form in sections.NOT_SUMMARIZED_FORMS)
    body, _, notice = output.partition("[local-delegate warning: 2 secciones sin resumir")
    assert notice, output
    for title in LEFT_OUT:
        assert f"## {title}\n" not in body
        assert output.count(f"«{title}»") == 1
        assert f"«{title}»" in notice


def test_a_failed_retry_keeps_the_summary_and_names_them(monkeypatch, tmp_path):
    output, _seen = _summarize(monkeypatch, tmp_path, _model(retry="error"))
    assert not output.startswith("[local-delegate error]")
    assert "## Sección 4\nResumen de Sección 4." in output
    assert not any(form in output for form in sections.NOT_SUMMARIZED_FORMS)
    for title in LEFT_OUT:
        assert output.count(f"«{title}»") == 1


def test_an_empty_heading_is_retried_and_filled_in_place(monkeypatch, tmp_path):
    output, seen = _summarize(monkeypatch, tmp_path, _model(retry="ok", empty=True))
    assert len([p for p in seen if _is_retry(p)]) == 1
    for title in LEFT_OUT:
        assert output.count(f"## {title}\n") == 1
        assert f"## {title}\nResumen nuevo de {title}." in output
    assert "sin resumir por el límite" not in output


def test_an_obedient_model_gets_no_retry(monkeypatch, tmp_path):
    def _obedient(payload, _n):
        listed = _listed(payload["messages"][1]["content"])
        return 200, "\n\n".join(f"## {t}\nResumen de {t}." for t in listed), "stop"

    output, seen = _summarize(monkeypatch, tmp_path, _obedient)
    (event,) = _events(tmp_path)
    assert event["chunks"] == len(seen) == len(event["steps"])
    assert "sections_retry" not in [s["kind"] for s in event["steps"]]
    assert "sin resumir" not in output


def test_merge_retry_puts_the_sections_in_their_slot():
    expected = ["Uno", "Dos", "Tres", "Cuatro"]
    output = "## Uno\nuno uno uno.\n\n## Tres\n\n## Cuatro\ncuatro cuatro cuatro."
    targets = sections.retry_targets(output, expected)
    assert targets == [1, 2]
    merged = sections.merge_retry(
        output, expected, "## Dos\ndos dos dos.\n\n## Tres\ntres tres tres."
    )
    assert merged == (
        "## Uno\nuno uno uno.\n\n## Dos\ndos dos dos.\n\n## Tres\ntres tres tres.\n\n"
        "## Cuatro\ncuatro cuatro cuatro."
    )
    assert sections.retry_targets(merged, expected) == []


def test_complete_naming_the_missing_inserts_nothing():
    expected = ["Uno", "Dos", "Tres"]
    output = "## Uno\nuno uno uno.\n\n## Tres\ntres tres tres."
    done = sections.complete(output, expected, name_missing=True)
    assert done.missing == 1
    assert "## Dos" not in done.text.split("[local-delegate warning:")[0]
    assert done.text.endswith(
        "[local-delegate warning: 1 sección sin resumir por el límite de "
        "palabras o del modelo: «Dos»]"
    )


def test_a_heading_cut_midway_is_dropped_before_the_retry():
    expected = ["Uno", "Dos", "Tres"]
    cut = "## Uno\nuno uno uno.\n\n## Dos\ndos dos dos.\n\n## Tr"
    assert (
        sections.without_cut_heading(cut, expected)
        == "## Uno\nuno uno uno.\n\n## Dos\ndos dos dos."
    )
    assert sections.retry_targets(sections.without_cut_heading(cut, expected), expected) == [2]
    whole = "## Uno\nuno uno uno."
    assert sections.without_cut_heading(whole, expected) == whole


def test_empty_in_the_chunk_and_again_in_the_retry_is_named_once_and_leaves_the_body(
    monkeypatch, tmp_path
):
    """J1 of the #691 review: a heading empty twice stays out of the body, named once."""
    output, seen = _summarize(monkeypatch, tmp_path, _model(retry="again", empty=True))
    assert len([p for p in seen if _is_retry(p)]) == 1
    body, _, notice = output.partition("[local-delegate warning: 2 secciones sin resumir")
    assert notice, output
    # Control: the neighbours are still there, summarized.
    assert "## Sección 4\nResumen de Sección 4." in body
    assert "## Sección 6\nResumen de Sección 6." in body
    for title in LEFT_OUT:
        assert f"## {title}\n" not in body and not body.rstrip().endswith(f"## {title}")
        assert output.count(f"«{title}»") == 1
        assert f"«{title}»" in notice


def test_complete_naming_the_missing_drops_an_empty_heading():
    expected = ["Uno", "Dos", "Tres"]
    output = "## Uno\nuno uno uno.\n\n## Dos\n\n## Tres\ntres tres tres."
    done = sections.complete(output, expected, name_missing=True)
    assert done.empty == 1
    assert done.text == (
        "## Uno\nuno uno uno.\n\n## Tres\ntres tres tres.\n\n"
        "[local-delegate warning: 1 sección sin resumir por el límite de "
        "palabras o del modelo: «Dos»]"
    )
    # Without `name_missing` (the single call) the empty heading stays, as before.
    assert "## Dos" in sections.complete(output, expected).text
    # An empty last section goes too.
    last = sections.complete(
        "## Uno\nuno uno uno.\n\n## Dos\ndos dos dos.\n\n## Tres\n", expected, name_missing=True
    )
    assert last.text.startswith("## Uno\nuno uno uno.\n\n## Dos\ndos dos dos.\n\n[local-delegate")
    # A section empty in the document itself keeps its heading.
    kept = sections.complete(output, expected, name_missing=True, empty_in_document=frozenset({1}))
    assert "## Dos" in kept.text and "warning" not in kept.text


def test_an_empty_parent_keeps_its_heading_over_its_subsections():
    """Second judge, S2: an empty parent whose subsections follow keeps its heading."""
    expected = ["Uno", "Dos", "Dos A", "Tres"]
    output = "## Uno\nuno uno uno.\n\n## Dos\n\n### Dos A\ndos a dos a.\n\n## Tres\ntres tres tres."
    done = sections.complete(output, expected, name_missing=True)
    assert "## Dos\n" in done.text and "### Dos A\ndos a dos a." in done.text
    assert "«Dos»" in done.text
