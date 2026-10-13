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

from local_delegate import failures, legacy_names
from local_delegate.failures import BackendResponse, FailureClass, classify


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
    assert classify(httpx2.ConnectTimeout("timed out")) is FailureClass.ENDPOINT


def test_read_timeout_no_es_del_endpoint():
    """Control positivo del anterior: mismo padre `TimeoutException`, destino distinto."""
    assert classify(httpx2.ReadTimeout("timed out")) is not FailureClass.ENDPOINT


def test_connect_error_sigue_siendo_del_endpoint():
    assert classify(httpx2.ConnectError("connection refused")) is FailureClass.ENDPOINT


@pytest.mark.parametrize("excepcion", [httpx2.WriteTimeout("x"), httpx2.PoolTimeout("x")])
def test_los_demas_timeouts_son_del_endpoint(excepcion):
    """No todo `TimeoutException` es un timeout de lectura: el modelo no llegó a responder."""
    assert classify(excepcion) is FailureClass.ENDPOINT


# --- Capacidad y timeout de lectura ---------------------------------------------------------


def test_read_timeout_sin_saber_si_estaba_cargado_es_capacidad():
    """El lado que no castiga a un modelo lento de montar, que es lo que pide REQ-F0-2."""
    assert classify(httpx2.ReadTimeout("timed out")) is FailureClass.CAPACITY


def test_read_timeout_con_el_modelo_cargado_es_timeout_de_lectura():
    """Control positivo: la MISMA excepción cambia de clase según la señal de carga."""
    assert classify(httpx2.ReadTimeout("timed out"), model_loaded=True) is FailureClass.READ_TIMEOUT


def test_un_5xx_con_patron_de_capacidad_no_es_del_modelo(monkeypatch):
    """El punto de extensión de REQ-020 funciona; hoy está vacío porque los patrones son de F3."""
    monkeypatch.setattr(failures, "CAPACITY_PATTERNS", ("failed to load model",))
    assert classify(BackendResponse(status=503, text="Failed to load model: out of memory")) is (
        FailureClass.CAPACITY
    )


def test_sin_patrones_un_5xx_es_del_modelo(monkeypatch):
    """Control positivo del anterior: sin patrones, el mismo cuerpo va a MODELO.

    La tupla ya no está vacía (los patrones reales llegaron con las capturas de F3), así que el test
    la vacía él mismo: lo que prueba es el punto de extensión, no el contenido de la tupla.
    """
    monkeypatch.setattr(failures, "CAPACITY_PATTERNS", ())
    assert classify(BackendResponse(status=503, text="Failed to load model: out of memory")) is (
        FailureClass.MODEL
    )


# --- Petición -------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413, 422, 499])
def test_los_4xx_son_de_la_peticion(status):
    """Incluye el desborde de contexto (400): cambiar de modelo no arregla ninguno."""
    assert classify(BackendResponse(status=status)) is FailureClass.REQUEST


def test_un_500_no_es_de_la_peticion():
    assert classify(BackendResponse(status=500)) is not FailureClass.REQUEST


def test_el_status_error_de_httpx_se_clasifica_por_su_codigo():
    error_404 = httpx2.HTTPStatusError(
        "not found", request=_respuesta_http(404).request, response=_respuesta_http(404)
    )
    error_503 = httpx2.HTTPStatusError(
        "unavailable", request=_respuesta_http(503).request, response=_respuesta_http(503)
    )
    assert classify(error_404) is FailureClass.REQUEST
    assert classify(error_503) is FailureClass.MODEL


# --- Configuración --------------------------------------------------------------------------


def test_length_con_razonamiento_es_de_configuracion():
    """El canary de julio: el modelo se gastó `max_tokens` pensando y no contestó."""
    cuerpo = _cuerpo(None, finish_reason="length", reasoning="pensando muy fuerte")
    assert classify(BackendResponse(status=200, data=cuerpo)) is FailureClass.CONFIGURATION


def test_length_sin_razonamiento_no_es_de_configuracion():
    """Control positivo: mismo síntoma, sin rastro de razonamiento, no se adivina la causa."""
    cuerpo = _cuerpo(None, finish_reason="length")
    assert classify(BackendResponse(status=200, data=cuerpo)) is FailureClass.UNCLASSIFIED


def test_length_con_razonamiento_en_blanco_tampoco_cuenta():
    cuerpo = _cuerpo(None, finish_reason="length", reasoning="   ")
    assert classify(BackendResponse(status=200, data=cuerpo)) is FailureClass.UNCLASSIFIED


def test_contenido_vacio_con_length_y_razonamiento_es_de_configuracion():
    """Lo que devuelve de verdad llama-server b10909 (captura del 2026-09-15): `content: ""`, no nulo.

    Con solo el nulo, la clase de configuración no saltaba nunca contra el backend real y el usuario
    recibía una respuesta vacía como si todo hubiera ido bien (decisión del usuario, opción A).
    """
    cuerpo = _cuerpo("", finish_reason="length", reasoning="pensando muy fuerte")
    assert classify(BackendResponse(status=200, data=cuerpo)) is FailureClass.CONFIGURATION


def test_contenido_vacio_con_length_sin_razonamiento_no_es_un_fallo():
    """Control positivo: sin rastro de razonamiento, la cadena vacía sigue tratándose como hoy."""
    cuerpo = _cuerpo("", finish_reason="length")
    assert classify(BackendResponse(status=200, data=cuerpo)) is None


def test_contenido_vacio_con_razonamiento_que_termino_bien_no_es_un_fallo():
    """Control positivo: si no se agotó `max_tokens`, un razonamiento no convierte el vacío en fallo."""
    cuerpo = _cuerpo("", finish_reason="stop", reasoning="pensé y no hacía falta decir nada")
    assert classify(BackendResponse(status=200, data=cuerpo)) is None


# --- Modelo ---------------------------------------------------------------------------------


def test_content_nulo_por_otro_motivo_es_del_modelo():
    """El defecto verificado: hoy esto revienta con `AttributeError` fuera de `_post_chat`."""
    assert classify(BackendResponse(status=200, data=_cuerpo(None))) is FailureClass.MODEL


def test_content_ausente_es_del_modelo():
    assert classify(BackendResponse(status=200, data=_cuerpo(...))) is FailureClass.MODEL


@pytest.mark.parametrize(
    "datos",
    [{}, {"choices": []}, {"choices": [{}]}, {"choices": ["texto suelto"]}],
    ids=["sin choices", "choices vacio", "sin message", "choice que no es dict"],
)
def test_una_respuesta_rota_es_del_modelo(datos):
    assert classify(BackendResponse(status=200, data=datos)) is FailureClass.MODEL


def test_un_200_que_no_era_json_es_del_modelo():
    assert (
        classify(BackendResponse(status=200, data=None, text="<html>502</html>"))
        is FailureClass.MODEL
    )


# --- Lo que NO es un fallo ------------------------------------------------------------------


def test_una_respuesta_buena_no_es_ningun_fallo():
    assert classify(BackendResponse(status=200, data=_cuerpo("la respuesta"))) is None


def test_el_content_vacio_no_es_un_fallo():
    """Se trata como hoy. Control positivo del `content` nulo, que sí lo es."""
    assert classify(BackendResponse(status=200, data=_cuerpo(""))) is None
    assert classify(BackendResponse(status=200, data=_cuerpo(None))) is not None


# --- Sin clasificar -------------------------------------------------------------------------


def test_una_excepcion_ajena_no_se_achaca_al_modelo():
    """La regla de la casa: lo desconocido nunca va a MODELO, que es la clase cara."""
    assert classify(ValueError("vete a saber")) is FailureClass.UNCLASSIFIED


def test_un_status_raro_no_se_achaca_al_modelo():
    """Un 3xx no es una respuesta de chat, pero tampoco es culpa del modelo.

    La segunda mitad ejercita la rama defensiva de `_classify_status`: `raise_for_status` nunca
    fabrica un `HTTPStatusError` con un 3xx, pero nada impide construirlo a mano, y una rama sin
    prueba es la que se pudre.
    """
    assert classify(BackendResponse(status=302)) is FailureClass.UNCLASSIFIED
    error_302 = httpx2.HTTPStatusError(
        "redirect", request=_respuesta_http(302).request, response=_respuesta_http(302)
    )
    assert classify(error_302) is FailureClass.UNCLASSIFIED


# --- Arrancar o no arrancar el backend ------------------------------------------------------


@pytest.mark.parametrize(
    "excepcion",
    [httpx2.ConnectError("refused"), httpx2.ConnectTimeout("timed out")],
    ids=["ConnectError", "ConnectTimeout"],
)
def test_nadie_escuchando_habilita_el_autoarranque(excepcion):
    """REQ-F0-6: el segundo caso es el defecto verificado, hoy no ofrece arrancar nada."""
    assert failures.is_backend_missing(excepcion) is True


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
    assert failures.is_backend_missing(excepcion) is False


def test_una_respuesta_nunca_habilita_el_autoarranque():
    assert failures.is_backend_missing(BackendResponse(status=503)) is False


# --- Valores viejos (REQ-006) -------------------------------------------------------------------


@pytest.mark.parametrize("viejo,nuevo", sorted(legacy_names.FAILURE_CLASS_VALUES.items()))
def test_el_valor_viejo_de_la_clase_se_lee_como_el_nuevo(viejo, nuevo):
    """El log de uso y los eventos de enfriamiento ya escritos traen la clase en español."""
    if nuevo == "cooldown":
        # No es un miembro: es la clase que el daemon escribe en `fallback_class` al saltar por un
        # modelo enfriado. Solo se traduce el valor.
        assert legacy_names.new_value(legacy_names.FAILURE_CLASS_VALUES, viejo) == "cooldown"
        return
    assert FailureClass(viejo) is FailureClass(nuevo)


def test_los_valores_que_se_escriben_son_los_nuevos():
    escritos = {c.value for c in FailureClass}
    assert escritos == {
        "endpoint",
        "request",
        "capacity_or_load",
        "read_timeout",
        "configuration",
        "model",
        "unclassified",
    }
    assert not escritos & set(legacy_names.FAILURE_CLASS_VALUES), (
        "un valor viejo sigue escribiéndose"
    )
