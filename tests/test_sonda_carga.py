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

from local_delegate import config, fallos, server

URL_CHAT = "http://test-backend/v1/chat/completions"
URL_RUNNING = "http://test-backend/running"


def _running(modelo: str, estado: str) -> httpx2.Response:
    return httpx2.Response(200, json={"running": [{"model": modelo, "state": estado}]})


# --- La sonda, sin red ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("estado", "esperado"), [("ready", True), ("starting", False), ("stopping", None), (None, None)]
)
def test_la_muestra_se_traduce_a_modelo_cargado(estado, esperado):
    sonda = server._SondaDeCarga("m", retraso_s=0.0, consultar=lambda _modelo: estado)
    sonda.iniciar()
    # En produccion el timeout llega ~3 s despues de la muestra; aqui se espera a que la muestra
    # exista, porque pedirla antes de que el temporizador corra da «no se sabe», con razon.
    time.sleep(0.1)
    assert sonda.modelo_cargado(espera_s=1.0) is esperado


def test_gana_la_muestra_tomada_al_vencer_aunque_despues_cambie():
    """La carrera: se muestreó `starting`, y cuando llega el timeout ya diría `ready`."""
    estados = iter(["starting", "ready", "ready"])
    llamadas: list[str] = []

    def consultar(modelo: str) -> str:
        llamadas.append(modelo)
        return next(estados)

    sonda = server._SondaDeCarga("m", retraso_s=0.0, consultar=consultar)
    sonda.iniciar()
    time.sleep(0.1)  # la carga «termina» después de la muestra
    assert sonda.modelo_cargado(espera_s=1.0) is False
    assert llamadas == ["m"], "se volvió a consultar después del timeout"


def test_si_el_temporizador_no_llego_a_disparar_no_se_sabe_y_no_se_consulta():
    llamadas: list[str] = []
    sonda = server._SondaDeCarga("m", retraso_s=60.0, consultar=lambda m: llamadas.append(m))
    sonda.iniciar()
    assert sonda.modelo_cargado(espera_s=0.1) is None
    time.sleep(0.05)
    assert llamadas == []


def test_una_consulta_lenta_no_retiene_mas_que_su_tope():
    liberar = threading.Event()

    def consultar(_modelo: str) -> str:
        liberar.wait(5.0)
        return "ready"

    sonda = server._SondaDeCarga("m", retraso_s=0.0, consultar=consultar)
    sonda.iniciar()
    time.sleep(0.05)
    t0 = time.monotonic()
    assert sonda.modelo_cargado(espera_s=0.2) is None
    assert time.monotonic() - t0 < 1.0
    liberar.set()


def test_cancelar_evita_la_consulta():
    llamadas: list[str] = []
    sonda = server._SondaDeCarga("m", retraso_s=0.2, consultar=lambda m: llamadas.append(m))
    sonda.iniciar()
    sonda.cancelar()
    time.sleep(0.4)
    assert llamadas == []


# --- La consulta a llama-swap ---------------------------------------------------------------


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "AUTOSTART", False)


@backend_mock.mock
def test_estado_en_llamaswap_lee_el_estado_del_modelo(backend):
    backend_mock.get(URL_RUNNING).mock(return_value=_running("m", "starting"))
    assert server._estado_en_llamaswap("m") == "starting"


@backend_mock.mock
def test_estado_de_otro_modelo_no_cuenta(backend):
    backend_mock.get(URL_RUNNING).mock(return_value=_running("otro", "ready"))
    assert server._estado_en_llamaswap("m") is None


@backend_mock.mock
@pytest.mark.parametrize(
    "efecto", [httpx2.Response(404, text="not found"), httpx2.ConnectError("sin llama-swap")]
)
def test_sin_llamaswap_no_hay_senal(backend, efecto):
    """Ollama, LM Studio o un llama-swap caído: `None`, que el clasificador lee como carga."""
    ruta = backend_mock.get(URL_RUNNING)
    if isinstance(efecto, BaseException):
        ruta.mock(side_effect=efecto)
    else:
        ruta.mock(return_value=efecto)
    assert server._estado_en_llamaswap("m") is None


# --- En `_post_chat` ------------------------------------------------------------------------


def _timeout_tras(segundos: float):
    def efecto(_request):
        time.sleep(segundos)
        raise httpx2.ReadTimeout("timed out")

    return efecto


@backend_mock.mock
@pytest.mark.parametrize(
    ("estado", "clase"),
    [("ready", fallos.Clase.TIMEOUT_LECTURA), ("starting", fallos.Clase.CAPACIDAD)],
)
def test_post_chat_clasifica_el_timeout_con_la_muestra(backend, monkeypatch, estado, clase):
    """La pieza en su uso: el `ReadTimeout` real de `_post_chat` lleva la señal de la sonda."""
    monkeypatch.setattr(server, "_retraso_sonda", lambda: 0.0)
    backend_mock.get(URL_RUNNING).mock(return_value=_running("m", estado))
    backend_mock.post(URL_CHAT).mock(side_effect=_timeout_tras(0.3))
    resultado = server._post_chat("m", {"model": "m"})
    assert resultado.ok is False
    assert resultado.clase == clase


@backend_mock.mock
def test_el_camino_feliz_no_consulta_running(backend, monkeypatch):
    """Sin timeout no se paga nada: el temporizador se cancela antes de disparar.

    El retraso es corto A PROPÓSITO y se espera después: con uno largo, un temporizador que nadie
    cancelara tampoco dispararía durante el test, y el test pasaría con el defecto vivo.
    """
    monkeypatch.setattr(server, "_retraso_sonda", lambda: 0.2)
    running = backend_mock.get(URL_RUNNING).mock(return_value=_running("m", "ready"))
    backend_mock.post(URL_CHAT).mock(
        return_value=httpx2.Response(200, json={"choices": [{"message": {"content": "hola"}}]})
    )
    resultado = server._post_chat("m", {"model": "m"})
    time.sleep(0.5)
    assert resultado.ok is True
    assert running.call_count == 0
