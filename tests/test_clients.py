"""Pruebas del observador de clientes MCP (`clients.py`).

Las de integración montan un `MCPServer` real y le conectan un `ClientSession` real por streams en
memoria. Es a propósito: lo que hay que comprobar —que en `initialize` todavía no hay datos, que
veinte mensajes dejan una sola línea— depende del orden real del handshake del SDK, y un doble del
contexto lo daría por bueno sin haberlo ejercido.
"""

from __future__ import annotations

import json

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.server.mcpserver import MCPServer
from mcp.shared.memory import create_client_server_memory_streams
from mcp.types import Implementation

from local_delegate import clients


@pytest.fixture(autouse=True)
def registro_limpio(tmp_path, monkeypatch):
    """Cada prueba arranca con el registro vacío y su propio LOG_DIR."""
    clients.reset()
    monkeypatch.setattr(clients.config, "LOG_DIR", tmp_path)
    yield
    clients.reset()


def _lineas(tmp_path) -> list[dict]:
    destino = tmp_path / clients.LOG_FILENAME
    if not destino.exists():
        return []
    return [json.loads(x) for x in destino.read_text(encoding="utf-8").splitlines() if x.strip()]


async def _conversar(nombre: str | None, version: str, llamadas: int = 1) -> str:
    """Levanta el servidor observado, conecta un cliente y hace `llamadas` a una tool.

    Devuelve la revisión de protocolo negociada, que es un dato que las pruebas comprueban en vez
    de dar por supuesto: no coincide con `LATEST_PROTOCOL_VERSION` ni con la constante de defecto.
    """
    servidor = MCPServer("prueba", version="0.0.0", middleware=[clients.observar_cliente])

    @servidor.tool()
    def eco(texto: str) -> str:
        """Devuelve lo que le den."""
        return texto

    negociada = ""
    async with create_client_server_memory_streams() as ((cr, cw), (sr, sw)):
        low = servidor._lowlevel_server
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: low.run(sr, sw, low.create_initialization_options(), raise_exceptions=True)
            )
            info = Implementation(name=nombre, version=version) if nombre is not None else None
            async with ClientSession(cr, cw, client_info=info) as cliente:
                resultado = await cliente.initialize()
                negociada = resultado.protocol_version
                for _ in range(llamadas):
                    await cliente.call_tool("eco", {"texto": "hola"})
            tg.cancel_scope.cancel()
    return negociada


# --- unitarias ---------------------------------------------------------------


class _Caps:
    def __init__(self, datos):
        self._datos = datos

    def model_dump(self, exclude_none=False):
        return dict(self._datos)


def test_capabilities_ausentes_y_vacias_no_son_lo_mismo():
    # None = el cliente no declaró capabilities. {} = declaró que no tiene ninguna. El registro
    # devuelve una tupla vacía en ambos casos, pero `registrar` los trata distinto (ver REQ-007).
    assert clients.nombres_capabilities(None) == ()
    assert clients.nombres_capabilities(_Caps({})) == ()


def test_capabilities_se_devuelven_ordenadas_y_sin_las_no_declaradas():
    caps = _Caps({"sampling": {}, "elicitation": {}, "roots": None})
    assert clients.nombres_capabilities(caps) == ("elicitation", "sampling")


def test_objeto_que_no_es_del_sdk_no_revienta():
    assert clients.nombres_capabilities(object()) == ()


def test_sin_capabilities_ni_identidad_no_registra(tmp_path):
    # REQ-007: el caso simétrico de "capabilities sin identidad".
    assert clients.registrar(None, None, "2025-11-25") is False
    assert _lineas(tmp_path) == []
    assert clients.snapshot() == []


def test_capabilities_sin_identidad_si_registra(tmp_path):
    # REQ-006: legítimo desde la revisión 2026-07-28, donde client_info es opcional.
    assert clients.registrar(_Caps({"elicitation": {}}), None, "2026-07-28") is True
    (linea,) = _lineas(tmp_path)
    assert linea["client"] is None
    assert linea["caps"] == ["elicitation"]


def test_la_linea_tiene_exactamente_los_campos_declarados(tmp_path):
    # "Exactamente", no "al menos": así una cabecera o una ruta coladas por descuido rompen aquí y
    # no acaban en disco.
    clients.registrar(_Caps({"roots": {}}), Implementation(name="x", version="1"), "2025-11-25")
    (linea,) = _lineas(tmp_path)
    assert set(linea) == set(clients.CAMPOS)


def test_snapshot_esta_desligado_del_estado_interno():
    clients.registrar(_Caps({"roots": {}}), Implementation(name="x", version="1"), "2025-11-25")
    copia = clients.snapshot()
    copia[0]["client"] = "mutado"
    assert clients.snapshot()[0]["client"] == "x"


def test_un_fallo_de_escritura_no_propaga(tmp_path, monkeypatch):
    # REQ-005 medido por contrato, no por permisos del sistema de ficheros: en Windows `chmod` no
    # los aplica como en POSIX y el test valdría una cosa en cada runner.
    def revienta(destino, linea):
        raise OSError("disco lleno")

    monkeypatch.setattr(clients, "_escribir_linea", revienta)
    with pytest.raises(OSError):
        clients.registrar(_Caps({}), Implementation(name="x", version="1"), "2025-11-25")
    # `registrar` sí propaga: quien la envuelve es el middleware, y eso se prueba end-to-end abajo.


# --- integración con servidor y cliente reales -------------------------------


def test_un_cliente_deja_una_linea_con_lo_negociado(tmp_path):
    negociada = anyio.run(_conversar, "cliente-prueba", "9.9.9")
    (linea,) = _lineas(tmp_path)
    assert linea["client"] == "cliente-prueba"
    assert linea["version"] == "9.9.9"
    assert linea["protocol"] == negociada
    # El dato que motivó el change: la revisión no la predicen las constantes del SDK.
    from mcp.types import LATEST_PROTOCOL_VERSION

    assert negociada != "" and negociada != LATEST_PROTOCOL_VERSION


def test_el_middleware_ignora_initialize_aunque_haya_datos(monkeypatch):
    """REQ-002, con dientes.

    La primera versión de esta prueba conectaba un cliente, hacía solo el handshake y comprobaba
    que no quedaba línea. **No probaba nada**: se verificó al revés y con el defecto puesto
    —observar también en `initialize`— los catorce tests seguían pasando, porque durante el
    handshake no hay ni capabilities ni identidad y la guarda de REQ-007 descartaba igual. O sea,
    medía la otra protección.

    Esta versión ataca la regla directa: aunque el contexto traiga datos, `initialize` se ignora.
    """
    llamadas = []
    monkeypatch.setattr(clients, "registrar", lambda *a, **k: llamadas.append(a))

    class _Sesion:
        client_capabilities = _Caps({"elicitation": {}})
        client_params = Implementation(name="x", version="1")

    class _Ctx:
        method = "initialize"
        protocol_version = "2025-11-25"
        session = _Sesion()

    async def call_next(ctx):
        return "resultado"

    assert anyio.run(clients.observar_cliente, _Ctx(), call_next) == "resultado"
    assert llamadas == [], "el observador leyó durante initialize"


def test_en_initialize_el_sdk_todavia_no_entrega_los_datos():
    """Fija la medición en la que se apoya el diseño, para que un cambio del SDK se note aquí.

    Si algún día `initialize` sí trae capabilities, este test falla y hay que revisar si el skip
    sigue teniendo sentido — en vez de descubrirlo por un registro que dejó de funcionar.
    """
    visto: list[tuple[str, bool]] = []

    async def espia(ctx, call_next):
        visto.append((ctx.method, ctx.session.client_capabilities is None))
        return await call_next(ctx)

    async def conversar():
        servidor = MCPServer("prueba", version="0.0.0", middleware=[espia])

        @servidor.tool()
        def eco(texto: str) -> str:
            """Devuelve lo que le den."""
            return texto

        async with create_client_server_memory_streams() as ((cr, cw), (sr, sw)):
            low = servidor._lowlevel_server
            async with anyio.create_task_group() as tg:
                tg.start_soon(
                    lambda: low.run(
                        sr, sw, low.create_initialization_options(), raise_exceptions=True
                    )
                )
                info = Implementation(name="cliente-prueba", version="9.9.9")
                async with ClientSession(cr, cw, client_info=info) as cliente:
                    await cliente.initialize()
                    await cliente.call_tool("eco", {"texto": "hola"})
                tg.cancel_scope.cancel()

    anyio.run(conversar)
    por_metodo = dict(visto)
    assert por_metodo["initialize"] is True, "el SDK ya entrega capabilities en initialize"
    assert por_metodo["tools/call"] is False, "el SDK dejó de entregarlas tras el handshake"


def test_veinte_mensajes_dejan_una_sola_linea(tmp_path):
    # REQ-003. Es la prueba que caza el dedupe roto y la sección crítica mal delimitada.
    anyio.run(_conversar, "cliente-prueba", "9.9.9", 20)
    assert len(_lineas(tmp_path)) == 1
    (vivo,) = clients.snapshot()
    assert vivo["messages"] > 1
    assert vivo["last_seen"] >= vivo["first_seen"]


def test_dos_clientes_distintos_dejan_dos_lineas(tmp_path):
    anyio.run(_conversar, "cliente-a", "1.0.0")
    anyio.run(_conversar, "cliente-b", "2.0.0")
    lineas = _lineas(tmp_path)
    assert len(lineas) == 2
    assert {x["client"] for x in lineas} == {"cliente-a", "cliente-b"}
    assert len(clients.snapshot()) == 2


def test_el_mismo_cliente_con_otra_version_es_otra_identidad(tmp_path):
    anyio.run(_conversar, "cliente-a", "1.0.0")
    anyio.run(_conversar, "cliente-a", "1.0.1")
    assert len(_lineas(tmp_path)) == 2


def test_api_status_expone_los_clientes_observados(tmp_path):
    """REQ-004: el estado en vivo llega al endpoint que alimenta el panel."""
    from fastapi.testclient import TestClient

    from local_delegate.web import metrics

    clients.registrar(
        _Caps({"elicitation": {}, "roots": {}}),
        Implementation(name="cliente-prueba", version="9.9.9"),
        "2025-11-25",
    )
    datos = TestClient(metrics.app).get("/api/status").json()
    (visto,) = datos["clients"]
    assert visto["client"] == "cliente-prueba"
    assert visto["protocol"] == "2025-11-25"
    assert visto["caps"] == ["elicitation", "roots"]


def test_un_observador_que_revienta_no_rompe_la_llamada(tmp_path, monkeypatch):
    # REQ-005 end-to-end: el middleware se traga el fallo y el cliente recibe su respuesta.
    def revienta(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(clients, "registrar", revienta)
    negociada = anyio.run(_conversar, "cliente-prueba", "9.9.9")
    assert negociada  # la conversación completa funcionó
    assert _lineas(tmp_path) == []


# --- El registro tiene techo, y el techo no puede cegar al diagnóstico -----------------------


def test_el_registro_rota_al_pasar_del_techo(tmp_path, monkeypatch):
    """Crecía sin límite. Medido: ~144 B por arranque, o sea despacio, pero sin nada que lo pare."""
    monkeypatch.setattr(clients.config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(clients, "MAX_BYTES", 200)  # techo diminuto para no escribir 256 KB aquí

    viva = clients.ruta_registro()
    viva.write_text("x" * 300 + "\n", encoding="utf-8")  # ya por encima del techo

    clients.reset()
    clients.registrar(None, Implementation(name="claude-code", version="2.1.220"), "2025-11-25")

    rotada = viva.with_name(viva.name + clients.SUFIJO_ROTADO)
    assert rotada.is_file(), "no se apartó la generación anterior"
    assert "claude-code" in viva.read_text(encoding="utf-8")
    assert viva.stat().st_size < 300, "el fichero vivo debe empezar de nuevo"


def test_rotar_NO_hace_perder_de_vista_a_un_cliente_ya_anotado(tmp_path, monkeypatch):
    """El riesgo real de ponerle techo, y por eso tiene test propio.

    Si `client.observed` leyera solo el fichero vivo, rotar borraría del diagnóstico a un cliente
    perfectamente observado: se habría cambiado un crecimiento sin límite por un diagnóstico que
    miente, que es peor.
    """
    from local_delegate import checks

    monkeypatch.setattr(clients.config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(clients, "MAX_BYTES", 200)

    viva = clients.ruta_registro()
    antiguo = json.dumps(
        {
            "ts": "2026-01-01T00:00:00+00:00",
            "client": "codex-mcp-client",
            "version": "0.146.0",
            "protocol": "2025-06-18",
            "caps": ["elicitation"],
        },
        ensure_ascii=False,
    )
    viva.write_text(antiguo + "\n" + "x" * 300 + "\n", encoding="utf-8")

    clients.reset()
    clients.registrar(None, Implementation(name="claude-code", version="2.1.220"), "2025-11-25")
    assert viva.with_name(viva.name + clients.SUFIJO_ROTADO).is_file(), "no llegó a rotar"

    vistos, motivo = checks._default_clients_seen()

    assert motivo is None
    nombres = {v.get("client") for v in vistos}
    assert nombres == {"codex-mcp-client", "claude-code"}, (
        f"tras rotar, el diagnóstico debe seguir viendo a los dos: {nombres}"
    )


def test_si_no_se_puede_rotar_se_sigue_anotando(tmp_path, monkeypatch):
    """Observar es best-effort: un fallo al rotar no puede tumbar el middleware MCP."""
    monkeypatch.setattr(clients.config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(clients, "MAX_BYTES", 200)

    def _rotar_roto(*_args):
        raise OSError("el sistema de ficheros dice que no")

    monkeypatch.setattr(clients.os, "replace", _rotar_roto)

    viva = clients.ruta_registro()
    viva.write_text("x" * 300 + "\n", encoding="utf-8")

    clients.reset()
    assert (
        clients.registrar(None, Implementation(name="claude-code", version="2.1.220"), "2025-11-25")
        is True
    )
    assert "claude-code" in viva.read_text(encoding="utf-8")
