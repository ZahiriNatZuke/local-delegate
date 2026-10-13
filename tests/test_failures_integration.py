"""`_post_chat` usando el clasificador: los tres defectos verificados, ya en su sitio.

Los tres se reprodujeron primero con dobles de `httpx2` y se vieron **rojos** antes de tocar
`server.py` (`.sdd/changes/delegacion-precisa-y-fiable/research.md`, sección 3). Lo que se prueba
aquí no es la clasificación —eso es `test_failures.py`, sin red— sino que la llamada real la usa:
probar la pieza no es probar el uso.
"""

from __future__ import annotations

import backend_mock
import httpx2
import pytest

from local_delegate import config, failures, server

URL = "http://test-backend/v1/chat/completions"


@pytest.fixture
def backend(monkeypatch):
    """Apunta al backend de mentira y devuelve el registrador de la ruta.

    Devuelve una FUNCION y no la ruta ya registrada a proposito: `@backend_mock.mock` limpia el
    registro de rutas al entrar, y las fixtures se resuelven antes de eso. Una ruta registrada en
    la fixture desaparece antes de que empiece el test, y el fallo que se ve luego es «peticion no
    mockeada», que no tiene nada que ver con lo que el test dice comprobar.
    """
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    # Origen fijado a local (REQ-018): la URL de mentira es REMOTA para `backend_origin()`, y con
    # un backend remoto ya no se pregunta «¿Lo arranco?». Sin esto, los dos tests que esperan la
    # pregunta fallarían, y los dos que esperan que NO se haga pasarían sin probar nada.
    monkeypatch.setattr(config, "BACKEND_ORIGIN_OVERRIDE", "local")
    monkeypatch.setattr(config, "AUTOSTART", False)
    return lambda **kwargs: backend_mock.post(URL).mock(**kwargs)


@pytest.fixture
def without_asking(monkeypatch):
    """Espía de la pregunta por elicitation: registra si se ofreció arrancar el backend."""
    offers: list[str] = []

    def spy(message, _schema):
        offers.append(message)

    monkeypatch.setattr(server.questions, "ask", spy)
    return offers


# --- REQ-F0-1: el `content` nulo deja de escaparse ------------------------------------------


@backend_mock.mock
def test_null_content_returns_a_readable_error(backend):
    """Hoy revienta con `AttributeError` fuera de `_post_chat` y se lleva la tool por delante."""
    backend(return_value=httpx2.Response(200, json={"choices": [{"message": {"content": None}}]}))
    result = server._post_chat("modelo", {"model": "modelo"})
    assert result.ok is False
    assert result.error_class == failures.FailureClass.MODEL
    assert "[local-delegate error]" in result.text


@backend_mock.mock
def test_empty_content_is_still_not_a_failure(backend):
    """Control positivo del anterior: la cadena vacía se trata como hoy."""
    backend(return_value=httpx2.Response(200, json={"choices": [{"message": {"content": ""}}]}))
    result = server._post_chat("modelo", {"model": "modelo"})
    assert result.ok is True
    assert result.text == ""


@backend_mock.mock
def test_reasoning_that_eats_max_tokens_is_said_plainly(backend):
    """El canary de julio: no es una avería, es configuración, y el mensaje lo tiene que decir."""
    backend(
        return_value=httpx2.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": None, "reasoning_content": "pensando"},
                        "finish_reason": "length",
                    }
                ]
            },
        )
    )
    result = server._post_chat("modelo", {"model": "modelo"})
    assert result.ok is False
    assert result.error_class == failures.FailureClass.CONFIGURATION
    assert "max_tokens" in result.text


@backend_mock.mock
def test_reasoning_with_empty_content_is_also_said_plainly(backend):
    """La forma real de b10909: `content: ""` en vez de nulo. Antes salía como éxito vacío."""
    backend(
        return_value=httpx2.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "", "reasoning_content": "pensando"},
                        "finish_reason": "length",
                    }
                ]
            },
        )
    )
    result = server._post_chat("modelo", {"model": "modelo"})
    assert result.ok is False
    assert result.error_class == failures.FailureClass.CONFIGURATION
    assert result.error == "config_max_tokens"


# --- REQ-F0-2 y REQ-F0-6: los timeouts dejan de ser todos `http_error` ----------------------


@backend_mock.mock
def test_connect_timeout_offers_to_start_the_backend(backend, without_asking):
    """El defecto: hoy cae en `http_error` y nadie ofrece arrancar nada."""
    backend(side_effect=httpx2.ConnectTimeout("timed out"))
    result = server._post_chat("modelo", {"model": "modelo"})
    assert without_asking, "no se ofreció arrancar el backend"
    assert result.ok is False
    assert result.error_class == failures.FailureClass.ENDPOINT
    assert result.error == "connect_error"


@backend_mock.mock
def test_connect_error_behaves_as_always(backend, without_asking):
    """Control positivo: la rama hermana no cambia."""
    backend(side_effect=httpx2.ConnectError("no route"))
    result = server._post_chat("modelo", {"model": "modelo"})
    assert without_asking, "no se ofreció arrancar el backend"
    assert result.error == "connect_error"


@backend_mock.mock
def test_read_timeout_offers_to_start_nothing(backend, without_asking):
    """El backend SÍ aceptó la conexión: arrancar otro no arregla que el modelo esté cargando."""
    backend(side_effect=httpx2.ReadTimeout("timed out"))
    result = server._post_chat("modelo", {"model": "modelo"})
    assert not without_asking, "se ofreció arrancar un backend que ya estaba corriendo"
    assert result.ok is False
    assert result.error_class == failures.FailureClass.CAPACITY
    assert result.error != "http_error"


@backend_mock.mock
def test_any_transport_error_is_still_the_endpoints(backend, without_asking):
    """Control positivo: ni se clasifica como carga ni se ofrece arrancar nada."""
    backend(side_effect=httpx2.RemoteProtocolError("server disconnected"))
    result = server._post_chat("modelo", {"model": "modelo"})
    assert not without_asking
    assert result.error_class == failures.FailureClass.ENDPOINT


@backend_mock.mock
def test_a_500_is_the_models(backend):
    backend(return_value=httpx2.Response(500, text="boom"))
    result = server._post_chat("modelo", {"model": "modelo"})
    assert result.error_class == failures.FailureClass.MODEL
    assert result.error == "http_500", "el codigo de error de siempre no cambia"


@backend_mock.mock
def test_a_400_is_the_requests(backend):
    """En test aparte: dos rutas para la misma URL no se pisan, gana la primera registrada."""
    backend(return_value=httpx2.Response(400, text="context too long"))
    result = server._post_chat("modelo", {"model": "modelo"})
    assert result.error_class == failures.FailureClass.REQUEST
    assert result.error == "http_400"


@backend_mock.mock
def test_a_good_response_carries_no_class(backend):
    """Lo que no es un fallo no se clasifica: `clase` solo existe cuando algo salió mal."""
    backend(return_value=httpx2.Response(200, json={"choices": [{"message": {"content": "hola"}}]}))
    result = server._post_chat("modelo", {"model": "modelo"})
    assert result.ok is True
    assert result.error_class is None
