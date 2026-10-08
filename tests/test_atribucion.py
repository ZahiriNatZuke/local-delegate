"""Atribución en vivo: `tool_use_id`, hook, resolución y reglas comunes (coste-api-y-cuota, T2).

Los transcripts, las notas y los logs son SINTÉTICOS y viven en `tmp_path`. Los tests que lanzan el
hook como proceso le ponen `TEMP`, `TMP` y `TMPDIR` en `tmp_path`, para no escribir en el temporal
real que lee el daemon en vivo.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.server.mcpserver import MCPServer
from mcp.shared.memory import create_client_server_memory_streams
from mcp.types import Implementation

from local_delegate import atribucion, clients, server
from local_delegate.resources.hooks import hook_common

HOOK = Path(hook_common.__file__).parent / "anotar_llamada.py"
AGENTE = "general-purpose"
OPUS = "claude-opus-5-5"


# --- Arnés --------------------------------------------------------------------------------------


def _temporal(tmp_path: Path, nombre: str = "temp") -> Path:
    destino = tmp_path / nombre
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def _entorno_del_hook(temporal: Path) -> dict[str, str]:
    entorno = dict(os.environ)
    entorno.update(
        {"TEMP": str(temporal), "TMP": str(temporal), "TMPDIR": str(temporal)},
        CLAUDE_EFFORT="high",
    )
    return entorno


def _lanzar_hook(entrada: bytes, temporal: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=entrada,
        env=_entorno_del_hook(temporal),
        capture_output=True,
        timeout=30,
        check=False,
    )


def _dir_notas(temporal: Path) -> Path:
    return temporal / "local-delegate-llamadas"


def _entrada_hook(tool_use_id: str, transcript: Path | str, **extra) -> dict:
    return {
        "session_id": "sesion-sintetica",
        "transcript_path": str(transcript),
        "cwd": "C:/proyecto",
        "hook_event_name": "PreToolUse",
        "tool_name": "mcp__local-delegate__local_summarize",
        "tool_use_id": tool_use_id,
        **extra,
    }


def _linea_tool_use(tool_use_id: str, modelo: str, sesion: str = "s1") -> str:
    return json.dumps(
        {
            "type": "assistant",
            "sessionId": sesion,
            "message": {
                "model": modelo,
                "content": [
                    {
                        "type": "tool_use",
                        "id": tool_use_id,
                        "name": "mcp__local-delegate__local_summarize",
                        "input": {},
                    }
                ],
            },
        }
    )


def _proyectos(tmp_path: Path) -> Path:
    raiz = tmp_path / "home" / ".claude" / "projects"
    (raiz / "D--proyecto").mkdir(parents=True, exist_ok=True)
    return raiz


def _escribir(ruta: Path, lineas: list[str]) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return ruta


def _anotar(notas: Path, tool_use_id: str, transcript: Path, **extra) -> None:
    assert hook_common.anotar_llamada(_entrada_hook(tool_use_id, transcript, **extra), notas)


# --- El hook ------------------------------------------------------------------------------------


def test_ida_y_vuelta_hook_servidor(tmp_path):
    """REQ-002: escribe el hook (proceso aparte) y lee el servidor. El esfuerzo sale de la entrada.

    Control (b): mutante «el hook toma `os.environ.get("CLAUDE_EFFORT")`» → el entorno dice
    `high` y la entrada `low`.
    """
    temporal = _temporal(tmp_path)
    entrada = _entrada_hook(
        "toolu_ida",
        "C:/x/s1.jsonl",
        agent_id="a1",
        agent_type=AGENTE,
        effort={"level": "low"},
    )
    proc = _lanzar_hook(json.dumps(entrada).encode("utf-8"), temporal)
    assert proc.returncode == 0, proc.stderr
    nota = atribucion.leer_nota("toolu_ida", directorio=_dir_notas(temporal))
    assert nota is not None, "el hook no dejó nota legible"
    assert nota.get("effort") == "low"
    assert nota.get("agent_id") == "a1"
    assert nota.get("agent_type") == AGENTE
    assert nota.get("transcript_path") == "C:/x/s1.jsonl"
    assert "session_id" not in nota


@pytest.mark.parametrize(
    "caso",
    ["valida", "stdin_roto", "id_malo"],
)
def test_el_hook_calla_y_sale_con_0(tmp_path, caso):
    """El hook no imprime nada y sale con 0 siempre; con un id que no casa, no deja nota.

    Control (b): mutante «el hook imprime la nota» → `proc.stdout` no vacío.
    """
    temporal = _temporal(tmp_path)
    if caso == "valida":
        entrada = json.dumps(_entrada_hook("toolu_calla", "C:/x/s.jsonl")).encode("utf-8")
    elif caso == "stdin_roto":
        entrada = b'{"tool_use_id": "toolu_roto", '
    else:
        entrada = json.dumps(_entrada_hook("toolu_../../fuera", "C:/x/s.jsonl")).encode("utf-8")
    proc = _lanzar_hook(entrada, temporal)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == b""
    dir_notas = _dir_notas(temporal)
    escritas = sorted(p.name for p in dir_notas.iterdir()) if dir_notas.exists() else []
    if caso == "valida":
        assert escritas == ["toolu_calla.json"], "guarda: el caso bueno sí escribe"
    else:
        assert escritas == []
    assert not any(tmp_path.rglob("fuera*")), "un id con `..` no puede escribir fuera"


def test_dos_llamadas_no_se_pisan(tmp_path):
    """Control (b), comprobado: con un nombre de fichero fijo la primera nota se pierde."""
    notas = tmp_path / "notas"
    _anotar(notas, "toolu_a", tmp_path / "s.jsonl")
    _anotar(notas, "toolu_b", tmp_path / "s.jsonl")
    assert atribucion.leer_nota("toolu_a", directorio=notas) is not None
    assert atribucion.leer_nota("toolu_b", directorio=notas) is not None


def test_ocho_hooks_a_la_vez(tmp_path):
    """Guarda: ocho procesos del hook lanzados juntos dejan ocho notas legibles."""
    temporal = _temporal(tmp_path)
    ids = [f"toolu_par{i}" for i in range(8)]
    procesos = [
        subprocess.Popen(
            [sys.executable, str(HOOK)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_entorno_del_hook(temporal),
        )
        for _ in ids
    ]
    for proceso, tool_use_id in zip(procesos, ids, strict=True):
        datos = json.dumps(_entrada_hook(tool_use_id, "C:/x/s.jsonl", agent_id=tool_use_id))
        proceso.communicate(datos.encode("utf-8"), timeout=30)
    assert all(p.returncode == 0 for p in procesos)
    notas = _dir_notas(temporal)
    assert sum(atribucion.leer_nota(i, directorio=notas) is not None for i in ids) == 8


def test_una_nota_a_medias_es_sin_nota(tmp_path):
    """Control (b): mutante «`leer_nota` sin `try`» → la excepción escapa."""
    notas = tmp_path / "notas"
    notas.mkdir()
    (notas / "toolu_medias.json").write_text('{"tool_use_id": ', encoding="utf-8")
    escapo = False
    resultado = "sin leer"
    try:
        resultado = atribucion.leer_nota("toolu_medias", directorio=notas)
    except Exception:
        escapo = True
    assert not escapo
    assert resultado is None


def test_el_hook_poda_las_notas_viejas(tmp_path):
    """Las notas de más de 10 min ya no cuentan, y el hook las borra al escribir otra."""
    notas = tmp_path / "notas"
    _anotar(notas, "toolu_vieja", tmp_path / "s.jsonl")
    vieja = notas / "toolu_vieja.json"
    hace_once_min = time.time() - 11 * 60
    os.utime(vieja, (hace_once_min, hace_once_min))
    _anotar(notas, "toolu_nueva", tmp_path / "s.jsonl")
    assert not vieja.exists()
    assert (notas / "toolu_nueva.json").is_file()


# --- La resolución ------------------------------------------------------------------------------


def test_resuelve_el_modelo_del_subagente(tmp_path):
    """REQ-003: la línea está en el transcript del SUBAGENTE, no en el que trae la nota.

    Control (b): mutante «buscar en el `transcript_path` de la nota» → `caller_model` None.
    """
    raiz = _proyectos(tmp_path)
    principal = _escribir(raiz / "D--proyecto" / "s1.jsonl", [_linea_tool_use("toolu_otro", OPUS)])
    _escribir(
        raiz / "D--proyecto" / "s1" / "subagents" / "agent-a1.jsonl",
        [_linea_tool_use("toolu_sub", OPUS)],
    )
    notas = tmp_path / "notas"
    _anotar(
        notas, "toolu_sub", principal, agent_id="a1", agent_type=AGENTE, effort={"level": "low"}
    )
    r = atribucion.resolver_llamada("toolu_sub", notas=notas, proyectos=raiz)
    assert r.get("caller_model") == OPUS
    assert r.get("caller_kind") == "subagent"
    assert r.get("caller_agent_type") == AGENTE
    assert r.get("caller_effort") == "low"
    assert r.get("caller_src") == "hook+transcript"


def test_en_el_principal_no_hay_agent_type(tmp_path):
    """Control (b): mutante «copiar siempre `agent_type`» → aparece en el principal."""
    raiz = _proyectos(tmp_path)
    principal = _escribir(raiz / "D--proyecto" / "s1.jsonl", [_linea_tool_use("toolu_main", OPUS)])
    notas = tmp_path / "notas"
    _anotar(notas, "toolu_main", principal, agent_type=AGENTE, effort={"level": "high"})
    r = atribucion.resolver_llamada("toolu_main", notas=notas, proyectos=raiz)
    assert r.get("caller_model") == OPUS, "guarda: la resolución llegó al transcript"
    assert r.get("caller_kind") == "main"
    assert "caller_agent_type" not in r


def test_una_ruta_fuera_de_projects_no_se_abre(tmp_path):
    """Control (b): mutante «sin la validación de la ruta» → el fichero tiene la línea."""
    raiz = _proyectos(tmp_path)
    fuera = _escribir(tmp_path / "fuera" / "s1.jsonl", [_linea_tool_use("toolu_fuera", OPUS)])
    notas = tmp_path / "notas"
    _anotar(notas, "toolu_fuera", fuera, effort={"level": "high"})
    r = atribucion.resolver_llamada("toolu_fuera", notas=notas, proyectos=raiz)
    assert r.get("caller_kind") == "main", "guarda: la nota sí se leyó"
    assert r.get("caller_model") is None
    assert r.get("caller_src") == "hook"


def test_la_carrera_deja_caller_src_hook(tmp_path):
    """Guarda: hay nota pero la línea aún no está escrita (la carrera medida)."""
    raiz = _proyectos(tmp_path)
    principal = _escribir(raiz / "D--proyecto" / "s1.jsonl", [_linea_tool_use("toolu_otra", OPUS)])
    notas = tmp_path / "notas"
    _anotar(notas, "toolu_carrera", principal, effort={"level": "high"})
    r = atribucion.resolver_llamada("toolu_carrera", notas=notas, proyectos=raiz)
    assert r.get("caller_src") == "hook"
    assert "caller_model" not in r


def test_una_nota_vieja_no_cuenta(tmp_path):
    """Control (b): mutante «sin el filtro de edad» → la nota de hace 11 min cuenta."""
    raiz = _proyectos(tmp_path)
    principal = _escribir(raiz / "D--proyecto" / "s1.jsonl", [_linea_tool_use("toolu_vieja", OPUS)])
    notas = tmp_path / "notas"
    _anotar(notas, "toolu_vieja", principal)
    ahora = time.time()
    assert "caller_kind" in atribucion.resolver_llamada(
        "toolu_vieja", notas=notas, proyectos=raiz, ahora=ahora
    ), "guarda: la misma nota, fresca, sí cuenta"
    r = atribucion.resolver_llamada("toolu_vieja", notas=notas, proyectos=raiz, ahora=ahora + 660)
    assert "caller_kind" not in r


def test_haiku_sin_esfuerzo_es_na_y_opus_sin_esfuerzo_falta(tmp_path):
    """Control (b): mutante «`n/a` para todo esfuerzo que falte» → Opus lleva `n/a`."""
    raiz = _proyectos(tmp_path)
    principal = _escribir(
        raiz / "D--proyecto" / "s1.jsonl",
        [
            _linea_tool_use("toolu_haiku", "claude-haiku-4-5-20251001"),
            _linea_tool_use("toolu_opus", OPUS),
        ],
    )
    notas = tmp_path / "notas"
    _anotar(notas, "toolu_haiku", principal)
    _anotar(notas, "toolu_opus", principal)
    r_haiku = atribucion.resolver_llamada("toolu_haiku", notas=notas, proyectos=raiz)
    r_opus = atribucion.resolver_llamada("toolu_opus", notas=notas, proyectos=raiz)
    assert r_haiku.get("caller_model") == "claude-haiku-4-5"
    assert r_haiku.get("caller_effort") == "n/a"
    assert r_opus.get("caller_model") == OPUS, "guarda: Opus también se resolvió"
    assert "caller_effort" not in r_opus


class _Contador:
    """Un flujo que suma en `espia.leidos` los bytes que se leen de verdad."""

    def __init__(self, flujo, espia) -> None:
        self._flujo = flujo
        self._espia = espia

    def seek(self, *a):
        return self._flujo.seek(*a)

    def tell(self):
        return self._flujo.tell()

    def read(self, *a):
        datos = self._flujo.read(*a)
        self._espia.leidos += len(datos)
        return datos


class _EspiaDeLectura:
    """Sustituye a `open` en `resolver_llamada(abrir=...)`."""

    def __init__(self) -> None:
        self.leidos = 0

    @contextlib.contextmanager
    def __call__(self, ruta, modo="r", *args, **kwargs):
        with open(ruta, modo, *args, **kwargs) as flujo:
            yield _Contador(flujo, self)


def test_no_lee_mas_de_256_kb(tmp_path):
    """Control (b): mutante «leer el fichero entero» → lee 50 MB."""
    raiz = _proyectos(tmp_path)
    principal = raiz / "D--proyecto" / "s1.jsonl"
    relleno = (json.dumps({"type": "user", "relleno": "x" * 1000}) + "\n").encode("utf-8")
    with principal.open("wb") as flujo:
        flujo.write((_linea_tool_use("toolu_lejos", OPUS) + "\n").encode("utf-8"))
        bloque = relleno * 1024
        while flujo.tell() < 50 * 1024 * 1024:
            flujo.write(bloque)
    notas = tmp_path / "notas"
    _anotar(notas, "toolu_lejos", principal)
    espia = _EspiaDeLectura()
    r = atribucion.resolver_llamada("toolu_lejos", notas=notas, proyectos=raiz, abrir=espia)
    assert espia.leidos > 0, "guarda: se llegó a abrir el transcript"
    assert espia.leidos <= 256 * 1024
    assert r.get("caller_model") is None


def test_el_presupuesto_de_50_ms_corta(tmp_path):
    """Control (b): mutante «ignorar el reloj» → la línea, que está en la cola, se encuentra."""
    raiz = _proyectos(tmp_path)
    principal = _escribir(
        raiz / "D--proyecto" / "s1.jsonl",
        [json.dumps({"type": "user"})] * 5 + [_linea_tool_use("toolu_lento", OPUS)],
    )
    notas = tmp_path / "notas"
    _anotar(notas, "toolu_lento", principal)
    parado = atribucion.resolver_llamada(
        "toolu_lento", notas=notas, proyectos=raiz, reloj=lambda: 0.0
    )
    assert parado.get("caller_model") == OPUS, "guarda: con tiempo de sobra se encuentra"

    instantes = iter(i * 0.060 for i in range(1000))
    r = atribucion.resolver_llamada(
        "toolu_lento", notas=notas, proyectos=raiz, reloj=lambda: next(instantes)
    )
    assert r.get("caller_model") is None


# --- `_log_event` -------------------------------------------------------------------------------


@pytest.fixture
def log_y_notas(tmp_path, monkeypatch):
    """El log de uso, el directorio de notas y la raíz de proyectos, todos en `tmp_path`."""
    log = tmp_path / "usage.jsonl"
    notas = tmp_path / "notas"
    raiz = _proyectos(tmp_path)
    monkeypatch.setattr(server, "_current_log_path", lambda: log)
    monkeypatch.setattr(hook_common, "directorio_de_notas_de_llamadas", lambda: notas)
    monkeypatch.setattr(atribucion, "_raiz_de_proyectos", lambda: raiz)
    return log, notas, raiz


def _lineas(log: Path) -> list[dict]:
    if not log.is_file():
        return []
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]


def _log_minimo() -> None:
    server._log_event(
        tool="local_summarize",
        model="m",
        source="inline",
        chars_in=10,
        chars_out=5,
        latency_ms=1,
        ok=True,
    )


def _en_peticion(tool_use_id: str, funcion):
    """Corre `funcion` como si fuera dentro de una petición con ese `tool_use_id`."""
    t1 = clients._TOOL_USE_ID_ACTUAL.set(tool_use_id)
    t2 = clients._MEMORIA_PETICION.set({})
    try:
        return funcion()
    finally:
        clients._MEMORIA_PETICION.reset(t2)
        clients._TOOL_USE_ID_ACTUAL.reset(t1)


def test_log_event_escribe_la_atribucion_y_ningun_id_de_sesion(log_y_notas):
    """Control (c): en el corte, `tool_use_id_actual()` devolvía `None` y no había campo."""
    log, notas, raiz = log_y_notas
    marcador = "sesion-marcador-7f3a"
    principal = _escribir(
        raiz / "D--proyecto" / f"{marcador}.jsonl",
        [_linea_tool_use("toolu_x", OPUS, sesion=marcador)],
    )
    _anotar(notas, "toolu_x", principal, session_id=marcador, effort={"level": "high"})
    _en_peticion("toolu_x", _log_minimo)
    lineas = _lineas(log)
    assert len(lineas) == 1
    linea = lineas[0]
    assert linea.get("tool_use_id") == "toolu_x"
    assert linea.get("caller_model") == OPUS
    assert linea.get("caller_src") == "hook+transcript"
    assert "session_id" not in linea
    assert marcador not in json.dumps(linea)


def test_sin_tool_use_id_la_linea_no_lleva_campos_de_atribucion(log_y_notas):
    log, _notas, _raiz = log_y_notas
    _log_minimo()
    linea = _lineas(log)[0]
    assert "tool_use_id" not in linea
    assert not [k for k in linea if k.startswith("caller_")]


def test_una_resolucion_rota_no_se_lleva_la_linea(log_y_notas, monkeypatch):
    """Control (b), comprobado: sin su `try` propio, la `RuntimeError` sale de `_log_event`."""
    log, _notas, _raiz = log_y_notas

    def revienta(*_a, **_k):
        raise RuntimeError("resolución rota")

    monkeypatch.setattr(atribucion, "resolver_llamada", revienta)
    escapo = False
    try:
        _en_peticion("toolu_roto", _log_minimo)
    except Exception:
        escapo = True
    assert not escapo
    lineas = _lineas(log)
    assert len(lineas) == 1
    assert lineas[0].get("tool_use_id") == "toolu_roto"


class _Espia:
    def __init__(self, original):
        self.original = original
        self.llamadas = 0

    def __call__(self, *a, **k):
        self.llamadas += 1
        return self.original(*a, **k)


async def _peticiones(ids: list[str], en_la_tool) -> list:
    """Arnés de `test_clients.py`: un servidor con el middleware y una llamada por id."""
    servidor = MCPServer("prueba", version="0.0.0", middleware=[clients.observar_cliente])
    vistos: list = []

    @servidor.tool()
    def delega() -> str:
        """Tool SÍNCRONA, como las de verdad."""
        vistos.append(en_la_tool())
        return "ok"

    async with create_client_server_memory_streams() as ((cr, cw), (sr, sw)):
        low = servidor._lowlevel_server
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: low.run(sr, sw, low.create_initialization_options(), raise_exceptions=True)
            )
            info = Implementation(name="claude-code", version="1.0.0")
            async with ClientSession(cr, cw, client_info=info) as cliente:
                await cliente.initialize()
                for tool_use_id in ids:
                    await cliente.call_tool(
                        "delega", {}, meta={clients.CLAVE_TOOL_USE_ID: tool_use_id}
                    )
            tg.cancel_scope.cancel()
    return vistos


def test_la_resolucion_se_hace_una_vez_por_peticion(log_y_notas, monkeypatch):
    """Control (b): mutante «`llamada_actual` sin memoria» → se resuelve dos veces."""
    log, notas, raiz = log_y_notas
    principal = _escribir(raiz / "D--proyecto" / "s1.jsonl", [_linea_tool_use("toolu_una", OPUS)])
    _anotar(notas, "toolu_una", principal)
    espia = _Espia(atribucion.resolver_llamada)
    monkeypatch.setattr(atribucion, "resolver_llamada", espia)

    def en_la_tool():
        _log_minimo()
        return atribucion.llamada_actual()

    vistos = anyio.run(_peticiones, ["toolu_una"], en_la_tool)
    assert vistos and vistos[0].get("caller_model") == OPUS, "guarda: se resolvió de verdad"
    assert _lineas(log)[0].get("caller_model") == OPUS
    assert espia.llamadas == 1


def test_la_memoria_no_cruza_peticiones(log_y_notas):
    """Control (b): mutante «memoria en un dict del módulo» → en la segunda hay dos entradas."""
    _log, notas, raiz = log_y_notas
    principal = _escribir(
        raiz / "D--proyecto" / "s1.jsonl",
        [_linea_tool_use("toolu_p1", OPUS), _linea_tool_use("toolu_p2", OPUS)],
    )
    _anotar(notas, "toolu_p1", principal)
    _anotar(notas, "toolu_p2", principal)

    def en_la_tool():
        atribucion.llamada_actual()
        memoria = clients.memoria_de_peticion()
        return sorted(memoria) if memoria is not None else None

    vistos = anyio.run(_peticiones, ["toolu_p1", "toolu_p2"], en_la_tool)
    assert len(vistos) == 2
    assert vistos[0] == ["toolu_p1"], "guarda: la primera memorizó su resolución"
    memoria_de_la_segunda = vistos[1]
    assert len(memoria_de_la_segunda) == 1
    assert memoria_de_la_segunda == ["toolu_p2"]


# --- Relleno, exclusión y plazo ------------------------------------------------------------------


def test_dos_lineas_del_mismo_segundo_no_comparten_clave():
    """REQ-005. Control (b): mutante «clave `ts|tool`» → las dos comparten clave."""
    ts = "2026-10-06T12:00:00+00:00"
    filas = [{"ts": ts, "tool": "local_summarize"}, {"ts": ts, "tool": "local_summarize"}]
    claves_antes = atribucion.claves_del_fichero(filas)
    assert len(set(claves_antes)) == 2
    claves = atribucion.claves_del_fichero([*filas, {"ts": ts, "tool": "local_summarize"}])
    assert claves[:2] == claves_antes
    assert len(set(claves)) == 3
    con_id = atribucion.claves_del_fichero([{"ts": ts, "tool": "x", "tool_use_id": "toolu_k"}])
    assert con_id == ["toolu_k"]


def test_el_relleno_solo_mejora(tmp_path):
    """REQ-005. Control (b): mutante «escribir siempre la nueva» → `ventana` pisa a `exacto`."""
    atribucion.escribir_relleno(
        tmp_path,
        "202610",
        {"k1": {"cruce": "exacto", "caller_model": OPUS}, "k2": {"cruce": "ambiguo"}},
    )
    atribucion.escribir_relleno(
        tmp_path,
        "202610",
        {
            "k1": {"cruce": "ventana", "caller_model": "claude-haiku-4-5"},
            "k2": {"cruce": "ventana", "caller_model": OPUS},
        },
    )
    assert (tmp_path / "atribucion-202610.json").is_file()
    entradas = atribucion.leer_relleno(tmp_path, "202610")
    assert entradas["k1"]["cruce"] == "exacto"
    assert entradas["k1"]["caller_model"] == OPUS
    assert entradas["k2"]["cruce"] == "ventana", "guarda: un cruce mejor sí sustituye"
    atribucion.escribir_relleno(tmp_path, "202610", {"k3": {"cruce": "sin_cruce"}})
    assert set(atribucion.leer_relleno(tmp_path, "202610")) == {"k1", "k2", "k3"}


def test_excluida():
    """REQ-007. Control (b): mutante «sin la rama de `banco`» → la de banco cuenta."""
    assert atribucion.excluida({"client": "codex-mcp-client"}) == "no es Claude"
    assert atribucion.excluida({"client": "mcp"}) == "pruebas"
    f = {"client": "claude-code"}
    assert atribucion.excluida(f, {"banco": True}) == "pruebas"
    assert atribucion.excluida(f, {"banco": False}) is None
    assert atribucion.excluida(f) is None


def test_plazo_de_borrado(tmp_path):
    """Enmienda 1. Control (b): mutante «devolver 30 siempre» → no lee los 90."""
    d = tmp_path / "claude"
    d.mkdir()
    assert atribucion.plazo_de_borrado(d) == 30
    (d / "settings.json").write_text(json.dumps({"cleanupPeriodDays": 90}), encoding="utf-8")
    assert atribucion.plazo_de_borrado(d) == 90
    for malo in ("abc", 0, -5, True, 1.5):
        (d / "settings.json").write_text(json.dumps({"cleanupPeriodDays": malo}), encoding="utf-8")
        assert atribucion.plazo_de_borrado(d) == 30, malo
    (d / "settings.json").write_text("{roto", encoding="utf-8")
    assert atribucion.plazo_de_borrado(d) == 30


# --- Una sola regla de «es una prueba» (test-windows-out-of-metrics, REQ-004) -------------------


def test_test_reason_reconoce_las_tres_clases_de_prueba():
    """Control: mutante «`test_reason` ignora `test_window`» → falla el caso de la ventana."""
    assert atribucion.test_reason({"client": "mcp"}) == "pruebas"
    assert atribucion.test_reason({"client": "claude-code"}, {"banco": True}) == "pruebas"
    # El panel la llama con un solo argumento sobre la fila ya fundida, que trae `banco`.
    assert atribucion.test_reason({"client": "claude-code", "banco": True}) == "pruebas"
    assert atribucion.test_reason({"client": "claude-code", "test_window": "w-1"}) == "pruebas"
    assert atribucion.test_reason({"client": "codex-mcp-client"}) is None
    assert atribucion.test_reason({"client": "claude-code"}) is None


def test_excluida_suma_no_claude_y_pruebas():
    assert atribucion.excluida({"client": "codex-mcp-client"}) == "no es Claude"
    assert atribucion.excluida({"client": "claude-code", "test_window": "w-1"}) == "pruebas"
    assert atribucion.excluida({"client": "claude-code"}) is None
