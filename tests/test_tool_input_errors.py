"""An input validation error reaches the MCP client with its message (issue #552).

The SDK passes the text of a `ToolError` to the client and turns any other exception into a bare
`Error executing tool <name>`. The `mcp.input.*` checks raised a plain `ValueError`, so a call
without `text` or `path`, with `fields=[]` or to an existing `target` came back with no hint of
what to fix. They now raise `server.InputError` (a `ToolError` and a `ValueError`); an internal
failure stays masked.

Checked through the in-memory MCP client and through the daemon's HTTP app (what Claude Code uses
on the PC), since the masking happens in the SDK and both paths must show the text.
"""

from __future__ import annotations

import anyio
import httpx2
import pytest
from mcp import Client
from test_desktop_bridge import _HTTP_TIMEOUT, TOKEN, _RawSession, real_daemon

from local_delegate import i18n, server

GENERIC = "Error executing tool {name}"


@pytest.fixture
def no_backend(monkeypatch):
    """Every case fails before the model: a call that got there would be a different bug."""
    calls: list = []

    def refuse(*args, **kwargs):
        calls.append(args)
        raise AssertionError("the backend must not be called")

    monkeypatch.setattr(server, "_post_chat", refuse)
    yield
    assert calls == []


def _cases(existing: str) -> list[tuple[str, dict, str]]:
    return [
        ("local_summarize", {"max_words": 50}, i18n.t("mcp.input.text_or_path")),
        ("local_extract", {"fields": [], "text": "abc"}, i18n.t("mcp.input.fields_required")),
        (
            "local_boilerplate",
            {"spec": "a function", "language": "python", "target": existing},
            i18n.t("mcp.input.target_exists", target=existing),
        ),
    ]


def _existing(tmp_path) -> str:
    target = tmp_path / "exists.py"
    target.write_text("x = 1\n", encoding="utf-8")
    return str(target)


def _call_in_memory(name: str, arguments: dict):
    async def scenario():
        async with Client(server.mcp) as client:
            return await client.call_tool(name, arguments)

    return anyio.run(scenario)


def _text(result) -> str:
    return "\n".join(b.text for b in result.content if getattr(b, "type", "") == "text")


def test_input_error_is_a_tool_error_and_still_a_value_error():
    error = server.InputError("message")
    assert isinstance(error, server.ToolError) and isinstance(error, ValueError)


@pytest.mark.parametrize("index", range(3))
def test_in_memory_the_validation_message_reaches_the_client(tmp_path, no_backend, index):
    name, arguments, message = _cases(_existing(tmp_path))[index]

    result = _call_in_memory(name, arguments)

    assert result.is_error is True
    text = _text(result)
    # The exact message, not just "something more than the generic line".
    assert text == f"{GENERIC.format(name=name)}: {message}", text


def test_over_the_daemon_http_the_validation_message_reaches_the_client(
    tmp_path, monkeypatch, no_backend
):
    cases = _cases(_existing(tmp_path))

    async def scenario(url):
        answers = []
        async with httpx2.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            session = _RawSession(client, url)
            await session.open()
            for number, (name, arguments, _message) in enumerate(cases, start=100):
                answers.append(
                    await session.call(
                        {
                            "jsonrpc": "2.0",
                            "id": number,
                            "method": "tools/call",
                            "params": {"name": name, "arguments": arguments},
                        }
                    )
                )
        return answers

    with real_daemon(monkeypatch, TOKEN) as url:
        answers = anyio.run(scenario, url)

    assert len(answers) == len(cases)
    for (name, _arguments, message), answer in zip(cases, answers, strict=True):
        assert answer is not None and "result" in answer, answer
        result = answer["result"]
        assert result.get("isError") is True, result
        text = " ".join(c.get("text", "") for c in result.get("content", []))
        assert text == f"{GENERIC.format(name=name)}: {message}", text


def test_an_internal_value_error_stays_masked(tmp_path, monkeypatch, no_backend):
    """Only `InputError` is for the caller: a plain `ValueError` from inside keeps its text on the
    server, so no internal detail (a path, a value) leaks through the new channel."""
    source = tmp_path / "in.txt"
    source.write_text("some text\n", encoding="utf-8")

    def broken(path, mode):
        raise ValueError("internal-detail-do-not-show")

    monkeypatch.setattr(server, "_check_path", broken)

    result = _call_in_memory("local_summarize", {"path": str(source)})

    assert result.is_error is True
    assert _text(result) == GENERIC.format(name="local_summarize")
