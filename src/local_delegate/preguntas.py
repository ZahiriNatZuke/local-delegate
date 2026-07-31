"""Preguntar al usuario en vez de fallar seco, vía `elicitation` del protocolo MCP.

Tres sitios del servidor fallan hoy con un error de texto aunque **ya sepan la solución**: el
backend está caído y hay un arranque disponible; el modelo pedido no existe y la lista de válidos va
en el propio mensaje de error; `output_format` viene vacío y nadie lo comprueba. En los tres, la
respuesta correcta no es adivinar ni rendirse: es preguntar.

Se apoya en tres cosas **medidas** contra el SDK instalado, ninguna evidente
(traza en `.sdd/changes/elicitation-preguntar-en-vez-de-fallar/`):

1. **Las 11 tools son síncronas y aun así pueden preguntar.** `anyio.from_thread.run(corrutina)`
   funciona desde el hilo del threadpool en el que el SDK las ejecuta. No hubo que convertir nada
   a `async`.
2. **El contexto llega solo.** Un `ContextVar` puesto por un `ServerMiddleware` se ve desde la tool
   síncrona, y desde cualquier capa por debajo de ella: anyio copia el contexto al hilo. Por eso
   `_post_chat` puede preguntar sin que ninguna de las 15 firmas de la cadena cambie — y por eso el
   schema público de las tools **no se toca**.
3. **El plazo tiene que ir DENTRO de la corrutina.** Un cliente que declara `elicitation` y no
   contesta cuelga la tool para siempre: el SDK no impone timeout. Y la forma intuitiva de ponerlo
   —`anyio.move_on_after` alrededor de `from_thread.run`— **ni siquiera se puede escribir**: lanza
   `NoEventLoopError`, porque desde el hilo no hay event loop que consultar. Lo cazó la revisión
   adversarial del plan y se confirmó midiendo.

Regla de la casa que hereda este módulo: **preguntar nunca puede empeorar nada**. Todo camino malo
—cliente sin la capability, sin canal de vuelta, que no responde, que dice que no, o una excepción
inesperada— devuelve `None`, y quien llama sigue haciendo exactamente lo que hacía antes.
"""

from __future__ import annotations

import contextvars
import logging
from typing import Any, TypeVar

import anyio
from pydantic import BaseModel

from . import config

logger = logging.getLogger(__name__)

ModeloT = TypeVar("ModeloT", bound=BaseModel)

# El contexto de la petición en curso. Lo puebla `recordar_contexto` y lo lee `preguntar` desde
# cualquier profundidad, incluida una tool síncrona corriendo en el threadpool.
CTX_ACTUAL: contextvars.ContextVar[Any | None] = contextvars.ContextVar("ctx_actual", default=None)


async def recordar_contexto(ctx: Any, call_next: Any) -> Any:
    """Middleware: deja el contexto de esta petición al alcance de las capas de abajo.

    Va DESPUÉS del observador de `clients.py` en la lista de `middleware=` (el SDK los aplica
    outermost-first): «observar primero, habilitar después». Hoy son independientes; el orden se
    fija para que nadie lo cambie creyendo que da igual.
    """
    CTX_ACTUAL.set(ctx)
    return await call_next(ctx)


def puede_preguntar() -> bool:
    """Si hay a quién preguntar y por dónde.

    Son **dos** condiciones independientes y las dos hacen falta. Que el cliente declare
    `elicitation` no implica que se le pueda hablar: desde la revisión 2026-07-28 el protocolo
    prohíbe las peticiones iniciadas por el servidor en algunos transportes, y `elicit` respondería
    con `NoBackChannelError`.
    """
    if not config.ASK_ENABLED:
        return False
    ctx = CTX_ACTUAL.get()
    if ctx is None:
        return False
    try:
        sesion = ctx.session
        caps = sesion.client_capabilities
        if caps is None or getattr(caps, "elicitation", None) is None:
            return False
        return bool(sesion.can_send_request)
    except Exception:
        return False


def preguntar(mensaje: str, modelo: type[ModeloT]) -> ModeloT | None:
    """Pregunta al usuario y devuelve la respuesta, o `None` si no la hay.

    `None` cubre a propósito **todos** los caminos malos —no se puede preguntar, no contestan a
    tiempo, dicen que no, la respuesta no valida, algo revienta—, para que quien llama tenga una
    sola rama y no pueda olvidarse de un caso.
    """
    if not puede_preguntar():
        return None
    ctx = CTX_ACTUAL.get()
    # `ServerRequestContext` —lo que ve un middleware— NO tiene `.elicit`: eso es del `Context` de
    # alto nivel, que solo llega a las tools que lo declaran en su firma. Desde aquí se va por la
    # sesión, que expone `elicit_form` con el esquema como dict y devuelve la respuesta en crudo,
    # así que la validación contra el modelo la hacemos nosotros.
    esquema = modelo.model_json_schema()

    async def _con_plazo():
        # El plazo va AQUÍ, dentro de la corrutina que corre en el event loop. Ponerlo del lado
        # del hilo lanza NoEventLoopError; está medido.
        with anyio.move_on_after(config.ASK_TIMEOUT):
            return await ctx.session.elicit_form(mensaje, esquema)
        return None

    try:
        resultado = anyio.from_thread.run(_con_plazo)
    except Exception:
        logger.debug("no se pudo preguntar al cliente", exc_info=True)
        return None

    if resultado is None:  # plazo agotado
        logger.debug("el cliente no respondió en %ss", config.ASK_TIMEOUT)
        return None
    if getattr(resultado, "action", None) != "accept":  # decline o cancel
        return None
    try:
        return modelo.model_validate(resultado.content or {})
    except Exception:
        # Respondieron algo que no encaja con lo pedido: cuenta como no haber respondido.
        logger.debug("la respuesta del cliente no valida contra el esquema", exc_info=True)
        return None


# --- Los esquemas de las preguntas -------------------------------------------
# Solo tipos primitivos: es lo que admite la especificación de elicitation.


class ArrancarBackend(BaseModel):
    """¿Arrancar el backend local que no responde?"""

    arrancar: bool


class ElegirModelo(BaseModel):
    """Cuál de los modelos del catálogo usar."""

    modelo: str


class ElegirFormato(BaseModel):
    """Qué formato de salida se espera."""

    formato: str
