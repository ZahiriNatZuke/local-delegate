"""Tests de F1 (config._env_float, server._read_input/_strip_think/_strip_fences/_post_chat/
_chat, enrutado de local_extract), F2 (response_format json_schema, local_status), F3
(feedback de ahorro) y F4 (rotación del log, inflight)."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time as _time
from datetime import UTC, datetime

import backend_mock
import httpx2
import pytest

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
@backend_mock.mock
def test_post_chat_ok_with_usage_and_finish_reason(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx2.Response(
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


@backend_mock.mock
def test_post_chat_http_500(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx2.Response(500, text="boom")
    )
    result = server._post_chat("modelo", {"model": "modelo"})
    assert result.ok is False
    assert result.error == "http_500"
    assert "[local-delegate error]" in result.text


@backend_mock.mock
def test_post_chat_connect_error_no_autostart(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "AUTOSTART", False)
    backend_mock.post("http://test-backend/v1/chat/completions").mock(
        side_effect=httpx2.ConnectError("no route")
    )
    result = server._post_chat("modelo", {"model": "modelo"})
    assert result.ok is False
    assert result.error == "connect_error"


@backend_mock.mock
def test_chat_appends_visible_notice_on_truncation(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx2.Response(
            200,
            json={"choices": [{"message": {"content": "parcial"}, "finish_reason": "length"}]},
        )
    )
    text = server._chat(config.MODEL_MECHANICAL, "system", "user", max_tokens=8)
    assert "[local-delegate aviso: salida truncada por max_tokens]" in text


@backend_mock.mock
def test_post_chat_response_without_usage_has_none_tokens(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx2.Response(
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
@backend_mock.mock
def test_local_extract_sends_response_format_by_default(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "auto")
    route = backend_mock.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx2.Response(
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


@backend_mock.mock
def test_local_extract_json_schema_off_skips_response_format(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    route = backend_mock.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx2.Response(
            200, json={"choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}]}
        )
    )
    server.local_extract(fields=["a"], text="hola")
    sent = json.loads(route.calls.last.request.content)
    assert "response_format" not in sent


@backend_mock.mock
def test_json_schema_auto_falls_back_on_400(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "auto")
    responses = [
        httpx2.Response(400, text="unsupported response_format"),
        httpx2.Response(
            200, json={"choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}]}
        ),
    ]
    route = backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=responses)
    data = server.local_extract(fields=["a"], text="hola")
    assert route.call_count == 2
    # Objeto ya parseado, no una cadena con JSON dentro.
    assert data == {"a": 1}


@backend_mock.mock
def test_json_schema_on_propagates_400(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "on")
    route = backend_mock.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx2.Response(400, text="unsupported response_format")
    )
    data = server.local_extract(fields=["a"], text="hola")
    assert route.call_count == 1
    # El fallo del backend no puede quedar mudo por devolver un objeto: viaja bajo la clave
    # reservada, que es donde quien llama puede encontrarlo sin adivinar.
    assert "[local-delegate error]" in data["_local_delegate"]["crudo"]


# --- salida estructurada de local_extract (REQ-008) -----------------------------------
@backend_mock.mock
def test_local_extract_returns_an_object_with_the_requested_keys(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx2.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": '{"host": "127.0.0.1", "port": "9393"}'},
                        "finish_reason": "stop",
                    }
                ]
            },
        )
    )
    data = server.local_extract(fields=["host", "port"], text="algo")
    assert data == {"host": "127.0.0.1", "port": "9393"}
    # Sin truncamiento, exactamente las claves pedidas y ninguna más.
    assert "_local_delegate" not in data


@backend_mock.mock
def test_local_extract_warns_about_truncation_without_breaking_the_keys(monkeypatch):
    """El aviso iba delante del JSON como texto; ahora va aparte y no estorba al parseo."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    # El tope que usa el modelo principal es el del ROL (F3, tarea 25), no el del modelo.
    monkeypatch.setattr(config, "max_chars_for_role", lambda _rol: 10)
    backend_mock.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx2.Response(
            200,
            json={"choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}]},
        )
    )
    data = server.local_extract(fields=["a"], text="x" * 500)
    assert data["a"] == 1
    assert data["_local_delegate"]["truncado"] is True
    assert "500" in data["_local_delegate"]["aviso"]


@backend_mock.mock
def test_local_extract_with_path_does_not_break_the_json_with_the_savings_line(
    monkeypatch, tmp_path
):
    """La regresión que se coló en la 0.13.0, encontrada usando el propio MCP.

    `_chat` anexa la línea «(leído server-side: N chars…)» al texto cuando la entrada vino de un
    `path`. Como esta tool **parsea** el resultado, ese sufijo convertía un JSON perfecto en uno
    imparseable y `local_extract(path=…)` devolvía siempre `_local_delegate.error` — justo en el
    modo que ahorra contexto, que es el que vale la pena usar.

    Ningún test lo vio porque **todos** los de `local_extract` usaban `text=`.
    """
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", True)
    source = tmp_path / "source.md"
    source.write_text("host 127.0.0.1 port 9393\n" * 40, encoding="utf-8")
    backend_mock.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx2.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": '{"host": "127.0.0.1", "port": "9393"}'},
                        "finish_reason": "stop",
                    }
                ]
            },
        )
    )

    data = server.local_extract(fields=["host", "port"], path=str(source))

    assert data["host"] == "127.0.0.1"
    assert data["port"] == "9393"
    assert "error" not in data.get("_local_delegate", {})
    # El dato de ahorro no se pierde: se recoloca donde no estorba al parseo.
    assert data["_local_delegate"]["leido_server_side"]["chars"] > 0


@backend_mock.mock
def test_local_extract_degrades_if_the_response_is_not_json(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx2.Response(
            200,
            json={"choices": [{"message": {"content": "no soy JSON"}, "finish_reason": "stop"}]},
        )
    )
    data = server.local_extract(fields=["a"], text="algo")
    assert data["_local_delegate"]["crudo"] == "no soy JSON"


# --- F2: local_status ----------------------------------------------------------------
@backend_mock.mock
def test_local_status_reports_backend_up_and_models(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    backend_mock.get("http://test-backend/v1/models").mock(
        return_value=httpx2.Response(200, json={"data": [{"id": "model-a"}]})
    )
    backend_mock.get("http://test-backend/running").mock(return_value=httpx2.Response(404))
    text = server.local_status()
    assert "arriba" in text
    assert "model-a" in text


@backend_mock.mock
def test_local_status_reports_backend_down(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    backend_mock.get("http://test-backend/v1/models").mock(side_effect=httpx2.ConnectError("down"))
    backend_mock.get("http://test-backend/running").mock(side_effect=httpx2.ConnectError("down"))
    text = server.local_status()
    assert "CAÍDO" in text


@backend_mock.mock
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
    backend_mock.get("http://test-backend/v1/models").mock(side_effect=httpx2.ConnectError("down"))
    backend_mock.get("http://test-backend/running").mock(side_effect=httpx2.ConnectError("down"))
    text = server.local_status()
    assert "eventos: 1" in text
    # coste-api-y-cuota: 400 chars por `path` sin extensión, respaldo Opus 5.5 → clase `otro`,
    # respaldo (3), c = 2,41: 400 × 100 // 241 = 165 tokens de Claude (antes 400 ÷ 4 = 100).
    assert "~165 tokens" in text


# --- F7.9: RAM de sistema en local_status ---------------------------------------------
def test_ram_info_smoke():
    # No mockeamos el SO: en cualquier Windows/Linux real debe devolver un string parseable
    # (o None si la plataforma no está soportada, p. ej. macOS) — nunca debe lanzar.
    info = server._ram_info()
    assert info is None or "GiB usados" in info


@backend_mock.mock
def test_local_status_includes_ram_line(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get("http://test-backend/v1/models").mock(side_effect=httpx2.ConnectError("down"))
    backend_mock.get("http://test-backend/running").mock(side_effect=httpx2.ConnectError("down"))
    text = server.local_status()
    if server._ram_info() is not None:
        assert "RAM de sistema:" in text


# --- F7: línea best-effort de groups activos en local_status --------------------------
def test_llamaswap_groups_without_env_returns_none(monkeypatch):
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    assert server._llamaswap_groups() is None


def test_llamaswap_groups_missing_file_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(tmp_path / "missing.yaml"))
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


@backend_mock.mock
def test_local_status_includes_groups_line(monkeypatch, tmp_path):
    from local_delegate import llamaswap_config as lc

    cfg = tmp_path / "config.yaml"
    lc.dump_config({"models": {}, "groups": {"resident": {"members": []}}}, cfg)
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(cfg))
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get("http://test-backend/v1/models").mock(side_effect=httpx2.ConnectError("down"))
    backend_mock.get("http://test-backend/running").mock(side_effect=httpx2.ConnectError("down"))
    text = server.local_status()
    assert "groups activos" in text
    assert "resident" in text


# --- F3: feedback de ahorro en _chat --------------------------------------------------
@backend_mock.mock
def test_chat_appends_feedback_when_source_path(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", True)
    backend_mock.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx2.Response(
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
    # coste-api-y-cuota, REQ-035: tokens de CLAUDE, no los 500 `prompt_tokens` del modelo local.
    # `_chat` sin `path`, respaldo Opus 5.5: clase `otro`, c = 2,41 → 2000 × 100 // 241 = 829.
    assert "2,000 chars ≈ 829 tokens de Claude que no entraron a tu contexto)" in text
    assert "500" not in text


@backend_mock.mock
def test_chat_feedback_disabled_by_env(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    backend_mock.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx2.Response(
            200, json={"choices": [{"message": {"content": "resumen"}, "finish_reason": "stop"}]}
        )
    )
    text = server._chat(
        config.MODEL_MECHANICAL, "system", "user", max_tokens=8, chars_in=2000, source="path"
    )
    assert "leído server-side" not in text


@backend_mock.mock
def test_chat_no_feedback_for_inline_source(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", True)
    backend_mock.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx2.Response(
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
    monkeypatch.setattr(server, "_utcnow", lambda: datetime(2026, 3, 15, tzinfo=UTC))
    assert server._current_log_path() == tmp_path / "usage-202603.jsonl"


def test_current_log_path_legacy_disables_rotation(monkeypatch, tmp_path):
    fixed = tmp_path / "usage.jsonl"
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    monkeypatch.setattr(config, "USAGE_LOG", fixed)
    monkeypatch.setattr(server, "_utcnow", lambda: datetime(2026, 3, 15, tzinfo=UTC))
    assert server._current_log_path() == fixed


@backend_mock.mock
def test_log_event_writes_to_rotated_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", True)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(server, "_utcnow", lambda: datetime(2026, 3, 15, tzinfo=UTC))
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx2.Response(
            200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        )
    )
    server._chat(config.MODEL_MECHANICAL, "s", "u", max_tokens=8)
    assert (tmp_path / "usage-202603.jsonl").is_file()


# --- F4: delegaciones en curso (inflight) -----------------------------------------------
def test_inflight_snapshot_during_and_after_chat(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)

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


def test_chat_applies_process_wide_concurrency_limit(tmp_path, monkeypatch):
    active = 0
    peak = 0
    state_lock = threading.Lock()
    two_active = threading.Event()
    release = threading.Event()

    def slow_post_chat(_model, _payload):
        nonlocal active, peak
        with state_lock:
            active += 1
            peak = max(peak, active)
            if active == 2:
                two_active.set()
        release.wait(timeout=5)
        with state_lock:
            active -= 1
        return server.ChatResult(text="ok", ok=True, finish_reason="stop")

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(server, "_post_chat", slow_post_chat)
    monkeypatch.setattr(server, "_chat_slots", threading.BoundedSemaphore(2))

    threads = [threading.Thread(target=server._chat, args=("m", "s", "u", 8)) for _ in range(5)]
    for thread in threads:
        thread.start()

    assert two_active.wait(timeout=5)
    with state_lock:
        assert active == 2
        assert peak == 2
    release.set()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    # Con los cinco hilos ya terminados hay dos cosas distintas que comprobar, y la segunda es la
    # que pilla una regresión de verdad: que el pico no pasó de 2 ni al desatascarse la cola de
    # golpe, y que el semáforo quedó con sus dos slots DEVUELTOS. Hoy `_chat` usa `with
    # _chat_slots:`, que libera pase lo que pase; si alguien lo cambiara a un acquire() manual y se
    # le escapara un camino de error, cada delegación fallida se comería un slot y a la tercera el
    # MCP se colgaría para siempre sin decir por qué.
    with state_lock:
        final_state = (peak, active)
    slots = [server._chat_slots.acquire(blocking=False) for _ in range(2)]
    for acquired in slots:
        if acquired:
            server._chat_slots.release()
    assert (final_state, slots) == ((2, 0), [True, True])


# --- F5: LOCAL_DELEGATE_ALLOWED_DIRS ----------------------------------------------------
def test_allowed_dirs_empty_means_unrestricted(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ALLOWED_DIRS", [])
    f = tmp_path / "outside.txt"
    f.write_text("hola", encoding="utf-8")
    content, _truncated, _raw_len = server._read_input(None, str(f), max_chars=100)
    assert content == "hola"


def test_allowed_dirs_accepts_path_inside_root(monkeypatch, tmp_path):
    root = tmp_path / "proyecto"
    root.mkdir()
    monkeypatch.setattr(config, "ALLOWED_DIRS", [root.resolve()])
    f = root / "inside.txt"
    f.write_text("hola", encoding="utf-8")
    content, _truncated, _raw_len = server._read_input(None, str(f), max_chars=100)
    assert content == "hola"


def test_allowed_dirs_rejects_path_outside_roots(monkeypatch, tmp_path):
    root = tmp_path / "proyecto"
    root.mkdir()
    outside = tmp_path / "otro" / "outside.txt"
    outside.parent.mkdir()
    outside.write_text("hola", encoding="utf-8")
    monkeypatch.setattr(config, "ALLOWED_DIRS", [root.resolve()])
    with pytest.raises(ValueError, match="fuera de las raíces permitidas"):
        server._read_input(None, str(outside), max_chars=100)


def test_allowed_dirs_resolves_relative_paths(monkeypatch, tmp_path):
    root = tmp_path / "proyecto"
    root.mkdir()
    f = root / "sub" / "inside.txt"
    f.parent.mkdir()
    f.write_text("hola", encoding="utf-8")
    monkeypatch.setattr(config, "ALLOWED_DIRS", [root.resolve()])
    monkeypatch.chdir(root)
    content, _truncated, _raw_len = server._read_input(None, "sub/inside.txt", max_chars=100)
    assert content == "hola"


# --- F5: lock de escritura del log ------------------------------------------------------
def test_log_event_writes_even_when_lock_times_out(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", True)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(server, "_utcnow", lambda: datetime(2026, 3, 15, tzinfo=UTC))

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


# --- Invariante de arranque: el stack web propio no entra al importar el paquete ---------
def test_importing_the_package_does_not_pull_in_its_own_web_stack():
    """Importar `local_delegate` no debe cargar `fastapi` ni los módulos del daemon/dashboard.

    De esto depende una decisión escrita en `pyproject.toml`: `fastapi` es dependencia de runtime
    **sin** techo de major, y una de sus dos razones es que no está en el camino de import de
    arranque —`web/metrics.py` y `daemon.py` entran perezosamente, desde dentro de una función—,
    así que una rotura suya no puede matar `uvx local-delegate-mcp` por stdio antes de que hable
    MCP. Basta un refactor que suba `from .web import metrics` al nivel de módulo para invalidar
    esa premisa **en silencio**; este test la convierte en un fallo visible.

    `uvicorn` queda deliberadamente **fuera** de la comprobación: sí se carga al arrancar, pero no
    por este paquete — lo arrastra el propio SDK (`mcp.server.fastmcp` → `mcp/server/sse.py` →
    `sse_starlette` → `uvicorn`). No es una invariante que este repo pueda sostener, así que
    afirmarla aquí sería fijar un detalle interno del SDK.

    Corre en un subproceso limpio a propósito: dentro de la suite otros tests ya han importado el
    stack web, así que el `sys.modules` de este proceso no serviría de nada.
    """
    watched = ("fastapi", "local_delegate.web.metrics", "local_delegate.daemon")
    code = (
        "import sys; import local_delegate; "
        f"print(','.join(m for m in {watched!r} if m in sys.modules))"
    )
    r = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=True
    )
    loaded = r.stdout.strip()
    assert loaded == "", (
        f"importar local_delegate arrastró {loaded}: la premisa del techo de dependencias en "
        "pyproject.toml ya no se cumple. O se restaura el import perezoso, o hay que revisar la "
        "política (ver docs/wiki/Repo-hardening.md)."
    )


# --- Inventario de un diff (local_commit_msg) --------------------------------
# El inventario es lo que hace que el mensaje vea el cambio COMPLETO aunque el diff se procese
# por partes: medido, el `--stat` de un diff de 164 585 chars son 2 987, o sea cabe donde el
# diff no cabe. Se calcula aquí y no se le pide al modelo porque es un conteo, no un juicio.
def test_the_inventory_counts_lines_per_file():
    diff = (
        "diff --git a/one.py b/one.py\n--- a/one.py\n+++ b/one.py\n"
        "@@ -1,2 +1,3 @@\n contexto\n-fuera\n+dentro\n+extra\n"
        "diff --git a/two.py b/two.py\n--- a/two.py\n+++ b/two.py\n"
        "@@ -1 +1 @@\n-vieja\n+nueva\n"
    )
    assert server._diff_inventory(diff) == [("one.py", 2, 1), ("two.py", 1, 1)]


def test_the_inventory_does_not_mistake_content_for_header():
    """Borrar una línea `---` da `----`, que empieza por `---` pero NO es cabecera.

    Distinguirlas por el texto haría que esa línea no se contara. Se distinguen por posición:
    solo son cabecera antes del primer `@@` del archivo.
    """
    diff = (
        "diff --git a/note.md b/note.md\ndeleted file mode 100644\n"
        "--- a/note.md\n+++ /dev/null\n@@ -1,2 +0,0 @@\n----\n-titulo\n"
    )
    assert server._diff_inventory(diff) == [("note.md", 0, 2)]


def test_the_inventory_follows_the_rename_and_records_the_binary():
    renamed = (
        "diff --git a/viejo.py b/new.py\nsimilarity index 90%\n"
        "rename from viejo.py\nrename to new.py\n"
        "--- a/viejo.py\n+++ b/new.py\n@@ -1,2 +1,2 @@\n igual\n-quitada\n+puesta\n"
    )
    binary = (
        "diff --git a/img.png b/img.png\nindex 111..222 100644\n"
        "Binary files a/img.png and b/img.png differ\n"
    )
    assert server._diff_inventory(renamed) == [("new.py", 1, 1)]
    # El binario no aporta líneas pero sí forma parte del cambio: tiene que salir en el alcance.
    assert server._diff_inventory(binary) == [("img.png", 0, 0)]


def test_a_text_that_is_not_a_diff_does_not_break_the_inventory():
    assert server._diff_inventory("texto normal\n- una lista\n+ otra cosa") == []
    assert server._diff_inventory("") == []


def test_the_inventory_collapses_by_directory_when_it_does_not_fit():
    """Sin tope, un diff de cientos de archivos desplazaría del prompt lo que hay que resumir."""
    files = [(f"src/mod{i}.py", 3, 1) for i in range(300)]
    complete = server._format_inventory(files, 40_000)
    collapsed = server._format_inventory(files, 4_000)

    assert "src/mod299.py" in complete
    assert len(collapsed) <= 4_000
    assert "300 archivos, +900 -300" in collapsed
    assert "300 en total" in collapsed  # el conteo real sobrevive al colapso


# --- test-windows-out-of-metrics (REQ-018): local_status sin pruebas -----------------------------
@backend_mock.mock
def test_local_status_leaves_out_tests_and_names_the_open_window(monkeypatch, tmp_path):
    from datetime import UTC, datetime, timedelta

    from local_delegate import test_windows

    now = datetime.now(UTC).replace(microsecond=0)
    log = tmp_path / f"usage-{now:%Y%m}.jsonl"
    rows = [
        {
            "ts": (now - timedelta(minutes=10 + i)).isoformat(),
            "tool": "local_summarize",
            "source": "path",
            "chars_in": 400,
            "ok": True,
            "client": "claude-code",
        }
        for i in range(4)
    ]
    in_window = now - timedelta(minutes=3)
    rows += [
        {
            "ts": in_window.isoformat(),
            "tool": "local_summarize",
            "source": "path",
            "chars_in": 400,
            "ok": True,
            "client": "claude-code",
        },
        {
            "ts": in_window.isoformat(),
            "tool": "local_extract",
            "source": "path",
            "chars_in": 400,
            "ok": True,
            "client": "claude-code",
        },
    ]
    log.write_text("".join(json.dumps(f) + "\n" for f in rows), encoding="utf-8")
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", True)
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get("http://test-backend/v1/models").mock(side_effect=httpx2.ConnectError("down"))
    backend_mock.get("http://test-backend/running").mock(side_effect=httpx2.ConnectError("down"))
    test_windows.add(tmp_path, in_window - timedelta(seconds=5), in_window)
    opened = test_windows.start(tmp_path, "en vivo")

    text = server.local_status()
    assert "eventos: 4 " in text
    assert "(2 de pruebas fuera)" in text
    assert f"Ventana de prueba abierta: {opened.id} desde" in text
