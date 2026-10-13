"""La señal «el modelo se estaba montando» de REQ-018, tomada AL VENCER el plazo y no después.

Por qué importa el momento (hallazgo de la revisión del plan de F3): si se consulta `/running`
después del `ReadTimeout`, se ve el estado de después. Una carga que termina en ese hueco sale
`ready` y el fallo se cuenta como timeout de lectura, justo lo que D-2 prohíbe para un modelo lento
de montar. Por eso un temporizador muestrea justo antes de vencer y el `ReadTimeout` usa esa muestra.

Estados reales de llama-swap v255 (capturados el 2026-09-15, `tests/fixtures/backend/`): `starting`
mientras carga y `ready` cuando ya responde.
"""

from __future__ import annotations

import threading
import time

import backend_mock
import httpx2
import pytest

from local_delegate import config, failures, server

URL_CHAT = "http://test-backend/v1/chat/completions"
URL_RUNNING = "http://test-backend/running"


def _running(model: str, state: str) -> httpx2.Response:
    return httpx2.Response(200, json={"running": [{"model": model, "state": state}]})


# --- La sonda, sin red ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "expected"), [("ready", True), ("starting", False), ("stopping", None), (None, None)]
)
def test_the_sample_translates_to_model_loaded(state, expected):
    probe = server._LoadProbe("m", delay_s=0.0, query=lambda _model: state)
    probe.start()
    # En produccion el timeout llega ~3 s despues de la muestra; aqui se espera a que la muestra
    # exista, porque pedirla antes de que el temporizador corra da «no se sabe», con razon.
    time.sleep(0.1)
    assert probe.model_loaded(wait_s=1.0) is expected


def test_the_sample_taken_at_expiry_wins_even_if_it_changes_later():
    """La carrera: se muestreó `starting`, y cuando llega el timeout ya diría `ready`."""
    states = iter(["starting", "ready", "ready"])
    calls: list[str] = []

    def query(model: str) -> str:
        calls.append(model)
        return next(states)

    probe = server._LoadProbe("m", delay_s=0.0, query=query)
    probe.start()
    time.sleep(0.1)  # la carga «termina» después de la muestra
    assert probe.model_loaded(wait_s=1.0) is False
    assert calls == ["m"], "se volvió a consultar después del timeout"


def test_if_the_timer_did_not_fire_it_is_unknown_and_not_queried():
    calls: list[str] = []
    probe = server._LoadProbe("m", delay_s=60.0, query=lambda m: calls.append(m))
    probe.start()
    assert probe.model_loaded(wait_s=0.1) is None
    time.sleep(0.05)
    assert calls == []


def test_a_slow_query_holds_no_longer_than_its_cap():
    release = threading.Event()

    def query(_model: str) -> str:
        release.wait(5.0)
        return "ready"

    probe = server._LoadProbe("m", delay_s=0.0, query=query)
    probe.start()
    time.sleep(0.05)
    t0 = time.monotonic()
    assert probe.model_loaded(wait_s=0.2) is None
    assert time.monotonic() - t0 < 1.0
    release.set()


def test_cancel_avoids_the_query():
    calls: list[str] = []
    probe = server._LoadProbe("m", delay_s=0.2, query=lambda m: calls.append(m))
    probe.start()
    probe.cancel()
    time.sleep(0.4)
    assert calls == []


# --- La consulta a llama-swap ---------------------------------------------------------------


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "AUTOSTART", False)


@backend_mock.mock
def test_state_in_llamaswap_reads_the_model_state(backend):
    backend_mock.get(URL_RUNNING).mock(return_value=_running("m", "starting"))
    assert server._llamaswap_state("m") == "starting"


@backend_mock.mock
def test_another_models_state_does_not_count(backend):
    backend_mock.get(URL_RUNNING).mock(return_value=_running("otro", "ready"))
    assert server._llamaswap_state("m") is None


@backend_mock.mock
@pytest.mark.parametrize(
    "effect", [httpx2.Response(404, text="not found"), httpx2.ConnectError("sin llama-swap")]
)
def test_without_llamaswap_there_is_no_signal(backend, effect):
    """Ollama, LM Studio o un llama-swap caído: `None`, que el clasificador lee como carga."""
    path = backend_mock.get(URL_RUNNING)
    if isinstance(effect, BaseException):
        path.mock(side_effect=effect)
    else:
        path.mock(return_value=effect)
    assert server._llamaswap_state("m") is None


# --- En `_post_chat` ------------------------------------------------------------------------


def _timeout_after(seconds: float):
    def effect(_request):
        time.sleep(seconds)
        raise httpx2.ReadTimeout("timed out")

    return effect


@backend_mock.mock
@pytest.mark.parametrize(
    ("state", "error_class"),
    [("ready", failures.FailureClass.READ_TIMEOUT), ("starting", failures.FailureClass.CAPACITY)],
)
def test_post_chat_classifies_the_timeout_with_the_sample(backend, monkeypatch, state, error_class):
    """La pieza en su uso: el `ReadTimeout` real de `_post_chat` lleva la señal de la sonda."""
    monkeypatch.setattr(server, "_probe_delay", lambda: 0.0)
    backend_mock.get(URL_RUNNING).mock(return_value=_running("m", state))
    backend_mock.post(URL_CHAT).mock(side_effect=_timeout_after(0.3))
    result = server._post_chat("m", {"model": "m"})
    assert result.ok is False
    assert result.error_class == error_class


@backend_mock.mock
def test_the_happy_path_does_not_query_running(backend, monkeypatch):
    """Sin timeout no se paga nada: el temporizador se cancela antes de disparar.

    El retraso es corto A PROPÓSITO y se espera después: con uno largo, un temporizador que nadie
    cancelara tampoco dispararía durante el test, y el test pasaría con el defecto vivo.
    """
    monkeypatch.setattr(server, "_probe_delay", lambda: 0.2)
    running = backend_mock.get(URL_RUNNING).mock(return_value=_running("m", "ready"))
    backend_mock.post(URL_CHAT).mock(
        return_value=httpx2.Response(200, json={"choices": [{"message": {"content": "hola"}}]})
    )
    result = server._post_chat("m", {"model": "m"})
    time.sleep(0.5)
    assert result.ok is True
    assert running.call_count == 0
