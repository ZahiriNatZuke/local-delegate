"""Pruebas de `preguntas.py`: preguntar en vez de fallar seco.

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

from local_delegate import config, preguntas, server


class Respuesta(BaseModel):
    valor: str


@pytest.fixture(autouse=True)
def contexto_limpio(monkeypatch):
    monkeypatch.setattr(preguntas.config, "ASK_ENABLED", True)
    monkeypatch.setattr(preguntas.config, "ASK_TIMEOUT", 2)
    preguntas.CTX_ACTUAL.set(None)
    yield
    preguntas.CTX_ACTUAL.set(None)


# --- puede_preguntar: las dos condiciones, por separado ----------------------


class _Caps:
    def __init__(self, elicitation):
        self.elicitation = elicitation


_DECLARADA = object()  # marcador: "el cliente declaró la capability"


class _Sesion:
    def __init__(self, elicitation=_DECLARADA, canal=True):
        self.client_capabilities = _Caps(elicitation)
        self.can_send_request = canal


class _Ctx:
    def __init__(self, **kw):
        self.session = _Sesion(**kw)


def test_sin_contexto_no_se_puede_preguntar():
    assert preguntas.puede_preguntar() is False


def test_con_capability_y_canal_si_se_puede():
    preguntas.CTX_ACTUAL.set(_Ctx())
    assert preguntas.puede_preguntar() is True


def test_sin_la_capability_no_se_puede():
    preguntas.CTX_ACTUAL.set(_Ctx(elicitation=None))
    assert preguntas.puede_preguntar() is False


def test_con_capability_pero_sin_canal_tampoco():
    # Son dos condiciones independientes: declarar `elicitation` no implica que se pueda hablar.
    preguntas.CTX_ACTUAL.set(_Ctx(canal=False))
    assert preguntas.puede_preguntar() is False


def test_apagado_por_configuracion(monkeypatch):
    monkeypatch.setattr(preguntas.config, "ASK_ENABLED", False)
    preguntas.CTX_ACTUAL.set(_Ctx())
    assert preguntas.puede_preguntar() is False
    assert preguntas.preguntar("¿?", Respuesta) is None


def test_una_sesion_que_revienta_no_propaga():
    class _Roto:
        @property
        def session(self):
            raise RuntimeError("boom")

    preguntas.CTX_ACTUAL.set(_Roto())
    assert preguntas.puede_preguntar() is False
    assert preguntas.preguntar("¿?", Respuesta) is None


# --- integración con servidor y cliente reales -------------------------------


def _montar(respuesta_cliente, tool_fn):
    servidor = MCPServer("prueba", version="0.0.0", middleware=[preguntas.recordar_contexto])
    servidor.tool()(tool_fn)
    return servidor


async def _correr(servidor, callback, nombre="probar"):
    async with create_client_server_memory_streams() as ((cr, cw), (sr, sw)):
        low = servidor._lowlevel_server
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: low.run(sr, sw, low.create_initialization_options(), raise_exceptions=True)
            )
            kwargs = {"elicitation_callback": callback} if callback is not None else {}
            async with ClientSession(
                cr, cw, client_info=Implementation(name="prueba", version="1.0"), **kwargs
            ) as cliente:
                await cliente.initialize()
                res = await cliente.call_tool(nombre, {})
                texto = res.content[0].text if res.content else "(vacio)"
            tg.cancel_scope.cancel()
    return texto


def probar() -> str:
    """Tool SÍNCRONA que pregunta desde su hilo, como hacen las 11 de verdad."""
    r = preguntas.preguntar("¿Cual?", Respuesta)
    return f"respuesta={r.valor if r is not None else None}"


async def acepta(context, params):
    return ElicitResult(action="accept", content={"valor": "elegido"})


async def declina(context, params):
    return ElicitResult(action="decline")


async def cancela(context, params):
    return ElicitResult(action="cancel")


async def muda(context, params):
    await anyio.sleep(3600)


def test_el_usuario_responde():
    assert anyio.run(_correr, _montar(None, probar), acepta) == "respuesta=elegido"


def test_el_usuario_declina():
    assert anyio.run(_correr, _montar(None, probar), declina) == "respuesta=None"


def test_el_usuario_cancela():
    # `cancel` y `decline` son cosas distintas en el protocolo pero aquí significan lo mismo: no.
    assert anyio.run(_correr, _montar(None, probar), cancela) == "respuesta=None"


def test_cliente_sin_soporte_de_elicitation():
    assert anyio.run(_correr, _montar(None, probar), None) == "respuesta=None"


def test_el_cliente_que_no_responde_no_cuelga_la_tool():
    """REQ-006, y es la prueba que justifica el diseño del plazo.

    Mide que la tool **vuelve sola**, no que se la pueda cortar desde fuera: un test que corta
    desde fuera pasa igual con el plazo mal puesto, y el plazo mal puesto —`move_on_after`
    alrededor de `from_thread.run`— lanza `NoEventLoopError`, que el `except` se tragaría. El
    síntoma sería «nunca se pregunta», silencioso.
    """
    t0 = time.monotonic()
    resultado = anyio.run(_correr, _montar(None, probar), muda)
    transcurrido = time.monotonic() - t0
    assert resultado == "respuesta=None"
    # ASK_TIMEOUT es 2s en el fixture; con holgura para el arranque del servidor.
    assert transcurrido < 15, f"la tool tardó {transcurrido:.1f}s: el plazo no está cortando"


def test_el_plazo_se_agota_y_no_antes():
    """Complemento del anterior: que no devuelva None por no haber preguntado siquiera."""
    t0 = time.monotonic()
    anyio.run(_correr, _montar(None, probar), muda)
    transcurrido = time.monotonic() - t0
    assert transcurrido >= 2, (
        f"volvió en {transcurrido:.1f}s, antes del plazo: no llegó a preguntar de verdad"
    )


# --- los tres puntos de uso --------------------------------------------------
# El mecanismo ya está probado end-to-end arriba; aquí se dobla `preguntar` para ejercer la lógica
# de cada punto de uso sin volver a montar un servidor MCP.


def _responde(valor):
    """Doble de `preguntar` que devuelve el modelo pedido relleno con `valor`."""

    def _fn(mensaje, modelo):
        campo = next(iter(modelo.model_fields))
        return modelo(**{campo: valor})

    return _fn


def _no_responde(mensaje, modelo):
    return None


@backend_mock.mock
def _delegar(monkeypatch, tmp_path, **kw):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    vistos: list[dict] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        vistos.append(json.loads(request.content))
        return httpx2.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    args = {"task": "t", "input": "i", "output_format": "bullets"}
    args.update(kw)
    return server.local_delegate(**args), vistos


def test_modelo_invalido_con_respuesta_continua_con_el_elegido(monkeypatch, tmp_path):
    """REQ-003."""
    valido = min(config.ALLOWED_MODELS)
    monkeypatch.setattr(server.preguntas, "preguntar", _responde(valido))
    resultado, vistos = _delegar(monkeypatch, tmp_path, model="no-existe")
    assert "modelo inválido" not in resultado
    assert len(vistos) == 1 and vistos[0]["model"] == valido


def test_modelo_invalido_sin_respuesta_falla_ya_y_sin_tocar_el_backend(monkeypatch, tmp_path):
    """REQ-003b: el cambio de comportamiento más visible, acotado.

    Sin respuesta el error es el de siempre **y no se consume backend**. Aseverar solo el texto no
    bastaría: lo que hay que impedir es que una llamada mal formada acabe gastando GPU.
    """
    monkeypatch.setattr(server.preguntas, "preguntar", _no_responde)
    resultado, vistos = _delegar(monkeypatch, tmp_path, model="no-existe")
    assert "modelo inválido 'no-existe'" in resultado
    assert vistos == [], "se llamó al backend con un modelo inválido"


def test_respuesta_que_no_esta_en_el_catalogo_tampoco_vale(monkeypatch, tmp_path):
    monkeypatch.setattr(server.preguntas, "preguntar", _responde("tampoco-existe"))
    resultado, vistos = _delegar(monkeypatch, tmp_path, model="no-existe")
    assert "modelo inválido" in resultado
    assert vistos == []


def test_output_format_en_blanco_se_pregunta(monkeypatch, tmp_path):
    """REQ-004."""
    monkeypatch.setattr(server.preguntas, "preguntar", _responde("JSON con dos claves"))
    _, vistos = _delegar(monkeypatch, tmp_path, output_format="   ")
    assert "JSON con dos claves" in vistos[0]["messages"][0]["content"]


def test_con_output_format_no_se_pregunta_nada(monkeypatch, tmp_path):
    llamadas = []

    def _espia(mensaje, modelo):
        llamadas.append(mensaje)

    monkeypatch.setattr(server.preguntas, "preguntar", _espia)
    _delegar(monkeypatch, tmp_path, output_format="bullets")
    assert llamadas == []


def test_ninguna_tool_expone_ctx_en_su_schema():
    """REQ-009: el contexto viaja por ContextVar, así que no puede haber aparecido en el contrato."""
    tools = server.mcp._tool_manager.list_tools()
    assert len(tools) == 11
    for t in tools:
        props = set(t.parameters.get("properties", {}))
        assert "ctx" not in props and "context" not in props, f"{t.name} expone el contexto"


def test_las_preguntas_no_llevan_rutas_ni_contenido(monkeypatch, tmp_path):
    """El mensaje que ve el usuario no debe filtrar el input ni rutas del disco."""
    mensajes = []

    def _espia(mensaje, modelo):
        mensajes.append(mensaje)

    monkeypatch.setattr(server.preguntas, "preguntar", _espia)
    _delegar(monkeypatch, tmp_path, model="no-existe", input="SECRETO-EN-EL-INPUT")
    assert mensajes and all("SECRETO-EN-EL-INPUT" not in m for m in mensajes)
    assert all(str(tmp_path) not in m for m in mensajes)


class RespuestaOpcional(BaseModel):
    """Todos los campos con default: valida incluso contra un cuerpo vacío."""

    valor: str = "por-defecto"


def responder_opcional() -> str:
    r = preguntas.preguntar("¿Cual?", RespuestaOpcional)
    return f"respuesta={r.valor if r is not None else None}"


def test_un_decline_no_se_cuela_como_aceptacion():
    """Cierra un hueco que encontró la verificación al revés.

    Con el defecto puesto —no mirar `action` y quedarse solo con validar el cuerpo— los 19 tests
    seguían pasando: `decline` no trae `content`, y validar `{}` contra un modelo de campos
    obligatorios falla igual, así que el rechazo ocurría por la razón equivocada. Con un modelo
    cuyos campos tienen default, `{}` **sí** valida, y entonces lo único que puede distinguir un
    «no» es la comprobación de `action`. Sin ella, el usuario diría que no y el servidor entendería
    que sí.
    """
    n = "responder_opcional"
    assert anyio.run(_correr, _montar(None, responder_opcional), declina, n) == "respuesta=None"
    assert anyio.run(_correr, _montar(None, responder_opcional), cancela, n) == "respuesta=None"
