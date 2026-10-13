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
from pydantic import BaseModel, ConfigDict, Field

from . import config

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

# El contexto de la petición en curso. Lo puebla `remember_context` y lo lee `ask` desde
# cualquier profundidad, incluida una tool síncrona corriendo en el threadpool.
CURRENT_CTX: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "current_ctx", default=None
)


async def remember_context(ctx: Any, call_next: Any) -> Any:
    """Middleware: deja el contexto de esta petición al alcance de las capas de abajo.

    Va DESPUÉS del observador de `clients.py` en la lista de `middleware=` (el SDK los aplica
    outermost-first): «observar primero, habilitar después». Hoy son independientes; el orden se
    fija para que nadie lo cambie creyendo que da igual.
    """
    CURRENT_CTX.set(ctx)
    return await call_next(ctx)


def can_ask() -> bool:
    """Si hay a quién preguntar y por dónde.

    Son **dos** condiciones independientes y las dos hacen falta. Que el cliente declare
    `elicitation` no implica que se le pueda hablar: desde la revisión 2026-07-28 el protocolo
    prohíbe las peticiones iniciadas por el servidor en algunos transportes, y `elicit` respondería
    con `NoBackChannelError`.
    """
    if not config.ASK_ENABLED:
        return False
    ctx = CURRENT_CTX.get()
    if ctx is None:
        return False
    try:
        session = ctx.session
        caps = session.client_capabilities
        if caps is None or getattr(caps, "elicitation", None) is None:
            return False
        return bool(session.can_send_request)
    except Exception:
        return False


def ask(message: str, model: type[ModelT]) -> ModelT | None:
    """Pregunta al usuario y devuelve la respuesta, o `None` si no la hay.

    `None` cubre a propósito **todos** los caminos malos —no se puede preguntar, no contestan a
    tiempo, dicen que no, la respuesta no valida, algo revienta—, para que quien llama tenga una
    sola rama y no pueda olvidarse de un caso.
    """
    if not can_ask():
        return None
    ctx = CURRENT_CTX.get()
    # `ServerRequestContext` —lo que ve un middleware— NO tiene `.elicit`: eso es del `Context` de
    # alto nivel, que solo llega a las tools que lo declaran en su firma. Desde aquí se va por la
    # sesión, que expone `elicit_form` con el esquema como dict y devuelve la respuesta en crudo,
    # así que la validación contra el modelo la hacemos nosotros.
    schema = model.model_json_schema()

    async def _with_timeout():
        # El plazo va AQUÍ, dentro de la corrutina que corre en el event loop. Ponerlo del lado
        # del hilo lanza NoEventLoopError; está medido.
        #
        # Se lee el `cancel_scope` en vez de poner un `return None` detrás del `with`: aquel
        # camino es perfectamente alcanzable —es lo que hace anyio al cancelar— pero CodeQL no
        # modela la cancelación y lo marcaba como código muerto. Así no hay que suprimir un aviso
        # falso, y de paso queda explícito por qué la respuesta puede faltar.
        response = None
        with anyio.move_on_after(config.ASK_TIMEOUT) as scope:
            response = await ctx.session.elicit_form(message, schema)
        return None if scope.cancelled_caught else response

    try:
        result = anyio.from_thread.run(_with_timeout)
    except Exception:
        logger.debug("no se pudo preguntar al cliente", exc_info=True)
        return None

    if result is None:  # plazo agotado
        logger.debug("el cliente no respondió en %ss", config.ASK_TIMEOUT)
        return None
    if getattr(result, "action", None) != "accept":  # decline o cancel
        return None
    try:
        return model.model_validate(result.content or {})
    except Exception:
        # Respondieron algo que no encaja con lo pedido: cuenta como no haber respondido.
        logger.debug("la respuesta del cliente no valida contra el esquema", exc_info=True)
        return None


# --- Los esquemas de las preguntas -------------------------------------------
# Solo tipos primitivos: es lo que admite la especificación de elicitation.


class StartBackend(BaseModel):
    """¿Arrancar el backend local que no responde?"""

    model_config = ConfigDict(title="ArrancarBackend")

    start: bool = Field(title="Arrancar")


class ChooseModel(BaseModel):
    """Cuál de los modelos del catálogo usar."""

    model_config = ConfigDict(title="ElegirModelo")

    model: str = Field(title="Modelo")


class ChooseFormat(BaseModel):
    """Qué formato de salida se espera."""

    model_config = ConfigDict(title="ElegirFormato")

    format: str = Field(title="Formato")
