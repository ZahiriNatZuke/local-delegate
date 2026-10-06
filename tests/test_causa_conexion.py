"""La causa de un fallo de conexión al backend (REQ-010, REQ-011 y la tabla de pistas de REQ-016).

Las excepciones se construyen **como las crea el socket**, con errno y mensaje, y encadenadas con
`raise … from …` para que `__cause__` sea real: un `OSError(10051)` con un solo argumento deja
`errno` en `None` y probaría otra regla (lo vigila `test_un_oserror_sin_errno_no_es_sin_ruta`).
Los fallos de red real van sin dobles ni `skip`: son los que dicen si la tabla acierta con lo que
de verdad devuelve `httpx2` en cada sistema del CI.
"""

from __future__ import annotations

import errno
import json
import socket
import threading

import httpx2
import pytest

from local_delegate import config
from local_delegate.fallos import (
    CausaConexion,
    VistaBackend,
    causa_conexion,
    detalle,
    etiqueta,
    pista,
)

HOST = "pc.tailnet.ts.net:9292"
_PETICION = httpx2.Request("GET", "http://pc.tailnet.ts.net:9292/v1/models")


def _envuelta(clase: type[BaseException], raiz: BaseException) -> BaseException:
    """`clase` lanzada con `raise … from raiz`, como hace `httpcore2` al traducir el `OSError`."""
    try:
        try:
            raise raiz
        except BaseException as original:
            raise clase("fallo de prueba") from original
    except BaseException as envoltura:
        return envoltura


def _http_status(codigo: int) -> httpx2.HTTPStatusError:
    respuesta = httpx2.Response(codigo, request=_PETICION)
    return httpx2.HTTPStatusError(f"HTTP {codigo}", request=_PETICION, response=respuesta)


class _Propia(Exception):
    """Una excepción de quien llama que envuelve a otra."""


# (id, fábrica del suceso, loopback, causa esperada). Fábricas, no instancias: cada caso construye
# su cadena de cero y ningún test comparte un `__context__` con otro.
_CASOS = [
    (
        "gaierror-es-dns",
        lambda: _envuelta(httpx2.ConnectError, socket.gaierror(11001, "getaddrinfo failed")),
        False,
        CausaConexion.DNS,
    ),
    (
        "gaierror-en-loopback-sigue-siendo-dns",
        lambda: _envuelta(httpx2.ConnectError, socket.gaierror(11001, "getaddrinfo failed")),
        True,
        CausaConexion.DNS,
    ),
    (
        "econnrefused-es-rechazada",
        lambda: _envuelta(httpx2.ConnectError, OSError(errno.ECONNREFUSED, "refused")),
        False,
        CausaConexion.RECHAZADA,
    ),
    (
        "enetunreach-es-sin-ruta",
        lambda: _envuelta(
            httpx2.ConnectError, OSError(errno.ENETUNREACH, "Network is unreachable")
        ),
        False,
        CausaConexion.SIN_RUTA,
    ),
    (
        "ehostunreach-es-sin-ruta",
        lambda: _envuelta(httpx2.ConnectError, OSError(errno.EHOSTUNREACH, "No route to host")),
        False,
        CausaConexion.SIN_RUTA,
    ),
    (
        "winsock-10051-es-sin-ruta",
        lambda: _envuelta(httpx2.ConnectError, OSError(10051, "red inalcanzable")),
        False,
        CausaConexion.SIN_RUTA,
    ),
    (
        "winsock-10065-es-sin-ruta",
        lambda: _envuelta(httpx2.ConnectError, OSError(10065, "host inalcanzable")),
        False,
        CausaConexion.SIN_RUTA,
    ),
    (
        "connect-timeout-en-loopback-es-rechazada",
        lambda: _envuelta(httpx2.ConnectTimeout, TimeoutError()),
        True,
        CausaConexion.RECHAZADA,
    ),
    (
        "connect-timeout-remoto-es-timeout-conexion",
        lambda: _envuelta(httpx2.ConnectTimeout, TimeoutError()),
        False,
        CausaConexion.TIMEOUT_CONEXION,
    ),
    (
        "caso-de-la-mac-etimedout-remoto",
        lambda: _envuelta(httpx2.ConnectTimeout, TimeoutError(errno.ETIMEDOUT, "timed out")),
        False,
        CausaConexion.TIMEOUT_CONEXION,
    ),
    (
        "caso-de-la-mac-etimedout-en-loopback",
        lambda: _envuelta(httpx2.ConnectTimeout, TimeoutError(errno.ETIMEDOUT, "timed out")),
        True,
        CausaConexion.RECHAZADA,
    ),
    ("read-timeout", lambda: httpx2.ReadTimeout("lectura"), False, CausaConexion.SIN_RESPUESTA),
    ("write-timeout", lambda: httpx2.WriteTimeout("escritura"), False, CausaConexion.SIN_RESPUESTA),
    ("value-error", lambda: ValueError("sin data"), False, CausaConexion.RESPUESTA_INVALIDA),
    (
        "json-roto",
        lambda: json.JSONDecodeError("Expecting value", "<html>", 0),
        False,
        CausaConexion.RESPUESTA_INVALIDA,
    ),
    (
        "remote-protocol-error",
        lambda: httpx2.RemoteProtocolError("cortado"),
        False,
        CausaConexion.TRANSPORTE,
    ),
    ("invalid-url", lambda: httpx2.InvalidURL("url rota"), False, CausaConexion.URL_INVALIDA),
    (
        "unsupported-protocol",
        lambda: httpx2.UnsupportedProtocol("ftp://"),
        False,
        CausaConexion.URL_INVALIDA,
    ),
    ("http-status-401", lambda: _http_status(401), False, CausaConexion.CREDENCIAL),
    ("http-status-403", lambda: _http_status(403), False, CausaConexion.CREDENCIAL),
    ("http-status-500", lambda: _http_status(500), False, CausaConexion.HTTP_ERROR),
    ("codigo-401", lambda: 401, False, CausaConexion.CREDENCIAL),
    ("codigo-403", lambda: 403, False, CausaConexion.CREDENCIAL),
    ("codigo-404", lambda: 404, False, CausaConexion.HTTP_ERROR),
    ("codigo-500", lambda: 500, False, CausaConexion.HTTP_ERROR),
    ("attribute-error", lambda: AttributeError("x"), False, CausaConexion.DESCONOCIDA),
    ("key-error", lambda: KeyError("data"), False, CausaConexion.DESCONOCIDA),
    (
        # Las reglas 7 a 12 miran solo la excepción de arriba: una propia que envuelve un
        # `ConnectTimeout` cae en la 12, de forma determinista.
        "propia-que-envuelve-connect-timeout",
        lambda: _envuelta(_Propia, httpx2.ConnectTimeout("plazo")),
        True,
        CausaConexion.DESCONOCIDA,
    ),
]


@pytest.mark.parametrize(
    ("fabrica", "loopback", "esperada"),
    [pytest.param(f, lb, esp, id=nombre) for nombre, f, lb, esp in _CASOS],
)
def test_cada_suceso_tiene_su_causa(fabrica, loopback, esperada):
    causa = causa_conexion(fabrica(), loopback=loopback)
    assert causa is esperada


def test_el_montaje_de_los_casos_es_el_del_socket():
    """Guarda del montaje: `ECONNREFUSED` nace como `ConnectionRefusedError` y la cadena es real."""
    rechazada = _envuelta(httpx2.ConnectError, OSError(errno.ECONNREFUSED, "refused"))
    assert type(rechazada.__cause__) is ConnectionRefusedError
    assert isinstance(rechazada, httpx2.ConnectError)


def test_un_oserror_sin_errno_no_es_sin_ruta():
    """Con UN argumento `errno` queda en `None`: el caso 10051 tiene que llevar dos."""
    assert OSError(10051).errno is None
    assert OSError(10051, "red inalcanzable").errno == 10051
    un_argumento = _envuelta(httpx2.ConnectError, OSError(10051))
    dos_argumentos = _envuelta(httpx2.ConnectError, OSError(10051, "red inalcanzable"))
    assert causa_conexion(un_argumento, loopback=False) is CausaConexion.TRANSPORTE
    assert causa_conexion(dos_argumentos, loopback=False) is CausaConexion.SIN_RUTA


@pytest.mark.parametrize("codigo", [200, 204, 299])
def test_un_2xx_no_se_clasifica(codigo):
    with pytest.raises(ValueError):
        causa_conexion(codigo, loopback=False)


def _clasifica_en_un_hilo(suceso: BaseException) -> list:
    """Clasifica en un hilo aparte: si la cadena con ciclo no terminara, el test falla en el
    assert en vez de colgar la suite."""
    resultado: list = []
    hilo = threading.Thread(
        target=lambda: resultado.append(causa_conexion(suceso, loopback=False)), daemon=True
    )
    hilo.start()
    hilo.join(timeout=5)
    assert not hilo.is_alive(), "la cadena con ciclo no terminó"
    return resultado


def test_una_cadena_con_ciclo_termina():
    propia = httpx2.ConnectError("se apunta a sí misma")
    propia.__context__ = propia
    assert _clasifica_en_un_hilo(propia) == [CausaConexion.TRANSPORTE]

    a = httpx2.ConnectError("a")
    b = OSError(errno.ENETUNREACH, "b")
    a.__cause__ = b
    b.__context__ = a
    assert _clasifica_en_un_hilo(a) == [CausaConexion.SIN_RUTA]


# --- Fallos de red real ---------------------------------------------------------------------


def _loopback(url: str) -> bool:
    """El criterio de REQ-010: el host real de la URL, sin puerto."""
    return config._is_loopback_host(config._split_host_port(url)[0])


def _fallo_real(url: str, *, conexion: float) -> BaseException:
    # `trust_env=False`: un proxy del entorno cambiaría el fallo que se quiere ver.
    plazo = httpx2.Timeout(5.0, connect=conexion)
    with httpx2.Client(timeout=plazo, trust_env=False) as cliente:
        try:
            respuesta = cliente.get(url)
        except Exception as exc:
            return exc
    pytest.fail(f"{url} respondió {respuesta.status_code}: se esperaba un fallo de conexión")


def _puerto_recien_liberado() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_red_real_un_nombre_que_no_resuelve_es_dns():
    url = "http://no-existe.invalid:9292/v1/models"
    causa = causa_conexion(_fallo_real(url, conexion=3.0), loopback=_loopback(url))
    assert causa is CausaConexion.DNS


def test_red_real_un_puerto_cerrado_en_loopback_es_rechazada():
    url = f"http://127.0.0.1:{_puerto_recien_liberado()}/v1/models"
    assert _loopback(url)
    causa = causa_conexion(_fallo_real(url, conexion=3.0), loopback=_loopback(url))
    assert causa is CausaConexion.RECHAZADA


def test_red_real_una_ip_que_no_contesta_no_es_dns_ni_rechazada():
    url = "http://192.0.2.1:9292/v1/models"
    assert not _loopback(url)
    causa = causa_conexion(_fallo_real(url, conexion=0.5), loopback=_loopback(url))
    assert causa in {CausaConexion.TIMEOUT_CONEXION, CausaConexion.SIN_RUTA}


# --- Textos ---------------------------------------------------------------------------------


def _sin_el_arranque_remoto(texto: str) -> str:
    """Quita «arranca llama-swap en <host>», que sí es válido en remoto: lo prohibido es a secas."""
    return texto.replace(f"arranca llama-swap en {HOST}", "")


def test_pista_remota_nunca_manda_a_arrancar_llama_swap_a_secas():
    for causa in [*CausaConexion, None]:
        for fuente in ("daemon", "directo"):
            texto = pista(causa, origen="remote", fuente=fuente, host=HOST)
            assert "arranca llama-swap" not in _sin_el_arranque_remoto(texto), (causa, texto)


def test_pista_local_de_rechazada_manda_a_arrancar_llama_swap():
    texto = pista(CausaConexion.RECHAZADA, origen="local", fuente="directo", host=HOST)
    assert "arranca llama-swap" in texto


def test_pista_de_credencial_depende_de_quien_vio_el_401():
    del_daemon = pista(CausaConexion.CREDENCIAL, origen="local", fuente="daemon", host=HOST)
    directa = pista(CausaConexion.CREDENCIAL, origen="local", fuente="directo", host=HOST)
    assert "lanzador" in del_daemon
    assert "en este entorno" in directa
    assert "lanzador" not in directa


def test_pista_sin_causa_es_la_generica():
    """Daemon antiguo que no manda `causa`, o una causa que este código no conoce."""
    esperada = f"revisa el backend en {HOST}"
    assert pista(None, origen="local", fuente="daemon", host=HOST) == esperada
    assert pista("causa_del_futuro", origen="remote", fuente="daemon", host=HOST) == esperada


def test_todos_los_detalles_dicen_el_host():
    for causa in CausaConexion:
        texto = detalle(
            causa,
            host=HOST,
            status=500,
            endpoint="/v1/models",
            excepcion=httpx2.ConnectError("x"),
        )
        if causa is CausaConexion.URL_INVALIDA:
            # La tabla de REQ-011 no lleva host aquí: con la URL rota puede no significar nada.
            assert "LOCAL_DELEGATE_BASE_URL" in texto
            continue
        assert HOST in texto, causa
    invalida = detalle(CausaConexion.RESPUESTA_INVALIDA, host=HOST, endpoint="/v1/models")
    assert "/v1/models" in invalida


def test_un_detalle_sin_datos_opcionales_no_escribe_none():
    for causa in CausaConexion:
        assert "None" not in detalle(causa, host=HOST), causa


_DETALLES = {
    CausaConexion.DNS: f"no se resuelve el nombre {HOST} (¿VPN o DNS?)",
    CausaConexion.RECHAZADA: f"{HOST} rechaza la conexión: no hay nada escuchando en ese puerto",
    CausaConexion.SIN_RUTA: f"no hay ruta de red hacia {HOST}",
    CausaConexion.TIMEOUT_CONEXION: f"{HOST} no contesta a la conexión (ruta, cortafuegos o VPN)",
    CausaConexion.CREDENCIAL: f"{HOST} responde 401: está arriba pero rechaza la credencial",
    CausaConexion.HTTP_ERROR: f"{HOST} responde HTTP 401",
    CausaConexion.SIN_RESPUESTA: f"{HOST} acepta la conexión pero no responde a tiempo",
    CausaConexion.RESPUESTA_INVALIDA: (
        f"{HOST} responde a /v1/models, pero con un cuerpo que no se entiende"
    ),
    CausaConexion.URL_INVALIDA: (
        "la URL del backend no es válida (HTTPStatusError): revisa LOCAL_DELEGATE_BASE_URL"
    ),
    CausaConexion.TRANSPORTE: f"fallo de red con {HOST} (HTTPStatusError)",
    CausaConexion.DESCONOCIDA: f"fallo inesperado al sondear {HOST} (HTTPStatusError)",
}

_ETIQUETAS = {
    "dns": "no resuelve",
    "rechazada": "nadie escucha",
    "sin_ruta": "sin ruta",
    "timeout_conexion": "no contesta",
    "credencial": "sin acceso",
    "http_error": "responde con error",
    "sin_respuesta": "no responde a tiempo",
    "respuesta_invalida": "respuesta no válida",
    "url_invalida": "URL no válida",
    "transporte": "fallo de red",
    "desconocida": "fallo inesperado",
}


def test_los_textos_son_los_de_la_tabla_de_req_011():
    """El código sale de la excepción cuando no se pasa: `HTTPStatusError(401)` da «responde 401»."""
    assert set(_ETIQUETAS) == {c.value for c in CausaConexion}
    for valor, esperada in _ETIQUETAS.items():
        assert etiqueta(valor) == esperada
    excepcion = _http_status(401)
    for causa, esperado in _DETALLES.items():
        texto = detalle(causa, host=HOST, endpoint="/v1/models", excepcion=excepcion)
        assert texto == esperado


def test_vista_backend_tiene_los_campos_de_req_016():
    vista = VistaBackend(sano=False, detalle="d", causa="credencial", fuente="daemon")
    assert vista._fields == ("sano", "detalle", "causa", "fuente")
    assert tuple(vista) == (False, "d", "credencial", "daemon")
