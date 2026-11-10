"""#649: a `local_extract` that answers with `_local_delegate.error` writes a failed usage row.

The backend answered 200 (often `finish_reason: "length"`), so `_chat` logged `ok: true`; the
JSON parse that fails comes later, in the tool. The row said success and the panel and
`local_status` counted the input read server-side as saved context, though the caller got no
data. Every test runs the real tool against a fake backend (`server._post_chat` replaced); the
usage log goes to the test's directory (`conftest.isolate_runtime_logs`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_delegate import backend_params as bp
from local_delegate import config, server

TRUNCATED_JSON = '{"title": "Plan", "tasks_with_lines": "12, 14, 1'


class Backend:
    """The fake backend: answers every call with `text` and `finish_reason`, counts the calls."""

    def __init__(self) -> None:
        self.calls = 0
        self.text = "{}"
        self.finish_reason = "stop"
        self.ok = True

    def __call__(self, model: str, payload: dict) -> server.ChatResult:
        self.calls += 1
        if not self.ok:
            return server.ChatResult(
                text=server.ERROR_PREFIX + "down",
                ok=False,
                error="connect_error",
                error_class="endpoint",
            )
        return server.ChatResult(
            text=self.text, ok=True, finish_reason=self.finish_reason, tokens_out=512
        )


@pytest.fixture
def backend(reload_config, monkeypatch):
    reload_config()
    bp._forget()
    fake = Backend()
    monkeypatch.setattr(server, "_post_chat", fake)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    yield fake
    bp._forget()


def _rows(tmp_path: Path, tool: str | None = "local_extract") -> list[dict]:
    rows: list[dict] = []
    for file in sorted(tmp_path.glob("usage*.jsonl")):
        rows += [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()]
    return [row for row in rows if tool is None or row.get("tool") == tool]


def _source(tmp_path: Path, chars: int = 2_000) -> str:
    target = tmp_path / "plan.md"
    target.write_text(("- [ ] una tarea del plan\n" * (chars // 25 + 1))[:chars], encoding="utf-8")
    return str(target)


def test_a_truncated_answer_that_is_not_json_writes_a_failed_row(backend, tmp_path):
    backend.text, backend.finish_reason = TRUNCATED_JSON, "length"

    data = server.local_extract(fields=["title", "tasks_with_lines"], path=_source(tmp_path))

    assert "error" in data["_local_delegate"], "precondition: the tool answered with an error"
    assert data["_local_delegate"].get("truncated") is True
    [row] = _rows(tmp_path)
    assert row["ok"] is False, "the caller got no data: the row is a failure"
    assert row["error"] == server.EXTRACT_INVALID_JSON
    assert row["error_class"] == "model"
    assert row["finish_reason"] == "length", "what the backend said is kept"


def test_a_failed_extract_row_claims_no_saved_context(backend, tmp_path):
    backend.text, backend.finish_reason = TRUNCATED_JSON, "length"

    server.local_extract(fields=["title"], path=_source(tmp_path))

    [row] = _rows(tmp_path)
    assert row["source"] == "path" and row["chars_in"] > 0
    accounting = server._accounting(row)
    assert accounting["failed"] is True
    assert accounting["chars_saved_text"] == 0, "no data reached the caller: nothing saved"


def test_json_that_is_not_an_object_writes_a_failed_row(backend, tmp_path):
    backend.text = '["Plan", 12]'

    data = server.local_extract(fields=["title"], text="# Plan\n\nuna tarea")

    assert "error" in data["_local_delegate"]
    [row] = _rows(tmp_path)
    assert row["ok"] is False
    assert row["error"] == server.EXTRACT_INVALID_JSON


def test_a_good_extract_still_writes_an_ok_row(backend, tmp_path):
    """Control: the same path with a parseable object keeps `ok: true` and its saving."""
    backend.text = '{"title": "Plan"}'

    data = server.local_extract(fields=["title"], path=_source(tmp_path))

    assert data["title"] == "Plan"
    [row] = _rows(tmp_path)
    assert row["ok"] is True
    assert "error" not in row
    assert server._accounting(row)["chars_saved_text"] > 0


def test_a_backend_failure_keeps_its_own_error(backend, tmp_path):
    """A row that was already a failure keeps the backend's error and class, untouched."""
    backend.ok = False

    data = server.local_extract(fields=["title"], text="# Plan")

    assert "error" in data["_local_delegate"]
    [row] = _rows(tmp_path)
    assert row["ok"] is False
    assert row["error"] == "connect_error"
    assert row["error_class"] == "endpoint"


def test_a_chunked_extract_that_ends_without_json_writes_a_failed_row(backend, tmp_path):
    backend.text, backend.finish_reason = "no soy JSON", "stop"
    long_text = "una línea del documento sin tabla\n" * (config.max_chars_for_role("long") // 30)

    data = server.local_extract(fields=["title"], text=long_text)

    assert backend.calls > 1, "precondition: the input was chunked"
    assert "error" in data["_local_delegate"]
    [row] = _rows(tmp_path)
    assert row["ok"] is False
    assert row["error"] == server.EXTRACT_INVALID_JSON


def test_the_next_call_writes_its_row_directly(backend, tmp_path):
    """The deferral ends with the extract: a later tool in the same thread logs as always."""
    backend.text = TRUNCATED_JSON
    server.local_extract(fields=["title"], text="# Plan")
    assert server._DEFERRED_EVENTS.get() is None

    backend.text = "un resumen"
    server.local_summarize(text="un texto que resumir")

    assert [row["ok"] for row in _rows(tmp_path, "local_summarize")] == [True]


def test_an_exception_after_the_backend_call_still_writes_the_row(backend, tmp_path, monkeypatch):
    """The row the backend call wrote is not lost when the tool raises afterwards."""
    backend.text = '{"title": "Plan"}'

    def boom(_raw: str) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(server, "_strip_fences", boom)
    with pytest.raises(RuntimeError):
        server.local_extract(fields=["title"], text="# Plan")

    assert len(_rows(tmp_path)) == 1
