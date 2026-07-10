"""Tests de F1 (config._env_float, server._read_input/_strip_think/_strip_fences/_post_chat/
_chat, enrutado de local_extract), F2 (response_format json_schema, local_status), F3
(feedback de ahorro) y F4 (rotación del log, inflight)."""

from __future__ import annotations

import json
import threading
import time as _time
from datetime import datetime, timezone

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


def test_json_schema_payload_restricts_properties_to_primitives():
    # Un sub-schema vacío ({}) permite objetos/arrays anidados: algunos modelos (p. ej.
    # gemma3-4b) responden {"campo": {"valor": "x"}} en vez de {"campo": "x"}. Cada
    # propiedad debe restringirse a string/number/boolean/null.
    payload = server._json_schema_payload(["a", "b"])
    props = payload["schema"]["properties"]
    assert set(props) == {"a", "b"}
    for prop in props.values():
        assert prop == {"type": ["string", "number", "boolean", "null"]}


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
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
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
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
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
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    respx.get("http://test-backend/v1/models").mock(side_effect=httpx.ConnectError("down"))
    respx.get("http://test-backend/running").mock(side_effect=httpx.ConnectError("down"))
    text = server.local_status()
    assert "eventos: 1" in text
    assert "~100 tokens" in text


# --- F7: línea best-effort de groups activos en local_status --------------------------
def test_llamaswap_groups_without_env_returns_none(monkeypatch):
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    assert server._llamaswap_groups() is None


def test_llamaswap_groups_missing_file_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(tmp_path / "no-existe.yaml"))
    assert server._llamaswap_groups() is None


def test_llamaswap_groups_reports_sorted_names(monkeypatch, tmp_path):
    from local_delegate import llamaswap_config as lc

    cfg = tmp_path / "config.yaml"
    lc.dump_config(
        {"models": {}, "groups": {"swap": {"members": []}, "resident": {"members": []}}}, cfg
    )
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(cfg))
    assert server._llamaswap_groups() == "resident, swap"


def test_llamaswap_groups_without_pyyaml_returns_none(monkeypatch, tmp_path):
    from local_delegate import llamaswap_config as lc

    cfg = tmp_path / "config.yaml"
    cfg.write_text("models: {}\ngroups: {swap: {members: []}}\n", encoding="utf-8")
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(cfg))
    monkeypatch.setattr(lc, "yaml", None)
    assert server._llamaswap_groups() is None


@respx.mock
def test_local_status_includes_groups_line(monkeypatch, tmp_path):
    from local_delegate import llamaswap_config as lc

    cfg = tmp_path / "config.yaml"
    lc.dump_config({"models": {}, "groups": {"resident": {"members": []}}}, cfg)
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(cfg))
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    respx.get("http://test-backend/v1/models").mock(side_effect=httpx.ConnectError("down"))
    respx.get("http://test-backend/running").mock(side_effect=httpx.ConnectError("down"))
    text = server.local_status()
    assert "groups activos" in text
    assert "resident" in text


# --- F3: feedback de ahorro en _chat --------------------------------------------------
@respx.mock
def test_chat_appends_feedback_when_source_path(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", True)
    respx.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "resumen"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 500, "completion_tokens": 3},
            },
        )
    )
    text = server._chat(
        config.MODEL_MECHANICAL, "system", "user", max_tokens=8, chars_in=2000, source="path"
    )
    assert "leído server-side: 2,000 chars" in text
    assert "500 tokens" in text


@respx.mock
def test_chat_feedback_disabled_by_env(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    respx.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "resumen"}, "finish_reason": "stop"}]}
        )
    )
    text = server._chat(
        config.MODEL_MECHANICAL, "system", "user", max_tokens=8, chars_in=2000, source="path"
    )
    assert "leído server-side" not in text


@respx.mock
def test_chat_no_feedback_for_inline_source(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", True)
    respx.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "resumen"}, "finish_reason": "stop"}]}
        )
    )
    text = server._chat(
        config.MODEL_MECHANICAL, "system", "user", max_tokens=8, chars_in=2000, source="inline"
    )
    assert "leído server-side" not in text


# --- F4: rotación del log --------------------------------------------------------------
def test_current_log_path_rotates_by_month(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", True)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(server, "_utcnow", lambda: datetime(2026, 3, 15, tzinfo=timezone.utc))
    assert server._current_log_path() == tmp_path / "usage-202603.jsonl"


def test_current_log_path_legacy_disables_rotation(monkeypatch, tmp_path):
    fixed = tmp_path / "usage.jsonl"
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    monkeypatch.setattr(config, "USAGE_LOG", fixed)
    monkeypatch.setattr(server, "_utcnow", lambda: datetime(2026, 3, 15, tzinfo=timezone.utc))
    assert server._current_log_path() == fixed


@respx.mock
def test_log_event_writes_to_rotated_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", True)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(server, "_utcnow", lambda: datetime(2026, 3, 15, tzinfo=timezone.utc))
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    respx.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        )
    )
    server._chat(config.MODEL_MECHANICAL, "s", "u", max_tokens=8)
    assert (tmp_path / "usage-202603.jsonl").is_file()


# --- F4: delegaciones en curso (inflight) -----------------------------------------------
def test_inflight_snapshot_during_and_after_chat(monkeypatch):
    def slow_post_chat(model, payload):
        _time.sleep(0.3)
        return server.ChatResult(text="ok", ok=True, finish_reason="stop")

    monkeypatch.setattr(server, "_post_chat", slow_post_chat)
    assert server.inflight_snapshot() == []
    t = threading.Thread(
        target=server._chat,
        args=(config.MODEL_MECHANICAL, "s", "u"),
        kwargs={"max_tokens": 8, "tool": "local_summarize", "chars_in": 10, "source": "path"},
    )
    t.start()
    _time.sleep(0.1)
    snap = server.inflight_snapshot()
    assert len(snap) == 1
    assert snap[0]["tool"] == "local_summarize"
    assert snap[0]["elapsed_s"] >= 0
    t.join(timeout=2)
    assert server.inflight_snapshot() == []


# --- F5: LOCAL_DELEGATE_ALLOWED_DIRS ----------------------------------------------------
def test_allowed_dirs_empty_means_unrestricted(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ALLOWED_DIRS", [])
    f = tmp_path / "afuera.txt"
    f.write_text("hola", encoding="utf-8")
    content, _truncated, _raw_len = server._read_input(None, str(f), max_chars=100)
    assert content == "hola"


def test_allowed_dirs_accepts_path_inside_root(monkeypatch, tmp_path):
    root = tmp_path / "proyecto"
    root.mkdir()
    monkeypatch.setattr(config, "ALLOWED_DIRS", [root.resolve()])
    f = root / "dentro.txt"
    f.write_text("hola", encoding="utf-8")
    content, _truncated, _raw_len = server._read_input(None, str(f), max_chars=100)
    assert content == "hola"


def test_allowed_dirs_rejects_path_outside_roots(monkeypatch, tmp_path):
    root = tmp_path / "proyecto"
    root.mkdir()
    outside = tmp_path / "otro" / "afuera.txt"
    outside.parent.mkdir()
    outside.write_text("hola", encoding="utf-8")
    monkeypatch.setattr(config, "ALLOWED_DIRS", [root.resolve()])
    with pytest.raises(ValueError, match="fuera de las raíces permitidas"):
        server._read_input(None, str(outside), max_chars=100)


def test_allowed_dirs_resolves_relative_paths(monkeypatch, tmp_path):
    root = tmp_path / "proyecto"
    root.mkdir()
    f = root / "sub" / "dentro.txt"
    f.parent.mkdir()
    f.write_text("hola", encoding="utf-8")
    monkeypatch.setattr(config, "ALLOWED_DIRS", [root.resolve()])
    monkeypatch.chdir(root)
    content, _truncated, _raw_len = server._read_input(None, "sub/dentro.txt", max_chars=100)
    assert content == "hola"


# --- F5: lock de escritura del log ------------------------------------------------------
def test_log_event_writes_even_when_lock_times_out(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", True)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(server, "_utcnow", lambda: datetime(2026, 3, 15, tzinfo=timezone.utc))

    class FakeLock:
        def __init__(self, *_a, **_k):
            pass

        def __enter__(self):
            raise server.Timeout("locked")

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(server, "FileLock", FakeLock)
    server._log_event(
        tool="t", model="m", source="inline", chars_in=1, chars_out=1, latency_ms=1, ok=True
    )
    target = tmp_path / "usage-202603.jsonl"
    assert target.is_file()
    assert json.loads(target.read_text(encoding="utf-8").strip())["tool"] == "t"
