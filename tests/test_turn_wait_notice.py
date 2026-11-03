"""A long wait for the common turn is said in the answer (issue #537).

Measured on 2026-11-02: a `local_summarize` took 343 s, 292 of them waiting for the common turn
behind a burst that alternated two models that cannot be loaded together. The answer said nothing,
so it looked like a slow model. Now a call that waited at least `TURN_WAIT_NOTICE_S` ends its
answer with a notice; a shorter wait leaves the answer exactly as it was.

No test sleeps: the wait is injected in the call's token (`turn_wait_ms`), which is what the turn
itself writes. The end-to-end tests go through the real MCP server with the SDK's in-memory client,
with `_chat` replaced so no backend is needed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import anyio
import pytest
from mcp import Client

from local_delegate import cancellation, config, i18n, server

THRESHOLD_S = 60.0


@pytest.fixture(autouse=True)
def _threshold(monkeypatch):
    monkeypatch.setattr(config, "TURN_WAIT_NOTICE_S", THRESHOLD_S)


def _notice(seconds: int) -> str:
    return i18n.t("mcp.warning.turn_wait", seconds=str(seconds))


def _in_call(waited_ms: int, fn):
    """Runs `fn` inside a call token that waited `waited_ms` for the turn."""
    token = cancellation.Token("local_summarize")
    token.turn_wait_ms = waited_ms
    reset = cancellation._CURRENT.set(token)
    try:
        return fn()
    finally:
        cancellation._CURRENT.reset(reset)


# --- The notice itself -------------------------------------------------------------------------


def test_long_wait_appends_the_notice_to_text():
    out = _in_call(291_600, lambda: server._add_turn_wait_notice("summary"))
    assert out == f"summary\n\n{server.WARNING_MARKER}{_notice(292)}]"


def test_notice_says_seconds_queue_and_group_by_tool():
    """The text carries what the issue asks: how long, queue not model, group by tool."""
    with i18n.override("es"):
        es = i18n.t("mcp.warning.turn_wait", seconds="292")
    with i18n.override("en"):
        en = i18n.t("mcp.warning.turn_wait", seconds="292")
    assert "292 s" in es and "cola" in es and "no lentitud del modelo" in es and "por tool" in es
    assert "292 s" in en and "queue" in en and "not a slow model" in en and "by tool" in en


@pytest.mark.parametrize("waited_ms", [0, 30_000, 59_499])
def test_short_wait_leaves_the_answer_untouched(waited_ms):
    assert _in_call(waited_ms, lambda: server._add_turn_wait_notice("summary")) == "summary"
    data = {"a": 1, "_local_delegate": {"warning": "w"}}
    assert _in_call(waited_ms, lambda: server._add_turn_wait_notice(data)) is data


def test_exactly_the_threshold_counts():
    out = _in_call(60_000, lambda: server._add_turn_wait_notice("x"))
    assert out.endswith(f"{_notice(60)}]")


def test_no_call_token_no_notice():
    assert cancellation.current() is None
    assert server._add_turn_wait_notice("summary") == "summary"


def test_zero_disables_it(monkeypatch):
    monkeypatch.setattr(config, "TURN_WAIT_NOTICE_S", 0.0)
    assert _in_call(900_000, lambda: server._add_turn_wait_notice("summary")) == "summary"


def test_error_text_is_left_alone():
    error = f"{server.ERROR_PREFIX}read_timeout: the model did not answer"
    assert _in_call(900_000, lambda: server._add_turn_wait_notice(error)) == error


@pytest.mark.parametrize("language", ["es", "en"])
def test_notice_goes_before_the_trailing_receipt_lines(language):
    with i18n.override(language):
        read = i18n.t("mcp.receipt.read_server_side", amount="10", unit="chars")
        passes = i18n.t("mcp.receipt.map_reduce", parts=4, calls=5)
        text = f"summary\n\n(an aside of the model)\n\n{passes}\n\n{read}"
        out = _in_call(120_000, lambda: server._add_turn_wait_notice(text))
        notice = f"{server.WARNING_MARKER}{_notice(120)}]"
    assert out == f"summary\n\n(an aside of the model)\n\n{notice}\n\n{passes}\n\n{read}"


def test_other_types_pass_through():
    value = ["a", "b"]
    assert _in_call(900_000, lambda: server._add_turn_wait_notice(value)) is value


def test_json_answer_gets_turn_wait_and_warning_when_there_is_none():
    out = _in_call(120_000, lambda: server._add_turn_wait_notice({"name": "x"}))
    assert out["name"] == "x"
    assert out["_local_delegate"] == {
        "turn_wait": {"seconds": 120, "notice": _notice(120)},
        "warning": _notice(120),
    }


def test_json_answer_keeps_an_existing_warning_exactly():
    original = {"name": "x", "_local_delegate": {"truncated": True, "warning": "cut"}}
    out = _in_call(120_000, lambda: server._add_turn_wait_notice(original))
    assert out["_local_delegate"]["warning"] == "cut"
    assert out["_local_delegate"]["truncated"] is True
    assert out["_local_delegate"]["turn_wait"]["seconds"] == 120
    # The tool's own dict is not mutated.
    assert original["_local_delegate"] == {"truncated": True, "warning": "cut"}


@pytest.mark.parametrize(("value", "expected"), [(None, 60.0), ("15", 15.0), ("0", 0.0)])
def test_env_variable_sets_the_threshold(value, expected):
    """The real `config` read in a fresh process: default 60, the variable overrides it."""
    env = {k: v for k, v in os.environ.items() if k != "LOCAL_DELEGATE_TURN_WAIT_NOTICE_S"}
    if value is not None:
        env["LOCAL_DELEGATE_TURN_WAIT_NOTICE_S"] = value
    src = str(Path(config.__file__).resolve().parents[1])
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "from local_delegate import config; print(config.TURN_WAIT_NOTICE_S)",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert float(out.stdout.strip()) == expected


# --- Installed over every tool -----------------------------------------------------------------


def test_every_registered_tool_is_wrapped_once():
    tools = server.mcp._tool_manager.list_tools()
    assert len(tools) >= 10  # guard: the registry is the real one
    for tool in tools:
        if tool.name in server._TURN_WAIT_NOTICE_EXCLUDED:
            assert not getattr(tool.fn, "__turn_wait_notice__", False), tool.name
            continue
        assert getattr(tool.fn, "__turn_wait_notice__", False), tool.name
        assert not getattr(tool.fn.__wrapped__, "__turn_wait_notice__", False), tool.name
    server._install_turn_wait_notice()  # idempotent: a second pass does not wrap again
    for tool in server.mcp._tool_manager.list_tools():
        if tool.name not in server._TURN_WAIT_NOTICE_EXCLUDED:
            assert not getattr(tool.fn.__wrapped__, "__turn_wait_notice__", False), tool.name


def _fake_chat(waited_ms: int, answer: str):
    def fake(*_args, **_kwargs):
        token = cancellation.current()
        assert token is not None  # guard: the tool ran inside the middleware's call token
        token.turn_wait_ms += waited_ms
        return answer

    return fake


def _call(name: str, arguments: dict):
    async def scenario():
        async with Client(server.mcp) as client:
            return await client.call_tool(name, arguments)

    return anyio.run(scenario)


def _text(result) -> str:
    return "\n".join(b.text for b in result.content if getattr(b, "type", "") == "text")


def _receipt() -> str:
    return i18n.t("mcp.receipt.chunked", calls=2)


def test_mcp_text_tool_gets_the_notice_before_the_receipt(monkeypatch):
    answer = f"hola\n\n{_receipt()}"
    monkeypatch.setattr(server, "_chat_chunked", _fake_chat(292_000, answer))
    result = _call("local_translate", {"target_lang": "Spanish", "text": "hello"})
    assert getattr(result, "is_error", False) is not True, result
    notice = f"{server.WARNING_MARKER}{_notice(292)}]"
    assert result.structured_content["result"] == f"hola\n\n{notice}\n\n{_receipt()}"


def test_mcp_text_tool_without_wait_is_unchanged(monkeypatch):
    answer = f"hola\n\n{_receipt()}"
    monkeypatch.setattr(server, "_chat_chunked", _fake_chat(10_000, answer))
    result = _call("local_translate", {"target_lang": "Spanish", "text": "hello"})
    assert result.structured_content["result"] == answer


def test_mcp_classify_keeps_the_exact_label(monkeypatch):
    """`local_classify` returns one label of the list: a notice would break whoever compares it."""
    monkeypatch.setattr(server, "_chat", _fake_chat(292_000, "positive"))
    result = _call("local_classify", {"text": "great", "labels": ["positive", "negative"]})
    assert getattr(result, "is_error", False) is not True, result
    assert result.structured_content["result"] == "positive"


def test_mcp_error_gets_no_notice(monkeypatch):
    """An error would read «it was the queue, not the model» right under a model timeout."""
    error = f"{server.ERROR_PREFIX}read_timeout: the model did not answer"
    monkeypatch.setattr(server, "_chat_chunked", _fake_chat(292_000, error))
    result = _call("local_translate", {"target_lang": "Spanish", "text": "hello"})
    assert server.WARNING_MARKER not in _text(result)
    assert error in _text(result)


def test_mcp_extract_gets_it_inside_local_delegate(monkeypatch):
    monkeypatch.setattr(server, "_chat", _fake_chat(150_000, '{"name": "Ada"}'))
    result = _call("local_extract", {"fields": ["name"], "text": "Ada wrote it."})
    assert getattr(result, "is_error", False) is not True, result
    data = result.structured_content
    assert data["name"] == "Ada"
    assert data["_local_delegate"]["turn_wait"] == {"seconds": 150, "notice": _notice(150)}
    assert data["_local_delegate"]["warning"] == _notice(150)
    # The JSON text block says the same as the structured content.
    assert json.loads(_text(result)) == data
