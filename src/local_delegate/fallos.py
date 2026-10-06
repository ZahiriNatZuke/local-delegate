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

Regla de la casa para este módulo: **lo que no encaje va a `SIN_CLASIFICAR`, nunca a `MODELO`.**
Equivocarse hacia `MODELO` es lo caro: es la única clase que dispara el respaldo y suma para el
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


class Clase(str, Enum):
    """Las siete clases de la tabla de la spec. Hereda de `str` para que el log las escriba solas."""

    ENDPOINT = "endpoint"
    PETICION = "peticion"
    CAPACIDAD = "capacidad_o_carga"
    TIMEOUT_LECTURA = "timeout_lectura"
    CONFIGURACION = "configuracion"
    MODELO = "modelo"
    SIN_CLASIFICAR = "sin_clasificar"


#: Patrones que delatan un fallo de capacidad o de carga dentro de un 5xx, en minúsculas.
#:
#: Salen de respuestas **reales**, nunca adivinadas (REQ-020): un patrón inventado que leyera un OOM
#: como fallo del modelo haría saltar el respaldo a otro modelo grande y encadenaría swaps y OOM.
#: Cada uno lleva la versión de la que salió; si el backend cambia, se recapturan
#: (`tests/fixtures/backend/`, `tests/test_fallos_capturas.py`).
PATRONES_DE_CAPACIDAD: tuple[str, ...] = (
    # llama-swap v255 + llama-server b10909, capturado el 2026-09-15. Es el 500 que da llama-swap
    # cuando el `llama-server` que arranca muere antes de estar listo, y es el MISMO cuerpo, byte a
    # byte, para un OOM con la política «Prefer No Sysmem Fallback» y para un modelo que no existe.
    "upstream command exited prematurely",
)


@dataclass(frozen=True)
class Respuesta:
    """Lo justo que hace falta de una respuesta HTTP para clasificarla.

    No es el objeto vivo de `httpx2` a propósito: así el clasificador se puede probar entero sin
    montar una respuesta real, y no hay forma de que alguien le pida el cuerpo dos veces.
    """

    status: int
    #: El JSON ya parseado, o `None` si no se pudo parsear (que en sí mismo es un fallo del modelo).
    datos: dict | None = None
    #: El cuerpo crudo, recortado. Solo se usa para los patrones de capacidad.
    texto: str = ""


def clasificar(
    suceso: BaseException | Respuesta,
    *,
    modelo_cargado: bool | None = None,
) -> Clase | None:
    """La clase del fallo, o `None` si lo que llegó no es un fallo.

    `modelo_cargado` dice si el modelo ya estaba en memoria cuando venció el plazo de lectura.
    `None` significa «no se sabe», que es lo normal en F0: sin esa señal, un `ReadTimeout` se lee
    como carga y no como modelo colgado.
    """
    if isinstance(suceso, BaseException):
        return _clasificar_excepcion(suceso, modelo_cargado=modelo_cargado)
    return _clasificar_respuesta(suceso)


def es_backend_ausente(suceso: BaseException | Respuesta) -> bool:
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
    return isinstance(suceso, (httpx2.ConnectError, httpx2.ConnectTimeout))


def _clasificar_excepcion(exc: BaseException, *, modelo_cargado: bool | None) -> Clase:
    # `ReadTimeout` va ANTES que su padre `TimeoutException` y que el `HTTPError` genérico: es la
    # única excepción de transporte que no es culpa del endpoint, porque ahí el backend sí aceptó
    # la conexión. `ConnectTimeout` no necesita rama propia —cae en `HTTPError` y ya da ENDPOINT—;
    # lo que sí necesita es `es_backend_ausente()`, que es donde su diferencia se nota.
    if isinstance(exc, httpx2.ReadTimeout):
        return Clase.TIMEOUT_LECTURA if modelo_cargado else Clase.CAPACIDAD
    if isinstance(exc, httpx2.HTTPStatusError):
        return _clasificar_status(exc.response.status_code, getattr(exc.response, "text", ""))
    # `ConnectError`, el resto de timeouts (`WriteTimeout`, `PoolTimeout`) y cualquier otro error
    # de transporte: el modelo no llegó a responder, así que no se le puede achacar nada.
    if isinstance(exc, httpx2.HTTPError):
        return Clase.ENDPOINT
    return Clase.SIN_CLASIFICAR


def _clasificar_respuesta(respuesta: Respuesta) -> Clase | None:
    if respuesta.status >= 400:
        return _clasificar_status(respuesta.status, respuesta.texto)
    if not 200 <= respuesta.status < 300:
        # Un 1xx o un 3xx que llegue hasta aqui no es lo que el protocolo espera, pero tampoco hay
        # nada que achacarle al modelo: no llego a responder una peticion de chat.
        return Clase.SIN_CLASIFICAR
    if respuesta.datos is None:
        # Se recibió un 2xx que no era JSON: el modelo respondió algo roto.
        return Clase.MODELO
    return _clasificar_cuerpo(respuesta.datos)


def _clasificar_status(status: int, texto: str) -> Clase:
    if 400 <= status < 500:
        # Incluye el desborde de contexto (400), el schema no soportado y la autenticación. Culpa
        # de la petición: cambiar de modelo no arregla ninguno.
        return Clase.PETICION
    if status >= 500:
        minusculas = texto.lower()
        if any(patron in minusculas for patron in PATRONES_DE_CAPACIDAD):
            return Clase.CAPACIDAD
        return Clase.MODELO
    return Clase.SIN_CLASIFICAR


def _clasificar_cuerpo(datos: dict) -> Clase | None:
    choices = datos.get("choices")
    if not isinstance(choices, list) or not choices:
        return Clase.MODELO
    primera = choices[0]
    if not isinstance(primera, dict):
        return Clase.MODELO
    mensaje = primera.get("message")
    if not isinstance(mensaje, dict):
        return Clase.MODELO

    contenido = mensaje.get("content")
    motivo = primera.get("finish_reason")
    razonamiento = mensaje.get("reasoning_content") or ""
    if isinstance(contenido, str):
        # Un contenido vacío ("") NO es un fallo: se trata como hoy. Con UNA excepción, decidida por
        # el usuario el 2026-09-15: vacío + `length` + razonamiento es la forma REAL en que
        # llama-server b10909 devuelve un razonamiento que agotó `max_tokens` (capturado; no llega
        # como `null`). Sin esta rama la clase de configuración no saltaba nunca contra el backend
        # real y la respuesta vacía llegaba como éxito.
        if not contenido.strip() and motivo == "length" and razonamiento.strip():
            return Clase.CONFIGURACION
        return None

    if motivo == "length":
        # El modelo se gastó `max_tokens` pensando y no llegó a contestar. Es configuración, no
        # avería: taparlo con un respaldo haría que nadie lo arreglara nunca.
        if razonamiento.strip():
            return Clase.CONFIGURACION
        # Mismo síntoma sin rastro de razonamiento: no se sabe qué pasó, y adivinar aquí es
        # justo lo que la regla de la casa prohíbe.
        return Clase.SIN_CLASIFICAR
    return Clase.MODELO


# --- Causa de un fallo de conexión ------------------------------------------------------------
#
# Responde a otra pregunta que `clasificar`. Aquella decide respaldo y enfriamiento; esta le dice a
# una persona POR QUÉ no se llega al backend, con el mismo texto en el panel, en `local_status`, en
# `doctor` y en el error de una delegación (REQ-010, REQ-011, REQ-016). Por eso nadie fuera de aquí
# redacta los textos de una causa. Sigue la regla del módulo: sin red y sin leer configuración;
# host, loopback, origen, fuente, código y endpoint entran como argumentos.


class CausaConexion(str, Enum):
    """Las once causas de REQ-010. Hereda de `str` para viajar tal cual en el JSON y en el log."""

    DNS = "dns"
    RECHAZADA = "rechazada"
    SIN_RUTA = "sin_ruta"
    TIMEOUT_CONEXION = "timeout_conexion"
    CREDENCIAL = "credencial"
    HTTP_ERROR = "http_error"
    SIN_RESPUESTA = "sin_respuesta"
    RESPUESTA_INVALIDA = "respuesta_invalida"
    URL_INVALIDA = "url_invalida"
    TRANSPORTE = "transporte"
    DESCONOCIDA = "desconocida"


class VistaBackend(NamedTuple):
    """Lo que `doctor` sabe del backend: si está sano, el texto que enseña y la causa.

    `fuente` dice quién lo vio: `"daemon"` (la causa viene del `/api/backend` del daemon) o
    `"directo"` (sondeo propio de esta consola). Importa para la pista de una credencial: no es lo
    mismo que falte la clave en la consola que en el lanzador del daemon (REQ-016). `causa` es
    `None` cuando está sano o cuando el daemon es antiguo y no la manda.
    """

    sano: bool
    detalle: str
    causa: str | None
    fuente: str


#: «No hay ruta»: los errno de la plataforma y, siempre, los de Winsock (10051 red inalcanzable,
#: 10065 host inalcanzable), que en Linux y macOS no coinciden con `errno.ENETUNREACH`.
_ERRNO_SIN_RUTA = frozenset({errno.ENETUNREACH, errno.EHOSTUNREACH, 10051, 10065})

_CODIGOS_DE_CREDENCIAL = frozenset({401, 403})


def _cadena(exc: BaseException) -> Iterator[BaseException]:
    """La excepción y todas las de sus `__cause__`/`__context__`, cada una una sola vez.

    Los visitados van por identidad: una cadena con ciclo (una excepción que es su propio
    `__context__`, o dos que se apuntan) termina en vez de dar vueltas.
    """
    vistas: set[int] = set()
    pendientes: list[BaseException | None] = [exc]
    while pendientes:
        actual = pendientes.pop()
        if actual is None or id(actual) in vistas:
            continue
        vistas.add(id(actual))
        yield actual
        pendientes.append(actual.__context__)
        pendientes.append(actual.__cause__)


def _errno_sin_ruta(exc: BaseException) -> bool:
    return isinstance(exc, OSError) and exc.errno in _ERRNO_SIN_RUTA


def causa_conexion(suceso: BaseException | int, *, loopback: bool) -> CausaConexion:
    """La causa de un fallo al hablar con el backend. Total: toda entrada tiene causa.

    `suceso` es el código de una respuesta no 2xx o la excepción que saltó. `loopback` dice si el
    **host real** de la URL es de loopback (no el origen declarado: un túnel en loopback hacia un
    backend remoto sigue siendo loopback para esto). Las reglas van en el orden de la tabla de
    REQ-010 y gana la primera; las 3 a 6 buscan en toda la cadena de la excepción y las demás miran
    solo la de arriba, así que una excepción propia que envuelva un `ConnectTimeout` cae en la 12.

    Un código 2xx no es un fallo: lanza `ValueError`, porque llamar así es un error de quien llama.
    """
    if isinstance(suceso, int):
        if 200 <= suceso < 300:
            raise ValueError(f"un {suceso} no es un fallo: no tiene causa que clasificar")
        # Reglas 1 y 2 para un código suelto.
        if suceso in _CODIGOS_DE_CREDENCIAL:
            return CausaConexion.CREDENCIAL
        return CausaConexion.HTTP_ERROR

    # 1 y 2. Un `HTTPStatusError` es un backend que contesta: lo que dice su código manda.
    if isinstance(suceso, httpx2.HTTPStatusError):
        if suceso.response.status_code in _CODIGOS_DE_CREDENCIAL:
            return CausaConexion.CREDENCIAL
        return CausaConexion.HTTP_ERROR

    cadena = list(_cadena(suceso))
    # 3. `InvalidURL` no es un `HTTPError` (comprobado contra el `httpx2` instalado): va por nombre.
    if any(isinstance(e, (httpx2.InvalidURL, httpx2.UnsupportedProtocol)) for e in cadena):
        return CausaConexion.URL_INVALIDA
    # 4. Va antes que 5 y 6: `gaierror` también es un `OSError`.
    if any(isinstance(e, socket.gaierror) for e in cadena):
        return CausaConexion.DNS
    # 5. `OSError(ECONNREFUSED, …)` ya nace como `ConnectionRefusedError`.
    if any(isinstance(e, ConnectionRefusedError) for e in cadena):
        return CausaConexion.RECHAZADA
    # 6. Red o host inalcanzable: inmediato y con su errno, distinto del timeout de una VPN.
    if any(_errno_sin_ruta(e) for e in cadena):
        return CausaConexion.SIN_RUTA
    # 7. En Windows un puerto cerrado tarda ~2 s en rechazarse y con un plazo menor llega como
    #    `ConnectTimeout`. En loopback no hay ruta que perder: es que nadie escucha.
    if isinstance(suceso, httpx2.ConnectTimeout) and loopback:
        return CausaConexion.RECHAZADA
    # 8. Incluye el plazo del kernel (el caso de la Mac: `TimeoutError(ETIMEDOUT)` en la cadena).
    if isinstance(suceso, httpx2.ConnectTimeout):
        return CausaConexion.TIMEOUT_CONEXION
    # 9. Lectura, escritura o pool: la conexión sí se estableció.
    if isinstance(suceso, httpx2.TimeoutException):
        return CausaConexion.SIN_RESPUESTA
    # 10. Un 2xx con un cuerpo que no es JSON o no tiene la forma esperada.
    if isinstance(suceso, ValueError):
        return CausaConexion.RESPUESTA_INVALIDA
    # 11.
    if isinstance(suceso, httpx2.HTTPError):
        return CausaConexion.TRANSPORTE
    # 12.
    return CausaConexion.DESCONOCIDA


_ETIQUETAS: dict[CausaConexion, str] = {
    CausaConexion.DNS: "no resuelve",
    CausaConexion.RECHAZADA: "nadie escucha",
    CausaConexion.SIN_RUTA: "sin ruta",
    CausaConexion.TIMEOUT_CONEXION: "no contesta",
    CausaConexion.CREDENCIAL: "sin acceso",
    CausaConexion.HTTP_ERROR: "responde con error",
    CausaConexion.SIN_RESPUESTA: "no responde a tiempo",
    CausaConexion.RESPUESTA_INVALIDA: "respuesta no válida",
    CausaConexion.URL_INVALIDA: "URL no válida",
    CausaConexion.TRANSPORTE: "fallo de red",
    CausaConexion.DESCONOCIDA: "fallo inesperado",
}


def etiqueta(causa: CausaConexion | str) -> str:
    """La etiqueta corta de la causa (la del badge). Acepta el valor en texto, como llega del JSON."""
    return _ETIQUETAS[CausaConexion(causa)]


def detalle(
    causa: CausaConexion | str,
    *,
    host: str,
    status: int | None = None,
    endpoint: str | None = None,
    excepcion: BaseException | None = None,
) -> str:
    """El texto largo de la causa (REQ-011), con el host, el código y el endpoint que se pasen.

    Si falta `status` y la excepción es un `HTTPStatusError`, el código se toma de su respuesta.
    Lo que no se pase se omite del texto en vez de escribirse como `None`.
    """
    causa = CausaConexion(causa)
    if status is None and isinstance(excepcion, httpx2.HTTPStatusError):
        status = excepcion.response.status_code
    tipo = f" ({type(excepcion).__name__})" if excepcion is not None else ""
    codigo = f" {status}" if status is not None else ""

    if causa is CausaConexion.DNS:
        return f"no se resuelve el nombre {host} (¿VPN o DNS?)"
    if causa is CausaConexion.RECHAZADA:
        return f"{host} rechaza la conexión: no hay nada escuchando en ese puerto"
    if causa is CausaConexion.SIN_RUTA:
        return f"no hay ruta de red hacia {host}"
    if causa is CausaConexion.TIMEOUT_CONEXION:
        return f"{host} no contesta a la conexión (ruta, cortafuegos o VPN)"
    if causa is CausaConexion.CREDENCIAL:
        return f"{host} responde{codigo}: está arriba pero rechaza la credencial"
    if causa is CausaConexion.HTTP_ERROR:
        if status is None:
            return f"{host} responde con un error HTTP"
        return f"{host} responde HTTP {status}"
    if causa is CausaConexion.SIN_RESPUESTA:
        return f"{host} acepta la conexión pero no responde a tiempo"
    if causa is CausaConexion.RESPUESTA_INVALIDA:
        a_quien = f" a {endpoint}" if endpoint else ""
        return f"{host} responde{a_quien}, pero con un cuerpo que no se entiende"
    if causa is CausaConexion.URL_INVALIDA:
        # Sin host, como en la tabla de REQ-011: con la URL rota, el host puede no significar nada.
        return f"la URL del backend no es válida{tipo}: revisa LOCAL_DELEGATE_BASE_URL"
    if causa is CausaConexion.TRANSPORTE:
        return f"fallo de red con {host}{tipo}"
    return f"fallo inesperado al sondear {host}{tipo}"


def pista(causa: CausaConexion | str | None, *, origen: str, fuente: str, host: str) -> str:
    """Qué hacer ante la causa (tabla de REQ-016). Depende de quién la vio y de dónde corre el backend.

    `origen` es el de `config.backend_origin()`: solo `"local"` cuenta como local, así que un valor
    raro nunca manda a arrancar llama-swap aquí. `fuente` es la de `VistaBackend`. Una causa `None`
    (daemon antiguo que no la manda) o que este código no conoce da la pista genérica.
    """
    generica = f"revisa el backend en {host}"
    if causa is None:
        return generica
    try:
        causa = CausaConexion(causa)
    except ValueError:
        return generica
    local = origen == "local"

    if causa is CausaConexion.RECHAZADA:
        if local:
            return "arranca llama-swap (o revisa LOCAL_DELEGATE_BASE_URL)"
        return f"arranca llama-swap en {host} o revisa el puerto"
    if causa is CausaConexion.DNS:
        if local:
            return "revisa el nombre en LOCAL_DELEGATE_BASE_URL"
        return (
            "revisa el nombre en LOCAL_DELEGATE_BASE_URL"
            " o usa la IP (p. ej. la 100.x de la tailnet)"
        )
    if causa in (CausaConexion.SIN_RUTA, CausaConexion.TIMEOUT_CONEXION):
        if local:
            return "revisa LOCAL_DELEGATE_BASE_URL"
        return f"revisa la red hacia {host} (VPN, cortafuegos, Tailscale)"
    if causa is CausaConexion.CREDENCIAL:
        if fuente == "daemon":
            return "la clave del daemon no vale: revisa LOCAL_DELEGATE_API_KEY en su lanzador"
        return "exporta LOCAL_DELEGATE_API_KEY en este entorno"
    if causa in (
        CausaConexion.HTTP_ERROR,
        CausaConexion.RESPUESTA_INVALIDA,
        CausaConexion.URL_INVALIDA,
    ):
        return "revisa LOCAL_DELEGATE_BASE_URL"
    return generica
