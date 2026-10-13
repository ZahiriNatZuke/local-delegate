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


def _http_response(status: int, text: str = "") -> httpx2.Response:
    return httpx2.Response(
        status_code=status,
        text=text,
        request=httpx2.Request("POST", "http://127.0.0.1:9292/v1/chat/completions"),
    )


def _body(content, *, finish_reason: str | None = "stop", reasoning: str | None = None) -> dict:
    message: dict = {"role": "assistant"}
    if content is not ...:
        message["content"] = content
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return {"choices": [{"message": message, "finish_reason": finish_reason}]}


# --- Endpoint -------------------------------------------------------------------------------


def test_connect_timeout_is_the_endpoints():
    """El defecto verificado: hoy cae en `http_error` y por eso no ofrece arrancar el backend."""
    assert classify(httpx2.ConnectTimeout("timed out")) is FailureClass.ENDPOINT


def test_read_timeout_is_not_the_endpoints():
    """Control positivo del anterior: mismo padre `TimeoutException`, destino distinto."""
    assert classify(httpx2.ReadTimeout("timed out")) is not FailureClass.ENDPOINT


def test_connect_error_is_still_the_endpoints():
    assert classify(httpx2.ConnectError("connection refused")) is FailureClass.ENDPOINT


@pytest.mark.parametrize("exception", [httpx2.WriteTimeout("x"), httpx2.PoolTimeout("x")])
def test_the_other_timeouts_are_the_endpoints(exception):
    """No todo `TimeoutException` es un timeout de lectura: el modelo no llegó a responder."""
    assert classify(exception) is FailureClass.ENDPOINT


# --- Capacidad y timeout de lectura ---------------------------------------------------------


def test_read_timeout_without_knowing_if_it_was_loaded_is_capacity():
    """El lado que no castiga a un modelo lento de montar, que es lo que pide REQ-F0-2."""
    assert classify(httpx2.ReadTimeout("timed out")) is FailureClass.CAPACITY


def test_read_timeout_with_the_model_loaded_is_a_read_timeout():
    """Control positivo: la MISMA excepción cambia de clase según la señal de carga."""
    assert classify(httpx2.ReadTimeout("timed out"), model_loaded=True) is FailureClass.READ_TIMEOUT


def test_a_5xx_with_a_capacity_pattern_is_not_the_models(monkeypatch):
    """El punto de extensión de REQ-020 funciona; hoy está vacío porque los patrones son de F3."""
    monkeypatch.setattr(failures, "CAPACITY_PATTERNS", ("failed to load model",))
    assert classify(BackendResponse(status=503, text="Failed to load model: out of memory")) is (
        FailureClass.CAPACITY
    )


def test_without_patterns_a_5xx_is_the_models(monkeypatch):
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
def test_4xx_are_the_requests(status):
    """Incluye el desborde de contexto (400): cambiar de modelo no arregla ninguno."""
    assert classify(BackendResponse(status=status)) is FailureClass.REQUEST


def test_a_500_is_not_the_requests():
    assert classify(BackendResponse(status=500)) is not FailureClass.REQUEST


def test_the_httpx_status_error_is_classified_by_its_code():
    error_404 = httpx2.HTTPStatusError(
        "not found", request=_http_response(404).request, response=_http_response(404)
    )
    error_503 = httpx2.HTTPStatusError(
        "unavailable", request=_http_response(503).request, response=_http_response(503)
    )
    assert classify(error_404) is FailureClass.REQUEST
    assert classify(error_503) is FailureClass.MODEL


# --- Configuración --------------------------------------------------------------------------


def test_length_with_reasoning_is_configuration():
    """El canary de julio: el modelo se gastó `max_tokens` pensando y no contestó."""
    body = _body(None, finish_reason="length", reasoning="pensando muy fuerte")
    assert classify(BackendResponse(status=200, data=body)) is FailureClass.CONFIGURATION


def test_length_without_reasoning_is_not_configuration():
    """Control positivo: mismo síntoma, sin rastro de razonamiento, no se adivina la causa."""
    body = _body(None, finish_reason="length")
    assert classify(BackendResponse(status=200, data=body)) is FailureClass.UNCLASSIFIED


def test_length_with_blank_reasoning_does_not_count_either():
    body = _body(None, finish_reason="length", reasoning="   ")
    assert classify(BackendResponse(status=200, data=body)) is FailureClass.UNCLASSIFIED


def test_empty_content_with_length_and_reasoning_is_configuration():
    """Lo que devuelve de verdad llama-server b10909 (captura del 2026-09-15): `content: ""`, no nulo.

    Con solo el nulo, la clase de configuración no saltaba nunca contra el backend real y el usuario
    recibía una respuesta vacía como si todo hubiera ido bien (decisión del usuario, opción A).
    """
    body = _body("", finish_reason="length", reasoning="pensando muy fuerte")
    assert classify(BackendResponse(status=200, data=body)) is FailureClass.CONFIGURATION


def test_empty_content_with_length_without_reasoning_is_not_a_failure():
    """Control positivo: sin rastro de razonamiento, la cadena vacía sigue tratándose como hoy."""
    body = _body("", finish_reason="length")
    assert classify(BackendResponse(status=200, data=body)) is None


def test_empty_content_with_reasoning_that_ended_well_is_not_a_failure():
    """Control positivo: si no se agotó `max_tokens`, un razonamiento no convierte el vacío en fallo."""
    body = _body("", finish_reason="stop", reasoning="pensé y no hacía falta decir nada")
    assert classify(BackendResponse(status=200, data=body)) is None


# --- Modelo ---------------------------------------------------------------------------------


def test_null_content_for_another_reason_is_the_models():
    """El defecto verificado: hoy esto revienta con `AttributeError` fuera de `_post_chat`."""
    assert classify(BackendResponse(status=200, data=_body(None))) is FailureClass.MODEL


def test_missing_content_is_the_models():
    assert classify(BackendResponse(status=200, data=_body(...))) is FailureClass.MODEL


@pytest.mark.parametrize(
    "data",
    [{}, {"choices": []}, {"choices": [{}]}, {"choices": ["texto suelto"]}],
    ids=["sin choices", "choices vacio", "sin message", "choice que no es dict"],
)
def test_a_broken_response_is_the_models(data):
    assert classify(BackendResponse(status=200, data=data)) is FailureClass.MODEL


def test_a_200_that_was_not_json_is_the_models():
    assert (
        classify(BackendResponse(status=200, data=None, text="<html>502</html>"))
        is FailureClass.MODEL
    )


# --- Lo que NO es un fallo ------------------------------------------------------------------


def test_a_good_response_is_no_failure_at_all():
    assert classify(BackendResponse(status=200, data=_body("la respuesta"))) is None


def test_empty_content_is_not_a_failure():
    """Se trata como hoy. Control positivo del `content` nulo, que sí lo es."""
    assert classify(BackendResponse(status=200, data=_body(""))) is None
    assert classify(BackendResponse(status=200, data=_body(None))) is not None


# --- Sin clasificar -------------------------------------------------------------------------


def test_a_foreign_exception_is_not_blamed_on_the_model():
    """La regla de la casa: lo desconocido nunca va a MODELO, que es la clase cara."""
    assert classify(ValueError("vete a saber")) is FailureClass.UNCLASSIFIED


def test_an_odd_status_is_not_blamed_on_the_model():
    """Un 3xx no es una respuesta de chat, pero tampoco es culpa del modelo.

    La segunda mitad ejercita la rama defensiva de `_classify_status`: `raise_for_status` nunca
    fabrica un `HTTPStatusError` con un 3xx, pero nada impide construirlo a mano, y una rama sin
    prueba es la que se pudre.
    """
    assert classify(BackendResponse(status=302)) is FailureClass.UNCLASSIFIED
    error_302 = httpx2.HTTPStatusError(
        "redirect", request=_http_response(302).request, response=_http_response(302)
    )
    assert classify(error_302) is FailureClass.UNCLASSIFIED


# --- Arrancar o no arrancar el backend ------------------------------------------------------


@pytest.mark.parametrize(
    "exception",
    [httpx2.ConnectError("refused"), httpx2.ConnectTimeout("timed out")],
    ids=["ConnectError", "ConnectTimeout"],
)
def test_nobody_listening_enables_autostart(exception):
    """REQ-F0-6: el segundo caso es el defecto verificado, hoy no ofrece arrancar nada."""
    assert failures.is_backend_missing(exception) is True


@pytest.mark.parametrize(
    "exception",
    [
        httpx2.WriteTimeout("timed out"),
        httpx2.PoolTimeout("timed out"),
        httpx2.ReadTimeout("timed out"),
        httpx2.RemoteProtocolError("boom"),
    ],
    ids=["WriteTimeout", "PoolTimeout", "ReadTimeout", "RemoteProtocolError"],
)
def test_the_other_transport_failures_do_not_enable_it(exception):
    """Control positivo: tres de estos cuatro también son ENDPOINT, y aun así no se arranca nada.

    Por eso la decisión no puede salir de la clase: arrancar otro backend no arregla un fallo que
    ocurrió con la conexión ya establecida.
    """
    assert failures.is_backend_missing(exception) is False


def test_a_response_never_enables_autostart():
    assert failures.is_backend_missing(BackendResponse(status=503)) is False


# --- Valores viejos (REQ-006) -------------------------------------------------------------------


@pytest.mark.parametrize("old,new", sorted(legacy_names.FAILURE_CLASS_VALUES.items()))
def test_the_old_class_value_reads_as_the_new_one(old, new):
    """El log de uso y los eventos de enfriamiento ya escritos traen la clase en español."""
    if new == "cooldown":
        # No es un miembro: es la clase que el daemon escribe en `fallback_class` al saltar por un
        # modelo enfriado. Solo se traduce el valor.
        assert legacy_names.new_value(legacy_names.FAILURE_CLASS_VALUES, old) == "cooldown"
        return
    assert FailureClass(old) is FailureClass(new)


def test_the_values_written_are_the_new_ones():
    written = {c.value for c in FailureClass}
    assert written == {
        "endpoint",
        "request",
        "capacity_or_load",
        "read_timeout",
        "configuration",
        "model",
        "unclassified",
    }
    assert not written & set(legacy_names.FAILURE_CLASS_VALUES), (
        "un valor viejo sigue escribiéndose"
    )
