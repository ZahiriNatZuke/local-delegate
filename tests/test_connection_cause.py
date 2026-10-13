"""La causa de un fallo de conexión al backend (REQ-010, REQ-011 y la tabla de pistas de REQ-016).

Las excepciones se construyen **como las crea el socket**, con errno y mensaje, y encadenadas con
`raise … from …` para que `__cause__` sea real: un `OSError(10051)` con un solo argumento deja
`errno` en `None` y probaría otra regla (lo vigila `test_an_oserror_without_errno_is_not_no_route`).
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

from local_delegate import config, legacy_names
from local_delegate.failures import (
    BackendView,
    ConnectionCause,
    connection_cause,
    detail,
    hint,
    label,
)

HOST = "pc.tailnet.ts.net:9292"
_REQUEST = httpx2.Request("GET", "http://pc.tailnet.ts.net:9292/v1/models")


def _wrapped(cls: type[BaseException], root: BaseException) -> BaseException:
    """`cls` lanzada con `raise … from root`, como hace `httpcore2` al traducir el `OSError`."""
    try:
        try:
            raise root
        except type(root) as original:
            raise cls("fallo de prueba") from original
    except cls as wrapper:
        return wrapper


def _http_status(code: int) -> httpx2.HTTPStatusError:
    response = httpx2.Response(code, request=_REQUEST)
    return httpx2.HTTPStatusError(f"HTTP {code}", request=_REQUEST, response=response)


class _OwnError(Exception):
    """Una excepción de quien llama que envuelve a otra."""


# (id, fábrica del suceso, loopback, causa esperada). Fábricas, no instancias: cada caso construye
# su cadena de cero y ningún test comparte un `__context__` con otro.
_CASES = [
    (
        "gaierror-es-dns",
        lambda: _wrapped(httpx2.ConnectError, socket.gaierror(11001, "getaddrinfo failed")),
        False,
        ConnectionCause.DNS,
    ),
    (
        "gaierror-en-loopback-sigue-siendo-dns",
        lambda: _wrapped(httpx2.ConnectError, socket.gaierror(11001, "getaddrinfo failed")),
        True,
        ConnectionCause.DNS,
    ),
    (
        "econnrefused-es-rechazada",
        lambda: _wrapped(httpx2.ConnectError, OSError(errno.ECONNREFUSED, "refused")),
        False,
        ConnectionCause.REFUSED,
    ),
    (
        "enetunreach-es-sin-ruta",
        lambda: _wrapped(httpx2.ConnectError, OSError(errno.ENETUNREACH, "Network is unreachable")),
        False,
        ConnectionCause.NO_ROUTE,
    ),
    (
        "ehostunreach-es-sin-ruta",
        lambda: _wrapped(httpx2.ConnectError, OSError(errno.EHOSTUNREACH, "No route to host")),
        False,
        ConnectionCause.NO_ROUTE,
    ),
    (
        "winsock-10051-es-sin-ruta",
        lambda: _wrapped(httpx2.ConnectError, OSError(10051, "red inalcanzable")),
        False,
        ConnectionCause.NO_ROUTE,
    ),
    (
        "winsock-10065-es-sin-ruta",
        lambda: _wrapped(httpx2.ConnectError, OSError(10065, "host inalcanzable")),
        False,
        ConnectionCause.NO_ROUTE,
    ),
    (
        "connect-timeout-en-loopback-es-rechazada",
        lambda: _wrapped(httpx2.ConnectTimeout, TimeoutError()),
        True,
        ConnectionCause.REFUSED,
    ),
    (
        "connect-timeout-remoto-es-timeout-conexion",
        lambda: _wrapped(httpx2.ConnectTimeout, TimeoutError()),
        False,
        ConnectionCause.CONNECT_TIMEOUT,
    ),
    (
        "caso-de-la-mac-etimedout-remoto",
        lambda: _wrapped(httpx2.ConnectTimeout, TimeoutError(errno.ETIMEDOUT, "timed out")),
        False,
        ConnectionCause.CONNECT_TIMEOUT,
    ),
    (
        "caso-de-la-mac-etimedout-en-loopback",
        lambda: _wrapped(httpx2.ConnectTimeout, TimeoutError(errno.ETIMEDOUT, "timed out")),
        True,
        ConnectionCause.REFUSED,
    ),
    ("read-timeout", lambda: httpx2.ReadTimeout("lectura"), False, ConnectionCause.NO_RESPONSE),
    ("write-timeout", lambda: httpx2.WriteTimeout("escritura"), False, ConnectionCause.NO_RESPONSE),
    ("value-error", lambda: ValueError("sin data"), False, ConnectionCause.INVALID_RESPONSE),
    (
        "json-roto",
        lambda: json.JSONDecodeError("Expecting value", "<html>", 0),
        False,
        ConnectionCause.INVALID_RESPONSE,
    ),
    (
        "remote-protocol-error",
        lambda: httpx2.RemoteProtocolError("cortado"),
        False,
        ConnectionCause.TRANSPORT,
    ),
    ("invalid-url", lambda: httpx2.InvalidURL("url rota"), False, ConnectionCause.INVALID_URL),
    (
        "unsupported-protocol",
        lambda: httpx2.UnsupportedProtocol("ftp://"),
        False,
        ConnectionCause.INVALID_URL,
    ),
    ("http-status-401", lambda: _http_status(401), False, ConnectionCause.CREDENTIAL),
    ("http-status-403", lambda: _http_status(403), False, ConnectionCause.CREDENTIAL),
    ("http-status-500", lambda: _http_status(500), False, ConnectionCause.HTTP_ERROR),
    ("codigo-401", lambda: 401, False, ConnectionCause.CREDENTIAL),
    ("codigo-403", lambda: 403, False, ConnectionCause.CREDENTIAL),
    ("codigo-404", lambda: 404, False, ConnectionCause.HTTP_ERROR),
    ("codigo-500", lambda: 500, False, ConnectionCause.HTTP_ERROR),
    ("attribute-error", lambda: AttributeError("x"), False, ConnectionCause.UNKNOWN),
    ("key-error", lambda: KeyError("data"), False, ConnectionCause.UNKNOWN),
    (
        # Las reglas 7 a 12 miran solo la excepción de arriba: una propia que envuelve un
        # `ConnectTimeout` cae en la 12, de forma determinista.
        "propia-que-envuelve-connect-timeout",
        lambda: _wrapped(_OwnError, httpx2.ConnectTimeout("plazo")),
        True,
        ConnectionCause.UNKNOWN,
    ),
]


@pytest.mark.parametrize(
    ("factory", "loopback", "expected"),
    [pytest.param(f, lb, expected, id=name) for name, f, lb, expected in _CASES],
)
def test_each_event_has_its_cause(factory, loopback, expected):
    cause = connection_cause(factory(), loopback=loopback)
    assert cause is expected


def test_the_case_setup_matches_the_socket():
    """Guarda del montaje: `ECONNREFUSED` nace como `ConnectionRefusedError` y la cadena es real."""
    rejected = _wrapped(httpx2.ConnectError, OSError(errno.ECONNREFUSED, "refused"))
    assert type(rejected.__cause__) is ConnectionRefusedError
    assert isinstance(rejected, httpx2.ConnectError)


def test_an_oserror_without_errno_is_not_no_route():
    """Con UN argumento `errno` queda en `None`: el caso 10051 tiene que llevar dos."""
    assert OSError(10051).errno is None
    assert OSError(10051, "red inalcanzable").errno == 10051
    one_argument = _wrapped(httpx2.ConnectError, OSError(10051))
    two_arguments = _wrapped(httpx2.ConnectError, OSError(10051, "red inalcanzable"))
    assert connection_cause(one_argument, loopback=False) is ConnectionCause.TRANSPORT
    assert connection_cause(two_arguments, loopback=False) is ConnectionCause.NO_ROUTE


@pytest.mark.parametrize("code", [200, 204, 299])
def test_a_2xx_is_not_classified(code):
    with pytest.raises(ValueError):
        connection_cause(code, loopback=False)


def _classify_in_a_thread(event: BaseException) -> list:
    """Clasifica en un hilo aparte: si la cadena con ciclo no terminara, el test falla en el
    assert en vez de colgar la suite."""
    result: list = []
    thread = threading.Thread(
        target=lambda: result.append(connection_cause(event, loopback=False)), daemon=True
    )
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive(), "la cadena con ciclo no terminó"
    return result


def test_a_chain_with_a_cycle_terminates():
    own = httpx2.ConnectError("se apunta a sí misma")
    own.__context__ = own
    assert _classify_in_a_thread(own) == [ConnectionCause.TRANSPORT]

    a = httpx2.ConnectError("a")
    b = OSError(errno.ENETUNREACH, "b")
    a.__cause__ = b
    b.__context__ = a
    assert _classify_in_a_thread(a) == [ConnectionCause.NO_ROUTE]


# --- Fallos de red real ---------------------------------------------------------------------


def _loopback(url: str) -> bool:
    """El criterio de REQ-010: el host real de la URL, sin puerto."""
    return config._is_loopback_host(config._split_host_port(url)[0])


def _real_failure(url: str, *, connection: float) -> BaseException:
    # `trust_env=False`: un proxy del entorno cambiaría el fallo que se quiere ver.
    timeout = httpx2.Timeout(5.0, connect=connection)
    with httpx2.Client(timeout=timeout, trust_env=False) as client:
        try:
            response = client.get(url)
        except Exception as exc:
            return exc
    raise AssertionError(
        f"{url} respondió {response.status_code}: se esperaba un fallo de conexión"
    )


def _just_freed_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_real_network_a_name_that_does_not_resolve_is_dns():
    url = "http://no-existe.invalid:9292/v1/models"
    cause = connection_cause(_real_failure(url, connection=3.0), loopback=_loopback(url))
    assert cause is ConnectionCause.DNS


def test_real_network_a_closed_loopback_port_is_refused():
    url = f"http://127.0.0.1:{_just_freed_port()}/v1/models"
    assert _loopback(url)
    cause = connection_cause(_real_failure(url, connection=3.0), loopback=_loopback(url))
    assert cause is ConnectionCause.REFUSED


def test_real_network_an_ip_that_does_not_answer_is_neither_dns_nor_refused():
    url = "http://192.0.2.1:9292/v1/models"
    assert not _loopback(url)
    cause = connection_cause(_real_failure(url, connection=0.5), loopback=_loopback(url))
    assert cause in {ConnectionCause.CONNECT_TIMEOUT, ConnectionCause.NO_ROUTE}


# --- Textos ---------------------------------------------------------------------------------


def _without_remote_start(text: str) -> str:
    """Quita «arranca llama-swap en <host>», que sí es válido en remoto: lo prohibido es a secas."""
    return text.replace(f"arranca llama-swap en {HOST}", "")


def test_remote_hint_never_just_says_to_start_llama_swap():
    for cause in [*ConnectionCause, None]:
        for source in ("daemon", "direct"):
            text = hint(cause, origin="remote", source=source, host=HOST)
            assert "arranca llama-swap" not in _without_remote_start(text), (cause, text)


def test_local_refused_hint_says_to_start_llama_swap():
    text = hint(ConnectionCause.REFUSED, origin="local", source="direct", host=HOST)
    assert "arranca llama-swap" in text


def test_credential_hint_depends_on_who_saw_the_401():
    from_daemon = hint(ConnectionCause.CREDENTIAL, origin="local", source="daemon", host=HOST)
    direct = hint(ConnectionCause.CREDENTIAL, origin="local", source="direct", host=HOST)
    assert "lanzador" in from_daemon
    assert "en este entorno" in direct
    assert "lanzador" not in direct


def test_hint_without_cause_is_the_generic_one():
    """Daemon antiguo que no manda `causa`, o una causa que este código no conoce."""
    expected = f"revisa el backend en {HOST}"
    assert hint(None, origin="local", source="daemon", host=HOST) == expected
    assert hint("causa_del_futuro", origin="remote", source="daemon", host=HOST) == expected


def test_every_detail_names_the_host():
    for cause in list(ConnectionCause):
        text = detail(
            cause,
            host=HOST,
            status=500,
            endpoint="/v1/models",
            exception=httpx2.ConnectError("x"),
        )
        if cause is ConnectionCause.INVALID_URL:
            # La tabla de REQ-011 no lleva host aquí: con la URL rota puede no significar nada.
            assert "LOCAL_DELEGATE_BASE_URL" in text
            continue
        assert HOST in text, cause
    invalid = detail(ConnectionCause.INVALID_RESPONSE, host=HOST, endpoint="/v1/models")
    assert "/v1/models" in invalid


def test_a_detail_without_optional_data_does_not_write_none():
    for cause in list(ConnectionCause):
        assert "None" not in detail(cause, host=HOST), cause


_DETAILS = {
    ConnectionCause.DNS: f"no se resuelve el nombre {HOST} (¿VPN o DNS?)",
    ConnectionCause.REFUSED: f"{HOST} rechaza la conexión: no hay nada escuchando en ese puerto",
    ConnectionCause.NO_ROUTE: f"no hay ruta de red hacia {HOST}",
    ConnectionCause.CONNECT_TIMEOUT: f"{HOST} no contesta a la conexión (ruta, cortafuegos o VPN)",
    ConnectionCause.CREDENTIAL: f"{HOST} responde 401: está arriba pero rechaza la credencial",
    ConnectionCause.HTTP_ERROR: f"{HOST} responde HTTP 401",
    ConnectionCause.NO_RESPONSE: f"{HOST} acepta la conexión pero no responde a tiempo",
    ConnectionCause.INVALID_RESPONSE: (
        f"{HOST} responde a /v1/models, pero con un cuerpo que no se entiende"
    ),
    ConnectionCause.INVALID_URL: (
        "la URL del backend no es válida (HTTPStatusError): revisa LOCAL_DELEGATE_BASE_URL"
    ),
    ConnectionCause.TRANSPORT: f"fallo de red con {HOST} (HTTPStatusError)",
    ConnectionCause.UNKNOWN: f"fallo inesperado al sondear {HOST} (HTTPStatusError)",
}

_LABELS = {
    "dns": "no resuelve",
    "refused": "nadie escucha",
    "no_route": "sin ruta",
    "connect_timeout": "no contesta",
    "credential": "sin acceso",
    "http_error": "responde con error",
    "no_response": "no responde a tiempo",
    "invalid_response": "respuesta no válida",
    "invalid_url": "URL no válida",
    "transport": "fallo de red",
    "unknown": "fallo inesperado",
}


def test_the_texts_are_the_ones_in_the_req_011_table():
    """El código sale de la excepción cuando no se pasa: `HTTPStatusError(401)` da «responde 401»."""
    assert set(_LABELS) == {c.value for c in ConnectionCause}
    for value, expected_label in _LABELS.items():
        assert label(value) == expected_label
    exception = _http_status(401)
    for cause, expected_detail in _DETAILS.items():
        text = detail(cause, host=HOST, endpoint="/v1/models", exception=exception)
        assert text == expected_detail


def test_backend_view_has_the_req_016_fields():
    view = BackendView(healthy=False, detail="d", cause="credential", source="daemon")
    assert view._fields == ("healthy", "detail", "cause", "source")
    assert tuple(view) == (False, "d", "credential", "daemon")


# --- Valores viejos (REQ-006) -------------------------------------------------------------------
#
# El log de uso guarda `connection_failure` (antes `fallo_conexion`) y un daemon de la 0.34.0 manda
# `causa` con el valor en español. Los dos se siguen entendiendo, con la misma etiqueta.


@pytest.mark.parametrize("old,new", sorted(legacy_names.CONNECTION_CAUSE_VALUES.items()))
def test_the_old_cause_value_gives_the_same_member_and_label(old, new):
    assert ConnectionCause(old) is ConnectionCause(new)
    assert label(old) == label(new)
    assert hint(old, origin="local", source="direct", host=HOST) == hint(
        new, origin="local", source="direct", host=HOST
    )


def test_the_old_causes_table_covers_every_one_that_changed():
    """Cada miembro cuyo valor no es ya el de antes tiene su valor viejo en la tabla."""
    unchanged = {"dns", "http_error"}
    new_ones = {c.value for c in ConnectionCause} - unchanged
    assert set(legacy_names.CONNECTION_CAUSE_VALUES.values()) == new_ones
    with pytest.raises(ValueError):
        ConnectionCause("no_existe")
