"""`_post_chat` usando el clasificador: los tres defectos verificados, ya en su sitio.

Los tres se reprodujeron primero con dobles de `httpx2` y se vieron **rojos** antes de tocar
`server.py` (`.sdd/changes/delegacion-precisa-y-fiable/research.md`, sección 3). Lo que se prueba
aquí no es la clasificación —eso es `test_fallos.py`, sin red— sino que la llamada real la usa:
probar la pieza no es probar el uso.
"""

from __future__ import annotations

import backend_mock
import httpx2
import pytest

from local_delegate import config, fallos, server

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
    monkeypatch.setattr(config, "AUTOSTART", False)
    return lambda **kwargs: backend_mock.post(URL).mock(**kwargs)


@pytest.fixture
def sin_preguntar(monkeypatch):
    """Espía de la pregunta por elicitation: registra si se ofreció arrancar el backend."""
    ofertas: list[str] = []

    def espia(mensaje, _esquema):
        ofertas.append(mensaje)

    monkeypatch.setattr(server.preguntas, "preguntar", espia)
    return ofertas


# --- REQ-F0-1: el `content` nulo deja de escaparse ------------------------------------------


@backend_mock.mock
def test_content_nulo_devuelve_un_error_legible(backend):
    """Hoy revienta con `AttributeError` fuera de `_post_chat` y se lleva la tool por delante."""
    backend(return_value=httpx2.Response(200, json={"choices": [{"message": {"content": None}}]}))
    resultado = server._post_chat("modelo", {"model": "modelo"})
    assert resultado.ok is False
    assert resultado.clase == fallos.Clase.MODELO
    assert "[local-delegate error]" in resultado.text


@backend_mock.mock
def test_content_vacio_sigue_sin_ser_un_fallo(backend):
    """Control positivo del anterior: la cadena vacía se trata como hoy."""
    backend(return_value=httpx2.Response(200, json={"choices": [{"message": {"content": ""}}]}))
    resultado = server._post_chat("modelo", {"model": "modelo"})
    assert resultado.ok is True
    assert resultado.text == ""


@backend_mock.mock
def test_razonamiento_que_se_come_max_tokens_se_dice_en_claro(backend):
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
    resultado = server._post_chat("modelo", {"model": "modelo"})
    assert resultado.ok is False
    assert resultado.clase == fallos.Clase.CONFIGURACION
    assert "max_tokens" in resultado.text


# --- REQ-F0-2 y REQ-F0-6: los timeouts dejan de ser todos `http_error` ----------------------


@backend_mock.mock
def test_connect_timeout_ofrece_arrancar_el_backend(backend, sin_preguntar):
    """El defecto: hoy cae en `http_error` y nadie ofrece arrancar nada."""
    backend(side_effect=httpx2.ConnectTimeout("timed out"))
    resultado = server._post_chat("modelo", {"model": "modelo"})
    assert sin_preguntar, "no se ofreció arrancar el backend"
    assert resultado.ok is False
    assert resultado.clase == fallos.Clase.ENDPOINT
    assert resultado.error == "connect_error"


@backend_mock.mock
def test_connect_error_se_comporta_igual_que_siempre(backend, sin_preguntar):
    """Control positivo: la rama hermana no cambia."""
    backend(side_effect=httpx2.ConnectError("no route"))
    resultado = server._post_chat("modelo", {"model": "modelo"})
    assert sin_preguntar, "no se ofreció arrancar el backend"
    assert resultado.error == "connect_error"


@backend_mock.mock
def test_read_timeout_no_ofrece_arrancar_nada(backend, sin_preguntar):
    """El backend SÍ aceptó la conexión: arrancar otro no arregla que el modelo esté cargando."""
    backend(side_effect=httpx2.ReadTimeout("timed out"))
    resultado = server._post_chat("modelo", {"model": "modelo"})
    assert not sin_preguntar, "se ofreció arrancar un backend que ya estaba corriendo"
    assert resultado.ok is False
    assert resultado.clase == fallos.Clase.CAPACIDAD
    assert resultado.error != "http_error"


@backend_mock.mock
def test_un_error_de_transporte_cualquiera_sigue_siendo_del_endpoint(backend, sin_preguntar):
    """Control positivo: ni se clasifica como carga ni se ofrece arrancar nada."""
    backend(side_effect=httpx2.RemoteProtocolError("server disconnected"))
    resultado = server._post_chat("modelo", {"model": "modelo"})
    assert not sin_preguntar
    assert resultado.clase == fallos.Clase.ENDPOINT


@backend_mock.mock
def test_un_500_es_del_modelo(backend):
    backend(return_value=httpx2.Response(500, text="boom"))
    resultado = server._post_chat("modelo", {"model": "modelo"})
    assert resultado.clase == fallos.Clase.MODELO
    assert resultado.error == "http_500", "el codigo de error de siempre no cambia"


@backend_mock.mock
def test_un_400_es_de_la_peticion(backend):
    """En test aparte: dos rutas para la misma URL no se pisan, gana la primera registrada."""
    backend(return_value=httpx2.Response(400, text="context too long"))
    resultado = server._post_chat("modelo", {"model": "modelo"})
    assert resultado.clase == fallos.Clase.PETICION
    assert resultado.error == "http_400"


@backend_mock.mock
def test_una_respuesta_buena_no_trae_clase(backend):
    """Lo que no es un fallo no se clasifica: `clase` solo existe cuando algo salió mal."""
    backend(return_value=httpx2.Response(200, json={"choices": [{"message": {"content": "hola"}}]}))
    resultado = server._post_chat("modelo", {"model": "modelo"})
    assert resultado.ok is True
    assert resultado.clase is None
