"""Clasificación de fallos del backend, con control positivo en cada clase.

Cada clase se prueba con **dos** casos: uno que la produce y otro parecido que no. Sin el segundo,
un test puede pasar por la guarda equivocada y nadie se entera —ya ha pasado cuatro sesiones
seguidas en este repo—. Los pares son deliberados: `ConnectTimeout` contra `ReadTimeout` (hermanos
de `TimeoutException`, destinos distintos), `ReadTimeout` cargando contra ya cargado (misma
excepción, clase distinta), y `length` con razonamiento contra `length` sin él.
"""

from __future__ import annotations

import httpx2
import pytest

from local_delegate import fallos
from local_delegate.fallos import Clase, Respuesta, clasificar


def _respuesta_http(status: int, texto: str = "") -> httpx2.Response:
    return httpx2.Response(
        status_code=status,
        text=texto,
        request=httpx2.Request("POST", "http://127.0.0.1:9292/v1/chat/completions"),
    )


def _cuerpo(content, *, finish_reason: str | None = "stop", reasoning: str | None = None) -> dict:
    mensaje: dict = {"role": "assistant"}
    if content is not ...:
        mensaje["content"] = content
    if reasoning is not None:
        mensaje["reasoning_content"] = reasoning
    return {"choices": [{"message": mensaje, "finish_reason": finish_reason}]}


# --- Endpoint -------------------------------------------------------------------------------


def test_connect_timeout_es_del_endpoint():
    """El defecto verificado: hoy cae en `http_error` y por eso no ofrece arrancar el backend."""
    assert clasificar(httpx2.ConnectTimeout("timed out")) is Clase.ENDPOINT


def test_read_timeout_no_es_del_endpoint():
    """Control positivo del anterior: mismo padre `TimeoutException`, destino distinto."""
    assert clasificar(httpx2.ReadTimeout("timed out")) is not Clase.ENDPOINT


def test_connect_error_sigue_siendo_del_endpoint():
    assert clasificar(httpx2.ConnectError("connection refused")) is Clase.ENDPOINT


@pytest.mark.parametrize("excepcion", [httpx2.WriteTimeout("x"), httpx2.PoolTimeout("x")])
def test_los_demas_timeouts_son_del_endpoint(excepcion):
    """No todo `TimeoutException` es un timeout de lectura: el modelo no llegó a responder."""
    assert clasificar(excepcion) is Clase.ENDPOINT


# --- Capacidad y timeout de lectura ---------------------------------------------------------


def test_read_timeout_sin_saber_si_estaba_cargado_es_capacidad():
    """El lado que no castiga a un modelo lento de montar, que es lo que pide REQ-F0-2."""
    assert clasificar(httpx2.ReadTimeout("timed out")) is Clase.CAPACIDAD


def test_read_timeout_con_el_modelo_cargado_es_timeout_de_lectura():
    """Control positivo: la MISMA excepción cambia de clase según la señal de carga."""
    assert clasificar(httpx2.ReadTimeout("timed out"), modelo_cargado=True) is Clase.TIMEOUT_LECTURA


def test_un_5xx_con_patron_de_capacidad_no_es_del_modelo(monkeypatch):
    """El punto de extensión de REQ-020 funciona; hoy está vacío porque los patrones son de F3."""
    monkeypatch.setattr(fallos, "PATRONES_DE_CAPACIDAD", ("failed to load model",))
    assert clasificar(Respuesta(status=503, texto="Failed to load model: out of memory")) is (
        Clase.CAPACIDAD
    )


def test_sin_patrones_un_5xx_es_del_modelo():
    """Control positivo del anterior: con la tupla vacía de hoy, el mismo cuerpo va a MODELO."""
    assert fallos.PATRONES_DE_CAPACIDAD == ()
    assert clasificar(Respuesta(status=503, texto="Failed to load model: out of memory")) is (
        Clase.MODELO
    )


# --- Petición -------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413, 422, 499])
def test_los_4xx_son_de_la_peticion(status):
    """Incluye el desborde de contexto (400): cambiar de modelo no arregla ninguno."""
    assert clasificar(Respuesta(status=status)) is Clase.PETICION


def test_un_500_no_es_de_la_peticion():
    assert clasificar(Respuesta(status=500)) is not Clase.PETICION


def test_el_status_error_de_httpx_se_clasifica_por_su_codigo():
    error_404 = httpx2.HTTPStatusError(
        "not found", request=_respuesta_http(404).request, response=_respuesta_http(404)
    )
    error_503 = httpx2.HTTPStatusError(
        "unavailable", request=_respuesta_http(503).request, response=_respuesta_http(503)
    )
    assert clasificar(error_404) is Clase.PETICION
    assert clasificar(error_503) is Clase.MODELO


# --- Configuración --------------------------------------------------------------------------


def test_length_con_razonamiento_es_de_configuracion():
    """El canary de julio: el modelo se gastó `max_tokens` pensando y no contestó."""
    cuerpo = _cuerpo(None, finish_reason="length", reasoning="pensando muy fuerte")
    assert clasificar(Respuesta(status=200, datos=cuerpo)) is Clase.CONFIGURACION


def test_length_sin_razonamiento_no_es_de_configuracion():
    """Control positivo: mismo síntoma, sin rastro de razonamiento, no se adivina la causa."""
    cuerpo = _cuerpo(None, finish_reason="length")
    assert clasificar(Respuesta(status=200, datos=cuerpo)) is Clase.SIN_CLASIFICAR


def test_length_con_razonamiento_en_blanco_tampoco_cuenta():
    cuerpo = _cuerpo(None, finish_reason="length", reasoning="   ")
    assert clasificar(Respuesta(status=200, datos=cuerpo)) is Clase.SIN_CLASIFICAR


# --- Modelo ---------------------------------------------------------------------------------


def test_content_nulo_por_otro_motivo_es_del_modelo():
    """El defecto verificado: hoy esto revienta con `AttributeError` fuera de `_post_chat`."""
    assert clasificar(Respuesta(status=200, datos=_cuerpo(None))) is Clase.MODELO


def test_content_ausente_es_del_modelo():
    assert clasificar(Respuesta(status=200, datos=_cuerpo(...))) is Clase.MODELO


@pytest.mark.parametrize(
    "datos",
    [{}, {"choices": []}, {"choices": [{}]}, {"choices": ["texto suelto"]}],
    ids=["sin choices", "choices vacio", "sin message", "choice que no es dict"],
)
def test_una_respuesta_rota_es_del_modelo(datos):
    assert clasificar(Respuesta(status=200, datos=datos)) is Clase.MODELO


def test_un_200_que_no_era_json_es_del_modelo():
    assert clasificar(Respuesta(status=200, datos=None, texto="<html>502</html>")) is Clase.MODELO


# --- Lo que NO es un fallo ------------------------------------------------------------------


def test_una_respuesta_buena_no_es_ningun_fallo():
    assert clasificar(Respuesta(status=200, datos=_cuerpo("la respuesta"))) is None


def test_el_content_vacio_no_es_un_fallo():
    """Se trata como hoy. Control positivo del `content` nulo, que sí lo es."""
    assert clasificar(Respuesta(status=200, datos=_cuerpo(""))) is None
    assert clasificar(Respuesta(status=200, datos=_cuerpo(None))) is not None


# --- Sin clasificar -------------------------------------------------------------------------


def test_una_excepcion_ajena_no_se_achaca_al_modelo():
    """La regla de la casa: lo desconocido nunca va a MODELO, que es la clase cara."""
    assert clasificar(ValueError("vete a saber")) is Clase.SIN_CLASIFICAR


def test_un_status_raro_no_se_achaca_al_modelo():
    """Un 3xx no es una respuesta de chat, pero tampoco es culpa del modelo.

    La segunda mitad ejercita la rama defensiva de `_clasificar_status`: `raise_for_status` nunca
    fabrica un `HTTPStatusError` con un 3xx, pero nada impide construirlo a mano, y una rama sin
    prueba es la que se pudre.
    """
    assert clasificar(Respuesta(status=302)) is Clase.SIN_CLASIFICAR
    error_302 = httpx2.HTTPStatusError(
        "redirect", request=_respuesta_http(302).request, response=_respuesta_http(302)
    )
    assert clasificar(error_302) is Clase.SIN_CLASIFICAR


# --- Arrancar o no arrancar el backend ------------------------------------------------------


@pytest.mark.parametrize(
    "excepcion",
    [httpx2.ConnectError("refused"), httpx2.ConnectTimeout("timed out")],
    ids=["ConnectError", "ConnectTimeout"],
)
def test_nadie_escuchando_habilita_el_autoarranque(excepcion):
    """REQ-F0-6: el segundo caso es el defecto verificado, hoy no ofrece arrancar nada."""
    assert fallos.es_backend_ausente(excepcion) is True


@pytest.mark.parametrize(
    "excepcion",
    [
        httpx2.WriteTimeout("timed out"),
        httpx2.PoolTimeout("timed out"),
        httpx2.ReadTimeout("timed out"),
        httpx2.RemoteProtocolError("boom"),
    ],
    ids=["WriteTimeout", "PoolTimeout", "ReadTimeout", "RemoteProtocolError"],
)
def test_los_demas_fallos_de_transporte_no_lo_habilitan(excepcion):
    """Control positivo: tres de estos cuatro también son ENDPOINT, y aun así no se arranca nada.

    Por eso la decisión no puede salir de la clase: arrancar otro backend no arregla un fallo que
    ocurrió con la conexión ya establecida.
    """
    assert fallos.es_backend_ausente(excepcion) is False


def test_una_respuesta_nunca_habilita_el_autoarranque():
    assert fallos.es_backend_ausente(Respuesta(status=503)) is False
