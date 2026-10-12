"""Clasificar el fallo de una llamada al backend. Primera de las tres capas del respaldo.

Hoy `_post_chat` mezcla tres trabajos distintos en el mismo bloque de `except`: decidir **qué**
pasó, decidir **si se reintenta** y llevar el **estado de salud** del modelo. Mientras estén
mezclados no se puede probar ninguno por separado ni construir el respaldo encima. Este módulo se
queda solo con el primero: recibe lo que pasó y devuelve una clase. No hace red, no guarda estado,
no decide reintentos y no conoce la configuración.

Tres cosas que la clasificación de hoy hace mal, **verificadas por ejecución** antes de escribir
esto (`.sdd/changes/delegacion-precisa-y-fiable/research.md`, sección 3):

1. Una respuesta con `content: null` revienta con `AttributeError` en `choice["message"]
   ["content"].strip()`, y ese tipo no está en el `except (KeyError, IndexError, ValueError)` que
   la rodea: la excepción se escapa entera de `_post_chat`.
2. `ConnectTimeout` **no** es subclase de `ConnectError` —son ramas hermanas de `TransportError`,
   comprobado contra el `httpx2` instalado—, así que cae en el `except HTTPError` genérico y se
   clasifica como `http_error`. Consecuencia: un backend apagado que agota el plazo de conexión no
   dispara el autoarranque, que es justo lo que arreglaría el problema.
3. `ReadTimeout` cae en el mismo sitio, y no es lo mismo: ahí el backend **sí** aceptó la conexión.

Los dos `ReadTimeout` nacen separados a propósito (REQ-F0-2). Que el modelo estuviera cargándose o
ya cargado cambia qué hay que hacer después: un modelo que tarda en montarse no merece que se le
cuenten fallos, y uno ya cargado que no termina sí. F0 todavía no sabe distinguirlos siempre,
porque esa señal sale de los patrones reales que captura REQ-020 en F3; hasta entonces, lo que no
se pueda atribuir cae del lado que **no** castiga al modelo lento de montar.

Regla de la casa para este módulo: **lo que no encaje va a `UNCLASSIFIED`, nunca a `MODEL`.**
Equivocarse hacia `MODEL` es lo caro: es la única clase que dispara el respaldo y suma para el
enfriamiento, así que una variante desconocida mal leída provocaría saltos de modelo y expulsiones
de VRAM por un fallo que a lo mejor era de la petición.
"""

from __future__ import annotations

import errno
import socket
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

import httpx2

from . import legacy_names


class FailureClass(str, Enum):
    """Las siete clases de la tabla de la spec. Hereda de `str` para que el log las escriba solas.

    Acepta también el valor viejo en español (`FailureClass("modelo")` es `MODEL`): el log de uso y
    los eventos de enfriamiento ya escritos se leen para siempre (REQ-006).
    """

    ENDPOINT = "endpoint"
    REQUEST = "request"
    CAPACITY = "capacity_or_load"
    READ_TIMEOUT = "read_timeout"
    CONFIGURATION = "configuration"
    MODEL = "model"
    UNCLASSIFIED = "unclassified"

    @classmethod
    def _missing_(cls, value: object) -> FailureClass | None:
        new = legacy_names.FAILURE_CLASS_VALUES.get(value) if isinstance(value, str) else None
        return cls._value2member_map_.get(new) if new else None  # type: ignore[return-value]


#: Patrones que delatan un fallo de capacidad o de carga dentro de un 5xx, en minúsculas.
#:
#: Salen de respuestas **reales**, nunca adivinadas (REQ-020): un patrón inventado que leyera un OOM
#: como fallo del modelo haría saltar el respaldo a otro modelo grande y encadenaría swaps y OOM.
#: Cada uno lleva la versión de la que salió; si el backend cambia, se recapturan
#: (`tests/fixtures/backend/`, `tests/test_fallos_capturas.py`).
CAPACITY_PATTERNS: tuple[str, ...] = (
    # llama-swap v255 + llama-server b10909, capturado el 2026-09-15. Es el 500 que da llama-swap
    # cuando el `llama-server` que arranca muere antes de estar listo, y es el MISMO cuerpo, byte a
    # byte, para un OOM con la política «Prefer No Sysmem Fallback» y para un modelo que no existe.
    "upstream command exited prematurely",
)


@dataclass(frozen=True)
class BackendResponse:
    """Lo justo que hace falta de una respuesta HTTP para clasificarla.

    No es el objeto vivo de `httpx2` a propósito: así el clasificador se puede probar entero sin
    montar una respuesta real, y no hay forma de que alguien le pida el cuerpo dos veces.
    """

    status: int
    #: El JSON ya parseado, o `None` si no se pudo parsear (que en sí mismo es un fallo del modelo).
    data: dict | None = None
    #: El cuerpo crudo, recortado. Solo se usa para los patrones de capacidad.
    text: str = ""


def classify(
    event: BaseException | BackendResponse,
    *,
    model_loaded: bool | None = None,
) -> FailureClass | None:
    """La clase del fallo, o `None` si lo que llegó no es un fallo.

    `model_loaded` dice si el modelo ya estaba en memoria cuando venció el plazo de lectura.
    `None` significa «no se sabe», que es lo normal en F0: sin esa señal, un `ReadTimeout` se lee
    como carga y no como modelo colgado.
    """
    if isinstance(event, BaseException):
        return _classify_exception(event, model_loaded=model_loaded)
    return _classify_response(event)


def is_backend_missing(event: BaseException | BackendResponse) -> bool:
    """True si el fallo significa que no hay nadie escuchando en el endpoint.

    Es lo que separa «ofrezco arrancar el backend» de «no lo ofrezco», y por eso no se puede
    deducir de la clase: `ConnectError`, `ConnectTimeout`, un `WriteTimeout` y un
    `RemoteProtocolError` son los cuatro fallos `ENDPOINT`, pero solo los dos primeros dicen que
    nadie contestó al llamar a la puerta. Los otros dos ocurren con una conexión ya establecida,
    donde arrancar otro backend no arregla nada.

    `ConnectTimeout` **no** es subclase de `ConnectError` —son ramas hermanas de `TransportError`,
    comprobado contra el `httpx2` instalado—, y ese detalle es justo el defecto que se verificó por
    ejecución: hoy un plazo de conexión agotado no ofrece arrancar nada.
    """
    return isinstance(event, (httpx2.ConnectError, httpx2.ConnectTimeout))


def _classify_exception(exc: BaseException, *, model_loaded: bool | None) -> FailureClass:
    # `ReadTimeout` va ANTES que su padre `TimeoutException` y que el `HTTPError` genérico: es la
    # única excepción de transporte que no es culpa del endpoint, porque ahí el backend sí aceptó
    # la conexión. `ConnectTimeout` no necesita rama propia —cae en `HTTPError` y ya da ENDPOINT—;
    # lo que sí necesita es `is_backend_missing()`, que es donde su diferencia se nota.
    if isinstance(exc, httpx2.ReadTimeout):
        return FailureClass.READ_TIMEOUT if model_loaded else FailureClass.CAPACITY
    if isinstance(exc, httpx2.HTTPStatusError):
        return _classify_status(exc.response.status_code, getattr(exc.response, "text", ""))
    # `ConnectError`, el resto de timeouts (`WriteTimeout`, `PoolTimeout`) y cualquier otro error
    # de transporte: el modelo no llegó a responder, así que no se le puede achacar nada.
    if isinstance(exc, httpx2.HTTPError):
        return FailureClass.ENDPOINT
    return FailureClass.UNCLASSIFIED


def _classify_response(response: BackendResponse) -> FailureClass | None:
    if response.status >= 400:
        return _classify_status(response.status, response.text)
    if not 200 <= response.status < 300:
        # Un 1xx o un 3xx que llegue hasta aqui no es lo que el protocolo espera, pero tampoco hay
        # nada que achacarle al modelo: no llego a responder una peticion de chat.
        return FailureClass.UNCLASSIFIED
    if response.data is None:
        # Se recibió un 2xx que no era JSON: el modelo respondió algo roto.
        return FailureClass.MODEL
    return _classify_body(response.data)


def _classify_status(status: int, text: str) -> FailureClass:
    if 400 <= status < 500:
        # Incluye el desborde de contexto (400), el schema no soportado y la autenticación. Culpa
        # de la petición: cambiar de modelo no arregla ninguno.
        return FailureClass.REQUEST
    if status >= 500:
        lowered = text.lower()
        if any(pattern in lowered for pattern in CAPACITY_PATTERNS):
            return FailureClass.CAPACITY
        return FailureClass.MODEL
    return FailureClass.UNCLASSIFIED


def _classify_body(data: dict) -> FailureClass | None:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return FailureClass.MODEL
    first = choices[0]
    if not isinstance(first, dict):
        return FailureClass.MODEL
    message = first.get("message")
    if not isinstance(message, dict):
        return FailureClass.MODEL

    content = message.get("content")
    finish = first.get("finish_reason")
    reasoning = message.get("reasoning_content") or ""
    if isinstance(content, str):
        # Un contenido vacío ("") NO es un fallo: se trata como hoy. Con UNA excepción, decidida por
        # el usuario el 2026-09-15: vacío + `length` + razonamiento es la forma REAL en que
        # llama-server b10909 devuelve un razonamiento que agotó `max_tokens` (capturado; no llega
        # como `null`). Sin esta rama la clase de configuración no saltaba nunca contra el backend
        # real y la respuesta vacía llegaba como éxito.
        if not content.strip() and finish == "length" and reasoning.strip():
            return FailureClass.CONFIGURATION
        return None

    if finish == "length":
        # El modelo se gastó `max_tokens` pensando y no llegó a contestar. Es configuración, no
        # avería: taparlo con un respaldo haría que nadie lo arreglara nunca.
        if reasoning.strip():
            return FailureClass.CONFIGURATION
        # Mismo síntoma sin rastro de razonamiento: no se sabe qué pasó, y adivinar aquí es
        # justo lo que la regla de la casa prohíbe.
        return FailureClass.UNCLASSIFIED
    return FailureClass.MODEL


# --- Causa de un fallo de conexión ------------------------------------------------------------
#
# Responde a otra pregunta que `classify`. Aquella decide respaldo y enfriamiento; esta le dice a
# una persona POR QUÉ no se llega al backend, con el mismo texto en el panel, en `local_status`, en
# `doctor` y en el error de una delegación (REQ-010, REQ-011, REQ-016). Por eso nadie fuera de aquí
# redacta los textos de una causa. Sigue la regla del módulo: sin red y sin leer configuración;
# `host`, `loopback`, `origin`, `source`, el código y `endpoint` entran como argumentos.


class ConnectionCause(str, Enum):
    """Las once causas de REQ-010. Hereda de `str` para viajar tal cual en el JSON y en el log.

    Acepta también el valor viejo en español (`ConnectionCause("rechazada")` es `REFUSED`), el que
    escribían el log y un daemon de una versión anterior (REQ-006).
    """

    DNS = "dns"
    REFUSED = "refused"
    NO_ROUTE = "no_route"
    CONNECT_TIMEOUT = "connect_timeout"
    CREDENTIAL = "credential"
    HTTP_ERROR = "http_error"
    NO_RESPONSE = "no_response"
    INVALID_RESPONSE = "invalid_response"
    INVALID_URL = "invalid_url"
    TRANSPORT = "transport"
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value: object) -> ConnectionCause | None:
        new = legacy_names.CONNECTION_CAUSE_VALUES.get(value) if isinstance(value, str) else None
        return cls._value2member_map_.get(new) if new else None  # type: ignore[return-value]


class BackendView(NamedTuple):
    """Lo que `doctor` sabe del backend: si está sano, el texto que enseña y la causa.

    `source` dice quién lo vio: `"daemon"` (la causa viene del `/api/backend` del daemon) o
    `"direct"` (sondeo propio de esta consola). Importa para la pista de una credencial: no es lo
    mismo que falte la clave en la consola que en el lanzador del daemon (REQ-016). `cause` es
    `None` cuando está sano o cuando el daemon es antiguo y no la manda.
    """

    healthy: bool
    detail: str
    cause: str | None
    source: str


#: «No hay ruta»: los errno de la plataforma y, siempre, los de Winsock (10051 red inalcanzable,
#: 10065 host inalcanzable), que en Linux y macOS no coinciden con `errno.ENETUNREACH`.
_NO_ROUTE_ERRNOS = frozenset({errno.ENETUNREACH, errno.EHOSTUNREACH, 10051, 10065})

_CREDENTIAL_CODES = frozenset({401, 403})


def _chain(exc: BaseException) -> Iterator[BaseException]:
    """La excepción y todas las de sus `__cause__`/`__context__`, cada una una sola vez.

    Los visitados van por identidad: una cadena con ciclo (una excepción que es su propio
    `__context__`, o dos que se apuntan) termina en vez de dar vueltas.
    """
    seen: set[int] = set()
    pending: list[BaseException | None] = [exc]
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        pending.append(current.__context__)
        pending.append(current.__cause__)


def _is_no_route_errno(exc: BaseException) -> bool:
    return isinstance(exc, OSError) and exc.errno in _NO_ROUTE_ERRNOS


def connection_cause(event: BaseException | int, *, loopback: bool) -> ConnectionCause:
    """La causa de un fallo al hablar con el backend. Total: toda entrada tiene causa.

    `event` es el código de una respuesta no 2xx o la excepción que saltó. `loopback` dice si el
    **host real** de la URL es de loopback (no el origen declarado: un túnel en loopback hacia un
    backend remoto sigue siendo loopback para esto). Las reglas van en el orden de la tabla de
    REQ-010 y gana la primera; las 3 a 6 buscan en toda la cadena de la excepción y las demás miran
    solo la de arriba, así que una excepción propia que envuelva un `ConnectTimeout` cae en la 12.

    Un código 2xx no es un fallo: lanza `ValueError`, porque llamar así es un error de quien llama.
    """
    if isinstance(event, int):
        if 200 <= event < 300:
            raise ValueError(f"un {event} no es un fallo: no tiene causa que clasificar")
        # Reglas 1 y 2 para un código suelto.
        if event in _CREDENTIAL_CODES:
            return ConnectionCause.CREDENTIAL
        return ConnectionCause.HTTP_ERROR

    # 1 y 2. Un `HTTPStatusError` es un backend que contesta: lo que dice su código manda.
    if isinstance(event, httpx2.HTTPStatusError):
        if event.response.status_code in _CREDENTIAL_CODES:
            return ConnectionCause.CREDENTIAL
        return ConnectionCause.HTTP_ERROR

    chain = list(_chain(event))
    # 3. `InvalidURL` no es un `HTTPError` (comprobado contra el `httpx2` instalado): va por nombre.
    if any(isinstance(e, (httpx2.InvalidURL, httpx2.UnsupportedProtocol)) for e in chain):
        return ConnectionCause.INVALID_URL
    # 4. Va antes que 5 y 6: `gaierror` también es un `OSError`.
    if any(isinstance(e, socket.gaierror) for e in chain):
        return ConnectionCause.DNS
    # 5. `OSError(ECONNREFUSED, …)` ya nace como `ConnectionRefusedError`.
    if any(isinstance(e, ConnectionRefusedError) for e in chain):
        return ConnectionCause.REFUSED
    # 6. Red o host inalcanzable: inmediato y con su errno, distinto del timeout de una VPN.
    if any(_is_no_route_errno(e) for e in chain):
        return ConnectionCause.NO_ROUTE
    # 7. En Windows un puerto cerrado tarda ~2 s en rechazarse y con un plazo menor llega como
    #    `ConnectTimeout`. En loopback no hay ruta que perder: es que nadie escucha.
    if isinstance(event, httpx2.ConnectTimeout) and loopback:
        return ConnectionCause.REFUSED
    # 8. Incluye el plazo del kernel (el caso de la Mac: `TimeoutError(ETIMEDOUT)` en la cadena).
    if isinstance(event, httpx2.ConnectTimeout):
        return ConnectionCause.CONNECT_TIMEOUT
    # 9. Lectura, escritura o pool: la conexión sí se estableció.
    if isinstance(event, httpx2.TimeoutException):
        return ConnectionCause.NO_RESPONSE
    # 10. Un 2xx con un cuerpo que no es JSON o no tiene la forma esperada.
    if isinstance(event, ValueError):
        return ConnectionCause.INVALID_RESPONSE
    # 11.
    if isinstance(event, httpx2.HTTPError):
        return ConnectionCause.TRANSPORT
    # 12.
    return ConnectionCause.UNKNOWN


_LABELS: dict[ConnectionCause, str] = {
    ConnectionCause.DNS: "no resuelve",
    ConnectionCause.REFUSED: "nadie escucha",
    ConnectionCause.NO_ROUTE: "sin ruta",
    ConnectionCause.CONNECT_TIMEOUT: "no contesta",
    ConnectionCause.CREDENTIAL: "sin acceso",
    ConnectionCause.HTTP_ERROR: "responde con error",
    ConnectionCause.NO_RESPONSE: "no responde a tiempo",
    ConnectionCause.INVALID_RESPONSE: "respuesta no válida",
    ConnectionCause.INVALID_URL: "URL no válida",
    ConnectionCause.TRANSPORT: "fallo de red",
    ConnectionCause.UNKNOWN: "fallo inesperado",
}


def label(cause: ConnectionCause | str) -> str:
    """La etiqueta corta de la causa (la del badge). Acepta el valor en texto, como llega del JSON."""
    return _LABELS[ConnectionCause(cause)]


def detail(
    cause: ConnectionCause | str,
    *,
    host: str,
    status: int | None = None,
    endpoint: str | None = None,
    exception: BaseException | None = None,
) -> str:
    """El texto largo de la causa (REQ-011), con el host, el código y el endpoint que se pasen.

    Si falta `status` y la excepción es un `HTTPStatusError`, el código se toma de su respuesta.
    Lo que no se pase se omite del texto en vez de escribirse como `None`.
    """
    cause = ConnectionCause(cause)
    if status is None and isinstance(exception, httpx2.HTTPStatusError):
        status = exception.response.status_code
    type_suffix = f" ({type(exception).__name__})" if exception is not None else ""
    status_suffix = f" {status}" if status is not None else ""

    if cause is ConnectionCause.DNS:
        return f"no se resuelve el nombre {host} (¿VPN o DNS?)"
    if cause is ConnectionCause.REFUSED:
        return f"{host} rechaza la conexión: no hay nada escuchando en ese puerto"
    if cause is ConnectionCause.NO_ROUTE:
        return f"no hay ruta de red hacia {host}"
    if cause is ConnectionCause.CONNECT_TIMEOUT:
        return f"{host} no contesta a la conexión (ruta, cortafuegos o VPN)"
    if cause is ConnectionCause.CREDENTIAL:
        return f"{host} responde{status_suffix}: está arriba pero rechaza la credencial"
    if cause is ConnectionCause.HTTP_ERROR:
        if status is None:
            return f"{host} responde con un error HTTP"
        return f"{host} responde HTTP {status}"
    if cause is ConnectionCause.NO_RESPONSE:
        return f"{host} acepta la conexión pero no responde a tiempo"
    if cause is ConnectionCause.INVALID_RESPONSE:
        target = f" a {endpoint}" if endpoint else ""
        return f"{host} responde{target}, pero con un cuerpo que no se entiende"
    if cause is ConnectionCause.INVALID_URL:
        # Sin host, como en la tabla de REQ-011: con la URL rota, el host puede no significar nada.
        return f"la URL del backend no es válida{type_suffix}: revisa LOCAL_DELEGATE_BASE_URL"
    if cause is ConnectionCause.TRANSPORT:
        return f"fallo de red con {host}{type_suffix}"
    return f"fallo inesperado al sondear {host}{type_suffix}"


def hint(cause: ConnectionCause | str | None, *, origin: str, source: str, host: str) -> str:
    """Qué hacer ante la causa (tabla de REQ-016). Depende de quién la vio y de dónde corre el backend.

    `origin` es el de `config.backend_origin()`: solo `"local"` cuenta como local, así que un valor
    raro nunca manda a arrancar llama-swap aquí. `source` es la de `BackendView`. Una causa `None`
    (daemon antiguo que no la manda) o que este código no conoce da la pista genérica.
    """
    generic = f"revisa el backend en {host}"
    if cause is None:
        return generic
    try:
        cause = ConnectionCause(cause)
    except ValueError:
        return generic
    local = origin == "local"

    if cause is ConnectionCause.REFUSED:
        if local:
            return "arranca llama-swap (o revisa LOCAL_DELEGATE_BASE_URL)"
        return f"arranca llama-swap en {host} o revisa el puerto"
    if cause is ConnectionCause.DNS:
        if local:
            return "revisa el nombre en LOCAL_DELEGATE_BASE_URL"
        return (
            "revisa el nombre en LOCAL_DELEGATE_BASE_URL"
            " o usa la IP (p. ej. la 100.x de la tailnet)"
        )
    if cause in (ConnectionCause.NO_ROUTE, ConnectionCause.CONNECT_TIMEOUT):
        if local:
            return "revisa LOCAL_DELEGATE_BASE_URL"
        return f"revisa la red hacia {host} (VPN, cortafuegos, Tailscale)"
    if cause is ConnectionCause.CREDENTIAL:
        if source == "daemon":
            return "la clave del daemon no vale: revisa LOCAL_DELEGATE_API_KEY en su lanzador"
        return "exporta LOCAL_DELEGATE_API_KEY en este entorno"
    if cause in (
        ConnectionCause.HTTP_ERROR,
        ConnectionCause.INVALID_RESPONSE,
        ConnectionCause.INVALID_URL,
    ):
        return "revisa LOCAL_DELEGATE_BASE_URL"
    return generic
