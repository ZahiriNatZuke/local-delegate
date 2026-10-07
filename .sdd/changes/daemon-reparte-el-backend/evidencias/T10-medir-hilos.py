"""T10, punto 10 (copia del script de la medición; uso:
`uv run python <este fichero> tests/fixtures/topologia/hoy.yaml` desde la raíz del repo).

T10, punto 10 (REQ-007): ¿con cuántas esperas dejan de contestar `local_status` y /api/inflight?

Criterio, escrito en el plan ANTES de medir: se para y se lleva a la sesión principal solo si el N con
turno es menor que el de la línea base, o menor que 3 veces el pico de operaciones simultáneas de
T0.6 (8, o sea 24).

Montaje: un SOLO bucle de eventos, como en el daemon (uvicorn sirve MCP y panel en el mismo bucle, y
el limitador de hilos por defecto de anyio, 40, es uno por bucle). El MCP es el `server.mcp` real por
streams en memoria (el arnés de `tests/test_clients.py`); el panel es la app real del daemon
(`daemon.build_app`, sin token) por `httpx2.ASGITransport`, en el MISMO bucle. Con `TestClient` el
panel correría en otro bucle, con otro limitador, y no mediría nada.

Guion (idéntico en los dos casos salvo la topología):
- 2 operaciones `local_summarize` del 26B que el backend simulado retiene (las dos plazas);
- N operaciones `local_commit_msg` (Qwen3.6). Línea base (sin topología): esperan PLAZA. Con turno
  (topología de hoy, copia del fixture): esperan TURNO.
Para cada N de 1 a 45 se sondean `local_status` (por MCP) y `GET /api/inflight`, con tope de 2 s
cada uno. N medido = el menor N con el que alguno no contesta.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import anyio
import httpx2
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

# Sin ninguna variable del paquete ni de llama-swap del usuario (como la suite), ANTES de cargar el
# paquete: `config` lee el entorno al importarse.
for nombre in list(os.environ):
    if nombre.startswith(("LOCAL_DELEGATE_", "LLAMASWAP_")):
        del os.environ[nombre]

config = importlib.import_module("local_delegate.config")
daemon = importlib.import_module("local_delegate.daemon")
server = importlib.import_module("local_delegate.server")
topologia = importlib.import_module("local_delegate.topologia")

HOY = Path(sys.argv[1])  # tests/fixtures/topologia/hoy.yaml
TOPE_S = 2.0
N_MAX = 45

trabajo = Path(tempfile.mkdtemp(prefix="t10-hilos-"))
config.LOG_DIR = trabajo
config.USAGE_LOG = trabajo / "usage.jsonl"
copia = trabajo / "llamaswap.yaml"
copia.write_bytes(HOY.read_bytes())

soltar = threading.Event()


def post_chat(model, _payload):
    soltar.wait(60)
    return server.ChatResult(text="ok", ok=True, finish_reason="stop")


server._post_chat = post_chat
server.sondear_backend = lambda: server.EstadoBackend(True, [], False, None, None, 200)
server._llamaswap_running = lambda: None
server._vram_info = lambda: None
server._ram_info = lambda: None
server._port_listening = lambda _h, _p: True

TEXTO_LARGO = ("palabra " * 1000).strip()  # 7 999 chars > LONG_INPUT_CHARS: rol largo (26B)
DIFF = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n+hola\n"


def esperando() -> int:
    return sum(1 for e in server.inflight_snapshot() if e.get("espera_local") in ("plaza", "turno"))


def en_backend() -> int:
    return sum(1 for e in server.inflight_snapshot() if e.get("tool") == "local_summarize")


async def una_ronda(sesion: ClientSession, panel: httpx2.AsyncClient, n: int) -> dict:
    soltar.clear()
    server._reiniciar_turno()
    topologia._olvidar()
    resultado = {"n": n}
    async with anyio.create_task_group() as tg:
        for _ in range(2):
            tg.start_soon(sesion.call_tool, "local_summarize", {"text": TEXTO_LARGO})
        fin = time.monotonic() + 10
        while en_backend() < 2 and time.monotonic() < fin:
            await anyio.sleep(0.02)
        for _ in range(n):
            tg.start_soon(sesion.call_tool, "local_commit_msg", {"diff": DIFF})
        # Hasta que estén las N esperando, o hasta que el número deje de subir (sin hilo libre,
        # las que sobran no llegan ni a empezar).
        fin = time.monotonic() + 10
        visto, quieto_desde = -1, time.monotonic()
        while time.monotonic() < fin:
            ahora = esperando()
            if ahora >= n:
                break
            if ahora != visto:
                visto, quieto_desde = ahora, time.monotonic()
            elif time.monotonic() - quieto_desde > 1.0:
                break
            await anyio.sleep(0.02)
        resultado["esperando"] = esperando()
        resultado["motivos"] = sorted(
            {
                str(e.get("espera_local"))
                for e in server.inflight_snapshot()
                if e.get("espera_local")
            }
        )
        t0 = time.monotonic()
        resultado["status_ok"] = False
        with anyio.move_on_after(TOPE_S):
            r = await sesion.call_tool("local_status", {})
            texto = r.content[0].text if r.content else ""
            resultado["status_ok"] = "Turno:" in texto
            resultado["turno"] = next(
                (x for x in texto.splitlines() if x.startswith("Turno:")), None
            )
        resultado["status_s"] = round(time.monotonic() - t0, 2)
        t0 = time.monotonic()
        resultado["inflight_ok"] = False
        with anyio.move_on_after(TOPE_S):
            r = await panel.get("/api/inflight")
            resultado["inflight_ok"] = r.status_code == 200
        resultado["inflight_s"] = round(time.monotonic() - t0, 2)
        soltar.set()
    return resultado


async def medir(con_turno: bool) -> list[dict]:
    if con_turno:
        os.environ["LLAMASWAP_CONFIG"] = str(copia)
    else:
        os.environ.pop("LLAMASWAP_CONFIG", None)
    app = daemon.build_app("127.0.0.1", 9393)
    filas: list[dict] = []
    async with create_client_server_memory_streams() as ((cr, cw), (sr, sw)):
        low = server.mcp._lowlevel_server
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: low.run(sr, sw, low.create_initialization_options(), raise_exceptions=False)
            )
            async with (
                ClientSession(cr, cw) as sesion,
                httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:9393"
                ) as panel,
            ):
                await sesion.initialize()
                for n in range(1, N_MAX + 1):
                    fila = await una_ronda(sesion, panel, n)
                    filas.append(fila)
                    print(json.dumps({"turno": con_turno, **fila}, ensure_ascii=False), flush=True)
                    if not (fila["status_ok"] and fila["inflight_ok"]):
                        break
            tg.cancel_scope.cancel()
    return filas


def main() -> None:
    limitador = None

    async def leer_limitador() -> int:
        return int(anyio.to_thread.current_default_thread_limiter().total_tokens)

    limitador = anyio.run(leer_limitador)
    base = anyio.run(medir, False)
    turno = anyio.run(medir, True)
    n_base = next((f["n"] for f in base if not (f["status_ok"] and f["inflight_ok"])), None)
    n_turno = next((f["n"] for f in turno if not (f["status_ok"] and f["inflight_ok"])), None)
    pico = 8
    parar = (n_turno is not None) and (
        (n_base is not None and n_turno < n_base) or n_turno < 3 * pico
    )
    print(
        json.dumps(
            {
                "limitador": limitador,
                "n_base": n_base,
                "n_turno": n_turno,
                "pico_T0_6": pico,
                "umbral_3x_pico": 3 * pico,
                "parar": parar,
            }
        )
    )


if __name__ == "__main__":
    main()
