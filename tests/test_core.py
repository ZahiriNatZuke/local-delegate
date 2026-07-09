"""Tests de F1 (config._env_float, server._read_input/_strip_think/_strip_fences/_post_chat/
_chat, enrutado de local_extract) y F2 (response_format json_schema, local_status)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from local_delegate import config, server


# --- config._env_float -------------------------------------------------------
def test_env_float_malformed(monkeypatch):
    monkeypatch.setenv("LOCAL_DELEGATE_TIMEOUT", "abc")
    assert config._env_float("LOCAL_DELEGATE_TIMEOUT", 180.0) == 180.0


def test_env_float_valid(monkeypatch):
    monkeypatch.setenv("LOCAL_DELEGATE_TIMEOUT", "42.5")
    assert config._env_float("LOCAL_DELEGATE_TIMEOUT", 180.0) == 42.5


# --- server._read_input -------------------------------------------------------
def test_read_input_short_text():
    content, truncated, raw_len = server._read_input("hola", None, max_chars=100)
    assert content == "hola"
    assert truncated is False
    assert raw_len == 4


def test_read_input_missing_path_raises():
    with pytest.raises(ValueError):
        server._read_input(None, "no/existe/este/archivo.txt", max_chars=100)


def test_read_input_no_text_no_path_raises():
    with pytest.raises(ValueError):
        server._read_input(None, None, max_chars=100)


def test_read_input_truncates_and_reports_raw_len(tmp_path):
    p = tmp_path / "big.txt"
    p.write_text("x" * 500, encoding="utf-8")
    content, truncated, raw_len = server._read_input(None, str(p), max_chars=100)
    assert truncated is True
    assert raw_len == 500
    assert content.startswith("x" * 100)
    assert "[...contenido truncado...]" in content


def test_read_input_path_precedence_over_text(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("del archivo", encoding="utf-8")
    content, _truncated, _raw_len = server._read_input("del texto", str(p), max_chars=100)
    assert content == "del archivo"


# --- server._strip_think -------------------------------------------------------
def test_strip_think_removes_closed_block():
    assert server._strip_think("<think>razonando...</think>respuesta") == "respuesta"


def test_strip_think_no_block_passthrough():
    assert server._strip_think("respuesta directa") == "respuesta directa"


def test_strip_think_unclosed_block_at_start():
    assert server._strip_think("<think>razonando sin cerrar nunca") == ""


def test_strip_think_case_insensitive_and_thinking_variant():
    assert server._strip_think("<THINKING>algo</THINKING>ok") == "ok"


def test_strip_think_nested_in_text():
    assert server._strip_think("antes<think>razonando</think>después") == "antesdespués"


# --- server._strip_fences -------------------------------------------------------
def test_strip_fences_simple():
    assert server._strip_fences("```\nhola\n```") == "hola"


def test_strip_fences_with_language():
    assert server._strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_fences_no_fence():
    assert server._strip_fences("texto plano") == "texto plano"


# --- server._post_chat -----------------------------------------------------------
@respx.mock
def test_post_chat_ok_with_usage_and_finish_reason(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    respx.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": " hola "}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    result = server._post_chat("modelo", {"model": "modelo"})
    assert result.ok is True
    assert result.text == "hola"
    assert result.finish_reason == "length"
    assert result.tokens_in == 10
    assert result.tokens_out == 5


@respx.mock
def test_post_chat_http_500(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    respx.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx.Response(500, text="boom")
    )
    result = server._post_chat("modelo", {"model": "modelo"})
    assert result.ok is False
    assert result.error == "http_500"
    assert "[local-delegate error]" in result.text


@respx.mock
def test_post_chat_connect_error_no_autostart(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "AUTOSTART", False)
    respx.post("http://test-backend/v1/chat/completions").mock(
        side_effect=httpx.ConnectError("no route")
    )
    result = server._post_chat("modelo", {"model": "modelo"})
    assert result.ok is False
    assert result.error == "connect_error"


@respx.mock
def test_chat_appends_visible_notice_on_truncation(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    respx.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": "parcial"}, "finish_reason": "length"}]},
        )
    )
    text = server._chat(config.MODEL_MECHANICAL, "system", "user", max_tokens=8)
    assert "[local-delegate aviso: salida truncada por max_tokens]" in text


@respx.mock
def test_post_chat_response_without_usage_has_none_tokens(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    respx.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        )
    )
    result = server._post_chat("modelo", {"model": "modelo"})
    assert result.ok is True
    assert result.tokens_in is None
    assert result.tokens_out is None


# --- enrutado de local_extract ----------------------------------------------------
def test_local_extract_routes_long_input_to_model_long(monkeypatch):
    captured = {}

    def fake_chat(model, system, user, max_tokens, temperature=0.2, **kwargs):
        captured["model"] = model
        return "{}"

    monkeypatch.setattr(server, "_chat", fake_chat)
    long_text = "x" * (config.LONG_INPUT_CHARS + 1)
    server.local_extract(fields=["a"], text=long_text)
    assert captured["model"] == config.MODEL_LONG


def test_local_extract_routes_short_input_to_model_mechanical(monkeypatch):
    captured = {}

    def fake_chat(model, system, user, max_tokens, temperature=0.2, **kwargs):
        captured["model"] = model
        return "{}"

    monkeypatch.setattr(server, "_chat", fake_chat)
    server.local_extract(fields=["a"], text="corto")
    assert captured["model"] == config.MODEL_MECHANICAL


# --- F2: response_format json_schema en local_extract ------------------------------
@respx.mock
def test_local_extract_sends_response_format_by_default(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "auto")
    route = respx.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}]}
        )
    )
    server.local_extract(fields=["a"], text="hola")
    sent = json.loads(route.calls.last.request.content)
    assert sent["response_format"]["type"] == "json_object"
    assert sent["response_format"]["schema"]["required"] == ["a"]


@respx.mock
def test_local_extract_json_schema_off_skips_response_format(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    route = respx.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}]}
        )
    )
    server.local_extract(fields=["a"], text="hola")
    sent = json.loads(route.calls.last.request.content)
    assert "response_format" not in sent


@respx.mock
def test_json_schema_auto_falls_back_on_400(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "auto")
    responses = [
        httpx.Response(400, text="unsupported response_format"),
        httpx.Response(
            200, json={"choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}]}
        ),
    ]
    route = respx.post("http://test-backend/v1/chat/completions").mock(side_effect=responses)
    text = server.local_extract(fields=["a"], text="hola")
    assert route.call_count == 2
    assert text == '{"a": 1}'


@respx.mock
def test_json_schema_on_propagates_400(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "on")
    route = respx.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx.Response(400, text="unsupported response_format")
    )
    text = server.local_extract(fields=["a"], text="hola")
    assert route.call_count == 1
    assert "[local-delegate error]" in text


# --- F2: local_status ----------------------------------------------------------------
@respx.mock
def test_local_status_reports_backend_up_and_models(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    respx.get("http://test-backend/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "modelo-a"}]})
    )
    respx.get("http://test-backend/running").mock(return_value=httpx.Response(404))
    text = server.local_status()
    assert "arriba" in text
    assert "modelo-a" in text


@respx.mock
def test_local_status_reports_backend_down(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    respx.get("http://test-backend/v1/models").mock(side_effect=httpx.ConnectError("down"))
    respx.get("http://test-backend/running").mock(side_effect=httpx.ConnectError("down"))
    text = server.local_status()
    assert "CAÍDO" in text


@respx.mock
def test_local_status_reports_log_stats(monkeypatch, tmp_path):
    log = tmp_path / "usage.jsonl"
    log.write_text(
        json.dumps({"tool": "local_summarize", "source": "path", "chars_in": 400, "ok": True})
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "USAGE_LOG", log)
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    respx.get("http://test-backend/v1/models").mock(side_effect=httpx.ConnectError("down"))
    respx.get("http://test-backend/running").mock(side_effect=httpx.ConnectError("down"))
    text = server.local_status()
    assert "eventos: 1" in text
    assert "~100 tokens" in text
