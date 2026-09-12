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

from dataclasses import dataclass
from enum import Enum

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


#: Patrones que delatan un fallo de capacidad o de carga dentro de un 5xx.
#:
#: **Vacío a propósito.** REQ-020 exige que salgan de respuestas reales de llama-swap y
#: llama-server, capturadas con su versión anotada, y esa captura es trabajo de F3. Inventarlos
#: aquí sería justo el error que la spec prohíbe: un patrón adivinado que lee un OOM como fallo del
#: modelo haría saltar el respaldo a otro modelo grande y encadenaría swaps y OOM. Mientras la
#: tupla esté vacía, todo 5xx se clasifica como `MODELO`, que es el comportamiento de la tabla.
PATRONES_DE_CAPACIDAD: tuple[str, ...] = ()


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
    if isinstance(contenido, str):
        # Un contenido vacío ("") NO es un fallo: se trata como hoy. Solo cuenta el nulo o ausente.
        return None

    motivo = primera.get("finish_reason")
    razonamiento = mensaje.get("reasoning_content") or ""
    if motivo == "length":
        # El modelo se gastó `max_tokens` pensando y no llegó a contestar. Es configuración, no
        # avería: taparlo con un respaldo haría que nadie lo arreglara nunca.
        if razonamiento.strip():
            return Clase.CONFIGURACION
        # Mismo síntoma sin rastro de razonamiento: no se sabe qué pasó, y adivinar aquí es
        # justo lo que la regla de la casa prohíbe.
        return Clase.SIN_CLASIFICAR
    return Clase.MODELO
