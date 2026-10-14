"""Pruebas de `questions.py`: preguntar en vez de fallar seco.

Las de integración montan un `MCPServer` real con un `ClientSession` real, como en
`test_clients.py`. Aquí es todavía más necesario: lo que hay que comprobar —que el plazo corta de
verdad desde un hilo del threadpool— **no se puede medir con un doble**, y la forma intuitiva de
implementarlo ni siquiera funciona (lanza `NoEventLoopError`).
"""

from __future__ import annotations

import json
import time

import anyio
import backend_mock
import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.server.mcpserver import MCPServer
from mcp.shared.memory import create_client_server_memory_streams
from mcp.types import ElicitResult, Implementation
from pydantic import BaseModel

from local_delegate import config, questions, server


class Answer(BaseModel):
    value: str


@pytest.fixture(autouse=True)
def clean_context(monkeypatch):
    monkeypatch.setattr(questions.config, "ASK_ENABLED", True)
    monkeypatch.setattr(questions.config, "ASK_TIMEOUT", 2)
    questions.CURRENT_CTX.set(None)
    yield
    questions.CURRENT_CTX.set(None)


# --- puede_preguntar: las dos condiciones, por separado ----------------------


class _Caps:
    def __init__(self, elicitation):
        self.elicitation = elicitation


_DECLARED = object()  # marcador: "el cliente declaró la capability"


class _Session:
    def __init__(self, elicitation=_DECLARED, channel=True):
        self.client_capabilities = _Caps(elicitation)
        self.can_send_request = channel


class _Ctx:
    def __init__(self, **kw):
        self.session = _Session(**kw)


def test_without_context_it_cannot_ask():
    assert questions.can_ask() is False


def test_with_capability_and_channel_it_can():
    questions.CURRENT_CTX.set(_Ctx())
    assert questions.can_ask() is True


def test_without_the_capability_it_cannot():
    questions.CURRENT_CTX.set(_Ctx(elicitation=None))
    assert questions.can_ask() is False


def test_with_capability_but_no_channel_it_cannot_either():
    # Son dos condiciones independientes: declarar `elicitation` no implica que se pueda hablar.
    questions.CURRENT_CTX.set(_Ctx(channel=False))
    assert questions.can_ask() is False


def test_disabled_by_configuration(monkeypatch):
    monkeypatch.setattr(questions.config, "ASK_ENABLED", False)
    questions.CURRENT_CTX.set(_Ctx())
    assert questions.can_ask() is False
    assert questions.ask("¿?", Answer) is None


def test_a_session_that_blows_up_does_not_propagate():
    class _Broken:
        @property
        def session(self):
            raise RuntimeError("boom")

    questions.CURRENT_CTX.set(_Broken())
    assert questions.can_ask() is False
    assert questions.ask("¿?", Answer) is None


# --- integración con servidor y cliente reales -------------------------------


def _mount(client_answer, tool_fn):
    server = MCPServer("prueba", version="0.0.0", middleware=[questions.remember_context])
    server.tool()(tool_fn)
    return server


async def _run(server, callback, name="try_it"):
    async with create_client_server_memory_streams() as ((cr, cw), (sr, sw)):
        low = server._lowlevel_server
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: low.run(sr, sw, low.create_initialization_options(), raise_exceptions=True)
            )
            kwargs = {"elicitation_callback": callback} if callback is not None else {}
            async with ClientSession(
                cr, cw, client_info=Implementation(name="prueba", version="1.0"), **kwargs
            ) as client:
                await client.initialize()
                res = await client.call_tool(name, {})
                text = res.content[0].text if res.content else "(vacio)"
            tg.cancel_scope.cancel()
    return text


def try_it() -> str:
    """Tool SÍNCRONA que pregunta desde su hilo, como hacen las 11 de verdad."""
    r = questions.ask("¿Cual?", Answer)
    return f"respuesta={r.value if r is not None else None}"


async def accepts(context, params):
    return ElicitResult(action="accept", content={"value": "elegido"})


async def declines(context, params):
    return ElicitResult(action="decline")


async def cancels(context, params):
    return ElicitResult(action="cancel")


async def silent(context, params):
    await anyio.sleep(3600)


def test_the_user_answers():
    assert anyio.run(_run, _mount(None, try_it), accepts) == "respuesta=elegido"


def test_the_user_declines():
    assert anyio.run(_run, _mount(None, try_it), declines) == "respuesta=None"


def test_the_user_cancels():
    # `cancel` y `decline` son cosas distintas en el protocolo pero aquí significan lo mismo: no.
    assert anyio.run(_run, _mount(None, try_it), cancels) == "respuesta=None"


def test_client_without_elicitation_support():
    assert anyio.run(_run, _mount(None, try_it), None) == "respuesta=None"


def test_the_client_that_does_not_answer_does_not_hang_the_tool():
    """REQ-006, y es la prueba que justifica el diseño del plazo.

    Mide que la tool **vuelve sola**, no que se la pueda cortar desde fuera: un test que corta
    desde fuera pasa igual con el plazo mal puesto, y el plazo mal puesto —`move_on_after`
    alrededor de `from_thread.run`— lanza `NoEventLoopError`, que el `except` se tragaría. El
    síntoma sería «nunca se pregunta», silencioso.
    """
    t0 = time.monotonic()
    result = anyio.run(_run, _mount(None, try_it), silent)
    elapsed = time.monotonic() - t0
    assert result == "respuesta=None"
    # ASK_TIMEOUT es 2s en el fixture; con holgura para el arranque del servidor.
    assert elapsed < 15, f"la tool tardó {elapsed:.1f}s: el plazo no está cortando"


def test_the_timeout_expires_and_not_before():
    """Complemento del anterior: que no devuelva None por no haber preguntado siquiera."""
    t0 = time.monotonic()
    anyio.run(_run, _mount(None, try_it), silent)
    elapsed = time.monotonic() - t0
    assert elapsed >= 2, (
        f"volvió en {elapsed:.1f}s, antes del plazo: no llegó a preguntar de verdad"
    )


# --- los tres puntos de uso --------------------------------------------------
# El mecanismo ya está probado end-to-end arriba; aquí se dobla `ask` para ejercer la lógica
# de cada punto de uso sin volver a montar un servidor MCP.


def _reply(value):
    """Doble de `ask` que devuelve el modelo pedido relleno con `value`."""

    def _fn(message, model):
        field = next(iter(model.model_fields))
        return model(**{field: value})

    return _fn


def _no_answer(message, model):
    return None


@backend_mock.mock
def _delegate(monkeypatch, tmp_path, **kw):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    seen: list[dict] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    args = {"task": "t", "input": "i", "output_format": "bullets"}
    args.update(kw)
    return server.local_delegate(**args), seen


def test_invalid_model_with_answer_continues_with_the_chosen_one(monkeypatch, tmp_path):
    """REQ-003."""
    valid = min(config.ALLOWED_MODELS)
    monkeypatch.setattr(server.questions, "ask", _reply(valid))
    result, seen = _delegate(monkeypatch, tmp_path, model="missing")
    assert "modelo inválido" not in result
    assert len(seen) == 1 and seen[0]["model"] == valid


def test_invalid_model_without_answer_fails_now_without_touching_the_backend(monkeypatch, tmp_path):
    """REQ-003b: el cambio de comportamiento más visible, acotado.

    Sin respuesta el error es el de siempre **y no se consume backend**. Aseverar solo el texto no
    bastaría: lo que hay que impedir es que una llamada mal formada acabe gastando GPU.
    """
    monkeypatch.setattr(server.questions, "ask", _no_answer)
    result, seen = _delegate(monkeypatch, tmp_path, model="missing")
    assert "modelo inválido 'missing'" in result
    assert seen == [], "se llamó al backend con un modelo inválido"


def test_an_answer_not_in_the_catalog_is_not_valid_either(monkeypatch, tmp_path):
    monkeypatch.setattr(server.questions, "ask", _reply("also-missing"))
    result, seen = _delegate(monkeypatch, tmp_path, model="missing")
    assert "modelo inválido" in result
    assert seen == []


def test_blank_output_format_is_asked(monkeypatch, tmp_path):
    """REQ-004."""
    monkeypatch.setattr(server.questions, "ask", _reply("JSON con dos claves"))
    _, seen = _delegate(monkeypatch, tmp_path, output_format="   ")
    assert "JSON con dos claves" in seen[0]["messages"][0]["content"]


def test_with_output_format_nothing_is_asked(monkeypatch, tmp_path):
    calls = []

    def _spy(message, model):
        calls.append(message)

    monkeypatch.setattr(server.questions, "ask", _spy)
    _delegate(monkeypatch, tmp_path, output_format="bullets")
    assert calls == []


def test_no_tool_exposes_ctx_in_its_schema():
    """REQ-009: el contexto viaja por ContextVar, así que no puede haber aparecido en el contrato."""
    tools = server.mcp._tool_manager.list_tools()
    assert len(tools) == 11
    for t in tools:
        props = set(t.parameters.get("properties", {}))
        assert "ctx" not in props and "context" not in props, f"{t.name} expone el contexto"


def test_the_questions_carry_no_paths_or_content(monkeypatch, tmp_path):
    """El mensaje que ve el usuario no debe filtrar el input ni rutas del disco."""
    messages = []

    def _spy(message, model):
        messages.append(message)

    monkeypatch.setattr(server.questions, "ask", _spy)
    _delegate(monkeypatch, tmp_path, model="missing", input="SECRET-IN-THE-INPUT")
    assert messages and all("SECRET-IN-THE-INPUT" not in m for m in messages)
    assert all(str(tmp_path) not in m for m in messages)


class OptionalAnswer(BaseModel):
    """Todos los campos con default: valida incluso contra un cuerpo vacío."""

    value: str = "default-value"


def answer_optional() -> str:
    r = questions.ask("¿Cual?", OptionalAnswer)
    return f"respuesta={r.value if r is not None else None}"


def test_a_decline_does_not_slip_through_as_acceptance():
    """Cierra un hueco que encontró la verificación al revés.

    Con el defecto puesto —no mirar `action` y quedarse solo con validar el cuerpo— los 19 tests
    seguían pasando: `decline` no trae `content`, y validar `{}` contra un modelo de campos
    obligatorios falla igual, así que el rechazo ocurría por la razón equivocada. Con un modelo
    cuyos campos tienen default, `{}` **sí** valida, y entonces lo único que puede distinguir un
    «no» es la comprobación de `action`. Sin ella, el usuario diría que no y el servidor entendería
    que sí.
    """
    n = "answer_optional"
    assert anyio.run(_run, _mount(None, answer_optional), declines, n) == "respuesta=None"
    assert anyio.run(_run, _mount(None, answer_optional), cancels, n) == "respuesta=None"


# --- Los esquemas que ve el usuario -------------------------------------------------------------


@pytest.mark.parametrize(
    ("form", "expected"),
    [
        (
            questions.StartBackend,
            {
                "description": "¿Arrancar el backend local que no responde?",
                "properties": {"start": {"title": "Arrancar", "type": "boolean"}},
                "required": ["start"],
                "title": "ArrancarBackend",
                "type": "object",
            },
        ),
        (
            questions.ChooseModel,
            {
                "description": "Cuál de los modelos del catálogo usar.",
                "properties": {"model": {"title": "Modelo", "type": "string"}},
                "required": ["model"],
                "title": "ElegirModelo",
                "type": "object",
            },
        ),
        (
            questions.ChooseFormat,
            {
                "description": "Qué formato de salida se espera.",
                "properties": {"format": {"title": "Formato", "type": "string"}},
                "required": ["format"],
                "title": "ElegirFormato",
                "type": "object",
            },
        ),
    ],
    ids=["StartBackend", "ChooseModel", "ChooseFormat"],
)
def test_the_elicitation_schemas_keep_their_fields_and_visible_titles(form, expected):
    """Lo que el cliente MCP enseña al usuario es el esquema que manda `ask`
    (`questions._localized_schema`): los campos (`start`, `model`, `format`) son los que lee el
    servidor, y en español los `title` y la `description` son, byte a byte, los de antes de B2a.
    Desde B2a salen del catálogo al preguntar, no de la clase. Control: quitar la sustitución del
    título del campo deja el de la clase (`start`) y este test falla.
    """
    assert questions._localized_schema(form) == expected


@pytest.mark.parametrize(
    "form", [questions.StartBackend, questions.ChooseModel, questions.ChooseFormat]
)
def test_the_elicitation_schemas_follow_the_current_language(form, monkeypatch):
    """B2a: en inglés, ni el título, ni la descripción, ni el campo traen el texto español."""
    from local_delegate import i18n

    spanish = questions._localized_schema(form)
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    i18n.reset()
    english = questions._localized_schema(form)
    assert english["title"] != spanish["title"]
    assert english["description"] != spanish["description"]
    (field_es,) = spanish["properties"].values()
    (field_en,) = english["properties"].values()
    assert field_en["title"] != field_es["title"]
    assert english["required"] == spanish["required"]
