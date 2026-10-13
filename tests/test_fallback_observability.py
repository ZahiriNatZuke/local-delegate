"""Tarea 29 de F3: lo que el salto deja en el log y en `local_status` (REQ-013, REQ-019).

Los campos del log son ADITIVOS: un evento sin salto se escribe exactamente como antes, y `model`
sigue siendo el modelo que respondió, para que el histórico se lea igual. Los tests de la cuenta y
del panel están en `test_metrics.py`, junto a la paridad con el JavaScript.
"""

from __future__ import annotations

import json
import time

import backend_mock
import httpx2
import pytest
from test_fallback import (
    CODE,
    LONG,
    MECHANICAL,
    _backend,
    _cool_down,
    _failure,
    _last_event,
    _ok,
    _state_file,
    _text,
)

from local_delegate import cooldown, server
from local_delegate.failures import FailureClass

NEW_FIELDS = ("model_requested", "fallback_reason", "fallback_class", "error_class")


# --- El log ------------------------------------------------------------------------------------


@backend_mock.mock
def test_the_log_records_requested_answered_and_the_fallback_cause(reload_config, tmp_path):
    reload_config()
    _backend({LONG: _failure(500), CODE: _ok("resumen")})

    server.local_summarize(text=_text(10_000))

    event = _last_event(tmp_path)
    assert event["model"] == CODE, "`model` es el que respondió"
    assert event["model_requested"] == LONG
    assert event["fallback_reason"] == "http_500"
    assert event["fallback_class"] == "model"
    assert event["chunks"] == 2, "la llamada del respaldo también cuenta"
    assert "error_class" not in event


@backend_mock.mock
def test_in_chunks_chunks_also_counts_the_fallback_calls(reload_config, tmp_path):
    reload_config()
    _backend({LONG: [_ok("uno"), _failure(500)], CODE: _ok("otro")})

    server.local_translate(target_lang="inglés", text=_text(12_000))

    event = _last_event(tmp_path)
    assert event["chunks"] == 5  # largo, largo que falla, y tres del respaldo (el de código)
    assert event["model"] == CODE
    assert event["model_requested"] == LONG


@backend_mock.mock
def test_without_fallback_the_event_is_written_as_before(reload_config, tmp_path):
    reload_config()
    _backend({MECHANICAL: _ok("a")})

    server.local_classify(text="hola", labels=["a", "b"])

    event = _last_event(tmp_path)
    assert event["model"] == MECHANICAL
    assert not any(field in event for field in (*NEW_FIELDS, "chunks"))


@backend_mock.mock
def test_exhausted_reasoning_stays_as_a_configuration_cause(reload_config, tmp_path):
    reload_config()
    exhausted = httpx2.Response(
        200,
        json={
            "choices": [
                {"message": {"content": "", "reasoning_content": "x"}, "finish_reason": "length"}
            ]
        },
    )
    _backend({MECHANICAL: exhausted})

    server.local_classify(text="hola", labels=["a", "b"])

    event = _last_event(tmp_path)
    assert event["error_class"] == "configuration"
    assert event["error"] == "config_max_tokens"
    assert "model_requested" not in event


@backend_mock.mock
def test_the_fallback_due_to_cooldown_is_recorded_with_its_cause(reload_config, tmp_path):
    reload_config()
    _cool_down(tmp_path, CODE)
    _backend({LONG: _ok("explicado")})

    server.local_explain_code(code="x = 1")

    event = _last_event(tmp_path)
    assert event["model"] == LONG
    assert event["model_requested"] == CODE
    assert event["fallback_class"] == "cooldown"
    assert "chunks" not in event, "el modelo enfriado no se llamó: una sola llamada"


@backend_mock.mock
def test_in_map_reduce_the_fallback_also_stays_in_the_log(reload_config, tmp_path):
    reload_config()
    _backend({CODE: _failure(500), LONG: _ok("- a: cambia")})
    diff = "".join(
        f"diff --git a/f{i}.py b/f{i}.py\n" + "+linea de codigo nueva\n" * 200 for i in range(6)
    )

    server.local_commit_msg(diff=diff)

    event = _last_event(tmp_path)
    assert event["model"] == LONG and event["model_requested"] == CODE
    assert event["fallback_class"] == "model"


# --- local_status ------------------------------------------------------------------------------


@pytest.fixture
def status_offline(monkeypatch):
    """`local_status` consulta backend, GPU y llama-swap: aquí solo interesa lo que dice del estado."""
    # `local_status` sondea con `probe_backend` y solo pide `/running` si el backend respondió
    # (REQ-013), así que con este doble no hace falta doblar `_llamaswap_running`.
    monkeypatch.setattr(
        server,
        "probe_backend",
        lambda: server.BackendState(False, [], True, "refused", "sin red en los tests", None),
    )
    for name in ("_vram_info", "_ram_info", "_llamaswap_groups"):
        monkeypatch.setattr(server, name, lambda: None)
    monkeypatch.setattr(server, "_port_listening", lambda *_: False)


def _line_of(text: str, model: str) -> str:
    lines = [line for line in text.splitlines() if model in line and "quedan" in line]
    assert len(lines) == 1, text
    return lines[0]


def test_local_status_lists_the_cooled_model_with_its_remaining_time(
    reload_config, tmp_path, status_offline
):
    reload_config()
    state = cooldown.from_config()
    for _ in range(3):
        state.record_failure(CODE, FailureClass.MODEL)

    line = _line_of(server.local_status(), CODE)

    assert "1 vez seguida" in line
    remaining = int(line.split("quedan ")[1].split(" s")[0])
    assert 100 <= remaining <= 120


def test_local_status_counts_the_consecutive_reentries(reload_config, tmp_path, status_offline):
    reload_config()
    expired = {CODE: {"fallos": 0, "espera_s": 120.0, "hasta": time.time() - 1, "reentradas": 1}}
    _state_file(tmp_path).write_text(json.dumps(expired), encoding="utf-8")
    cooldown.from_config().record_failure(CODE, FailureClass.MODEL)

    line = _line_of(server.local_status(), CODE)

    assert "2 veces seguidas" in line
    assert int(line.split("quedan ")[1].split(" s")[0]) > 120, "la espera se dobló"


def test_local_status_without_cooled_models_says_so(reload_config, tmp_path, status_offline):
    reload_config()

    text = server.local_status()

    assert "Enfriamiento: encendido" in text
    assert "ningún modelo enfriado" in text


def test_local_status_with_the_cooldown_off_says_so(reload_config, tmp_path, status_offline):
    reload_config(LOCAL_DELEGATE_COOLDOWN="0")
    _cool_down(tmp_path, CODE)

    text = server.local_status()

    assert "Enfriamiento: apagado" in text
    assert "quedan" not in text
