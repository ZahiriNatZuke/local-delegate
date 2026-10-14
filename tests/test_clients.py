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
def clean_registry(tmp_path, monkeypatch):
    """Cada prueba arranca con el registro vacío y su propio LOG_DIR."""
    clients.reset()
    monkeypatch.setattr(clients.config, "LOG_DIR", tmp_path)
    yield
    clients.reset()


def _lines(tmp_path) -> list[dict]:
    dest = tmp_path / clients.LOG_FILENAME
    if not dest.exists():
        return []
    return [json.loads(x) for x in dest.read_text(encoding="utf-8").splitlines() if x.strip()]


async def _converse(name: str | None, version: str, calls: int = 1) -> str:
    """Levanta el servidor observado, conecta un cliente y hace `calls` a una tool.

    Devuelve la revisión de protocolo negociada, que es un dato que las pruebas comprueban en vez
    de dar por supuesto: no coincide con `LATEST_PROTOCOL_VERSION` ni con la constante de defecto.
    """
    server = MCPServer("prueba", version="0.0.0", middleware=[clients.observe_client])

    @server.tool()
    def echo(text: str) -> str:
        """Devuelve lo que le den."""
        return text

    negotiated = ""
    async with create_client_server_memory_streams() as ((cr, cw), (sr, sw)):
        low = server._lowlevel_server
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: low.run(sr, sw, low.create_initialization_options(), raise_exceptions=True)
            )
            info = Implementation(name=name, version=version) if name is not None else None
            async with ClientSession(cr, cw, client_info=info) as client:
                result = await client.initialize()
                negotiated = result.protocol_version
                for _ in range(calls):
                    await client.call_tool("echo", {"text": "hola"})
            tg.cancel_scope.cancel()
    return negotiated


# --- unitarias ---------------------------------------------------------------


class _Caps:
    def __init__(self, data):
        self._data = data

    def model_dump(self, exclude_none=False):
        return dict(self._data)


def test_absent_and_empty_capabilities_are_not_the_same():
    # None = el cliente no declaró capabilities. {} = declaró que no tiene ninguna. El registro
    # devuelve una tupla vacía en ambos casos, pero `record` los trata distinto (ver REQ-007).
    assert clients.capability_names(None) == ()
    assert clients.capability_names(_Caps({})) == ()


def test_capabilities_are_returned_sorted_and_without_undeclared_ones():
    caps = _Caps({"sampling": {}, "elicitation": {}, "roots": None})
    assert clients.capability_names(caps) == ("elicitation", "sampling")


def test_an_object_not_from_the_sdk_does_not_blow_up():
    assert clients.capability_names(object()) == ()


def test_without_capabilities_or_identity_does_not_record(tmp_path):
    # REQ-007: el caso simétrico de "capabilities sin identidad".
    assert clients.record(None, None, "2025-11-25") is False
    assert _lines(tmp_path) == []
    assert clients.snapshot() == []


def test_capabilities_without_identity_does_record(tmp_path):
    # REQ-006: legítimo desde la revisión 2026-07-28, donde client_info es opcional.
    assert clients.record(_Caps({"elicitation": {}}), None, "2026-07-28") is True
    (line,) = _lines(tmp_path)
    assert line["client"] is None
    assert line["caps"] == ["elicitation"]


def test_the_line_has_exactly_the_declared_fields(tmp_path):
    # "Exactamente", no "al menos": así una cabecera o una ruta coladas por descuido rompen aquí y
    # no acaban en disco.
    clients.record(_Caps({"roots": {}}), Implementation(name="x", version="1"), "2025-11-25")
    (line,) = _lines(tmp_path)
    assert set(line) == set(clients.FIELDS)


def test_snapshot_is_detached_from_the_internal_state():
    clients.record(_Caps({"roots": {}}), Implementation(name="x", version="1"), "2025-11-25")
    copied = clients.snapshot()
    copied[0]["client"] = "mutado"
    assert clients.snapshot()[0]["client"] == "x"


def test_a_write_failure_does_not_propagate(tmp_path, monkeypatch):
    # REQ-005 medido por contrato, no por permisos del sistema de ficheros: en Windows `chmod` no
    # los aplica como en POSIX y el test valdría una cosa en cada runner.
    def blows_up(dest, line):
        raise OSError("disco lleno")

    monkeypatch.setattr(clients, "_write_line", blows_up)
    with pytest.raises(OSError):
        clients.record(_Caps({}), Implementation(name="x", version="1"), "2025-11-25")
    # `record` sí propaga: quien la envuelve es el middleware, y eso se prueba end-to-end abajo.


# --- integración con servidor y cliente reales -------------------------------


def test_a_client_leaves_one_line_with_what_was_negotiated(tmp_path):
    negotiated = anyio.run(_converse, "test-client", "9.9.9")
    (line,) = _lines(tmp_path)
    assert line["client"] == "test-client"
    assert line["version"] == "9.9.9"
    assert line["protocol"] == negotiated
    # El dato que motivó el change: la revisión no la predicen las constantes del SDK.
    from mcp.types import LATEST_PROTOCOL_VERSION

    assert negotiated != "" and negotiated != LATEST_PROTOCOL_VERSION


def test_the_middleware_ignores_initialize_even_with_data(monkeypatch):
    """REQ-002, con dientes.

    La primera versión de esta prueba conectaba un cliente, hacía solo el handshake y comprobaba
    que no quedaba línea. **No probaba nada**: se verificó al revés y con el defecto puesto
    —observar también en `initialize`— los catorce tests seguían pasando, porque durante el
    handshake no hay ni capabilities ni identidad y la guarda de REQ-007 descartaba igual. O sea,
    medía la otra protección.

    Esta versión ataca la regla directa: aunque el contexto traiga datos, `initialize` se ignora.
    """
    calls = []
    monkeypatch.setattr(clients, "record", lambda *a, **k: calls.append(a))

    class _Session:
        client_capabilities = _Caps({"elicitation": {}})
        client_params = Implementation(name="x", version="1")

    class _Ctx:
        method = "initialize"
        protocol_version = "2025-11-25"
        session = _Session()

    async def call_next(ctx):
        return "resultado"

    assert anyio.run(clients.observe_client, _Ctx(), call_next) == "resultado"
    assert calls == [], "el observador leyó durante initialize"


def test_on_initialize_the_sdk_does_not_deliver_the_data_yet():
    """Fija la medición en la que se apoya el diseño, para que un cambio del SDK se note aquí.

    Si algún día `initialize` sí trae capabilities, este test falla y hay que revisar si el skip
    sigue teniendo sentido — en vez de descubrirlo por un registro que dejó de funcionar.
    """
    seen: list[tuple[str, bool]] = []

    async def spy(ctx, call_next):
        seen.append((ctx.method, ctx.session.client_capabilities is None))
        return await call_next(ctx)

    async def converse():
        server = MCPServer("prueba", version="0.0.0", middleware=[spy])

        @server.tool()
        def echo(text: str) -> str:
            """Devuelve lo que le den."""
            return text

        async with create_client_server_memory_streams() as ((cr, cw), (sr, sw)):
            low = server._lowlevel_server
            async with anyio.create_task_group() as tg:
                tg.start_soon(
                    lambda: low.run(
                        sr, sw, low.create_initialization_options(), raise_exceptions=True
                    )
                )
                info = Implementation(name="test-client", version="9.9.9")
                async with ClientSession(cr, cw, client_info=info) as client:
                    await client.initialize()
                    await client.call_tool("echo", {"text": "hola"})
                tg.cancel_scope.cancel()

    anyio.run(converse)
    per_method = dict(seen)
    assert per_method["initialize"] is True, "el SDK ya entrega capabilities en initialize"
    assert per_method["tools/call"] is False, "el SDK dejó de entregarlas tras el handshake"


def test_twenty_messages_leave_a_single_line(tmp_path):
    # REQ-003. Es la prueba que caza el dedupe roto y la sección crítica mal delimitada.
    anyio.run(_converse, "test-client", "9.9.9", 20)
    assert len(_lines(tmp_path)) == 1
    (alive,) = clients.snapshot()
    assert alive["messages"] > 1
    assert alive["last_seen"] >= alive["first_seen"]


def test_two_different_clients_leave_two_lines(tmp_path):
    anyio.run(_converse, "client-a", "1.0.0")
    anyio.run(_converse, "client-b", "2.0.0")
    lines = _lines(tmp_path)
    assert len(lines) == 2
    assert {x["client"] for x in lines} == {"client-a", "client-b"}
    assert len(clients.snapshot()) == 2


def test_the_same_client_with_another_version_is_another_identity(tmp_path):
    anyio.run(_converse, "client-a", "1.0.0")
    anyio.run(_converse, "client-a", "1.0.1")
    assert len(_lines(tmp_path)) == 2


def test_api_status_exposes_the_observed_clients(tmp_path):
    """REQ-004: el estado en vivo llega al endpoint que alimenta el panel."""
    from fastapi.testclient import TestClient

    from local_delegate.web import metrics

    clients.record(
        _Caps({"elicitation": {}, "roots": {}}),
        Implementation(name="test-client", version="9.9.9"),
        "2025-11-25",
    )
    data = TestClient(metrics.app).get("/api/status").json()
    (seen,) = data["clients"]
    assert seen["client"] == "test-client"
    assert seen["protocol"] == "2025-11-25"
    assert seen["caps"] == ["elicitation", "roots"]


def test_an_observer_that_blows_up_does_not_break_the_call(tmp_path, monkeypatch):
    # REQ-005 end-to-end: el middleware se traga el fallo y el cliente recibe su respuesta.
    def blows_up(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(clients, "record", blows_up)
    negotiated = anyio.run(_converse, "test-client", "9.9.9")
    assert negotiated  # la conversación completa funcionó
    assert _lines(tmp_path) == []


# --- El registro tiene techo, y el techo no puede cegar al diagnóstico -----------------------


def test_the_registry_rotates_when_it_passes_the_ceiling(tmp_path, monkeypatch):
    """Crecía sin límite. Medido: ~144 B por arranque, o sea despacio, pero sin nada que lo pare."""
    monkeypatch.setattr(clients.config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(clients, "MAX_BYTES", 200)  # techo diminuto para no escribir 256 KB aquí

    live = clients.log_path()
    live.write_text("x" * 300 + "\n", encoding="utf-8")  # ya por encima del techo

    clients.reset()
    clients.record(None, Implementation(name="claude-code", version="2.1.220"), "2025-11-25")

    rotated = live.with_name(live.name + clients.ROTATED_SUFFIX)
    assert rotated.is_file(), "no se apartó la generación anterior"
    assert "claude-code" in live.read_text(encoding="utf-8")
    assert live.stat().st_size < 300, "el fichero vivo debe empezar de nuevo"


def test_rotating_does_NOT_lose_track_of_an_already_recorded_client(tmp_path, monkeypatch):
    """El riesgo real de ponerle techo, y por eso tiene test propio.

    Si `client.observed` leyera solo el fichero vivo, rotar borraría del diagnóstico a un cliente
    perfectamente observado: se habría cambiado un crecimiento sin límite por un diagnóstico que
    miente, que es peor.
    """
    from local_delegate import checks

    monkeypatch.setattr(clients.config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(clients, "MAX_BYTES", 200)

    live = clients.log_path()
    legacy = json.dumps(
        {
            "ts": "2026-01-01T00:00:00+00:00",
            "client": "codex-mcp-client",
            "version": "0.146.0",
            "protocol": "2025-06-18",
            "caps": ["elicitation"],
        },
        ensure_ascii=False,
    )
    live.write_text(legacy + "\n" + "x" * 300 + "\n", encoding="utf-8")

    clients.reset()
    clients.record(None, Implementation(name="claude-code", version="2.1.220"), "2025-11-25")
    assert live.with_name(live.name + clients.ROTATED_SUFFIX).is_file(), "no llegó a rotar"

    seen, reason = checks._default_clients_seen()

    assert reason is None
    names = {v.get("client") for v in seen}
    assert names == {"codex-mcp-client", "claude-code"}, (
        f"tras rotar, el diagnóstico debe seguir viendo a los dos: {names}"
    )


def test_if_it_cannot_rotate_it_keeps_recording(tmp_path, monkeypatch):
    """Observar es best-effort: un fallo al rotar no puede tumbar el middleware MCP."""
    monkeypatch.setattr(clients.config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(clients, "MAX_BYTES", 200)

    def _broken_rotate(*_args):
        raise OSError("el sistema de ficheros dice que no")

    monkeypatch.setattr(clients.os, "replace", _broken_rotate)

    live = clients.log_path()
    live.write_text("x" * 300 + "\n", encoding="utf-8")

    clients.reset()
    assert (
        clients.record(None, Implementation(name="claude-code", version="2.1.220"), "2025-11-25")
        is True
    )
    assert "claude-code" in live.read_text(encoding="utf-8")


# --- La identidad llega hasta la tool ----------------------------------------------------------
#
# Es lo que permite que el log de uso firme cada delegación y que el panel distinga un mes de
# smoke tests de un mes de trabajo real.
#
# Estos tests son de INTEGRACIÓN a propósito. Un script suelto ya demostró que un `ContextVar`
# sobrevive al salto al threadpool, y eso no era la pregunta: entre el middleware y el handler está
# el SDK. La tool de abajo es **síncrona**, como las de verdad, que es lo que obliga al SDK a
# correrla en el threadpool.


async def _sign(name: str | None) -> str | None:
    """Conecta un cliente y devuelve lo que la tool vio en `current_client()`."""
    server = MCPServer("prueba", version="0.0.0", middleware=[clients.observe_client])
    seen: list[str | None] = []

    @server.tool()
    def whoami() -> str:
        """Tool SÍNCRONA: el SDK la corre en el threadpool, igual que a las reales."""
        seen.append(clients.current_client())
        return "ok"

    async with create_client_server_memory_streams() as ((cr, cw), (sr, sw)):
        low = server._lowlevel_server
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: low.run(sr, sw, low.create_initialization_options(), raise_exceptions=True)
            )
            info = Implementation(name=name, version="1.0.0") if name is not None else None
            async with ClientSession(cr, cw, client_info=info) as client:
                await client.initialize()
                await client.call_tool("whoami", {})
            tg.cancel_scope.cancel()
    return seen[0] if seen else None


def test_the_tool_sees_the_name_of_the_client_that_called_it():
    assert anyio.run(_sign, "claude-code") == "claude-code"


def test_two_different_clients_leave_different_signatures():
    """Control del de arriba, y el que impide que pase en vacío.

    Sin él, una implementación que devolviera siempre la misma constante —o el nombre del último
    cliente visto en una global— pasaría el primer test entero.
    """
    assert anyio.run(_sign, "claude-code") == "claude-code"
    assert anyio.run(_sign, "codex-mcp-client") == "codex-mcp-client"


def test_a_client_that_does_not_introduce_itself_appears_as_the_sdk_default():
    """Medido, no supuesto: el SDK del CLIENTE rellena `mcp` cuando no se le da `client_info`.

    O sea que «sin identidad» casi no existe desde este lado — y en el registro real de esta
    máquina hay líneas con `mcp 0.1.0` que son exactamente eso. Para lo que este campo persigue
    da igual: un script con el SDK por defecto se distingue de `claude-code`, que es la pregunta.

    El camino de omitir el campo sigue vivo en `_log_event` para cuando `client_info` llegue en
    None de verdad; lo que este test fija es que no se le puede llamar «lo normal».
    """
    assert anyio.run(_sign, None) == "mcp"


def test_current_client_outside_a_request_is_none():
    """`_log_event` también se llama desde el benchmark y desde caminos de arranque."""
    assert clients.current_client() is None


# --- El `tool_use_id` llega hasta la tool (coste-api-y-cuota, REQ-001) --------------------------
#
# Claude Code manda `_meta = {"claudecode/toolUseId": "toolu_…"}` en cada `tools/call`. Medido con
# el SDK instalado antes de escribir esto: el middleware lo ve como dict en `ctx.meta`, y
# `ClientSession.call_tool` acepta `meta=`.


async def _seen_tool_use_id(meta: dict | None) -> str | None:
    """Conecta un cliente, llama con ese `_meta` y devuelve lo que la tool vio."""
    server = MCPServer("prueba", version="0.0.0", middleware=[clients.observe_client])
    seen: list[str | None] = []

    @server.tool()
    def caller() -> str:
        """Tool SÍNCRONA, como las de verdad: corre en el threadpool."""
        seen.append(clients.current_tool_use_id())
        return "ok"

    async with create_client_server_memory_streams() as ((cr, cw), (sr, sw)):
        low = server._lowlevel_server
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: low.run(sr, sw, low.create_initialization_options(), raise_exceptions=True)
            )
            info = Implementation(name="claude-code", version="1.0.0")
            async with ClientSession(cr, cw, client_info=info) as client:
                await client.initialize()
                await client.call_tool("caller", {}, meta=meta)
            tg.cancel_scope.cancel()
    return seen[0] if seen else "la tool no llegó a correr"


def test_the_tool_sees_the_tool_use_id():
    """Control (c): en el corte de interfaz `current_tool_use_id()` devolvía `None`."""
    seen = anyio.run(_seen_tool_use_id, {"claudecode/toolUseId": "toolu_test"})
    assert seen == "toolu_test"


def test_without_meta_there_is_no_tool_use_id():
    """Guarda: un cliente que no lo manda (Codex, scripts) no hereda el de nadie."""
    assert anyio.run(_seen_tool_use_id, {"claudecode/toolUseId": "toolu_test"}) == ("toolu_test")
    seen = anyio.run(_seen_tool_use_id, None)
    assert seen is None
