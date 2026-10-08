"""metrics.py — dashboard de uso/ahorro de local-delegate.

Lee los usage-YYYYMM.jsonl rotados por mes (+ el usage.jsonl legado si existe) y sirve:
  GET /               -> dashboard HTML (Chart.js por CDN; rango temporal server-side)
  GET /api/events     -> eventos en [from, to] (más recientes primero) + meta
  GET /api/stats      -> agregados JSON del mismo rango
  GET /api/inflight   -> delegaciones en curso compartidas por usuario (inflight.json)
  GET /api/backend    -> proxy best-effort de /running de llama-swap
  GET /api/backend/stats -> proxy best-effort de /api/metrics/stats de llama-swap (#898, SQLite)
  GET /api/status     -> versión del MCP, modelos del backend con status loaded/unloaded (#901),
                         catálogo y tools
  GET /api/system     -> RAM/VRAM de sistema + consumo por proceso (best-effort, ver sysinfo)
  GET /api/llamaswap/status, POST /api/llamaswap/watch, GET /api/llamaswap/watch/<id>
                      -> estado de llama-swap y vigía de recarga para `llamaswap residency`
                         (siempre tras el token web)
  GET /favicon.svg    -> icono de marca (chip) servido inline

`from`/`to` son ISO 8601 (fecha u datetime); sin parámetros, por defecto los últimos 30 días.
Solo se abren los archivos cuyo mes interseca el rango pedido — releer un rango de un mes no
recorre el histórico completo. Cache en memoria por archivo (mtime+size); solo el archivo del
mes actual cambia entre refrescos.

/api/inflight lee un archivo compartido (LOG_DIR/inflight.json, ver server._inflight_mutate) en
vez de memoria local: ve las delegaciones en curso de TODAS las sesiones de Claude activas en
esta máquina (mismo usuario del SO), no solo la del proceso que sirve esta web.

Tres formas de arrancar:
  0) Recomendada multi-cliente: ``local-delegate serve`` monta esta app junto al MCP HTTP,
     con un único proceso persistente y un único puerto.
  1) Automática: el MCP (server.py) llama a run_in_thread() en un hilo daemon,
     de modo que la web vive y muere con el MCP. Si el puerto ya está ocupado
     (otra instancia de Claude), no monta una segunda.
  2) Manual: ``python -m local_delegate.web.metrics``  (127.0.0.1:9393 por defecto)

Solo LEE los JSONL; no interfiere con el MCP ni con el backend (salvo el proxy best-effort
de /api/backend, una lectura de estado sin efectos).
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from importlib.resources import files as _resource_files
from pathlib import Path

import httpx2
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .. import (
    atribucion,
    clients,
    config,
    coste,
    cuota,
    fallos,
    llamaswap_api,
    precios,
    recalcular,
    server,
    test_windows,
    topology,
    valoracion,
)
from . import auth, sysinfo

CHARS_PER_TOKEN = config.CHARS_PER_TOKEN  # aproximación: tokens ~ chars / 4
MAX_EVENTS = 5000  # tope de eventos servidos al cliente
_MONTH_FILE_RE = re.compile(r"^usage-(\d{6})\.jsonl$")

app = FastAPI(title="local-delegate metrics")

# {ruta: (mtime, size, filas)} — releer un archivo solo si cambió desde la última lectura.
_FILE_CACHE: dict[str, tuple[float, int, list[dict]]] = {}


def _log_files() -> list[tuple]:
    """Lista (path, ym) de archivos de log candidatos. ym=None = legado, siempre candidato."""
    files: list[tuple] = []
    seen = set()
    log_dir = config.LOG_DIR
    if log_dir.is_dir():
        for p in sorted(log_dir.glob("usage-*.jsonl")):
            m = _MONTH_FILE_RE.match(p.name)
            if m:
                files.append((p, m.group(1)))
                seen.add(p.resolve())
    legacy = config.USAGE_LOG
    if legacy.is_file() and legacy.resolve() not in seen:
        files.append((legacy, None))
    return files


def _read_file_cached(path) -> list[dict]:
    """Lee un JSONL tolerando líneas corruptas; cachea por (mtime, size)."""
    try:
        st = path.stat()
    except OSError:
        return []
    key = str(path)
    cached = _FILE_CACHE.get(key)
    if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
        return cached[2]
    rows: list[dict] = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    _FILE_CACHE[key] = (st.st_mtime, st.st_size, rows)
    return rows


def _month_span(ym: str) -> tuple[datetime, datetime]:
    year, month = int(ym[:4]), int(ym[4:6])
    start = datetime(year, month, 1, tzinfo=UTC)
    end = datetime(year + (month == 12), (month % 12) + 1, 1, tzinfo=UTC)
    return start, end


def _parse_ts(ts) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _parse_range_param(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _resolve_range(from_: str | None, to_: str | None) -> tuple[datetime, datetime]:
    """Sin from/to -> últimos 30 días. Con solo uno de los dos, el otro se abre hasta el límite."""
    range_from = _parse_range_param(from_)
    range_to = _parse_range_param(to_)
    if range_from is None and range_to is None:
        range_to = datetime.now(UTC)
        range_from = range_to - timedelta(days=30)
    elif range_to is None:
        range_to = datetime.now(UTC)
    elif range_from is None:
        range_from = datetime(2000, 1, 1, tzinfo=UTC)
    return range_from, range_to


def _load(range_from: datetime, range_to: datetime) -> tuple[list[dict], list[str]]:
    """Eventos en [range_from, range_to], abriendo solo los archivos cuyo mes toca el rango."""
    rows: list[dict] = []
    files_read: list[str] = []
    for path, ym in _log_files():
        if ym is not None:
            m_start, m_end = _month_span(ym)
            if m_start > range_to or m_end <= range_from:
                continue
        file_rows = _read_file_cached(path)
        if not file_rows:
            continue
        files_read.append(str(path))
        # Fusión del relleno y densidad resuelta (coste-api-y-cuota, REQ-006): por fichero y ANTES
        # de filtrar por rango, porque la clave de una línea sin `tool_use_id` lleva su ordinal en
        # el fichero entero. `fundir` copia cada fila: la caché de `_read_file_cached` no cambia.
        for r in coste.fundir(file_rows, log_dir=config.LOG_DIR):
            t = _parse_ts(r.get("ts"))
            if t is None or t < range_from or t > range_to:
                continue
            rows.append(r)
    return rows, files_read


def _last_event() -> dict | None:
    """El evento más reciente de TODO el histórico (no del rango elegido).

    El indicador EN CURSO/EN VIVO/EN REPOSO del dashboard tiene que ser independiente del
    selector de rango: mirar solo el rango hacía que "Hoy" (o un mes pasado) apagara el
    indicador aunque el MCP acabara de trabajar. Solo abre el archivo más nuevo y se apoya
    en el cache por (mtime, size), así que sondearlo es barato.

    Devuelve la fila entera —y no solo su `ts`— porque el panel "En curso" enseña la última
    delegación **terminada** cuando no hay ninguna viva: las tareas mecánicas duran 2-4 s y un
    panel que solo muestra lo que corre ahora mismo está vacío casi siempre.
    """
    files = _log_files()
    if not files:
        return None
    # el archivo del mes más reciente primero; el legado (ym=None) al final como respaldo
    ordered = sorted(files, key=lambda f: (f[1] is not None, f[1] or ""), reverse=True)
    for path, _ym in ordered:
        rows = _read_file_cached(path)
        for row in reversed(rows):
            ts = row.get("ts")
            if isinstance(ts, str) and ts:
                return row
    return None


def _last_event_ts() -> str | None:
    """`ts` del evento más reciente, o `None` si el log está vacío."""
    evento = _last_event()
    return evento.get("ts") if evento else None


# La contabilidad por evento vive en `server.py`, junto a `_log_event` que define el formato
# del log: es la ÚNICA implementación, y así `local_status` y el dashboard no pueden dar
# números distintos del mismo log.
_accounting = server._accounting


def _aggregate(rows: list[dict]) -> dict:
    by_tool: dict[str, dict] = defaultdict(
        lambda: {
            "calls": 0,
            "backend_calls": 0,
            "chars_in": 0,
            "chars_out": 0,
            "latency_ms": 0,
            "errors": 0,
            "saved": 0,
            "net": 0,
            "tokens_in": 0,
            "tokens_out": 0,
        }
    )
    by_model: dict[str, dict] = defaultdict(
        lambda: {
            "calls": 0,
            "backend_calls": 0,
            "chars_in": 0,
            "chars_out": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            # Operaciones que respondió este modelo en lugar de otro (F3, REQ-013).
            "fallback_calls": 0,
        }
    )
    # Quién PIDIÓ la delegación. Sin esto el KPI acumulado no puede distinguir un mes de smoke
    # tests de un mes de trabajo real: es lo que obligó a cruzar a mano contra los transcripts en
    # la medición del 3-ago. Las líneas anteriores a que existiera el campo caen en "desconocido"
    # —una casilla propia, ni repartidas ni descartadas—, que es lo que de verdad se sabe de ellas.
    by_client: dict[str, dict] = defaultdict(
        lambda: {
            "calls": 0,
            "backend_calls": 0,
            "saved": 0,
            "net": 0,
            "tokens_in": 0,
            "tokens_out": 0,
        }
    )
    # Origen del CÓMPUTO: "local" (backend en esta máquina), "remote" (p. ej. esta Mac usando
    # la GPU de la PC) o "unknown" para eventos anteriores a que se registrara el campo.
    by_backend: dict[str, dict] = defaultdict(
        lambda: {
            "calls": 0,
            "backend_calls": 0,
            "chars_in": 0,
            "chars_out": 0,
            "saved": 0,
            "net": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "hosts": set(),
        }
    )
    total = {
        "calls": 0,  # eventos, o sea delegaciones que pidió Claude
        "backend_calls": 0,  # llamadas REALES al backend: una troceada gasta N
        "chars_in": 0,
        "chars_out": 0,
        "errors": 0,
        "chars_in_path": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "saved": 0,  # bruto, ya sin fallos
        "returned": 0,  # lo que las tools devolvieron al contexto
        "net": 0,  # bruto − devuelto; puede ser negativo
        # Desglose en caracteres del contrato con `coste-api-y-cuota` (la imagen, en bytes).
        "chars_saved_text": 0,
        "bytes_saved_image": 0,
        "chars_saved_output": 0,
        "chars_returned": 0,
        "estimated_events": 0,  # cuántos no traían token real y hubo que estimar
        "fallback_events": 0,  # respondió un respaldo: la medición pudo contaminarla un swap
    }
    # Causa de cada fallo o salto (`configuracion`, `modelo`, `enfriamiento`…): una de configuración
    # tiene que verse en el panel para que alguien la arregle (REQ-019).
    causes: dict[str, int] = defaultdict(int)

    for r in rows:
        tool = str(r.get("tool", "?"))
        model = str(r.get("model", "?"))
        backend = str(r.get("backend") or "unknown")
        ci = int(r.get("chars_in", 0) or 0)
        co = int(r.get("chars_out", 0) or 0)
        lat = int(r.get("latency_ms", 0) or 0)
        is_path = r.get("source") == "path"
        acc = _accounting(r)
        # REQ-006: un solo predicado de fallo, el de la contabilidad (`ok` exactamente `False`).
        # Antes `bool(r.get("ok", True))` contaba un `ok: null` como error.
        failed = acc["failed"]

        t = by_tool[tool]
        t["calls"] += 1
        t["backend_calls"] += acc["backend_calls"]
        t["chars_in"] += ci
        t["chars_out"] += co
        t["latency_ms"] += lat
        t["tokens_in"] += acc["tokens_in"]
        t["tokens_out"] += acc["tokens_out"]
        t["saved"] += acc["saved"]
        t["net"] += acc["net"]
        if failed:
            t["errors"] += 1
        m = by_model[model]
        m["calls"] += 1
        m["backend_calls"] += acc["backend_calls"]
        m["chars_in"] += ci
        m["chars_out"] += co
        m["tokens_in"] += acc["tokens_in"]
        m["tokens_out"] += acc["tokens_out"]
        if acc["fallback"]:
            m["fallback_calls"] += 1

        b = by_backend[backend]
        b["calls"] += 1
        b["backend_calls"] += acc["backend_calls"]
        b["chars_in"] += ci
        b["chars_out"] += co
        b["tokens_in"] += acc["tokens_in"]
        b["tokens_out"] += acc["tokens_out"]
        b["saved"] += acc["saved"]
        b["net"] += acc["net"]
        host = r.get("backend_host")
        if isinstance(host, str) and host:
            b["hosts"].add(host)

        quien = r.get("client")
        c = by_client[quien if isinstance(quien, str) and quien else "desconocido"]
        c["calls"] += 1
        c["backend_calls"] += acc["backend_calls"]
        c["saved"] += acc["saved"]
        c["net"] += acc["net"]
        c["tokens_in"] += acc["tokens_in"]
        c["tokens_out"] += acc["tokens_out"]

        total["calls"] += 1
        total["backend_calls"] += acc["backend_calls"]
        total["chars_in"] += ci
        total["chars_out"] += co
        total["tokens_in"] += acc["tokens_in"]
        total["tokens_out"] += acc["tokens_out"]
        total["saved"] += acc["saved"]
        for campo in (
            "returned",
            "net",
            "chars_saved_text",
            "bytes_saved_image",
            "chars_saved_output",
            "chars_returned",
        ):
            total[campo] += acc[campo]
        if acc["estimated"]:
            total["estimated_events"] += 1
        if acc["fallback"]:
            total["fallback_events"] += 1
        if acc["cause"]:
            causes[acc["cause"]] += 1
        if failed:
            total["errors"] += 1
        if is_path:
            total["chars_in_path"] += ci

    tools = [
        {
            "tool": name,
            "calls": t["calls"],
            "backend_calls": t["backend_calls"],
            "chars_in": t["chars_in"],
            "chars_out": t["chars_out"],
            "errors": t["errors"],
            "tokens_saved": t["saved"],
            "tokens_net": t["net"],
            "tokens_in": t["tokens_in"],
            "tokens_out": t["tokens_out"],
            "avg_latency_ms": round(t["latency_ms"] / t["calls"]) if t["calls"] else 0,
        }
        for name, t in sorted(by_tool.items(), key=lambda kv: -kv[1]["saved"])
    ]
    models = [
        {"model": n, **v} for n, v in sorted(by_model.items(), key=lambda kv: -kv[1]["calls"])
    ]
    backends = [
        {
            "backend": name,
            "calls": v["calls"],
            "backend_calls": v["backend_calls"],
            "chars_in": v["chars_in"],
            "chars_out": v["chars_out"],
            "tokens_saved": v["saved"],
            "tokens_net": v["net"],
            "tokens_in": v["tokens_in"],
            "tokens_generated": v["tokens_out"],
            "hosts": sorted(v["hosts"]),
        }
        for name, v in sorted(by_backend.items(), key=lambda kv: -kv[1]["calls"])
    ]
    clientes = [
        {
            "client": name,
            "calls": v["calls"],
            "backend_calls": v["backend_calls"],
            "tokens_saved": v["saved"],
            "tokens_net": v["net"],
            "tokens_in": v["tokens_in"],
            "tokens_generated": v["tokens_out"],
        }
        for name, v in sorted(by_client.items(), key=lambda kv: -kv[1]["calls"])
    ]

    return {
        "total": total,
        # Ahorro BRUTO: contenido leído server-side que no entró al contexto de Claude, contado UNA
        # vez por delegación aunque se troceara, más la salida escrita a fichero. Sin fallos.
        "tokens_context_saved": total["saved"],
        # Lo que las tools devolvieron al contexto, y el NETO (bruto − devuelto) que enseña el KPI.
        "tokens_returned": total["returned"],
        "tokens_context_net": total["net"],
        # Desglose en caracteres (contrato con `coste-api-y-cuota`; la imagen, en bytes).
        "chars_saved_text": total["chars_saved_text"],
        "bytes_saved_image": total["bytes_saved_image"],
        "chars_saved_output": total["chars_saved_output"],
        "chars_returned": total["chars_returned"],
        "tokens_generated_local": total["tokens_out"],
        # Coste: lo que gastó de verdad el backend, con el prompt de sistema repetido por trozo.
        "tokens_local_input": total["tokens_in"],
        "backend_calls": total["backend_calls"],
        "estimated_events": total["estimated_events"],
        "fallback_events": total["fallback_events"],
        "causes": dict(causes),
        "by_tool": tools,
        "by_model": models,
        "by_backend": backends,
        "by_client": clientes,
    }


def _include_tests(value: str | None) -> bool:
    """`include_tests=1` (o `true`) enciende el interruptor «Pruebas»; cualquier otra cosa, no."""
    return str(value or "").strip().lower() in {"1", "true"}


def _split_tests(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """(uso, pruebas) con la ÚNICA regla de «es una prueba» (`atribucion.test_reason`).

    Es el único sitio del panel que separa las pruebas (test-windows-out-of-metrics, REQ-011):
    `/api/events` y `/api/stats` la llaman igual, así que cuentan el mismo conjunto.
    """
    kept: list[dict] = []
    tests: list[dict] = []
    for r in rows:
        (tests if atribucion.test_reason(r) else kept).append(r)
    return kept, tests


def _usage_rows(rows: list[dict], include: bool) -> tuple[list[dict], dict]:
    """Las filas que cuentan como uso y los contadores que lo explican (REQ-011, REQ-012)."""
    kept, tests = _split_tests(rows)
    shown = rows if include else kept
    return shown, {"excluded_tests": 0 if include else len(tests), "tests_in_range": len(tests)}


@app.get("/api/events")
def events(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    include_tests: str | None = Query(None),
):
    range_from, range_to = _resolve_range(from_, to)
    rows, files_read = _load(range_from, range_to)
    rows, cuenta = _usage_rows(rows, _include_tests(include_tests))
    rows.reverse()  # más recientes primero
    return JSONResponse(
        {
            "meta": {
                "chars_per_token": CHARS_PER_TOKEN,
                "log_dir": str(config.LOG_DIR),
                "count": len(rows),
                **cuenta,
                "files_read": files_read,
                "range_from": range_from.isoformat(),
                "range_to": range_to.isoformat(),
            },
            "events": rows[:MAX_EVENTS],
        }
    )


@app.get("/api/stats")
def stats(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    include_tests: str | None = Query(None),
):
    range_from, range_to = _resolve_range(from_, to)
    rows, _files_read = _load(range_from, range_to)
    usage, cuenta = _usage_rows(list(rows), _include_tests(include_tests))
    datos = _aggregate(usage)
    datos.update(cuenta)
    datos["open_test_windows"] = [
        {"id": w.id, "start": test_windows.format_instant(w.start)}
        for w in test_windows.load(config.LOG_DIR).open_windows()
    ]
    # Coste equivalente, imágenes y cuota (coste-api-y-cuota). Solo se lee lo que dejó el comando
    # `recalcular-coste` en el directorio de logs: el panel nunca abre `~/.claude` (REQ-073).
    # El coste ve SIEMPRE todas las filas del rango y aparta las pruebas él mismo con `excluida`:
    # no depende del interruptor (REQ-014). Las imágenes son uso: siguen al interruptor.
    ahora = _ahora()
    agregados = recalcular.leer_agregados(config.LOG_DIR)
    datos["coste"] = valoracion.bloque_coste(rows, agregados, ahora=ahora)
    datos["imagenes"] = valoracion.bloque_imagenes(usage)
    datos["densidad_tabla"] = {
        k: v for k, v in precios.cargar_densidad().items() if not k.startswith("_")
    }
    datos["cuota"] = _bloque_cuota(agregados, ahora)
    return JSONResponse(datos)


def _ahora() -> datetime:
    """El reloj de `/api/stats`, aparte para que un test pueda fijarlo."""
    return datetime.now(UTC)


def _bloque_cuota(agregados: dict | None, ahora: datetime) -> dict:
    """Estado de cada tipo de ventana con la vigencia aplicada AL LEER (REQ-054, `cuota.estado`).

    Un tipo `calibrado` lleva el % sobre SU ventana móvil, que termina ahora y no depende del
    rango que elija el panel (REQ-060): A = cota baja de lo delegado en las últimas 5 h (o 7 días)
    ÷ mediana(C) × 100, y B = la estimación de esos mismos eventos ÷ mediana(C) × 100.
    """
    estado = cuota.estado(agregados, ahora)
    for tipo, e in estado.items():
        if e.get("estado") != "calibrado":
            continue
        filas, _ = _load(ahora - cuota.DURACION[tipo], ahora)
        bloque = valoracion.bloque_coste(filas, agregados, ahora=ahora)
        capacidad = e.get("mediana_C")
        cifra = bloque["cifra"]
        if cifra and capacidad:
            e["a_pct"] = round(cifra["cota_baja"] / capacidad * 100, 1)
            e["b_pct"] = round(cifra["estimacion"] / capacidad * 100, 1)
        else:
            e["a_pct"] = e["b_pct"] = None
            e["motivo_pct"] = bloque["motivo"]
    return {**estado, "hay_agregados": agregados is not None, "comando": valoracion.COMANDO}


def _aggregate_hooks(rows: list[dict]) -> dict:
    """Agrega la telemetría de los hooks. Función pura: todo el criterio se prueba con esto.

    **Qué mide y qué NO mide**, porque confundirlo sería el peor resultado posible aquí: cuenta
    las veces que un hook consultivo **sugirió** delegar, no las veces que se delegó. El hook
    sugiere y el usuario decide; desde este lado no hay forma de saber si la sugerencia se siguió.
    Cruzarlo con el log de uso sería inventar una correlación —dos registros que no comparten
    identificador— y presentarla como un dato.
    """
    total = len(rows)
    sugeridas = 0
    por_evento: dict[str, dict[str, int]] = {}
    por_categoria: dict[str, dict[str, int]] = {}
    por_dia: dict[str, dict[str, int]] = {}
    # Puntería del hook de lectura: de todo lo que vio, en qué avisó y por qué descartó el resto.
    # Esto NO es conversión —nada enlaza una sugerencia con la delegación que vino después— sino
    # selectividad, que vive entera dentro de este mismo fichero y no hay que cruzarla con nada.
    #
    # Sólo entran los eventos de lectura: `motivo` y `ext` los escribe ese hook y nadie más, así
    # que meter los de `lint` o `summarize` daría un denominador que no es y la tarjeta diría
    # que el hook descarta sin motivo la mitad de las veces.
    por_motivo: dict[str, int] = {}
    por_ext: dict[str, int] = {}

    for row in rows:
        # `suggested` puede faltar en eventos viejos; su ausencia se cuenta como «no sugirió», que
        # es lo que significaba antes de que el campo existiera.
        sugerida = bool(row.get("suggested"))
        sugeridas += sugerida

        for clave, destino in (
            (row.get("event") or "?", por_evento),
            (row.get("category") or "sin categoría", por_categoria),
        ):
            casilla = destino.setdefault(str(clave), {"total": 0, "suggested": 0})
            casilla["total"] += 1
            casilla["suggested"] += sugerida

        if row.get("category") == "read":
            # Un evento sin `motivo` es o bien un aviso, o bien uno de antes del PR #146, que no
            # lo escribía. Se separan porque decir «descartado sin motivo» de una telemetría
            # vieja sería inventarle una razón que nunca tuvo.
            if sugerida:
                clave = "avisó"
            else:
                clave = str(row.get("motivo") or "sin registrar")
            por_motivo[clave] = por_motivo.get(clave, 0) + 1

            ext = row.get("ext")
            por_ext[str(ext) if ext else "sin extensión"] = (
                por_ext.get(str(ext) if ext else "sin extensión", 0) + 1
            )

        ts = _parse_ts(row.get("ts"))
        if ts is not None:
            casilla = por_dia.setdefault(ts.date().isoformat(), {"total": 0, "suggested": 0})
            casilla["total"] += 1
            casilla["suggested"] += sugerida

    def _lista(datos: dict[str, dict[str, int]], clave: str) -> list[dict]:
        return [
            {clave: nombre, **valores}
            for nombre, valores in sorted(datos.items(), key=lambda kv: (-kv[1]["total"], kv[0]))
        ]

    return {
        "total": total,
        "suggested": sugeridas,
        # Ratio y no porcentaje: el formato es cosa de quien pinta, no del dato.
        "rate": (sugeridas / total) if total else 0.0,
        "by_event": _lista(por_evento, "event"),
        "by_category": _lista(por_categoria, "category"),
        "by_day": sorted(
            ({"day": dia, **valores} for dia, valores in por_dia.items()),
            key=lambda d: d["day"],
        ),
        # Sólo de los eventos de lectura; su total NO es el `total` de arriba.
        "read_total": sum(por_motivo.values()),
        "by_motivo": [
            {"motivo": nombre, "total": n}
            for nombre, n in sorted(por_motivo.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "by_ext": [
            {"ext": nombre, "total": n}
            for nombre, n in sorted(por_ext.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
    }


@app.get("/api/hooks")
def hooks(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    include_tests: str | None = Query(None),
):
    """Lo que los hooks consultivos han sugerido, en el mismo rango que el resto del panel.

    `enabled` distingue las dos formas de no tener datos: el usuario no activó la telemetría, o la
    activó y todavía no hay eventos. Sin esa distinción, un panel vacío se lee como «los hooks no
    sugieren nada», que es una conclusión falsa sacada de un fichero que no existe.
    """
    ruta = config.HOOK_TELEMETRY_LOG
    if ruta is None:
        return JSONResponse(
            {
                "enabled": False,
                "reason": "LD_HOOK_TELEMETRY_LOG no está definida en el entorno del daemon",
                "excluded_tests": 0,
                **_aggregate_hooks([]),
            }
        )

    range_from, range_to = _resolve_range(from_, to)
    filas = [
        fila
        for fila in _read_file_cached(ruta)
        if (ts := _parse_ts(fila.get("ts"))) is not None and range_from <= ts <= range_to
    ]
    # La telemetría no lleva `client`: de la regla de pruebas solo le aplican las ventanas (REQ-013).
    excluidas = 0
    if not _include_tests(include_tests):
        ventanas = test_windows.load(config.LOG_DIR)
        if ventanas.windows:
            ahora = datetime.now(UTC)
            antes = len(filas)
            filas = [f for f in filas if ventanas.find(f.get("ts"), now=ahora) is None]
            excluidas = antes - len(filas)
    return JSONResponse(
        {
            "enabled": True,
            "log": str(ruta),
            "exists": ruta.is_file(),
            "excluded_tests": excluidas,
            **_aggregate_hooks(filas),
        }
    )


@app.get("/api/inflight")
def inflight():
    """Delegaciones en curso de todas las sesiones + señales de actividad del dashboard.

    `last_event_ts` es el evento más reciente de TODO el histórico y `now` la hora del
    servidor: con esos dos el cliente decide EN CURSO / EN VIVO / EN REPOSO sin depender del
    rango seleccionado ni de la hora (posiblemente desajustada) del navegador.
    """
    snapshot = server.inflight_snapshot()
    ultimo = _last_event()
    return JSONResponse(
        {
            "inflight": snapshot,
            "count": len(snapshot),
            "last_event_ts": (ultimo or {}).get("ts"),
            # Resumen de la última delegación TERMINADA, para que el panel diga algo cuando no
            # hay nada corriendo. Solo los campos que se pintan: el log entero no hace falta.
            "last_event": {
                k: ultimo.get(k)
                for k in ("ts", "tool", "model", "backend", "chars_in", "latency_ms", "ok")
            }
            if ultimo
            else None,
            "now": datetime.now(UTC).isoformat(),
        }
    )


@app.get("/api/backend")
def backend():
    """Estado del backend para el poll rápido (2s) del dashboard: modelos montados y su status.

    Combina dos señales, ambas refrescadas en el mismo ciclo de 2s para que el dashboard marque
    "montado"/loaded sin desfase (antes el status loaded/unloaded solo llegaba vía /api/status,
    que refresca cada 60s):
      - `running`: proxy best-effort de GET {base}/running de llama-swap (estado de montaje).
      - `models`: `[{id, status}]` de /v1/models (#901, loaded/unloaded); [] si el backend no lo da.

    Con un fallo, `causa`/`etiqueta`/`detalle` dicen por qué (REQ-012, textos de `fallos.py`) y
    `models` es la última lista buena de esta URL con `models_stale: true` (REQ-021). `/running`
    solo se pide si `/models` respondió (REQ-013), y `running_ok` dice si respondió (REQ-022).
    """
    estado = server.sondear_backend()
    running, running_ok = _running() if estado.available else ([], False)
    return JSONResponse(
        {
            "available": estado.available,
            "running": running,
            "running_ok": running_ok,
            "models": estado.models,
            "models_stale": estado.models_stale,
            **_causa_json(estado.causa, estado.detalle),
            "origin": config.backend_origin(),
            "host": config.backend_host(),
        }
    )


def _causa_json(causa: str | None, detalle: str | None) -> dict:
    """Las claves de la causa para el panel. La etiqueta corta sale de `fallos.py`, como el detalle:
    el JS no redacta los textos de una causa (REQ-011)."""
    return {
        "causa": causa,
        "etiqueta": fallos.etiqueta(causa) if causa else None,
        "detalle": detalle,
    }


def _running() -> tuple[list, bool]:
    """`GET {base sin /v1}/running` de llama-swap: (entradas, ¿respondió?). Con el plazo de sondeo."""
    base = config.BASE_URL.removesuffix("/v1")
    try:
        with httpx2.Client(timeout=server._plazo_sonda()) as c:
            r = c.get(f"{base}/running", headers=config.auth_headers())
        if not r.is_success:
            return [], False
        data = r.json()
    except (httpx2.HTTPError, ValueError):
        return [], False
    lista = data.get("running") if isinstance(data, dict) else None
    if lista is None:
        lista = []  # «ningún modelo montado»: llama-swap manda `null` o nada
    if not isinstance(data, dict) or not isinstance(lista, list):
        return [], False
    return lista, True


@app.get("/api/backend/stats")
def backend_stats():
    """Proxy best-effort de GET {base sin /v1}/api/metrics/stats de llama-swap (#898, timeout 1s).

    Métricas de actividad agregadas (histogramas/percentiles/tokens-por-segundo) que llama-swap
    persiste en SQLite. Requiere llama-swap >= v236; para que sobrevivan a reinicios necesita
    `store.path` en su config.yaml. Con otro backend o versión vieja responde 404/error y aquí
    degrada a {available: false} sin romper el dashboard.

    Sin datos, dice por qué (REQ-020): `causa`, `etiqueta`, `detalle` y `status_http` (este último
    solo con una respuesta HTTP). El panel solo culpa a la versión de llama-swap con un 404.
    """
    base = config.BASE_URL.removesuffix("/v1")
    endpoint = f"{base}/api/metrics/stats"
    loopback = server._backend_en_loopback()
    try:
        with httpx2.Client(timeout=server._plazo_sonda()) as c:
            r = c.get(endpoint, headers=config.auth_headers())
        if not r.is_success:
            causa = fallos.causa_conexion(r.status_code, loopback=loopback)
            texto = fallos.detalle(causa, host=config.backend_host(), status=r.status_code)
            return JSONResponse(_sin_stats(causa.value, texto, r.status_code))
        data = r.json()
    except Exception as exc:  # como el sondeo: lo que no se espera también tiene causa
        causa = fallos.causa_conexion(exc, loopback=loopback)
        texto = fallos.detalle(causa, host=config.backend_host(), endpoint=endpoint, excepcion=exc)
        return JSONResponse(_sin_stats(causa.value, texto, None))
    return JSONResponse({"available": True, "stats": data})


def _sin_stats(causa: str, detalle: str, status_http: int | None) -> dict:
    return {"available": False, **_causa_json(causa, detalle), "status_http": status_http}


@app.get("/api/status")
def status():
    """Identidad y disponibilidad: versión del MCP, modelos reales del backend, catálogo, tools.

    Los modelos salen de GET {BASE_URL}/models (lo que el backend de verdad expone), no del
    log de eventos — así el dashboard enseña también los modelos aún sin uso registrado.
    """
    # Modelos reales del backend con su estado loaded/unloaded (#901): el mismo sondeo que
    # /api/backend, con su causa (REQ-012) y la lista guardada cuando falla (REQ-021).
    estado = server.sondear_backend()
    catalog = [
        {"role": "mechanical", "label": "mecánico", "model": config.MODEL_MECHANICAL},
        {"role": "long", "label": "largo", "model": config.MODEL_LONG},
        {"role": "code", "label": "código", "model": config.MODEL_CODE},
        {"role": "vision", "label": "visión", "model": config.MODEL_VISION},
    ]
    tools: list[dict] = []
    try:
        tools = [
            {"name": t.name, "summary": (t.description or "").strip().splitlines()[0][:160]}
            for t in server.mcp._tool_manager.list_tools()
        ]
    except Exception:
        pass  # la lista de tools es informativa; nunca rompe el endpoint
    return JSONResponse(
        {
            "version": server._get_version(),
            "base_url": config.BASE_URL,
            "backend": {
                "available": estado.available,
                "models": estado.models,
                "models_stale": estado.models_stale,
                **_causa_json(estado.causa, estado.detalle),
                # dónde corre la inferencia de ESTE proceso MCP: loopback = local, si no remoto
                "origin": config.backend_origin(),
                "host": config.backend_host(),
            },
            "catalog": catalog,
            "tools": tools,
            # Clientes MCP observados en ESTA ejecución del daemon (el histórico está en
            # clients.jsonl). Se reinicia con el proceso a propósito: aquí interesa con quién se
            # está hablando ahora, no con quién se habló en marzo.
            "clients": clients.snapshot(),
            "log_dir": str(config.LOG_DIR),
        }
    )


@app.get("/api/system")
def system():
    """RAM/VRAM de sistema y consumo por proceso del backend local (best-effort).

    `platform`, `origin` y `host` (REQ-025) le dicen al panel por qué puede no haber procesos:
    el cómputo corre en otra máquina, o esta plataforma no los lista todavía.
    """
    return JSONResponse(
        {
            "ram": sysinfo.ram_stats(),
            "vram": sysinfo.vram_stats(),
            "processes": sysinfo.interesting_processes(),
            "platform": sys.platform,
            "origin": config.backend_origin(),
            "host": config.backend_host(),
            "panel_url": config.remote_panel_url(),
        }
    )


# --- llama-swap para el CLI de residencia (T13: REQ-034, REQ-039) ---------------------------
#
# El CLI no tiene la key de llama-swap (vive en el lanzador del daemon), así que pregunta aquí.
# Tras el token web dos veces: la puerta del puerto (`auth.proteger`, en `daemon.build_app`) y una
# dependencia propia de cada ruta, porque esta app también se sirve sola (`run_in_thread`, el
# modo manual) y ahí no hay puerta. Sin token configurado, como el resto del panel: abiertas.


def _require_web_token(request: Request) -> None:
    token = config.WEB_TOKEN
    if not token:
        return
    if auth.peticion_autorizada(request.headers.get("authorization"), token):
        return
    if auth.sesion_valida(request.cookies.get(auth.COOKIE), token) is not None:
        return
    raise HTTPException(status_code=401, detail="falta el token del puerto o no es correcto")


_WITH_WEB_TOKEN = [Depends(_require_web_token)]


@app.get("/api/llamaswap/status", dependencies=_WITH_WEB_TOKEN)
def llamaswap_status():
    """Estado de llama-swap para la comprobación previa: modelos con su estado y TTL, peticiones
    en vuelo por modelo (de cualquier cliente), delegaciones propias vivas y la config que usa
    el daemon, y si tiene turno (para `doctor`, REQ-036). Nunca devuelve `cmd`, cabeceras ni
    claves. El campo de la ruta es `residency.CONFIG_PATH_FIELD` (lo pone `Status.to_json`)."""
    status = llamaswap_api.query_status(
        llamaswap_api.local_backend(), own_delegations=len(server.inflight_snapshot())
    )
    status.config_path = config.llamaswap_config_path() or None
    status.watch_config = config.llamaswap_watch_config()
    status.autostart = config.AUTOSTART
    photo = server._topology()
    status.turn_active = not isinstance(photo, topology.NoTopology)
    if isinstance(photo, topology.NoTopology):
        status.turn_reason, status.turn_detail = photo.reason, photo.detail or ""
    else:
        status.turn_detail = server._clashes_by_groups(photo)
    return JSONResponse(status.to_json())


@app.post("/api/llamaswap/watch", dependencies=_WITH_WEB_TOKEN)
def llamaswap_watch_open():
    """Abre una vigía de recarga con la key del daemon. Responde con su id cuando ya se tragó la
    carga inicial de `/api/events`: lo que se escriba después, la vigía lo ve."""
    try:
        wid = llamaswap_api.watches.open(llamaswap_api.local_backend())
    except (llamaswap_api.QueryError, httpx2.HTTPError) as e:
        return JSONResponse({"error": str(e) or type(e).__name__}, status_code=502)
    return JSONResponse({"id": wid})


@app.get("/api/llamaswap/watch/{wid}", dependencies=_WITH_WEB_TOKEN)
def llamaswap_watch_result(wid: str):
    """La salida de la vigía (`outcome`, `null` mientras no se sabe) y la línea que la decidió."""
    result = llamaswap_api.watches.result(wid)
    if result is None:
        return JSONResponse({"error": "no hay ninguna vigía con ese id"}, status_code=404)
    return JSONResponse(result)


# Icono de marca: un corchete de terminal abrazando el chevrón de delegación — «lo que entra
# aquí, se queda aquí». El corchete de cierre va a menos opacidad para que el chevrón sea lo
# primero que se lee; a 16px la silueta son dos formas con aire entre ellas, que es lo que
# aguanta el tamaño mínimo.
#
# NO se escribe aquí: vive en `resources/brand/favicon.svg`, y la landing (`site/favicon.svg`)
# sirve **el mismo fichero**. Tenerlo dos veces es exactamente la clase de verdad duplicada que
# este repo ya ha pagado varias veces; hay un test que compara las dos copias byte a byte.
def _load_favicon() -> str:
    try:
        return (
            Path(str(_resource_files("local_delegate"))) / "resources" / "brand" / "favicon.svg"
        ).read_text(encoding="utf-8")
    except OSError:
        # Un icono ausente no puede tumbar el dashboard: se sirve un SVG vacío y ya.
        return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"></svg>'


FAVICON = _load_favicon()


@app.get("/favicon.svg")
def favicon():
    return Response(FAVICON, media_type="image/svg+xml")


# Chart.js se sirve DESDE EL PAQUETE, no desde un CDN: el dashboard de una herramienta
# local-first tiene que funcionar en una máquina sin salida a internet (y sin anunciar a un
# tercero cada vez que abres tu panel de uso). Copia exacta de la distribución npm (MIT,
# licencia junto al archivo). Se cachea en memoria tras la 1ª lectura.
#
# La versión NO se anota aquí a propósito: la declara `resources/vendor/vendor.json`, que es su
# fuente de verdad y lo que comprueba `scripts/check_vendor.py`. Dos sitios con el número se
# contradicen tarde o temprano, y el que se queda viejo es siempre el comentario.
_CHART_JS: str | None = None


@app.get("/vendor/chart.umd.min.js")
def vendor_chart_js():
    global _CHART_JS
    if _CHART_JS is None:
        try:
            _CHART_JS = (
                Path(str(_resource_files("local_delegate")))
                / "resources"
                / "vendor"
                / "chart.umd.min.js"
            ).read_text(encoding="utf-8")
        except OSError:
            _CHART_JS = ""  # sin gráficos, pero el resto del panel sigue funcionando
    return Response(
        _CHART_JS,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# La tipografía de marca (Inter / JetBrains Mono) es el ÚNICO recurso externo que queda, y es
# puramente cosmético: sin red, el stack de fallback del CSS (system-ui / ui-monospace) hace su
# trabajo. Quien no quiera ni esa petición pone LOCAL_DELEGATE_WEB_FONTS=0 y la página queda con
# cero peticiones a terceros.
_WEB_FONTS_TAGS = """<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">"""


def render_index() -> str:
    tags = _WEB_FONTS_TAGS if config.WEB_FONTS else "<!-- fuentes web desactivadas -->"
    # La marca del header se **inyecta** desde el mismo fichero que sirve `/favicon.svg` en vez
    # de estar escrita en el HTML. Antes había un SVG dibujado a mano ahí: al unificar la marca
    # se actualizó el favicon y el header se quedó con el icono viejo, así que el panel enseñaba
    # una marca y su propia pestaña otra. Inyectándolo no pueden volver a separarse.
    return HTML.replace("__WEB_FONTS__", tags).replace("__BRAND_MARK__", FAVICON.strip())


@app.get("/", response_class=HTMLResponse)
def index():
    return render_index()


def run_in_thread(host: str | None = None, port: int | None = None):
    """Arranca uvicorn en un hilo daemon (muere con el proceso del MCP).

    Devuelve el Thread, o None si el puerto ya está ocupado (otra instancia ya sirve la web).
    No instala signal handlers (solo válidos en el hilo principal) y nunca propaga excepciones.
    """
    import threading

    host = host or config.WEB_HOST
    port = port or config.WEB_PORT
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((host, port)) == 0:
                return None  # ya hay algo escuchando: no montamos una segunda web
        cfg = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
        server = uvicorn.Server(cfg)
        server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
        t = threading.Thread(target=server.run, daemon=True, name="metrics-web")
        t.start()
        return t
    except Exception:
        return None


HTML = r"""<!doctype html>
<html lang="es" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>local·delegate — panel de ahorro</title>
<meta name="description" content="Delegaciones a modelos locales de local-delegate: contexto conservado, equivalente a precio de API y estado de la cuota.">
<meta name="theme-color" content="#0a0c11">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
__WEB_FONTS__
<!-- Chart.js servido desde el propio paquete: el panel funciona sin conexión y no
     avisa a ningún tercero de que estás mirando tus métricas. -->
<script src="/vendor/chart.umd.min.js"></script>
<style>
:root{
  --bg:#0a0c11; --bg2:#0d1017; --panel:#12161f; --panel2:#0e121a; --bd:#212734; --bd2:#2c3444;
  --tx:#e8edf4; --tx2:#c3ccd9; --mut:#8b95a7; --faint:#5b6577;
  --acc:#34d399; --acc2:#6ee7b7; --acc-d:#059669;
  --blue:#60a5fa; --violet:#a78bfa; --amber:#fbbf24; --danger:#f87171; --cyan:#22d3ee; --pink:#f472b6;
  --glow:rgba(52,211,153,.14);
  --shadow:0 1px 2px rgba(0,0,0,.5),0 12px 32px -8px rgba(0,0,0,.55);
  --shadow-h:0 1px 2px rgba(0,0,0,.5),0 20px 44px -10px rgba(0,0,0,.6);
  --sans:'Inter',system-ui,'Segoe UI',Roboto,sans-serif;
  --mono:'JetBrains Mono',ui-monospace,'Cascadia Code',Consolas,monospace;
  /* Los controles nativos (icono del calendario de <input type=date>, lista del <select>, barras
     de scroll) siguen al tema: sin esto el icono del calendario salía negro sobre el panel oscuro. */
  color-scheme:dark;
}
[data-theme=light]{
  color-scheme:light;
  --bg:#f6f8fc; --bg2:#eef2f8; --panel:#ffffff; --panel2:#f4f7fb; --bd:#e4e9f1; --bd2:#d4dbe6;
  --tx:#0e1526; --tx2:#33405a; --mut:#64748b; --faint:#94a3b8;
  --glow:rgba(5,150,105,.10);
  --shadow:0 1px 2px rgba(15,23,42,.06),0 12px 28px -10px rgba(15,23,42,.14);
  --shadow-h:0 1px 2px rgba(15,23,42,.08),0 20px 40px -12px rgba(15,23,42,.2);
}
*{box-sizing:border-box}
/* Los controles no heredan la familia por defecto: sin esto, un botón sin clase sale en Arial. */
button,input,select,textarea{font-family:inherit}
html{scrollbar-color:var(--bd2) transparent}
body{margin:0;color:var(--tx);font-family:var(--sans);font-size:14px;line-height:1.5;
  background:var(--bg);
  background-image:
    radial-gradient(900px 460px at 82% -8%, var(--glow), transparent 62%),
    radial-gradient(700px 400px at 8% -6%, rgba(96,165,250,.06), transparent 60%);
  background-attachment:fixed;-webkit-font-smoothing:antialiased}
a{color:var(--blue);text-decoration:none}
::-webkit-scrollbar{width:11px;height:11px}
::-webkit-scrollbar-thumb{background:var(--bd2);border-radius:8px;border:3px solid transparent;background-clip:content-box}
::-webkit-scrollbar-thumb:hover{background:var(--mut);background-clip:content-box}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1}
.wrap{max-width:1280px;margin:0 auto;padding:0 22px 40px}

/* ---------- top bar / marca ---------- */
.topbar{position:sticky;top:0;z-index:40;margin:0 -22px 24px;padding:16px 22px;
  display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;
  background:color-mix(in srgb,var(--bg) 78%,transparent);backdrop-filter:blur(14px) saturate(1.3);
  -webkit-backdrop-filter:blur(14px) saturate(1.3);border-bottom:1px solid var(--bd)}
.brand{display:flex;align-items:center;gap:13px}
.mark{width:40px;height:40px;flex:0 0 auto;display:grid;place-items:center;border-radius:12px;
  background:linear-gradient(150deg,color-mix(in srgb,var(--acc) 22%,var(--panel)),var(--panel2));
  border:1px solid color-mix(in srgb,var(--acc) 34%,var(--bd));
  box-shadow:0 0 0 1px rgba(0,0,0,.25) inset,0 8px 20px -8px var(--acc-d)}
.mark svg{width:26px;height:26px;display:block}
.brand-txt{display:flex;flex-direction:column;line-height:1.05}
.brand-name{font-size:19px;font-weight:800;letter-spacing:-.02em}
.brand-name b{color:var(--acc);font-weight:800}
.brand-sub{font-size:11px;font-weight:600;color:var(--mut);letter-spacing:.14em;text-transform:uppercase;margin-top:3px}
.live{margin-left:6px;display:inline-flex;align-items:center;gap:6px;font-size:10.5px;font-weight:700;
  letter-spacing:.1em;color:var(--acc);background:color-mix(in srgb,var(--acc) 12%,transparent);
  border:1px solid color-mix(in srgb,var(--acc) 32%,transparent);border-radius:999px;padding:4px 9px;
  align-self:center;transition:.25s}
.live.stale{color:var(--mut);background:color-mix(in srgb,var(--mut) 12%,transparent);border-color:color-mix(in srgb,var(--mut) 30%,transparent)}
.live.busy{color:var(--amber);background:color-mix(in srgb,var(--amber) 12%,transparent);border-color:color-mix(in srgb,var(--amber) 34%,transparent)}
.live-dot{width:7px;height:7px;border-radius:50%;background:var(--acc);box-shadow:0 0 0 0 var(--acc);animation:pulse 2s infinite}
.live.stale .live-dot{background:var(--mut);animation:none}
.live.busy .live-dot{background:var(--amber);animation:pulse 1.1s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--acc) 70%,transparent)}
  70%{box-shadow:0 0 0 6px transparent}100%{box-shadow:0 0 0 0 transparent}}
.controls{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.btn{background:var(--panel);border:1px solid var(--bd);color:var(--tx2);border-radius:10px;
  padding:8px 12px;font-size:13px;cursor:pointer;font-weight:600;font-family:var(--sans);
  display:inline-flex;align-items:center;gap:6px;transition:.14s}
/* `background-color`, no el atajo `background`: el atajo borraba el `background-image` de la flecha
   del <select> al pasar el ratón. */
.btn:hover{border-color:var(--bd2);color:var(--tx);background-color:var(--panel2)}
.btn.on{border-color:color-mix(in srgb,var(--acc) 55%,transparent);color:var(--acc);
  background:color-mix(in srgb,var(--acc) 10%,transparent)}
.btn.icon{padding:8px 9px}
.btn svg{width:16px;height:16px;display:block;flex:0 0 auto}
/* Punto de aviso del botón «Pruebas»: hay una ventana de prueba abierta. Sin texto: la orden
   para cerrarla está en su ⓘ. */
.tdot{width:7px;height:7px;border-radius:50%;background:var(--amber);flex:0 0 auto;
  box-shadow:0 0 0 2px color-mix(in srgb,var(--amber) 28%,transparent)}
.ver{font-family:var(--mono);font-size:10px;font-weight:700;color:var(--acc);
  background:color-mix(in srgb,var(--acc) 10%,transparent);
  border:1px solid color-mix(in srgb,var(--acc) 30%,transparent);
  border-radius:6px;padding:2px 6px;margin-left:8px;vertical-align:2px;letter-spacing:.02em}
select.btn{appearance:none;padding-right:28px;
  background-image:linear-gradient(45deg,transparent 50%,var(--mut) 50%),linear-gradient(135deg,var(--mut) 50%,transparent 50%);
  background-position:calc(100% - 16px) 55%,calc(100% - 11px) 55%;background-size:5px 5px;background-repeat:no-repeat}
input[type=date].btn{font-family:var(--mono);font-weight:600;font-variant-numeric:tabular-nums}
input[type=date]::-webkit-calendar-picker-indicator{cursor:pointer;opacity:.65;transition:opacity .13s}
input[type=date]::-webkit-calendar-picker-indicator:hover{opacity:1}
.btn:focus-visible,.ibtn:focus-visible,.help-x:focus-visible,.pbtn:focus-visible{
  outline:2px solid color-mix(in srgb,var(--acc) 70%,transparent);outline-offset:2px}

/* ---------- grid + cards ---------- */
.grid{display:grid;gap:16px}
/* 6 tarjetas: el hero + ahorro/coste/generado/latencia/error. Los breakpoints de abajo las
   reparten en 3+3 y 2+2+2, así que ninguna se queda sola en una fila con el hueco al lado. */
.kpis{grid-template-columns:1.7fr repeat(5,1fr)}
@media(max-width:1320px){.kpis{grid-template-columns:1.7fr 1fr 1fr}}
@media(max-width:1040px){.kpis{grid-template-columns:1fr 1fr 1fr}}
@media(max-width:720px){.kpis{grid-template-columns:1fr 1fr}}
@media(max-width:460px){.kpis{grid-template-columns:1fr}}
.card{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--bd);
  border-radius:16px;padding:17px 18px;box-shadow:var(--shadow);transition:transform .16s,border-color .16s,box-shadow .16s}
.card:hover{border-color:var(--bd2)}
.chartcard:hover{transform:translateY(-2px);box-shadow:var(--shadow-h)}
.hero{position:relative;overflow:hidden;grid-row:span 1;container-type:inline-size;
  background:
    radial-gradient(120% 140% at 100% 0,color-mix(in srgb,var(--acc) 20%,transparent),transparent 55%),
    linear-gradient(180deg,var(--panel),var(--panel2));
  border-color:color-mix(in srgb,var(--acc) 30%,var(--bd))}
.hero::after{content:"";position:absolute;inset:0;pointer-events:none;
  background:radial-gradient(80% 60% at 90% 10%,color-mix(in srgb,var(--acc) 10%,transparent),transparent 60%)}
/* La línea del hero ocupa solo la franja de abajo, debajo de la pista: con 52 px cruzaba el
   texto «bruto … − devuelto …». La pista reserva dos líneas y el hero usa una. */
.hero .spark{position:absolute;inset:auto 0 0 0;height:24px;opacity:.7;pointer-events:none}
/* Fila de KPIs simétrica: el bloque del título mide lo mismo en todas (hasta dos líneas, con el ⓘ
   pegado a la última palabra), la cifra empieza a la misma altura y apoya en el fondo de una caja
   de alto fijo, y la pista reserva dos líneas. Así las cifras quedan en la misma línea. */
.k-top{display:flex;align-items:center;gap:6px}
/* El título va en UNA línea pase lo que pase con la fuente: si la de reserva es más ancha
   (sin Google Fonts, en otro sistema), se recorta con «…» y el título entero queda en `title`;
   el ⓘ no se recorta nunca. Con dos líneas posibles, la simetría dependía de la fuente. */
/* El título SÍ aporta su ancho a la rejilla (sin `width:0`): con una fuente ancha la columna crece
   en vez de recortar, y el hero, que escala su cifra, cede el sitio. El «…» queda de red. */
#kpis .k-top{height:26px}
#kpis .k-lbl{display:flex;align-items:center;gap:5px;min-width:0;flex:1 1 auto}
#kpis .k-lbl-t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
#kpis .k-lbl .info{flex:0 0 auto}
.k-ico{width:26px;height:26px;flex:0 0 auto;display:grid;place-items:center;border-radius:8px;
  background:color-mix(in srgb,var(--kc,var(--mut)) 15%,transparent);color:var(--kc,var(--mut))}
.k-ico svg{width:15px;height:15px}
.k-lbl{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.055em;font-weight:700}
.k-val{font-size:31px;font-weight:700;letter-spacing:-.02em;margin-top:12px;line-height:1;color:var(--tx)}
/* El hero escala la cifra con el ancho de SU tarjeta (unidades de contenedor): entre 1320 y 1440 px
   la tarjeta mide ~260 px y «3.161.168 tok» a 42 px no cabía, el `overflow:hidden` cortaba la unidad. */
.hero .k-val{font-size:clamp(26px,12cqi,42px);color:var(--acc);position:relative;z-index:1;
  text-shadow:0 2px 20px color-mix(in srgb,var(--acc) 40%,transparent)}
#kpis .k-val{height:44px;display:flex;align-items:flex-end;white-space:nowrap}
#kpis .k-num{display:inline-block;line-height:1}
.k-val .unit{font-size:15px;font-weight:600;color:var(--mut);margin-left:5px;letter-spacing:0}
.hero .k-val .unit{color:color-mix(in srgb,var(--acc) 75%,var(--mut))}
.k-hint{color:var(--mut);font-size:11.5px;line-height:1.45;margin-top:9px;position:relative;z-index:1}
#kpis .k-hint{min-height:calc(2 * 1.45em);display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}
/* En el hero la pista va en una sola línea (con «…» si no cabe): la segunda línea reservada es el
   sitio de su gráfico, y una pista partida (tarjeta estrecha, fuente ancha) caía encima. */
#kpis .hero .k-hint{display:block;white-space:nowrap;text-overflow:ellipsis}
.k-hint .num{color:var(--tx2)}
.info{width:14px;height:14px;color:var(--faint);cursor:help;flex:0 0 auto;display:inline-flex;transition:.13s}
.info svg{width:100%;height:100%;display:block}
.info:hover{color:var(--tx2)}

.cols{grid-template-columns:1.5fr 1fr;margin-top:16px}
.cols2{grid-template-columns:1fr 1fr;margin-top:16px}
.cols3{grid-template-columns:1fr 1fr 1fr;margin-top:16px}
@media(max-width:1040px){.cols3{grid-template-columns:1fr 1fr}}
@media(max-width:880px){.cols,.cols2,.cols3{grid-template-columns:1fr}}
.panel-h{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:0 0 14px}
.panel-h h2{font-size:13px;font-weight:700;margin:0;letter-spacing:.01em;display:flex;align-items:center;gap:8px}
.panel-h h2::before{content:"";width:3px;height:14px;border-radius:2px;background:var(--hc,var(--acc));opacity:.9}
.panel-h .mut{color:var(--mut);font-size:11.5px;font-weight:600;font-family:var(--mono)}
canvas{max-width:100%}
.cbox{position:relative;height:256px;width:100%}
.cbox.donut{height:224px}

/* ---------- tabla ---------- */
.tablecard{margin-top:16px;padding-bottom:8px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:9px 11px;border-bottom:1px solid var(--bd);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
thead th{color:var(--faint);font-weight:700;font-size:10.5px;text-transform:uppercase;letter-spacing:.05em}
tbody tr{transition:background .12s}
tbody tr:hover{background:color-mix(in srgb,var(--blue) 7%,transparent)}
tbody td{color:var(--tx2)}
/* Solo celdas: las cabeceras son etiquetas y van todas en Inter (`thead th`), también las de
   columnas numéricas. Un `th.num`/`th.mono` partía la misma fila de cabecera en dos familias. */
td.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.badge{display:inline-block;padding:3px 9px;border-radius:7px;font-size:11.5px;font-weight:600;font-family:var(--mono);
  background:color-mix(in srgb,var(--blue) 14%,transparent);color:var(--blue)}
.badge.model{background:color-mix(in srgb,var(--violet) 14%,transparent);color:var(--violet)}
.src{font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:6px;letter-spacing:.03em;text-transform:uppercase}
.src.path{background:color-mix(in srgb,var(--acc) 16%,transparent);color:var(--acc)}
.src.inline{background:color-mix(in srgb,var(--mut) 16%,transparent);color:var(--mut)}
/* origen del CÓMPUTO (backend local de esta máquina vs GPU remota) */
.org{font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:6px;letter-spacing:.03em;text-transform:uppercase}
.org.local{background:color-mix(in srgb,var(--acc) 16%,transparent);color:var(--acc)}
.org.remote{background:color-mix(in srgb,var(--cyan) 16%,transparent);color:var(--cyan)}
.org.unknown{background:color-mix(in srgb,var(--mut) 14%,transparent);color:var(--mut)}
.pill.org.local{color:var(--acc);background:color-mix(in srgb,var(--acc) 12%,transparent);border:1px solid color-mix(in srgb,var(--acc) 32%,transparent)}
.pill.org.remote{color:var(--cyan);background:color-mix(in srgb,var(--cyan) 12%,transparent);border:1px solid color-mix(in srgb,var(--cyan) 32%,transparent)}
.chunkchip{font-family:var(--mono);font-size:10px;font-weight:700;padding:1.5px 6px;border-radius:5px;margin-left:6px;
  background:color-mix(in srgb,var(--violet) 14%,transparent);color:var(--violet)}
.fbchip{background:color-mix(in srgb,var(--amber,#d97706) 16%,transparent);color:var(--amber,#d97706)}
.slowchip{background:color-mix(in srgb,var(--red,#dc2626) 14%,transparent);color:var(--red,#dc2626)}
.flow{color:var(--faint)}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%}
.dot.ok{background:var(--acc);box-shadow:0 0 8px color-mix(in srgb,var(--acc) 60%,transparent)}
.dot.err{background:var(--danger);box-shadow:0 0 8px color-mix(in srgb,var(--danger) 60%,transparent)}

/* ---------- backend local + sistema ---------- */
.duo{grid-template-columns:1.15fr 1fr;margin-bottom:16px}
@media(max-width:880px){.duo{grid-template-columns:1fr}}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:10.5px;font-weight:700;letter-spacing:.06em;
  border-radius:999px;padding:3px 10px;text-transform:uppercase}
.pill.up{color:var(--acc);background:color-mix(in srgb,var(--acc) 12%,transparent);border:1px solid color-mix(in srgb,var(--acc) 32%,transparent)}
.pill.down{color:var(--danger);background:color-mix(in srgb,var(--danger) 12%,transparent);border:1px solid color-mix(in srgb,var(--danger) 32%,transparent)}
.pill.warn{color:var(--amber);background:color-mix(in srgb,var(--amber) 12%,transparent);border:1px solid color-mix(in srgb,var(--amber) 32%,transparent)}
.pill.neutral{color:var(--mut);background:color-mix(in srgb,var(--mut) 10%,transparent);border:1px solid color-mix(in srgb,var(--mut) 28%,transparent)}
.mrow.atenuada{opacity:.5}
.mrow{display:flex;align-items:center;gap:10px;padding:8px 2px;border-bottom:1px dashed color-mix(in srgb,var(--bd) 75%,transparent);border-radius:8px;transition:background .2s}
.mrow:last-child{border-bottom:0}
.mrow.busy{background:color-mix(in srgb,var(--amber) 9%,transparent);padding-left:6px;padding-right:6px}
.mdot{width:8px;height:8px;border-radius:50%;background:var(--faint);opacity:.55;flex:0 0 auto;transition:.2s}
.mdot.ready{background:var(--acc);opacity:1;box-shadow:0 0 8px color-mix(in srgb,var(--acc) 60%,transparent)}
.mdot.starting{background:var(--amber);opacity:1;box-shadow:0 0 8px color-mix(in srgb,var(--amber) 60%,transparent)}
.mdot.busy{background:var(--amber);opacity:1;box-shadow:0 0 8px color-mix(in srgb,var(--amber) 60%,transparent);animation:pulse 1.4s infinite}
.mstatus{font-size:9.5px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;padding:2px 7px;border-radius:6px;margin-left:10px;min-width:74px;text-align:center}
.mstatus.loaded{background:color-mix(in srgb,var(--acc) 16%,transparent);color:var(--acc)}
.mstatus.unloaded{background:color-mix(in srgb,var(--mut) 14%,transparent);color:var(--mut)}
.mstatus.neutral{background:transparent;color:var(--mut);border:1px solid color-mix(in srgb,var(--mut) 28%,transparent)}
/* #898: métricas persistidas del backend (llama-swap) */
.bstats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:4px 0 2px}
.bstat{background:color-mix(in srgb,var(--violet) 7%,transparent);border-radius:10px;padding:9px 10px}
.bstat .bk{font-size:10px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--mut)}
.bstat .bv{font-family:var(--mono);font-size:16px;font-weight:700;color:var(--tx);margin-top:2px}
.bstat .bv .bp{font-size:9.5px;font-weight:600;color:var(--faint);margin-left:4px}
.bstat .bsub{font-size:10.5px;color:var(--tx2);margin-top:1px;font-family:var(--mono)}
.mname{font-family:var(--mono);font-size:12.5px;font-weight:600;color:var(--tx)}
.mrole{font-size:9.5px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;padding:2px 7px;border-radius:6px;
  background:color-mix(in srgb,var(--violet) 13%,transparent);color:var(--violet)}
.mstate{margin-left:auto;min-width:58px;text-align:right;font-size:11px;color:var(--mut);font-family:var(--mono)}
.mrow.busy .mstate{color:var(--amber);font-weight:600}
.subh{font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);margin:14px 0 6px}
.toolchips{display:flex;flex-wrap:wrap;gap:6px}
.tchip{font-family:var(--mono);font-size:10.5px;color:var(--mut);border:1px solid var(--bd);border-radius:7px;padding:3px 8px;cursor:default;transition:.13s}
.tchip:hover{color:var(--acc);border-color:color-mix(in srgb,var(--acc) 40%,transparent)}
.tchip.busy{color:var(--amber);border-color:color-mix(in srgb,var(--amber) 50%,transparent);background:color-mix(in srgb,var(--amber) 12%,transparent)}
.ifrow{display:flex;align-items:center;gap:9px;padding:6px 2px;font-size:12.5px;color:var(--tx2);font-family:var(--mono)}
.spin{width:12px;height:12px;border-radius:50%;flex:0 0 auto;
  border:2px solid color-mix(in srgb,var(--amber) 28%,transparent);border-top-color:var(--amber);animation:rot .8s linear infinite}
@keyframes rot{to{transform:rotate(360deg)}}
.meter-lbl{display:flex;justify-content:space-between;align-items:baseline;gap:10px;
  font-size:10.5px;color:var(--faint);font-weight:700;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
.meter-val{font-family:var(--mono);text-transform:none;letter-spacing:0;color:var(--tx2);font-weight:600;font-size:12px}
.meter-val b{color:var(--tx);font-weight:700}
.meter{height:8px;border-radius:6px;background:color-mix(in srgb,var(--bd) 75%,transparent);overflow:hidden;margin-bottom:15px}
.meter i{display:block;height:100%;border-radius:6px;width:0;transition:width .6s cubic-bezier(.2,.8,.2,1);
  background:linear-gradient(90deg,color-mix(in srgb,var(--mc,var(--acc)) 45%,transparent),var(--mc,var(--acc)))}
/* Misma tipografía que las demás tablas del panel (13 px las celdas, 10,5 px las cabeceras). */
.proc{width:100%;border-collapse:collapse;font-size:13px}
.proc th,.proc td{padding:6px 8px;border-bottom:1px solid color-mix(in srgb,var(--bd) 75%,transparent);text-align:right;white-space:nowrap}
.proc th:first-child,.proc td:first-child{text-align:left}
.proc thead th{color:var(--faint);font-weight:700;font-size:10.5px;text-transform:uppercase;letter-spacing:.05em}
.proc tbody tr:last-child td{border-bottom:0}
.proc td{color:var(--tx2)}
.selfchip{font-family:var(--sans);font-size:9.5px;font-weight:700;padding:1.5px 6px;border-radius:5px;margin-left:6px;letter-spacing:.04em;
  background:color-mix(in srgb,var(--acc) 14%,transparent);color:var(--acc)}

/* ---------- paginación ---------- */
.pager{display:flex;align-items:center;justify-content:flex-end;gap:6px;padding:11px 4px 3px;color:var(--mut);font-size:12px}
.pbtn{width:28px;height:28px;display:grid;place-items:center;border-radius:8px;border:1px solid var(--bd);
  background:var(--panel);color:var(--tx2);cursor:pointer;transition:.13s;font-family:var(--sans)}
.pbtn svg{width:14px;height:14px}
.pbtn:hover:not(:disabled){border-color:color-mix(in srgb,var(--acc) 45%,transparent);color:var(--acc)}
.pbtn:disabled{opacity:.35;cursor:default}
.pinfo{font-family:var(--mono);padding:0 6px}
.pinfo b{color:var(--tx)}

/* ---------- dialog de ayuda ---------- */
dialog.help{background:linear-gradient(180deg,var(--panel),var(--panel2));color:var(--tx2);
  border:1px solid var(--bd2);border-radius:18px;padding:0;max-width:580px;width:calc(100vw - 48px);
  box-shadow:var(--shadow-h)}
dialog.help::backdrop{background:rgba(3,5,9,.6);backdrop-filter:blur(5px)}
.help-in{padding:22px 26px 22px}
.help-h{display:flex;align-items:center;gap:11px}
.help-h .k-ico{width:32px;height:32px;border-radius:10px}
.help-h .k-ico svg{width:17px;height:17px}
.help-h h3{margin:0;font-size:15.5px;color:var(--tx);font-weight:800;letter-spacing:-.01em}
.help-x{margin-left:auto;width:30px;height:30px;display:grid;place-items:center;border-radius:9px;cursor:pointer;
  border:1px solid var(--bd);background:transparent;color:var(--mut);transition:.13s}
.help-x:hover{color:var(--tx);border-color:var(--bd2)}
.help-x svg{width:14px;height:14px}
.help-in p{margin:14px 0 0;line-height:1.7;font-size:13px}
.help-in .frm{margin:14px 0 0;padding:12px 14px;border-radius:11px;font-family:var(--mono);font-size:12px;
  background:color-mix(in srgb,var(--acc) 7%,transparent);border:1px solid color-mix(in srgb,var(--acc) 22%,transparent);color:var(--tx2)}
.help-in .frm b{color:var(--acc)}
/* El diálogo de información de coste, cuota e imágenes: la prosa que no cabe en un dashboard. */
dialog.help.wide{max-width:680px;max-height:calc(100vh - 48px);overflow:auto}
.help-in section{scroll-margin-top:12px}
.help-in h4{margin:22px 0 0;font-size:11px;font-weight:700;color:var(--tx);text-transform:uppercase;letter-spacing:.055em;
  display:flex;align-items:center;gap:8px}
.help-in h4::before{content:"";width:3px;height:12px;border-radius:2px;background:var(--hc,var(--acc))}
.help-in section p{margin:8px 0 0;line-height:1.6;font-size:13px}
.help-in section p.lead{color:var(--tx);font-weight:700}
.help-in code{font-family:var(--mono);font-size:12px;color:var(--tx);padding:1px 5px;border-radius:5px;
  background:color-mix(in srgb,var(--bd) 60%,transparent)}

/* ---------- coste, cuota e imágenes: cifras como los KPIs ---------- */
.ph-r{display:flex;align-items:center;gap:10px}
.ibtn{width:26px;height:26px;flex:0 0 auto;display:grid;place-items:center;border-radius:8px;padding:0;cursor:pointer;
  border:1px solid var(--bd);background:transparent;color:var(--mut);transition:.13s}
.ibtn:hover{color:var(--tx);border-color:var(--bd2)}
.ibtn svg{width:15px;height:15px;display:block}
.kstats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px 18px}
.kstat .k-val{margin-top:10px}
.kstat .k-hint{margin-top:7px}
#costeCard .kstats{padding-bottom:14px;margin-bottom:4px;border-bottom:1px solid var(--bd)}
.qrange{position:relative;height:8px;border-radius:6px;margin-top:12px;overflow:hidden;
  background:color-mix(in srgb,var(--bd) 75%,transparent)}
.qrange i{position:absolute;top:0;bottom:0;border-radius:6px}
.qrange .qa{left:0;background:var(--violet)}
.qrange .qb{background:color-mix(in srgb,var(--violet) 38%,transparent)}
.qscale{display:flex;justify-content:space-between;margin-top:5px;font-family:var(--mono);font-size:10px;color:var(--faint)}

/* ---------- misc ---------- */
/* Los estados vacíos viven dentro de paneles técnicos —modelos, métricas del backend, RAM/VRAM,
   actividad— donde todo lo demás (nombres de modelo, badges, chips, tabla, pie) va en mono. Sin
   font-family propia heredaban la sans del body y cantaban: el mismo panel llegaba a enseñar dos
   estados vacíos con tipografías distintas, porque el de tools usa `.tchip`, que sí es mono. */
.empty{color:var(--mut);padding:30px;text-align:center;font-size:12.5px;
  font-family:var(--mono);letter-spacing:.01em}
/* Filas etiqueta/valor de la tarjeta Sistema cuando una cifra no se mide aquí (backend remoto,
   macOS): la etiqueta como la de los medidores, el valor en mono como `.meter-val`, y la
   explicación en el diálogo ⓘ, no en la tarjeta. */
.sysrow{display:flex;justify-content:space-between;align-items:baseline;gap:10px;padding:7px 0;
  border-bottom:1px solid color-mix(in srgb,var(--bd) 75%,transparent)}
.sysrow:last-child{border-bottom:0}
.sysrow-lbl{font-size:10.5px;color:var(--faint);font-weight:700;text-transform:uppercase;letter-spacing:.06em}
.sysrow-val{font-family:var(--mono);font-variant-numeric:tabular-nums;font-size:12px;font-weight:600;color:var(--tx);
  min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sysrow-val.nodata{color:var(--mut);font-weight:400}
.sysrow-val a{color:var(--blue);display:inline-flex;align-items:center;gap:5px}
.sysrow-val a:hover{text-decoration:underline}
.sysrow-val a svg{width:12px;height:12px;flex:0 0 auto}
footer{color:var(--faint);font-size:11.5px;margin-top:26px;padding-top:18px;border-top:1px solid var(--bd);
  text-align:center;font-family:var(--mono);letter-spacing:.01em}
.tt{position:fixed;z-index:60;max-width:270px;background:var(--bg2);border:1px solid var(--bd2);
  border-radius:10px;padding:10px 12px;font-size:12px;line-height:1.5;color:var(--tx2);
  box-shadow:var(--shadow-h);pointer-events:none;opacity:0;transform:translateY(3px);transition:.12s}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>
</head>
<body>
<div class="wrap">
  <header class="topbar">
    <div class="brand">
      <!-- El icono sale de resources/brand/favicon.svg, el mismo que sirve /favicon.svg y usa
           la landing. `aria-hidden` en el contenedor oculta todo el subárbol al lector de
           pantalla, incluido el aria-label del propio SVG: el nombre ya lo dice .brand-name
           justo al lado y repetirlo sería ruido. -->
      <span class="mark" aria-hidden="true">__BRAND_MARK__</span>
      <div class="brand-txt">
        <div class="brand-name">local<b>·</b>delegate<span class="ver" id="ver" title="Versión del MCP que sirve este panel" style="display:none"></span></div>
        <div class="brand-sub">panel de ahorro</div>
      </div>
      <span class="live" id="live" title="Estado de los datos"><span class="live-dot"></span><span id="liveTxt">EN VIVO</span></span>
    </div>
    <div class="controls">
      <select id="range" class="btn" title="Rango temporal">
        <option value="today" selected>Hoy</option>
        <option value="7">Últimos 7 días</option>
        <option value="30">Últimos 30 días</option>
        <option value="prev-month">Mes anterior</option>
        <option value="all">Todo el histórico</option>
        <option value="custom">Personalizado…</option>
      </select>
      <input type="date" id="rangeFrom" class="btn" style="display:none" title="Desde">
      <input type="date" id="rangeTo" class="btn" style="display:none" title="Hasta">
      <!-- Interruptor «Pruebas» (test-windows-out-of-metrics, REQ-016): apagado, el panel aparta
           las pruebas; encendido, las tres peticiones de fetchData llevan include_tests=1. -->
      <button id="tests" class="btn" title="Incluir pruebas" aria-pressed="false">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 3h6"/><path d="M10 3v6.5L4.6 18.4A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.4-2.6L14 9.5V3"/><path d="M7.5 15h9"/></svg>
        Pruebas<span class="tdot" id="testsDot" hidden></span></button>
      <button class="ibtn" id="testsInfo" data-group="tests" aria-haspopup="dialog"
        title="Qué cuenta como prueba" aria-label="Información sobre las pruebas"></button>
      <button id="auto" class="btn on" title="Auto-refresco cada 15 s">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 0 1 15.4-6.4L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15.4 6.4L3 16"/><path d="M3 21v-5h5"/></svg>
        Auto</button>
      <button id="reload" class="btn icon" title="Refrescar ahora" aria-label="Refrescar">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/></svg></button>
      <button id="theme" class="btn icon" title="Tema claro / oscuro" aria-label="Cambiar tema">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.4 14.2A8.5 8.5 0 0 1 9.8 3.6a8.5 8.5 0 1 0 10.6 10.6z"/></svg></button>
      <button id="help" class="btn icon" title="¿Cómo se calcula el ahorro?" aria-label="Ayuda">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M9.2 9.2a2.8 2.8 0 1 1 3.9 2.6c-.8.4-1.1 1-1.1 1.9"/><path d="M12 17h.01"/></svg></button>
    </div>
  </header>

  <div class="grid duo">
    <div class="card" style="--hc:var(--violet)">
      <div class="panel-h"><h2>Backend</h2><span style="display:flex;gap:6px;align-items:center">
        <span id="originPill" class="pill org local" style="display:none">cómputo local</span>
        <span id="backendPill" class="pill down">sin datos</span></span></div>
      <div id="modelsBody"><div class="empty" style="padding:16px">Consultando el backend…</div></div>
      <div class="subh">Rendimiento del backend <span class="mut" id="bstatsHead"></span></div>
      <div id="backendStats"><div class="empty" style="padding:12px">sin datos</div></div>
      <div class="subh" id="inflightHead">En curso</div>
      <div id="inflightBody"></div>
      <div class="subh">Tools MCP disponibles <span id="toolsCount" class="num" style="color:var(--tx2)"></span></div>
      <div class="toolchips" id="toolsBody"><span class="tchip">…</span></div>
    </div>
    <div class="card" style="--hc:var(--amber)">
      <div class="panel-h"><h2>Sistema</h2>
        <span class="ph-r"><button class="ibtn" id="systemInfo" data-group="sistema" aria-haspopup="dialog"
          title="Qué mide esta tarjeta" aria-label="Información sobre la tarjeta Sistema"></button></span></div>
      <div id="metersBody"><div class="empty" style="padding:16px">Leyendo métricas…</div></div>
      <div id="procSection">
        <div class="subh">Procesos del backend</div>
        <div style="overflow-x:auto"><table class="proc" id="procTable"></table></div>
      </div>
    </div>
  </div>

  <div class="grid kpis" id="kpis"></div>

  <!-- Coste equivalente a precio de API, cuota e imágenes (coste-api-y-cuota). Todo lo calcula
       Python en /api/stats; aquí solo se pinta. Las tarjetas llevan cifras; los supuestos sin los
       que no hay cifra (REQ-044) van en el diálogo `infoDlg`, a un clic del botón ⓘ de cada una. -->
  <div class="card tablecard" id="costeCard" style="--hc:var(--amber);display:none">
    <div class="panel-h"><h2>Equivalente a precio de API</h2>
      <span class="ph-r"><span class="mut" id="costeHead"></span>
        <button class="ibtn" id="costeInfo" data-group="coste" data-section="dlgCoste" aria-haspopup="dialog"
          title="Cómo leer esta cifra, la cuota y las imágenes" aria-label="Información sobre el equivalente a precio de API"></button></span></div>
    <div id="costeBody"></div>
  </div>

  <div class="grid cols2" id="cuotaImgRow" style="display:none">
    <div class="card" id="cuotaCard" style="--hc:var(--violet);display:none">
      <div class="panel-h"><h2>Cuota de la suscripción</h2>
        <span class="ph-r"><span class="mut" id="cuotaHead"></span>
          <button class="ibtn" data-group="coste" data-section="dlgCuota" aria-haspopup="dialog"
            title="Cómo se calibra la cuota" aria-label="Información sobre la cuota"></button></span></div>
      <div id="cuotaBody"></div>
    </div>
    <div class="card" id="imagenesCard" style="--hc:var(--cyan);display:none">
      <div class="panel-h"><h2>Imágenes</h2>
        <span class="ph-r"><span class="mut">fuera del neto</span>
          <button class="ibtn" data-group="coste" data-section="dlgImagenes" aria-haspopup="dialog"
            title="Por qué las imágenes van aparte" aria-label="Información sobre las imágenes"></button></span></div>
      <div id="imagenesBody"></div>
    </div>
  </div>

  <div class="grid cols">
    <div class="card chartcard" style="--hc:var(--acc)">
      <div class="panel-h"><h2>Ahorro de contexto en el tiempo</h2><span class="mut" id="tsMode">tokens · día</span></div>
      <div class="cbox"><canvas id="tsChart"></canvas></div>
    </div>
    <div class="card chartcard" style="--hc:var(--blue)">
      <div class="panel-h"><h2>Ahorro por herramienta</h2><span class="mut">tokens</span></div>
      <div class="cbox donut"><canvas id="toolDonut"></canvas></div>
    </div>
  </div>

  <!-- «Dónde corrió el cómputo» se quitó: el backend es fijo por instalación, así que el donut
       siempre daba 100 % de un lado; lo dice ya la píldora de cómputo local/remoto del Backend. -->
  <div class="grid cols2">
    <div class="card chartcard" style="--hc:var(--violet)">
      <div class="panel-h"><h2>Llamadas por modelo</h2><span class="mut">llamadas</span></div>
      <div class="cbox donut"><canvas id="modelBar"></canvas></div>
    </div>
    <div class="card chartcard" style="--hc:var(--acc)">
      <div class="panel-h"><h2>Origen del input</h2><span class="mut">por ruta = ahorro real</span></div>
      <div class="cbox donut"><canvas id="srcDonut"></canvas></div>
    </div>
  </div>

  <div class="card tablecard">
    <div class="panel-h" style="--hc:var(--cyan)"><h2>Actividad reciente</h2><span class="mut" id="actCount"></span></div>
    <div style="overflow-x:auto"><table id="activity"></table></div>
    <div class="pager" id="pager" style="display:none">
      <button class="pbtn" id="pgPrev" aria-label="Página anterior">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg></button>
      <span class="pinfo" id="pgInfo"></span>
      <button class="pbtn" id="pgNext" aria-label="Página siguiente">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg></button>
    </div>
  </div>

  <!-- Quién pidió las delegaciones. El KPI de ahorro es acumulativo y no distingue un mes de
       smoke tests de un mes de trabajo real; esto sí. NO se lee como conversión: dice quién llamó,
       no cuántas sugerencias se siguieron. -->
  <div class="card tablecard" id="clientsCard" style="display:none">
    <div class="panel-h" style="--hc:var(--cyan)"><h2>Quién delegó</h2>
      <span class="mut" id="clientsHead"></span></div>
    <div id="clientsBody"></div>
  </div>

  <!-- Los hooks consultivos sugieren; el usuario decide. Esta tarjeta cuenta lo primero y NO
       pretende medir lo segundo: no hay identificador que una una sugerencia con una delegación,
       y cruzarlos sería inventar una correlación. El texto de la tarjeta lo dice. -->
  <div class="card tablecard" id="hooksCard" style="display:none">
    <div class="panel-h" style="--hc:var(--amber)"><h2>Sugerencias de los hooks</h2>
      <span class="ph-r"><span class="mut" id="hooksHead"></span>
        <button class="ibtn" id="hooksInfo" data-group="hooks" aria-haspopup="dialog"
          title="Qué mide esta tarjeta" aria-label="Información sobre las sugerencias de los hooks"></button></span></div>
    <div id="hooksBody"></div>
  </div>

  <footer id="foot"></footer>
</div>

<dialog class="help" id="helpDlg" aria-labelledby="helpTitle">
  <div class="help-in">
    <div class="help-h">
      <span class="k-ico" style="--kc:var(--acc)">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.9 12a8.9 8.9 0 1 1-3.6-7.2"/><path d="M9 12l2.5 2.5L21 5"/></svg></span>
      <h3 id="helpTitle">¿Cómo se calcula el ahorro?</h3>
      <button class="help-x" id="helpClose" aria-label="Cerrar">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg></button>
    </div>
    <p><b>Contexto conservado</b> = el contenido de entrada que el MCP leyó <i>server-side</i>
    (llamadas con <span class="src path">path</span>) y que <b>nunca entró a la ventana de contexto de
    Claude</b>. Son tokens que no ocuparon tu contexto, no un trozo de cuota medido: Anthropic no
    publica la cuota en tokens, y la cuota tiene su propio bloque. Las llamadas <span class="src inline">inline</span> ya
    viajaron por tu contexto, así que no cuentan como ahorro. Se cuenta <b>una vez</b> por delegación
    aunque el MCP la trocee: lo que no entró a tu contexto es el documento, no el trabajo de la GPU.</p>
    <p><b>Coste local</b> = los tokens de entrada que consumió de verdad el backend, sumando
    <b>todas</b> las llamadas. Una delegación troceada repite el prompt de sistema en cada trozo, así
    que aquí sí paga el troceo. Enfrentado al ahorro, distingue una delegación eficiente de una que
    quemó la GPU varias veces.</p>
    <p><b>Generado en local</b> = tokens de salida: trabajo de generación que hicieron los modelos
    locales en vez de Claude.</p>
    <div class="frm">coste local: el token <b>real</b> que reporta el backend, caracteres ÷ 4 solo
    cuando falta &nbsp;·&nbsp; contexto conservado: tokens de Claude por familia y tipo de contenido
    &nbsp;·&nbsp; ahorro real = solo llamadas con <b>source=path</b></div>
  </div>
</dialog>

<!-- Diálogo de información: la prosa que no cabe en un dashboard. Cada botón ⓘ lo abre con su
     grupo de secciones (`data-group`). El texto del coste, la cuota y las imágenes sale de
     textoCoste/textoCuota/textoImagenes (las funciones puras que prueba node), así que lo que se lee
     aquí es lo que se prueba. La sección de la cuota está aunque su tarjeta no se pinte: sin
     calibrar, este es su único sitio. -->
<dialog class="help wide" id="infoDlg" aria-labelledby="infoDlgTitle">
  <div class="help-in">
    <div class="help-h">
      <span class="k-ico" id="infoDlgIco"></span>
      <h3 id="infoDlgTitle"></h3>
      <button class="help-x" id="infoDlgClose" aria-label="Cerrar">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg></button>
    </div>
    <section id="dlgCoste" data-group="coste" style="--hc:var(--amber)"><h4>Equivalente a precio de API</h4><div id="dlgCosteBody"></div></section>
    <section id="dlgCuota" data-group="coste" style="--hc:var(--violet)"><h4>Cuota de la suscripción</h4><div id="dlgCuotaBody"></div></section>
    <section id="dlgImagenes" data-group="coste" style="--hc:var(--cyan)"><h4>Imágenes</h4><div id="dlgImagenesBody"></div></section>
    <section id="dlgPruebas" data-group="tests" style="--hc:var(--amber)"><h4>Qué cuenta como prueba</h4><div id="dlgPruebasBody"></div></section>
    <section id="dlgHooks" data-group="hooks" style="--hc:var(--amber)"><h4>Qué mide esta tarjeta</h4>
      <p>Los hooks <b>sugieren</b>; delegar lo decides tú. Esto no mide cuántas sugerencias se
      siguieron —nada enlaza una sugerencia con la delegación que vino después—, sino en qué avisó
      el hook de lectura y por qué se calló en el resto.</p>
      <p><b>Categoría</b> es el hook que sugirió (lectura, shell) o la tarea que el hook de prompt
      reconoció en tu mensaje (resumen, extracción, clasificación, traducción, código repetitivo).
      <b>Lecturas vistas</b> reparte las lecturas que vio el hook de lectura por lo que hizo con
      ellas: avisó, o se calló porque la lectura era acotada, de código, pequeña, iba por otro
      MCP o el backend no estaba.</p></section>
    <section id="dlgSistema" data-group="sistema" style="--hc:var(--amber)"><h4>Qué mide esta tarjeta</h4>
      <p>La <b>RAM</b>, la <b>carga de la GPU</b> y la <b>VRAM</b> de la máquina donde corre este
      panel, y los procesos del backend que encuentra en ella. La lista de procesos solo se lee en
      Windows y Linux; en macOS todavía no se miden ni la RAM ni la VRAM, y la fila sale con «—».</p>
      <p>Con el <b>backend en otra máquina</b>, la fila <b>Backend</b> enlaza al panel de esa
      máquina, que es donde se ven su RAM, su VRAM y sus procesos. Ese panel pide el token de
      aquella máquina, no el de esta.</p></section>
  </div>
</dialog>

<div class="tt" id="tt"></div>
<script>
const CPT = 4, F = {format: n => fmtNum(n, 0)}, PAGE = 10;
const F1 = {format: n => fmtNum(n, 1)};
// Formato de números del panel: punto de miles SIEMPRE, coma decimal y signo menos. No se usa
// `Intl.NumberFormat('es')`: el español no agrupa los números de cuatro cifras (8003), y la opción
// que lo arregla (`useGrouping:'always'`) un navegador sin Intl v3 la convierte en `true` y vuelve
// a pintar 8003 sin avisar. Sin `toFixed` para no mezclar dos maneras de redondear.
function fmtNum(n, decimales){
  if(n===null || n===undefined || !isFinite(n)) return '–';
  const d = decimales || 0, p = Math.pow(10, d);
  const r = Math.round(Math.abs(n) * p);
  const ent = Math.floor(r / p), frac = r - ent * p;
  let s = String(ent).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  if(d > 0) s += ',' + String(frac).padStart(d, '0');
  return (n < 0 && r > 0 ? '-' : '') + s;
}
// Latencias y duraciones en segundos con un decimal. Por debajo de 50 ms redondearía a «0,0 s»,
// que se lee como «no tardó nada»: se dice «< 0,1 s».
function fmtSeg(ms){
  if(ms===null || ms===undefined || !isFinite(ms)) return '–';
  if(ms < 50) return '< 0,1 s';
  return F1.format(ms / 1000) + ' s';
}
// «1 estimado / 4 estimados»: la cifra con su formato y la palabra concordada, sin «(s)».
function plural(n, uno, varios){ return fmtNum(n, 0) + ' ' + (n === 1 ? uno : varios); }
const state = {events:[], stats:null, range:'today', auto:true, tests:false, charts:{},
  page:0, status:null, running:{}, backendUp:undefined, inflight:[],
  activity:null, lastEvent:null, backendOrigin:null, backendHost:null};
const cssv = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
// floor, no round: `_accounting` en Python usa `// CHARS_PER_TOKEN`, y con redondeo las series
// del gráfico se irían un token respecto a la tarjeta que tienen encima.
const tok = c => Math.floor(c/CPT);
const MONO = "'JetBrains Mono',ui-monospace,monospace";
const SANS = "'Inter',system-ui,sans-serif";

// #rrggbb -> rgba(...) con alpha (para gradientes de canvas, que no aceptan var())
function hexA(hex,a){ hex=(hex||'').replace('#',''); if(hex.length===3) hex=hex.split('').map(c=>c+c).join('');
  const n=parseInt(hex||'888888',16); return `rgba(${(n>>16)&255},${(n>>8)&255},${n&255},${a})`; }
function vGrad(chart,from,to){ const a=chart.chartArea; if(!a) return from;
  const g=chart.ctx.createLinearGradient(0,a.bottom,0,a.top); g.addColorStop(0,from); g.addColorStop(1,to); return g; }
function hGrad(chart,from,to){ const a=chart.chartArea; if(!a) return from;
  const g=chart.ctx.createLinearGradient(a.left,0,a.right,0); g.addColorStop(0,from); g.addColorStop(1,to); return g; }
function palette(){ return [cssv('--acc'),cssv('--blue'),cssv('--violet'),cssv('--amber'),cssv('--cyan'),cssv('--pink'),cssv('--danger')]; }

// Chart.js viene de un CDN: en una máquina sin salida a internet (o con el CDN caído) no
// carga. El panel es local-first, así que degrada a "sin gráficos" en vez de romperse entero:
// KPIs, tabla de actividad, backend, sistema e indicador de actividad siguen funcionando.
const HAS_CHART = typeof Chart !== 'undefined';

if(HAS_CHART) Chart.register({ id:'centerText',
  afterDraw(chart,args,opts){
    if(!opts||!opts.text) return;
    const a=chart.chartArea; if(!a) return; const ctx=chart.ctx;
    const x=(a.left+a.right)/2, y=(a.top+a.bottom)/2;
    ctx.save(); ctx.textAlign='center'; ctx.textBaseline='middle';
    ctx.fillStyle=opts.color||cssv('--tx'); ctx.font='700 26px '+MONO; ctx.fillText(opts.text,x,y-7);
    ctx.fillStyle=cssv('--mut'); ctx.font='700 10px '+SANS;
    ctx.fillText((opts.sub||'').toUpperCase(),x,y+15); ctx.restore();
  }});

function applyDefaults(){
  if(!HAS_CHART) return;
  Chart.defaults.font.family=SANS; Chart.defaults.font.size=11;
  // Ejes y tooltips con el formato del panel (punto de miles, coma decimal), como `fmtNum`: sin
  // esto Chart.js formatea con el idioma del navegador y un eje enseñaba «1,000» o «0.5».
  Chart.defaults.locale='de-DE';
  Chart.defaults.color=cssv('--mut');
  Chart.defaults.animation.duration=650; Chart.defaults.animation.easing='easeOutQuart';
  Chart.defaults.plugins.tooltip.backgroundColor=cssv('--bg2');
  Chart.defaults.plugins.tooltip.borderColor=cssv('--bd2');
  Chart.defaults.plugins.tooltip.borderWidth=1;
  Chart.defaults.plugins.tooltip.titleColor=cssv('--tx');
  Chart.defaults.plugins.tooltip.bodyColor=cssv('--tx2');
  Chart.defaults.plugins.tooltip.padding=10;
  Chart.defaults.plugins.tooltip.cornerRadius=9;
  Chart.defaults.plugins.tooltip.boxPadding=5;
  Chart.defaults.plugins.tooltip.usePointStyle=true;
  Chart.defaults.plugins.tooltip.titleFont={family:MONO,weight:'700',size:11};
  Chart.defaults.plugins.tooltip.bodyFont={family:MONO,size:12};
}

const ICON = {
  save:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.2 19 6v5.2c0 4.7-2.9 7.7-7 9.6-4.1-1.9-7-4.9-7-9.6V6z"/><path d="m9.2 11.9 2 2 3.6-4"/></svg>',
  calls:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2.5 4.5 13H11l-1 8.5L18.5 11H12z"/></svg>',
  gen:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5.5" y="5.5" width="13" height="13" rx="2.6"/><rect x="9.6" y="9.6" width="4.8" height="4.8" rx="1"/><path d="M9.5 2.6v2.9M14.5 2.6v2.9M9.5 18.5v2.9M14.5 18.5v2.9M2.6 9.5h2.9M2.6 14.5h2.9M18.5 9.5h2.9M18.5 14.5h2.9"/></svg>',
  lat:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 14 4-4"/><path d="M3.3 19a10 10 0 1 1 17.4 0"/></svg>',
  cost:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21.5c3.9 0 6.4-2.6 6.4-5.9 0-4.4-3.9-5.9-4.9-9.8-2 1.5-3 3.4-3 5.4-1-.5-1.5-1.5-1.5-2.4-1 1.4-3.4 3.9-3.4 6.8 0 3.3 2.5 5.9 6.4 5.9z"/></svg>',
  err:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.6 1.8 18a1.7 1.7 0 0 0 1.5 2.6h17.4A1.7 1.7 0 0 0 22.2 18L13.7 3.6a1.7 1.7 0 0 0-2.9 0z"/><path d="M12 9v4M12 17h.01"/></svg>',
  info:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 11.2V16"/><path d="M12 8h.01"/></svg>',
};

// --- Zona horaria ------------------------------------------------------------
// El log se escribe en UTC (instantes sin ambigüedad), pero los rangos, los días del
// gráfico y las horas de la tabla son del USUARIO: "Hoy" tiene que ser hoy en tu reloj,
// no el día UTC. Todo lo que se manda al servidor sigue siendo un instante absoluto
// (toISOString() incluye el offset), así que el backend no necesita saber tu zona.
const TZ = (Intl.DateTimeFormat().resolvedOptions().timeZone) || 'local';
const TZ_OFFSET_TXT = (()=>{ const m=-new Date().getTimezoneOffset();
  const s=m<0?'-':'+', a=Math.abs(m); return 'UTC'+s+String(Math.floor(a/60)).padStart(2,'0')+':'+String(a%60).padStart(2,'0'); })();
// medianoche LOCAL del día de `d`, desplazada `deltaDays`
function localMidnight(d, deltaDays){ return new Date(d.getFullYear(), d.getMonth(), d.getDate()+(deltaDays||0)); }
// clave YYYY-MM-DD en hora LOCAL (no uses toISOString(): eso vuelve a UTC)
function localDayKey(d){
  return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
}
const FMT_TIME = new Intl.DateTimeFormat('es',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
function fmtLocalTs(ts){ const d=new Date(ts); return isFinite(d) ? FMT_TIME.format(d).replace(',','') : (ts||''); }

// Presets de rango -> {from, to} ISO absoluto. 'custom' lee los <input type=date> (que el
// navegador entrega como fecha local, así que se interpretan en hora local).
function computeRange(preset){
  const now = new Date();
  if(preset==='today') return {from:localMidnight(now).toISOString(), to:now.toISOString()};
  if(preset==='7') return {from:localMidnight(now,-6).toISOString(), to:now.toISOString()};
  if(preset==='30') return {from:localMidnight(now,-29).toISOString(), to:now.toISOString()};
  if(preset==='prev-month'){
    const y=now.getFullYear(), m=now.getMonth();
    return {from:new Date(y, m-1, 1).toISOString(), to:new Date(y, m, 1).toISOString()};
  }
  if(preset==='all') return {from:'2000-01-01T00:00:00Z', to:now.toISOString()};
  if(preset==='custom'){
    const f=document.getElementById('rangeFrom').value, t=document.getElementById('rangeTo').value;
    const [fy,fm,fd]=(f||'').split('-').map(Number), [ty,tm,td]=(t||'').split('-').map(Number);
    return {from:f?new Date(fy,fm-1,fd,0,0,0).toISOString():null,
            to:t?new Date(ty,tm-1,td,23,59,59,999).toISOString():null};
  }
  return {from:null, to:null};
}

// La query de las tres peticiones del panel. Pura, para que node la pruebe: rango e interruptor
// «Pruebas» van juntos y una petición no puede salir con otro conjunto que las demás.
function buildQuery(range, includeTests){
  const qs = new URLSearchParams();
  if(range && range.from) qs.set('from', range.from);
  if(range && range.to) qs.set('to', range.to);
  if(includeTests) qs.set('include_tests', '1');
  return qs.toString();
}

async function fetchData(){
  try{
    const q = buildQuery(computeRange(state.range), state.tests);
    // Los KPIs vienen de /api/stats y NO se recalculan aquí: es la única implementación de las
    // cuentas (la de Python). Además /api/events viene topado a MAX_EVENTS, así que sumar sobre
    // esta lista subestimaría en rangos grandes mientras el pie muestra el total real.
    const [r, rs, rh] = await Promise.all([
      fetch('/api/events?' + q),
      fetch('/api/stats?' + q),
      // Mismo rango (y mismo interruptor) que el resto de la página: una tarjeta que contara otro
      // conjunto se leería como una contradicción de los KPIs de arriba.
      fetch('/api/hooks?' + q),
    ]);
    const j = await r.json();
    state.events = j.events||[]; state.meta = j.meta||{};
    try{ state.stats = await rs.json(); }catch(e){ state.stats = null; }
    renderClients(state.stats);
    renderCoste(state.stats);
    renderPruebas(state.stats);
    try{ renderHooks(await rh.json()); }catch(e){ renderHooks(null); }
    render(); updateLive();
    const cnt = plural(state.meta.count||0, 'evento', 'eventos');
    const filesN = (state.meta.files_read||[]).length;
    document.getElementById('foot').textContent =
      (state.meta.log_dir||'') + '   ·   ' + cnt + '   ·   '
      + plural(filesN, 'archivo leído', 'archivos leídos')
      + '   ·   tokens de Claude por familia y tipo de contenido; modelo local ~' + CPT
      + ' chars/token   ·   horas en ' + TZ + ' (' + TZ_OFFSET_TXT + ')   ·   local·delegate';
  }catch(e){
    document.getElementById('kpis').innerHTML='<div class="card empty">No se pudo leer <b>/api/events</b>. ¿El MCP está corriendo?</div>';
    document.getElementById('live').classList.add('stale');
    document.getElementById('liveTxt').textContent='SIN DATOS';
  }
}

// --- Quién delegó: el desglose por cliente de /api/stats ---
//
// "desconocido" no es un fallo: son las llamadas anteriores a que se registrara el cliente, y las
// que no vienen de una sesión MCP (el benchmark, un script). Se muestra tal cual porque
// repartirlas entre los demás sería inventar de quién eran.
function renderClients(s){
  const card = document.getElementById('clientsCard');
  const filas = (s && s.by_client) || [];
  if(!filas.length){ card.style.display='none'; return; }
  card.style.display='';

  const totalCalls = filas.reduce((a,c)=>a+c.calls,0);
  document.getElementById('clientsHead').textContent =
    filas.length + (filas.length===1 ? ' cliente' : ' clientes');

  const cuerpo = filas.map(c=>{
    const p = totalCalls ? (c.calls/totalCalls*100) : 0;
    return '<tr><td class="mono" title="' + escHooks(c.client) + '">' + escHooks(labelFor('client', c.client)) + '</td>'
      + '<td class="num">' + F.format(c.calls) + '</td>'
      + '<td class="num" style="color:var(--tx2)">' + F.format(c.backend_calls) + '</td>'
      + '<td class="num" style="color:var(--green)">' + F.format(c.tokens_net) + '</td>'
      + '<td class="num" style="color:var(--cyan)">' + F1.format(p) + ' %</td></tr>';
  }).join('');

  document.getElementById('clientsBody').innerHTML =
    '<div style="overflow-x:auto"><table>'
    + '<thead><tr><th>Cliente</th><th>Delegaciones</th>'
    + '<th>Llamadas al backend</th><th>Tokens netos</th>'
    + '<th>Reparto</th></tr></thead>'
    + '<tbody>' + cuerpo + '</tbody></table></div>';
}

// --- Coste equivalente, cuota e imágenes: /api/stats (coste-api-y-cuota) ---
//
// El coste solo lo calcula Python; estas funciones son puras (las prueba node en
// `test_panel_coste.py`) y devuelven LÍNEAS de texto, la primera es el titular. Ninguna frase lo
// presenta como dinero en el bolsillo ni como un trozo de cuota medido (REQ-045), y sin calibrar no
// hay % (REQ-059).
const HILO_TXT = {main:'hilo principal', subagent:'subagente'};

// Etiquetas de presentación: clave interna (la del log y la de la API, que NO cambian) → texto que
// se lee en el panel. Los nombres propios de tools y modelos (`local_summarize`, `gemma4-26b-a4b`)
// no pasan por aquí: se enseñan tal cual. Una clave que no esté en el mapa no sale cruda:
// `humanLabel` le quita los guiones bajos y le pone la mayúscula inicial.
const LABELS = {
  // Categoría de la sugerencia: el hook que la emitió (lectura, shell) o la tarea que el hook de
  // prompt reconoció en el mensaje (resumir, extraer, …).
  hookCategory: {read:'Lectura', shell:'Shell', bash:'Shell', lint:'Lint', summarize:'Resumen',
    extract:'Extracción', classify:'Clasificación', translate:'Traducción',
    boilerplate:'Código repetitivo', 'sin categoría':'Sin categoría'},
  // Por qué el hook de lectura avisó o se calló (`motivo` del log de hooks).
  hookReason: {'avisó':'Avisó', aviso:'Avisó', acotada:'Lectura acotada', codigo:'Código',
    pequeno:'Pequeño', mcp_ajeno:'Por otro MCP', backend_ausente:'Backend ausente',
    modelo_enfriado:'Modelo enfriado', prosa_grande:'Prosa grande', no_es_prosa:'No es prosa',
    no_es_volcado:'No es un volcado', sin_fichero:'Sin fichero', bloqueo_apagado:'Bloqueo apagado',
    'sin registrar':'Sin registrar'},
  client: {'claude-code':'Claude Code', 'claude-desktop':'Claude Desktop', 'claude-ai':'Claude Desktop',
    codex:'Codex', 'codex-mcp-client':'Codex',
    desconocido:'Desconocido'},
  effort: {low:'Bajo', medium:'Medio', high:'Alto', xhigh:'Muy alto', max:'Máximo', 'sin dato':'Sin dato'},
  thread: {main:'Hilo principal', subagent:'Subagente'},
  origin: {local:'Local', remote:'Remoto', unknown:'Sin dato'},
  // Estado del modelo que informa el backend (llama-swap) en la insignia de cada fila.
  // Origen del input: `path` = el MCP leyó el fichero server-side (ahorro real); `inline`, no.
  source: {path:'Por ruta (path)', inline:'Texto en línea (inline)'},
  modelStatus: {loaded:'Cargado', unloaded:'Sin cargar', starting:'Cargando', stopping:'Descargando', ready:'Listo'},
};
function humanLabel(key){
  const s = String(key===null || key===undefined || key==='' ? 'sin dato' : key).replace(/_/g, ' ').trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}
function labelFor(kind, key){
  const m = LABELS[kind] || {};
  return Object.prototype.hasOwnProperty.call(m, key) ? m[key] : humanLabel(key);
}
function dolares(x){ return '$' + fmtNum(x, 2); }

// Las dos celdas en dólares de una fila del desglose. Con T ≤ 0 la tool devolvió tanto o más de lo
// que leyó: la fila no tiene ahorro y no se pinta una cifra (sería «$0,00» o un negativo sin signo).
function celdasCoste(g){
  if(!(g.T > 0)) return '<td class="num" colspan="2" style="color:var(--mut)">sin ahorro</td>';
  return '<td class="num">' + dolares(g.cota_baja) + '</td>'
    + '<td class="num" style="color:var(--amber)">' + dolares(g.estimacion) + '</td>';
}

// --- Pruebas: el texto de su ⓘ y el punto del botón (test-windows-out-of-metrics) ---
function textoPruebas(j){
  if(!j) return [];
  const L = [];
  const fuera = j.excluded_tests||0, enRango = j.tests_in_range||0;
  if(fuera) L.push('Fuera de las cifras: ' + plural(fuera, 'fila de prueba', 'filas de prueba') + ' en el rango elegido.');
  else if(enRango) L.push('Pruebas incluidas: ' + plural(enRango, 'fila de prueba', 'filas de prueba') + ' en el rango elegido.');
  else L.push('En el rango elegido no hay pruebas.');
  // Los comandos y los ids van entre comillas invertidas: `renderPruebas` los pinta como código.
  for(const w of (j.open_test_windows||[])){
    L.push('Ventana de prueba abierta: `' + w.id + '` desde ' + fmtLocalTs(w.start)
      + '. Ciérrala con `local-delegate test-window stop ' + w.id + '`.');
  }
  L.push('Una prueba es una delegación del cliente `mcp` de los scripts del repo, la de un banco, '
    + 'o cualquiera hecha dentro de una ventana de prueba. Apagado, el interruptor las aparta de '
    + 'todo el panel; encendido, las enseña.');
  L.push('El coste equivalente y la cuota las apartan siempre, con el interruptor como esté.');
  L.push('Para marcar una prueba en vivo: `local-delegate test-window start --label «…»` antes de '
    + 'empezar, guarda el id que imprime, y `local-delegate test-window stop <id>` al acabar.');
  return L;
}

function renderPruebas(s){
  // Se escapa primero y después cada `…` pasa a <code> (mono, como los demás valores de máquina).
  document.getElementById('dlgPruebasBody').innerHTML = parrafosHtml(textoPruebas(s), true)
    .replace(/`([^`]+)`/g, '<code>$1</code>');
  document.getElementById('testsDot').hidden = !((s && s.open_test_windows)||[]).length;
}

function textoCoste(j){
  const c = j && j.coste;
  if(!c) return [];
  const L = [];
  L.push(c.cifra
    ? 'Equivalente estimado a precio de API: entre ' + dolares(c.cifra.cota_baja)
      + ' y ~' + dolares(c.cifra.estimacion)
    : 'Equivalente estimado a precio de API: sin cifra (' + c.motivo + ')');
  L.push('No es dinero que hayas ahorrado: tu suscripción es de tarifa plana.');
  if(c.cifra) L.push('El primer número es la cota baja con estos supuestos (una sola escritura de caché); '
    + 'el segundo suma las relecturas de caché posteriores y las caducidades.');
  const b = c.barra || {}, r = c.respaldo || {};
  L.push('Cobertura: ' + plural(b.al_momento||0, 'atribuida al momento', 'atribuidas al momento')
    + ' · ' + F.format(b.por_relleno||0) + ' por relleno · ' + F.format(b.pendiente||0)
    + ' pendientes · ' + F.format(b.supuesto||0) + ' supuestas · ' + F.format(b.excluido||0)
    + ' excluidas (pruebas: scripts, bancos y ventanas de prueba; y clientes que no son Claude).');
  L.push(F.format(b.con_modelo_supuesto||0) + ' de ' + F.format(b.valoradas||0)
    + ' con modelo supuesto: ' + (r.nombre||'') + ' en ' + (HILO_TXT[r.hilo]||r.hilo||'')
    + (r.invalido ? ' (el valor de ' + r.variable + ' no es válido: se usa el declarado)' : '') + '.');
  const n = c.n_origen || {}, nd = c.n_declarado || {};
  L.push('Relecturas (N): ' + F.format(n.relleno||0) + ' del relleno, ' + F.format(n.agregado||0)
    + ' de la mediana de su grupo, ' + F.format(n.declarado||0) + ' con el valor declarado (principal '
    + F.format(nd.main) + ', subagente ' + F.format(nd.subagent) + ').');
  const d = c.densidad || {}, o = d.origen || {};
  const fams = Object.entries(d.familias||{}).map(([k,v]) => k + ' ' + F.format(v)).join(', ');
  L.push('Densidad de Claude por familia de tokenizador (' + (fams || 'ninguna') + '): celda medida '
    + F.format(o.medida||0) + ', sin numerar ' + F.format(o.sin_numerar||0) + ', conservadora '
    + F.format(o.conservadora||0) + '; ' + F.format(d.densidad_de_la_familia||0)
    + ' con densidad de la familia y ' + F.format(d.familia_supuesta||0) + ' con familia supuesta.');
  const sp = c.sin_precio || {};
  if(sp.n) L.push(plural(sp.n, 'delegación de un modelo sin precio', 'delegaciones de modelos sin precio')
    + ', fuera de la suma: ' + (sp.ids||[]).join(', ') + '.');
  const fb = c.fuera_de_la_base || {};
  L.push('Fuera de la cifra: ' + plural(fb.imagenes||0, 'imagen', 'imágenes') + ' y '
    + plural(fb.salida_a_fichero||0, 'salida a fichero', 'salidas a fichero') + '.');
  L.push('Neto de la respuesta de la tool. Contrafactual: si Claude hubiera leído el fichero entero '
    + 'una vez con Read. No descuenta las relecturas del mismo fichero (medidas entre ~3 % y ~30 %).');
  L.push('Precios de la tabla del paquete del ' + ((c.tabla||{}).consultado || 'sin fecha') + '.');
  return L;
}

function textoCuota(j){
  const q = j && j.cuota;
  if(!q) return [];
  const L = [];
  [['five_hour','Ventana de 5 h'], ['seven_day','Ventana semanal']].forEach(([tipo, nombre])=>{
    const e = q[tipo];
    if(!e) return;
    const disp = (e.dispersion!==undefined && e.dispersion!==null)
      ? ', dispersión ' + F1.format(e.dispersion*100) + ' %' : '';
    if(e.estado==='calibrado'){
      const v = tipo==='five_hour'
        ? 'de una ventana de 5 h (lo delegado en las últimas 5 h'
        : 'de una ventana semanal (lo delegado en los últimos 7 días';
      L.push(e.a_pct!==null && e.a_pct!==undefined
        ? nombre + ': ≈ entre ' + F1.format(e.a_pct) + ' % y ' + F1.format(e.b_pct) + ' % ' + v
          + '; la estimación incluye relecturas que pueden caer después de la ventana); estimación '
          + 'calibrada con ' + plural(e.puntos||0, 'punto', 'puntos') + disp
          + '; supone que la cuota sigue al precio de lista.'
        : nombre + ': calibrada, sin cifra (' + (e.motivo_pct||'') + ').');
      if(e.aviso) L.push(nombre + ': ' + e.aviso + '.');
      return;
    }
    let t = nombre + ': sin calibrar (' + (e.motivo||'') + ')';
    if(!q.hay_agregados) t += '; los genera ' + q.comando;
    L.push(t + '.');
    // Los motivos de descarte son claves de `cuota.py`; aquí, en palabras.
    const DESCARTE = {linea_corrupta:'línea corrupta', fuera_de_rango:'fuera de rango',
      delta_pequeno:'variación pequeña', sin_uso_local:'sin uso local', contaminado:'contaminado'};
    const desc = Object.entries(e.descartes||{}).filter(([,k])=>k)
      .map(([m,k]) => (DESCARTE[m] || String(m).replace(/_/g, ' ')) + ' ' + F.format(k));
    L.push(nombre + ': ' + plural(e.puntos||0, 'punto del statusline vigente', 'puntos del statusline vigentes')
      + ', ' + plural(e.puntos_rechazo||0, 'punto de rechazo', 'puntos de rechazo') + ' (solo comprobación)'
      + disp + '; descartes: ' + (desc.length ? desc.join(', ') : 'ninguno')
      + (e.deriva ? '; hubo deriva' : '') + (e.reinicio ? '; reiniciada a mano el ' + e.reinicio : '') + '.');
  });
  return L;
}

function textoImagenes(j){
  const i = j && j.imagenes;
  if(!i) return [];
  return [plural(i.n||0, 'imagen', 'imágenes') + ' · ' + F.format(i.bytes||0) + ' bytes leídos server-side · '
      + F.format(i.chars_devueltos||0) + ' caracteres devueltos a Claude',
    'Sin cifra de tokens de Claude: el log guarda bytes, no dimensiones. No entran en el contexto '
      + 'conservado ni en el equivalente a precio de API.'];
}

// Las líneas de texto van al diálogo de información, como párrafos; la primera del coste es el
// titular. En las tarjetas solo quedan cifras (un dashboard no lleva párrafos).
function parrafosHtml(L, lead){
  return L.map((x, i) => '<p' + (lead && i===0 ? ' class="lead"' : '') + '>' + escHooks(x) + '</p>').join('');
}

// Una cifra con la misma forma que los KPIs de arriba: etiqueta, valor en mono y una pista corta.
// `val` y `hint` llegan ya escapados o son cifras formateadas.
function kstat(lbl, val, hint, color){
  return '<div class="kstat"><div class="k-lbl">' + lbl + '</div>'
    + '<div class="k-val num"' + (color ? ' style="color:' + color + '"' : '') + '>' + val + '</div>'
    + (hint ? '<div class="k-hint">' + hint + '</div>' : '') + '</div>';
}

const VENTANAS = [['five_hour','Ventana de 5 h'], ['seven_day','Ventana semanal']];

// Ventanas calibradas: sin ninguna, la tarjeta de cuota no se pinta (su explicación vive en el
// diálogo). Calibrada sin cifra cuenta como calibrada: se pinta con «–».
function ventanasCalibradas(q){
  return q ? VENTANAS.filter(([t]) => q[t] && q[t].estado==='calibrado').length : 0;
}

// Medidor de una ventana: de 0 a la cota baja (A) en sólido y de A a la estimación (B) en claro,
// sobre una escala de 0 a 100 % de la ventana. Sin cifra no hay medidor.
// Ancho CSS con dos decimales, sin arrastrar el error de coma flotante de una resta.
function pct2(x){ return Math.round(x*100)/100; }

function medidorCuota(e, nombre){
  if(!e || e.estado!=='calibrado' || e.a_pct===null || e.a_pct===undefined){
    return kstat(nombre, '–', e && e.estado==='calibrado' ? 'calibrada, sin cifra' : 'sin calibrar');
  }
  const a = Math.max(0, Math.min(100, e.a_pct)), b = Math.max(a, Math.min(100, e.b_pct));
  return kstat(nombre, F1.format(e.a_pct) + ' – ' + F1.format(e.b_pct) + '<span class="unit">%</span>',
      'calibrada con ' + plural(e.puntos||0, 'punto', 'puntos'))
    + '<div class="qrange" role="img" aria-label="Entre ' + F1.format(e.a_pct) + ' % y '
    + F1.format(e.b_pct) + ' % de la ventana"><i class="qa" style="width:' + pct2(a) + '%"></i>'
    + '<i class="qb" style="left:' + pct2(a) + '%;width:' + pct2(b - a) + '%"></i></div>'
    + '<div class="qscale"><span>0 %</span><span>100 %</span></div>';
}

function renderCoste(s){
  const cc = document.getElementById('costeCard'), qc = document.getElementById('cuotaCard');
  const ic = document.getElementById('imagenesCard'), row = document.getElementById('cuotaImgRow');
  const c = s && s.coste;
  cc.style.display = c ? '' : 'none';
  if(c){
    document.getElementById('costeHead').textContent = c.cifra ? plural(c.eventos||0, 'delegación', 'delegaciones') : '';
    const filas = (c.desglose||[]).map(g => '<tr><td class="mono">' + escHooks(g.nombre) + '</td>'
      + '<td class="mono">' + escHooks(labelFor('thread', g.hilo)) + '</td>'
      + '<td class="mono">' + escHooks(labelFor('effort', g.esfuerzo)) + '</td>'
      + '<td class="num">' + F.format(g.casos) + '</td>'
      + '<td class="num">' + F.format(g.T) + '</td>'
      + celdasCoste(g) + '</tr>').join('');
    const cifras = c.cifra
      ? kstat('Cota baja', dolares(c.cifra.cota_baja), 'no es un ahorro: tarifa plana')
        + kstat('Estimación', '~' + dolares(c.cifra.estimacion), 'con relecturas de caché', 'var(--amber)')
        + (c.T !== undefined ? kstat('Tokens valorados', F.format(c.T) + '<span class="unit">tok</span>',
            'netos de Claude, con precio') : '')
      : kstat('Equivalente a precio de API', '–', escHooks('sin cifra: ' + (c.motivo||'')));
    document.getElementById('costeBody').innerHTML = '<div class="kstats">' + cifras + '</div>'
      + (filas ? '<div style="overflow-x:auto"><table><thead><tr><th>Modelo</th><th>Hilo</th>'
        + '<th>Esfuerzo</th><th>Casos</th><th>T (tokens)</th><th>Cota baja</th><th>Estimación</th>'
        + '</tr></thead><tbody>' + filas + '</tbody></table></div>' : '');
  }
  const q = s && s.cuota, cal = ventanasCalibradas(q);
  qc.style.display = cal ? '' : 'none';
  if(cal){
    document.getElementById('cuotaHead').textContent = plural(cal, 'ventana calibrada', 'ventanas calibradas');
    document.getElementById('cuotaBody').innerHTML = '<div class="kstats">'
      + VENTANAS.map(([t, nombre]) => '<div>' + medidorCuota(q[t], nombre) + '</div>').join('') + '</div>';
  }
  // Sin imágenes en el rango la tarjeta no se pinta, como «Quién delegó» sin clientes.
  const im = s && s.imagenes, hayImg = !!(im && im.n);
  ic.style.display = hayImg ? '' : 'none';
  if(hayImg){
    document.getElementById('imagenesBody').innerHTML = '<div class="kstats">'
      + kstat('Imágenes', F.format(im.n), 'delegaciones sin fallo')
      + kstat('Bytes leídos', F.format(im.bytes||0) + '<span class="unit">B</span>', 'leídos server-side')
      + kstat('Devuelto a Claude', F.format(im.chars_devueltos||0) + '<span class="unit">car.</span>', 'texto de la descripción')
      + '</div>';
  }
  // Una sola tarjeta visible ocupa la fila entera en vez de dejar medio hueco al lado.
  row.style.display = (cal || hayImg) ? '' : 'none';
  qc.style.gridColumn = hayImg ? '' : '1 / -1';
  ic.style.gridColumn = cal ? '' : '1 / -1';
  // El diálogo de información: el mismo texto que antes llenaba las tarjetas.
  document.getElementById('dlgCosteBody').innerHTML = c ? parrafosHtml(textoCoste(s), true) : '';
  document.getElementById('dlgCuotaBody').innerHTML = q ? parrafosHtml(textoCuota(s)) : '<p>Sin datos de cuota.</p>';
  document.getElementById('dlgImagenesBody').innerHTML = im ? parrafosHtml(textoImagenes(s)) : '<p>Sin imágenes en el rango.</p>';
}

// --- Sugerencias de los hooks: /api/hooks ---
//
// La tarjeta se ESCONDE si la telemetría no está activada, en vez de enseñar ceros. Un panel a
// cero se lee como «los hooks no sugieren nada», que es una conclusión falsa sacada de un fichero
// que no existe — y es exactamente el error que este panel no puede permitirse.
// La categoría sale de un fichero que escriben los hooks, no del propio panel: es el único texto
// de esta página cuyo contenido no controla el daemon. Escaparlo cuesta una línea.
function escHooks(s){
  return String(s==null?'':s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
}

function renderHooks(h){
  const card = document.getElementById('hooksCard');
  if(!h || !h.enabled || !h.total){ card.style.display='none'; return; }
  card.style.display='';

  const pct = F1.format(h.rate*100);
  document.getElementById('hooksHead').textContent =
    F.format(h.suggested) + ' de ' + F.format(h.total) + ' (' + pct + ' %)';

  const filas = (h.by_category||[]).map(c=>{
    const p = c.total ? (c.suggested/c.total*100) : 0;
    return `<tr><td class="mono" title="${escHooks(c.category)}">${escHooks(labelFor('hookCategory', c.category))}</td>`
      + `<td class="num">${F.format(c.suggested)}</td>`
      + `<td class="num" style="color:var(--tx2)">${F.format(c.total)}</td>`
      + `<td class="num" style="color:var(--amber)">${F1.format(p)} %</td></tr>`;
  }).join('');

  // Puntería del hook de lectura: de lo que vio, en qué avisó y por qué descartó el resto.
  // "sin registrar" son los eventos anteriores a que el hook escribiera el motivo; se muestran
  // aparte en vez de repartirlos, porque de esos no se sabe la razón.
  const motivos = (h.by_motivo||[]);
  const totalRead = h.read_total || 0;
  const punteria = !motivos.length ? '' :
    '<div style="overflow-x:auto;margin-top:4px"><table>'
    + '<thead><tr><th>Lecturas vistas</th><th>Eventos</th>'
    + '<th>Reparto</th></tr></thead><tbody>'
    + motivos.map(m=>{
        const p = totalRead ? (m.total/totalRead*100) : 0;
        return '<tr><td class="mono" title="' + escHooks(m.motivo) + '">' + escHooks(labelFor('hookReason', m.motivo)) + '</td>'
          + '<td class="num">' + F.format(m.total) + '</td>'
          + '<td class="num" style="color:var(--amber)">' + F1.format(p) + ' %</td></tr>';
      }).join('')
    + '</tbody></table></div>';

  document.getElementById('hooksBody').innerHTML =
    '<div style="overflow-x:auto"><table>'
    + '<thead><tr><th>Categoría</th><th>Sugeridas</th>'
    + '<th>Vistas</th><th>Tasa</th></tr></thead>'
    + '<tbody>' + filas + '</tbody></table></div>'
    + punteria;
}

// --- Backend local: /api/status (identidad, 1x/min) + /api/backend (estado y modelos, 2s) ---
// /api/status trae el catálogo, las tools y la versión; la lista de modelos y su estado salen del
// sondeo de 2 s de /api/backend (REQ-021), a través del estado visible (REQ-028).
async function fetchStatus(){
  try{
    const r = await fetch('/api/status'); const j = await r.json();
    state.status = j;
    if(j.version){ const v=document.getElementById('ver'); v.textContent='v'+j.version; v.style.display=''; }
    renderBackend(); renderTools();
  }catch(e){ /* el panel de backend es opcional: si falla, la web sigue funcionando */ }
  try{
    const sr = await fetch('/api/backend/stats'); renderBackendStats(await sr.json());
  }catch(e){ renderBackendStats(null); }
}

function roleLabels(model){
  return ((state.status||{}).catalog||[]).filter(c=>c.model===model).map(c=>c.label);
}

// Causas en las que ALGUIEN CONTESTA (REQ-014): el badge dice su etiqueta en ámbar, sin «caído».
// Las etiquetas y los detalles no se escriben aquí: llegan del daemon, redactados por fallos.py.
const CAUSAS_CONTESTA = {credencial:1, http_error:1, respuesta_invalida:1, sin_respuesta:1};
// Estados de /running y motivos de espera local, en palabras (REQ-022).
const PALABRAS_RUNNING = {ready:'listo', starting:'cargando', stopping:'descargando'};
const PALABRAS_ESPERA = {slot:'esperando plaza (máximo de llamadas a la vez)'};

// La espera de turno del daemon en palabras (REQ-008): una sola fuente para el title de la fila
// del modelo y para «En curso».
function turnWords(it){
  return 'esperando turno del daemon (en uso: '+((it.turn_in_use||[]).join(', ')||'nada')+')';
}

function vistaInicial(){
  return {estado:'comprobando', disponible:false, ref:null, bueno:null, fallos:0, ultimo:null};
}

// Estado VISIBLE del backend (REQ-028), lo que pintan el badge y las filas. Un sondeo bueno lo
// deja disponible al instante; un fallo tras uno bueno conserva lo que se pintaba (y el sondeo
// bueno como referencia de las filas); el SEGUNDO fallo seguido lo pasa a caído. Sin ningún
// sondeo bueno todavía, el primer fallo es «comprobando».
function estadoVisible(prev, bj){
  const UMBRAL = 2;   // fallos seguidos antes de «caído»
  const p = prev || vistaInicial();
  if(bj && bj.available) return {estado:'conectado', disponible:true, ref:bj, bueno:bj, fallos:0, ultimo:bj};
  const fallos = (p.fallos||0) + 1;
  if(fallos < UMBRAL && p.bueno)
    return {estado:'conectado', disponible:true, ref:p.bueno, bueno:p.bueno, fallos, ultimo:bj};
  if(fallos < UMBRAL)
    return {estado:'comprobando', disponible:false, ref:bj, bueno:null, fallos, ultimo:bj};
  return {estado:'caido', disponible:false, ref:bj, bueno:p.bueno, fallos, ultimo:bj};
}

// Badge del backend (REQ-014) a partir del estado visible: {texto, clase, title}.
function badgeBackend(vista, baseUrl){
  const v = vista || vistaInicial(), u = v.ultimo || {};
  if(v.estado==='conectado'){
    const aviso = v.fallos>0 ? ' · último sondeo: '+(u.detalle||u.etiqueta||'sin respuesta') : '';
    return {texto:'conectado', clase:'up', title:(baseUrl||'')+aviso};
  }
  if(v.estado==='comprobando') return {texto:'comprobando…', clase:'neutral', title:u.detalle||''};
  const et = u.etiqueta || u.causa || 'sin respuesta';
  if(CAUSAS_CONTESTA[u.causa]) return {texto:et, clase:'warn', title:u.detalle||''};
  return {texto:'caído · '+et, clase:'down', title:u.detalle||''};
}

// Clase de la chip de /v1/models (REQ-023): cualquier valor tiene chip; null o ausente, ninguna.
function chipEstado(status){
  if(status===null || status===undefined || status==='') return null;
  return (status==='loaded' || status==='unloaded') ? status : 'neutral';
}

// Filas de modelos (REQ-021): lo que expone el backend más el catálogo, ordenado por el primer rol
// que lo usa (mecánico, largo, código, visión) y después por id. Con y sin conexión, lo mismo.
function ordenModelos(ids, catalog){
  const cat = catalog || [], todos = [];
  (ids||[]).forEach(id=>{ if(id && !todos.includes(id)) todos.push(id); });
  cat.forEach(c=>{ if(c && c.model && !todos.includes(c.model)) todos.push(c.model); });
  const pos = id => { const k = cat.findIndex(c=>c && c.model===id); return k<0 ? cat.length : k; };
  return todos.sort((a,b)=> (pos(a)-pos(b)) || (a<b ? -1 : a>b ? 1 : 0));
}

// Texto de la fila de un modelo (tabla de REQ-022, en orden: gana la primera). «En vuelo» sale del
// último /api/inflight; running, status y running_ok, del sondeo de REFERENCIA del estado visible.
function estadoModelo(o){
  const vista = o.vista || vistaInicial(), ref = vista.ref || {}, disponible = !!vista.disponible;
  const llamadas = (o.inflight||[]).filter(it=>it && it.model===o.modelo);
  const enVuelo = llamadas.length>0;
  const esperaLocal = enVuelo && llamadas.every(it=>it.local_wait!==undefined && it.local_wait!==null);
  const run = (ref.running||[]).find(r=>r && r.model===o.modelo);
  const running = run ? (run.state||'ready') : null;
  const mod = (ref.models||[]).find(m=>m && m.id===o.modelo);
  const status = mod ? mod.status : null;
  const fila = (texto, title) => ({texto, title:title||'', atenuada:!disponible});
  if(!disponible && enVuelo) return fila('esperando al backend');
  if(!disponible) return fila('desconocido', 'sin conexión con el backend: '
    +(((vista.ultimo||{}).etiqueta) || 'comprobando…'));
  if(enVuelo && esperaLocal){
    // El motivo «turno» (daemon-reparte-el-backend, REQ-008) dice con qué modelos está ocupado el
    // turno, con sus propias palabras (sin el prefijo de las demás, que repetiría «esperando»).
    // Solo cambia el title: la fila sigue siendo la 3, como cualquier espera local.
    const motivos = [], turnParts = [];
    llamadas.forEach(it=>{
      const bucket = it.local_wait==='turn' ? turnParts : motivos;
      const m = it.local_wait==='turn' ? turnWords(it)
        : (PALABRAS_ESPERA[it.local_wait] || String(it.local_wait));
      if(!bucket.includes(m)) bucket.push(m); });
    const parts = motivos.length ? ['esperando dentro de local-delegate: '+motivos.join(', ')] : [];
    return fila('en cola local', parts.concat(turnParts).join('; '));
  }
  if(!ref.running_ok && enVuelo) return fila('en curso');
  if(!ref.running_ok) return fila(status==='loaded' ? 'montado' : 'frío');
  if(running==='starting') return fila('cargando');
  if(running==='ready' && enVuelo) return fila('procesando');
  if(running==='ready') return fila('montado');
  if(enVuelo){
    const lista = (ref.running||[]).filter(r=>r && r.model)
      .map(r=>r.model+' '+(PALABRAS_RUNNING[r.state||'ready'] || r.state));
    return fila('esperando turno', lista.length
      ? 'llama-swap aún no lo atiende; en /running: '+lista.join(', ')
      : 'llama-swap aún no lo atiende; /running está vacío');
  }
  if(running==='stopping') return fila('descargando');
  return fila('frío');
}

function renderBackend(){
  const st = state.status || {};
  const vista = state.vista || vistaInicial();
  const b = badgeBackend(vista, st.base_url);
  const pill = document.getElementById('backendPill');
  pill.className = 'pill '+b.clase;
  pill.textContent = b.texto;
  pill.title = b.title;
  // Dónde corre la INFERENCIA: loopback = esta máquina; cualquier otro host = GPU remota
  // (p. ej. esta Mac contra el llama-swap de la PC). El MCP y la lectura de 'path' son
  // siempre locales — esta insignia habla del cómputo, no de los archivos.
  const origin = state.backendOrigin || ((st.backend||{}).origin) || null;
  const host = state.backendHost || ((st.backend||{}).host) || '';
  const oPill = document.getElementById('originPill');
  if(oPill){
    if(origin){
      oPill.className = 'pill org '+origin;
      oPill.textContent = origin==='remote' ? 'cómputo remoto' : 'cómputo local';
      oPill.title = (origin==='remote'
        ? 'La inferencia corre en otra máquina: ' : 'La inferencia corre en esta máquina: ')+(host||st.base_url||'');
      oPill.style.display='';
    } else { oPill.style.display='none'; }
  }
  // Las filas salen del sondeo de REFERENCIA (el último bueno mientras se conserva «disponible»),
  // no del último: un fallo suelto no las toca (REQ-028).
  const ref = vista.ref || {};
  const ids = ordenModelos((ref.models||[]).map(m=>(typeof m==='string') ? m : (m&&m.id)), st.catalog);
  const statusById = {};
  (ref.models||[]).forEach(m=>{ if(m && m.id) statusById[m.id] = m.status; });
  const body = document.getElementById('modelsBody');
  if(!ids.length){
    body.innerHTML = '<div class="empty" style="padding:16px">'+(vista.disponible
      ? 'El backend no expone modelos ('+escHooks(st.base_url||'?')+').' : 'Consultando el backend…')+'</div>';
    return;
  }
  const PUNTO = {'montado':'ready', 'cargando':'starting', 'descargando':'starting',
    'esperando turno':'starting', 'en cola local':'starting', 'esperando al backend':'starting',
    'procesando':'busy', 'en curso':'busy'};
  body.innerHTML = ids.map(m=>{
    const e = estadoModelo({modelo:m, vista, inflight:state.inflight});
    const busy = !e.atenuada && (e.texto==='procesando' || e.texto==='en curso');
    const cls = (PUNTO[e.texto]||'') + (busy && PUNTO[e.texto]!=='busy' ? ' busy' : '');
    const roles = roleLabels(m).map(l=>`<span class="mrole">${l}</span>`).join('');
    const chip = chipEstado(statusById[m]);
    const badge = chip ? `<span class="mstatus ${chip}" title="${escHooks(statusById[m])}">${escHooks(labelFor('modelStatus', statusById[m]))}</span>` : '';
    const filaCls = (busy?' busy':'') + (e.atenuada?' atenuada':'');
    return `<div class="mrow${filaCls}"><span class="mdot ${cls}"></span><span class="mname">${escHooks(m)}</span>${roles}`
      + `<span class="mstate" title="${escHooks(e.title)}">${escHooks(humanLabel(e.texto))}</span>${badge}</div>`;
  }).join('');
}

// Lo que dice la tarjeta de métricas de llama-swap sin datos (REQ-020): la versión solo se culpa
// con un 404; con cualquier otra causa, su etiqueta corta.
function textoStats(j){
  if(j && j.status_http===404) return 'sin datos (este backend no expone /api/metrics/stats: requiere llama-swap ≥ v236)';
  if(j && j.etiqueta) return 'sin datos: '+j.etiqueta;
  return 'sin datos';
}

// #898: métricas de actividad que llama-swap persiste en SQLite (proxy /api/backend/stats).
function renderBackendStats(j){
  const el = document.getElementById('backendStats'); if(!el) return;
  const head = document.getElementById('bstatsHead');
  if(!j || !j.available || !j.stats){
    el.innerHTML = '<div class="empty" style="padding:12px" title="'+escHooks((j&&j.detalle)||'')+'">'
      + escHooks(textoStats(j))+'</div>';
    if(head) head.textContent=''; return;
  }
  const s = j.stats, gen = s.gen_histogram||{}, pr = s.prompt_histogram||{};
  const f1 = x => F1.format(x);   // sin dato, «–» (lo pone fmtNum)
  if(head) head.textContent = (s.total_requests!=null) ? ('· '+F.format(s.total_requests)+' '+(s.total_requests===1?'petición':'peticiones')) : '';
  el.innerHTML = `<div class="bstats">
    <div class="bstat"><div class="bk">Generación tok/s</div><div class="bv">${f1(gen.p50)}<span class="bp">p50</span></div><div class="bsub">p95 ${f1(gen.p95)}</div></div>
    <div class="bstat"><div class="bk">Entrada tok/s</div><div class="bv">${f1(pr.p50)}<span class="bp">p50</span></div><div class="bsub">p95 ${f1(pr.p95)}</div></div>
    <div class="bstat"><div class="bk">Tokens entrada/salida</div><div class="bv">${F.format(s.total_input_tokens||0)}/${F.format(s.total_output_tokens||0)}</div><div class="bsub">caché ${F.format(s.total_cache_tokens||0)}</div></div>
  </div>`;
}

function renderTools(){
  const tools = ((state.status||{}).tools)||[];
  const busyTools = new Set((state.inflight||[]).map(it=>it.tool));
  document.getElementById('toolsCount').textContent = tools.length?('('+tools.length+')'):'';
  document.getElementById('toolsBody').innerHTML = tools.length
    ? tools.map(t=>`<span class="tchip${busyTools.has(t.name)?' busy':''}" title="${(t.summary||'').replace(/"/g,'&quot;')}">${t.name}</span>`).join('')
    : '<span class="tchip">sin datos</span>';
}

// Sondeos de 2 s (REQ-026): /api/inflight y /api/backend van POR SEPARADO, cada uno con su guarda
// (como mucho una petición de cada uno en vuelo) y su siguiente vuelta programada 2 s después de
// que TERMINE la anterior. Así un /api/backend lento no congela «En curso», y una llamada manual
// (pestaña visible, «Refrescar») con otra en vuelo no lanza una segunda.
const SONDEO = {inflight:false, backend:false, tInflight:null, tBackend:null};

async function pollInflight(){
  if(document.visibilityState!=='visible' || SONDEO.inflight) return;
  SONDEO.inflight = true;
  try{
    const ij = await (await fetch('/api/inflight')).json();
    state.inflight = ij.inflight||[];
    const serverNow = Date.parse(ij.now), lastMs = ij.last_event_ts ? Date.parse(ij.last_event_ts) : 0;
    state.activity = {
      lastEventTs: ij.last_event_ts || null,
      lastEventMs: isFinite(lastMs) ? lastMs : 0,
      // desfase reloj-navegador vs reloj-servidor: si el equipo tiene la hora corrida, el
      // "hace N minutos" seguiría siendo correcto
      skewMs: isFinite(serverNow) ? (Date.now() - serverNow) : 0,
    };
    state.lastEvent = ij.last_event || null;
    renderBackend(); renderTools(); updateLive(); renderInflight();
  }catch(e){ /* el panel de inflight es opcional: si falla, la web sigue funcionando */ }
  finally{
    SONDEO.inflight = false;
    clearTimeout(SONDEO.tInflight); SONDEO.tInflight = setTimeout(pollInflight, 2000);
  }
}

async function pollBackend(){
  if(document.visibilityState!=='visible' || SONDEO.backend) return;
  SONDEO.backend = true;
  try{
    aplicarBackend(await (await fetch('/api/backend')).json());
  }catch(e){ /* si el daemon no contesta, no es un sondeo del backend: no cambia el estado */ }
  finally{
    SONDEO.backend = false;
    clearTimeout(SONDEO.tBackend); SONDEO.tBackend = setTimeout(pollBackend, 2000);
  }
}

// Un sondeo de /api/backend: deriva el estado visible y, si acaba de volver (de no disponible a
// disponible), refresca ya /api/status y /api/backend/stats sin esperar al ciclo de 60 s (REQ-027).
function aplicarBackend(bj){
  const prev = state.vista;
  state.vista = estadoVisible(prev, bj);
  if(bj && bj.origin) state.backendOrigin = bj.origin;
  if(bj && bj.host) state.backendHost = bj.host;
  if(prev && !prev.disponible && state.vista.disponible) fetchStatus();
  renderBackend();
}

function sondearAhora(){ pollInflight(); pollBackend(); }

// Pinta el panel "En curso". Se llama desde pollInflight (datos frescos, 2s) y desde updateLive
// (1s), para que el "hace Ns" de la última terminada suba suave sin pedir nada al servidor.
function renderInflight(){
  const body = document.getElementById('inflightBody');
  const head = document.getElementById('inflightHead');
  if(!body || !head) return;

  if(state.inflight.length){
    body.innerHTML = state.inflight.map(it=>{
      const chunk = it.chunks ? `<span class="chunkchip">Trozo ${it.chunk||1}/${it.chunks}</span>` : '';
      const org = it.backend ? `<span class="org ${it.backend}">${it.backend==='remote'?'remoto':'local'}</span>` : '';
      // Espera de turno del daemon (REQ-008): las mismas palabras que el title de la fila del modelo.
      const turnText = it.local_wait==='turn' ? turnWords(it) : '';
      const turnChip = turnText ? `<span class="chunkchip" title="${escHooks(turnText)}">${escHooks(turnText)}</span>` : '';
      return `<div class="ifrow"><span class="spin"></span><span class="badge">${it.tool}</span>
        <span class="badge model">${it.model}</span>${chunk}${turnChip}${org}
        <span class="num" style="color:var(--mut)">${escHooks(fmtSeg((it.elapsed_s||0)*1000))} · ${F.format(it.chars_in||0)} car.</span></div>`;
    }).join('');
    head.innerHTML = 'En curso <span class="num" style="color:var(--amber)">('+state.inflight.length+')</span>';
    return;
  }

  // Nada corriendo. Una delegación mecánica dura 2-4 s, así que este es el estado normal del
  // panel aunque el MCP acabe de trabajar: enseñar la última terminada evita que parezca que
  // no pasó nada. El desfase de reloj ya está medido en state.activity.skewMs.
  const ev = state.lastEvent;
  if(ev && ev.ts){
    const skew = (state.activity && state.activity.skewMs) || 0;
    const hace = Math.max(0, Math.round((Date.now() - skew - Date.parse(ev.ts))/1000));
    const org = ev.backend ? `<span class="org ${ev.backend}">${ev.backend==='remote'?'remoto':'local'}</span>` : '';
    const dur = ev.latency_ms!=null ? escHooks(fmtSeg(ev.latency_ms))+' · ' : '';
    const marca = ev.ok===false
      ? '<span class="num" style="color:var(--red)">✕</span>'
      : '<span class="num" style="color:var(--ok)">✓</span>';
    body.innerHTML = `<div class="ifrow" style="opacity:.75">${marca}
      <span class="num" style="color:var(--faint)">hace ${fmtHace(hace)}</span>
      <span class="badge">${ev.tool||'?'}</span>
      <span class="badge model">${ev.model||'?'}</span>${org}
      <span class="num" style="color:var(--mut)">${dur}${F.format(ev.chars_in||0)} car.</span></div>`;
  } else {
    body.innerHTML = '<div class="ifrow" style="color:var(--faint)">Sin delegaciones todavía</div>';
  }
  // REQ-024: lo que se pinta es la última terminada, no algo en curso.
  head.innerHTML = (ev && ev.ts) ? 'Última delegación' : 'En curso';
}

function fmtHace(s){
  if(s < 60) return s+'s';
  if(s < 3600) return Math.floor(s/60)+' min';
  if(s < 86400) return Math.floor(s/3600)+' h';
  return Math.floor(s/86400)+' d';
}

// --- Sistema: /api/system (RAM/VRAM + procesos, 5s) ---
// Lo que la tarjeta no puede medir aquí, como filas etiqueta/valor (REQ-025): con el backend en
// otra máquina, una fila «Backend» que enlaza a su panel; sin RAM ni VRAM, una fila con «—». La
// explicación va en el diálogo ⓘ de la tarjeta. Pura: la prueba node en test_panel_estados.py.
function systemRows(j){
  const plat = (j && j.platform) || '', remote = !!(j && j.origin==='remote');
  const procs = (j && j.processes) || [];
  const rows = [];
  if(remote){
    const host = String((j && j.host) || '').replace(/:\d+$/, '');
    const url = String((j && j.panel_url) || '');
    rows.push({label:'Backend', value: host || null, href: /^https?:\/\//.test(url) ? url : null});
  }
  if(!(j && (j.ram || j.vram))) rows.push({label:'RAM / VRAM', value:null, href:null});
  // Con el backend remoto sus procesos no están aquí: la sección se oculta si no hay ninguno.
  const listable = !plat || plat==='win32' || plat==='linux';
  if(!remote && !listable && !procs.length) rows.push({label:'Procesos', value:null, href:null});
  const showProcs = procs.length > 0 || (!remote && listable);
  return {rows, showProcs};
}
const EXT_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/></svg>';
function systemRowHTML(r){
  let val;
  if(r.value==null) val = '<span class="sysrow-val nodata">—</span>';
  else if(r.href) val = '<span class="sysrow-val"><a href="'+escHooks(r.href)+'" target="_blank" rel="noopener noreferrer"'
    + ' title="Abrir el panel de esa máquina">'+escHooks(r.value)+EXT_ICON+'</a></span>';
  else val = '<span class="sysrow-val">'+escHooks(r.value)+'</span>';
  return '<div class="sysrow"><span class="sysrow-lbl">'+escHooks(r.label)+'</span>'+val+'</div>';
}
function fmtMB(mb){ return mb>=1024 ? F1.format(mb/1024)+' GiB' : F.format(Math.round(mb))+' MiB'; }
// Una fila con barra de la tarjeta Sistema. `valTxt` vacío: la fila es solo un porcentaje (la carga
// de la GPU). `color` fija el color: la carga alta de la GPU es trabajo, no un aviso de memoria llena.
function meterHTML(lbl,valTxt,pct,color){
  const col = color || (pct>=88?'var(--danger)':pct>=70?'var(--amber)':'var(--acc)');
  const pctTxt = F.format(pct)+' %';
  return `<div class="meter-lbl"><span>${lbl}</span><span class="meter-val">${valTxt?'<b>'+valTxt+'</b> · '+pctTxt:'<b>'+pctTxt+'</b>'}</span></div>
    <div class="meter" style="--mc:${col}"><i style="width:${Math.min(100,pct)}%"></i></div>`;
}
async function pollSystem(){
  if(document.visibilityState!=='visible') return;
  try{
    const r = await fetch('/api/system'); const j = await r.json();
    let h = '';
    if(j.ram) h += meterHTML('RAM de sistema', F1.format(j.ram.used_gb)+' / '+F1.format(j.ram.total_gb)+' GiB', j.ram.pct);
    // Carga de la GPU (uso del procesador gráfico) y, debajo, VRAM (memoria llena). Sin GPU que
    // medir (otra plataforma, sin nvidia-smi) no hay `vram` y las dos filas se ocultan, como la RAM.
    if(j.vram && j.vram.gpu_util_pct!=null) h += meterHTML('Carga de la GPU', '', j.vram.gpu_util_pct, 'var(--violet)');
    if(j.vram) h += meterHTML('VRAM', F1.format(j.vram.used_mb/1024)+' / '+F1.format(j.vram.total_mb/1024)+' GiB', j.vram.pct);
    const sr = systemRows(j);
    document.getElementById('metersBody').innerHTML = h + sr.rows.map(systemRowHTML).join('');
    const procs = j.processes||[];
    const tbl = document.getElementById('procTable');
    document.getElementById('procSection').hidden = !sr.showProcs;
    if(!procs.length){
      // Estado vacío: `.empty` (mono), como los demás vacíos del panel.
      tbl.innerHTML = '<tbody><tr><td class="empty" style="padding:10px 8px;color:var(--faint);border:0">'
        + 'Ningún proceso del backend detectado.</td></tr></tbody>';
    }else{
      tbl.innerHTML = '<thead><tr><th>Proceso</th><th>PID</th><th>RAM</th><th>VRAM</th></tr></thead><tbody>'
        + procs.map(p=>`<tr><td class="mono">${p.name}${p.self?'<span class="selfchip">DAEMON MCP</span>':''}</td>
            <td class="mono">${p.pid}</td><td class="mono">${fmtMB(p.ram_mb||0)}</td>
            <td class="mono">${p.vram_mb!=null?fmtMB(p.vram_mb):'—'}</td></tr>`).join('')
        + '</tbody>';
    }
  }catch(e){ /* el panel de sistema es opcional: si falla, la web sigue funcionando */ }
}

// Estado de actividad. Antes se calculaba SOLO dentro de fetchData(), con el evento más
// reciente DEL RANGO elegido: con el auto-refresco apagado se congelaba, y con un rango
// pasado (o "Hoy" en UTC) mentía. Ahora se apoya en /api/inflight (delegaciones vivas +
// último evento de todo el histórico + hora del servidor) y lo repinta un tick de 1 s.
const IDLE_MIN = 30;   // minutos sin actividad para considerar reposo
function updateLive(){
  const live=document.getElementById('live'), txt=document.getElementById('liveTxt'), a=state.activity;
  const set=(cls,label,title)=>{ live.classList.toggle('stale',cls==='stale');
    live.classList.toggle('busy',cls==='busy'); txt.textContent=label; live.title=title; };
  if(state.inflight && state.inflight.length){
    const n=state.inflight.length;
    return set('busy','EN CURSO'+(n>1?' ('+n+')':''), plural(n,'delegación','delegaciones')+' ejecutándose ahora');
  }
  if(!a || !a.lastEventMs){ return set('stale','SIN DATOS','Todavía no hay ninguna delegación registrada'); }
  // el desfase entre el reloj del navegador y el del servidor se descuenta con a.skewMs
  const mins=(Date.now()-a.skewMs-a.lastEventMs)/6e4;
  if(mins>IDLE_MIN) return set('stale','EN REPOSO','Última delegación '+fmtLocalTs(a.lastEventTs)+' ('+Math.round(mins)+' min)');
  set('','EN VIVO','Última delegación '+fmtLocalTs(a.lastEventTs));
}

function kpiCard(o){
  const i = o.tip?`<span class="info" data-tip="${o.tip}">${ICON.info}</span>`:'';
  const ico = o.icon?`<span class="k-ico" style="--kc:${o.kc||'var(--mut)'}">${o.icon}</span>`:'';
  const unit = o.unit?`<span class="unit">${o.unit}</span>`:'';
  return `<div class="card ${o.hero?'hero':''}">${o.hero?'<div class="spark"><canvas id="spark"></canvas></div>':''}
    <div class="k-top">${ico}<div class="k-lbl" title="${o.lbl}"><span class="k-lbl-t">${o.lbl}</span>${i}</div></div>
    <div class="k-val num"><span class="k-num">${o.val}${unit}</span></div>
    <div class="k-hint">${o.hint||''}</div></div>`;
}

// Conversión a tokens de CLAUDE de lo ahorrado y lo devuelto. Espejo de `tokens_claude` en
// server.py y única conversión del panel: `acct` no divide por CPT para saved/returned/net.
// Aquí no se resuelve nada (coste-api-y-cuota, REQ-033): /api/events entrega cada fila ya
// fundida por Python, con `densidad[tipo] = [c100, origen]`. Imagen o sin densidad: 0; si no,
// cantidad×100/c100 redondeado hacia abajo, como la división entera de Python.
function tokensClaude(cantidad,tipo,e){
  if(tipo!=='text'&&tipo!=='returned'&&tipo!=='output'&&tipo!=='image') throw new Error('tipo de conversión desconocido: '+tipo);
  if(tipo==='image') return 0;
  const celda = e && e.densidad ? e.densidad[tipo] : null;
  if(!celda) return 0;
  return Math.floor(cantidad*100/celda[0]);
}

// Contabilidad de UN evento. Espejo exacto de `_accounting` en server.py: las series por día se
// agrupan en el navegador (dependen de tu zona horaria) y no pueden venir del servidor, así que la
// regla vive aquí también. `test_metrics.py` corre esta función con node y la compara con la de
// Python: si divergen, el gráfico contradiría a la tarjeta que tiene encima.
// Regla de contabilidad de la spec `panel-cuentas-y-estados-honestos`, letra a letra: un fallo
// (`ok` exactamente false) no ahorra, no devuelve, no se estima y no genera; el neto es bruto menos
// devuelto y puede ser negativo; lo ahorrado y lo devuelto pasan SOLO por `tokensClaude`.
function acct(e){
  const failed = e.ok===false;
  const ci = e.chars_in||0, co = e.chars_out||0;
  const calls = e.chunks || 1;            // `chunks` son LLAMADAS al backend; se omite cuando es 1
  const ti = e.tokens_in, to = e.tokens_out;
  const tiRep = ti!==undefined&&ti!==null, toRep = to!==undefined&&to!==null;
  // chars_in no siempre son caracteres: en local_describe_image son BYTES de la imagen
  const unit = e.input_unit || (e.tool==='local_describe_image' ? 'bytes' : 'chars');
  const estimable = unit==='chars';
  // Coste del modelo LOCAL (no pasa por tokensClaude). En un fallo, solo lo que reportó el backend.
  const tokensIn  = tiRep ? ti : (failed ? 0 : (estimable ? tok(ci) : 0));
  const tokensOut = toRep ? to : (failed ? 0 : tok(co));
  const estimated = failed ? false : (!tiRep || !toRep);
  const porPath = e.source==='path', aFichero = !!e.output_to_file;
  let charsSavedText = 0, bytesSavedImage = 0, charsSavedOutput = 0, charsReturned = 0;
  let saved = 0, returned = 0;
  if(!failed){
    if(porPath && estimable) charsSavedText = ci;
    if(porPath && !estimable) bytesSavedImage = ci;   // la imagen, en BYTES
    // La salida escrita a archivo no entró al contexto; el recibo no se registra (devuelto 0).
    if(aFichero) charsSavedOutput = co;
    const reclama = porPath && !aFichero && ((estimable && ci>0) || (!estimable && (ti||0)>0));
    if(reclama) charsReturned = co;
    if(porPath && estimable) saved += tokensClaude(charsSavedText,'text',e);
    if(porPath && !estimable) saved += tokensClaude(bytesSavedImage,'image',e);
    if(aFichero) saved += tokensClaude(charsSavedOutput,'output',e);
    returned = tokensClaude(charsReturned,'returned',e);
  }
  // F3: si respondio un respaldo y la causa. Un evento viejo, sin esos campos, da false y null.
  // T15 (REQ-016): la afinidad tambien lleva model_requested, pero no es un respaldo.
  const fallback = !!e.model_requested && e.routing !== 'affinity';
  const cause = e.error_class || e.fallback_class || null;
  const copia = v => (v===undefined ? null : v);
  return {calls:calls, tokensIn:tokensIn, tokensOut:tokensOut, saved:saved, returned:returned,
    net:saved-returned, estimated:estimated, fallback:fallback, cause:cause,
    charsSavedText:charsSavedText, bytesSavedImage:bytesSavedImage,
    charsSavedOutput:charsSavedOutput, charsReturned:charsReturned, failed:failed,
    tool:copia(e.tool), model:copia(e.model), source:copia(e.source), unit:unit};
}

function render(){
  // el rango temporal ya lo aplicó el servidor (/api/events?from=&to=)
  const ev = state.events;
  const s = state.stats||{}; const tt = s.total||{};
  const errs = tt.errors!==undefined ? tt.errors : ev.filter(e=>e.ok===false).length;
  const nEv  = tt.calls!==undefined ? tt.calls : ev.length;
  // Sin eventos no hay latencia media: «–», no «< 0,1 s».
  const lat = ev.length? ev.reduce((a,e)=>a+(e.latency_ms||0),0)/ev.length : null;
  const errPct = F1.format(nEv? 100*errs/nEv : 0);
  // REQ-004: el KPI es el NETO (bruto − devuelto), que puede ser negativo; la pista dice los dos.
  const saved = s.tokens_context_saved||0;
  const devuelto = s.tokens_returned||0;
  const neto = s.tokens_context_net||0;
  const gen = s.tokens_generated_local||0;
  const costIn = s.tokens_local_input||0;
  const bCalls = s.backend_calls||nEv;
  const estN = s.estimated_events||0;
  // Las llamadas de más salen de trocear o de un respaldo que respondió: las dos gastan backend.
  // El desglose va al tooltip del ⓘ: la pista de cada KPI es UNA línea corta (REQ de simetría).
  const extra = bCalls>nEv ? ' Desglose: +'+F.format(bCalls-nEv)+' por trocear o saltar' : '';
  const estTxt = estN ? ' En este rango: '+plural(estN,'estimado','estimados')+'.' : '';
  const fbN = s.fallback_events||0;
  const fbTxt = fbN ? (extra ? ', ' : ' Desglose: ')+F.format(fbN)+' con salto' : '';

  document.getElementById('kpis').innerHTML =
    kpiCard({hero:true,icon:ICON.save,kc:'var(--acc)',val:F.format(neto),unit:'tok',
       lbl:'Contexto conservado',
       hint:'bruto <span class="num">'+F.format(saved)+'</span> − devuelto <span class="num">'+F.format(devuelto)+'</span>',
       tip:'Neto: lo que el MCP leyó server-side (source=path) o escribió a un fichero y no viajó al contexto de Claude, menos lo que la tool devolvió a tu contexto. Se cuenta UNA vez por delegación aunque se trocee, y los fallos no suman. No descuenta relecturas: si luego lees tú el mismo fichero, eso no se resta.'})
    + kpiCard({icon:ICON.calls,kc:'var(--blue)',val:F.format(nEv),lbl:'Delegaciones',
       hint:'<span class="num">'+F.format(bCalls)+'</span> '+(bCalls===1?'llamada':'llamadas')+' al backend',
       tip:'Invocaciones a tools locales. Una delegación troceada gasta N llamadas al backend: por eso las dos cifras pueden no coincidir.'+extra+fbTxt+((extra||fbTxt)?'.':'')})
    + kpiCard({icon:ICON.gen,kc:'var(--violet)',val:F.format(gen),unit:'tok',lbl:'Generado',
       hint:'salida de los modelos locales',tip:'Tokens de salida que reportó el backend (usage.completion_tokens). Solo se estima con chars÷4 cuando el backend no los da.'+estTxt})
    + kpiCard({icon:ICON.cost,kc:'var(--amber)',val:F.format(costIn),unit:'tok',lbl:'Coste local',
       hint:'entrada leída por la GPU',
       tip:'Tokens de entrada que consumió de verdad el backend (usage.prompt_tokens), sumando TODAS las llamadas. Incluye el prompt de sistema repetido en cada trozo: por eso crece con el troceo y el contexto conservado no. Son tokens del modelo local, no de Claude.'})
    // La unidad va dentro del valor («116,9 s», «< 0,1 s»): `fmtSeg` decide la forma entera.
    + kpiCard({icon:ICON.lat,kc:'var(--mut)',val:escHooks(fmtSeg(lat)),lbl:'Latencia',
       hint:'con la carga del modelo',tip:'Promedio de latency_ms. La 1ª llamada a cada modelo paga la carga en VRAM vía llama-swap.'})
    + kpiCard({icon:ICON.err,kc:errs?'var(--danger)':'var(--acc)',val:errPct,unit:'%',lbl:'Errores',
       hint:'<span class="num">'+F.format(errs)+'</span> '+(errs===1?'fallo':'fallos'),tip:'Porcentaje de llamadas con ok=false.'});

  if(HAS_CHART){
    drawSpark(ev); drawTs(ev); drawToolDonut(ev); drawModelBar(ev); drawSrcDonut(ev);
  } else {
    document.querySelectorAll('.cbox').forEach(el=>{
      el.innerHTML='<div class="empty">Gráficos no disponibles: no se pudo cargar Chart.js (¿sin conexión?). El resto del panel funciona igual.</div>';
    });
  }
  drawActivity(ev);
  bindTips();
}

// Agrupado por día LOCAL: el ts del log es UTC, así que un evento de las 21:00 en UTC-5
// pertenece al día siguiente en UTC y caería en la barra equivocada si se cortara el string.
function byDay(ev){
  const m = new Map();
  ev.forEach(e=>{ const d=new Date(e.ts); if(!isFinite(d)) return;
    const k=localDayKey(d);
    const a=acct(e);
    const cur=m.get(k)||{net:0,calls:0,backendCalls:0};
    cur.net+=a.net; cur.calls++; cur.backendCalls+=a.calls; m.set(k,cur); });
  return [...m.entries()].sort((a,b)=>a[0]<b[0]?-1:1);
}

function fresh(id){ if(state.charts[id]) state.charts[id].destroy(); return document.getElementById(id); }

function drawSpark(ev){
  const el=document.getElementById('spark'); if(!el) return;
  if(state.charts.spark) state.charts.spark.destroy();
  // byDay ya devuelve el neto EN TOKENS (via acct): no se vuelve a dividir entre 4
  const days=byDay(ev); let acc=0; const data=days.map(([,v])=>{acc+=v.net;return acc;});
  // suggestedMin y no un mínimo fijo: el 0 sigue en el borde inferior mientras el acumulado sea
  // positivo, y un neto negativo se ve por debajo en vez de quedarse pegado al borde (REQ-004).
  const dmax=Math.max(1,...data);
  state.charts.spark = new Chart(el,{type:'line',
    data:{labels:days.map(d=>d[0]).length?days.map(d=>d[0]):[''],datasets:[{data:data.length?data:[0],
      borderColor:cssv('--acc'),borderWidth:2,pointRadius:0,tension:.4,fill:true,
      backgroundColor:c=>vGrad(c.chart,hexA(cssv('--acc'),0),hexA(cssv('--acc'),.32))}]},
    options:{responsive:true,maintainAspectRatio:false,animation:{duration:800},
      plugins:{legend:{display:false},tooltip:{enabled:false},centerText:false},
      scales:{x:{display:false},y:{display:false,suggestedMin:0,suggestedMax:dmax}}}});
}

function drawTs(ev){
  const days=byDay(ev);
  const acc=cssv('--acc'), blue=cssv('--blue'), grid=hexA(cssv('--bd'),.6), mut=cssv('--mut');
  state.charts.tsChart = new Chart(fresh('tsChart'),{
    data:{labels:days.map(d=>d[0]),datasets:[
      {type:'bar',label:'tokens netos',data:days.map(d=>d[1].net),order:2,
        backgroundColor:c=>vGrad(c.chart,hexA(acc,.35),acc),hoverBackgroundColor:cssv('--acc2'),
        borderRadius:6,maxBarThickness:46},
      {type:'line',label:'delegaciones',data:days.map(d=>d[1].calls),order:1,yAxisID:'y1',
        borderColor:blue,borderWidth:2,pointRadius:3,pointBackgroundColor:blue,
        pointBorderColor:cssv('--panel'),pointBorderWidth:1.5,tension:.35,fill:true,
        backgroundColor:c=>vGrad(c.chart,hexA(blue,0),hexA(blue,.14))}]},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
      plugins:{centerText:false,legend:{labels:{color:mut,boxWidth:9,boxHeight:9,usePointStyle:true,pointStyle:'rectRounded',padding:16,font:{size:11}}}},
      scales:{x:{ticks:{color:mut,font:{family:MONO,size:10}},grid:{display:false},border:{color:grid}},
        y:{ticks:{color:mut,font:{family:MONO,size:10}},grid:{color:grid},border:{display:false},beginAtZero:true},
        y1:{position:'right',beginAtZero:true,grid:{display:false},border:{display:false},
          ticks:{color:hexA(blue,.85),font:{family:MONO,size:10}}}}}});
}

// `opts.conNegativos`: conserva las categorías con total negativo (solo descarta las de 0). Sin la
// opción, como siempre: fuera las de 0 o menos (un donut no pinta porciones negativas).
function agg(ev,key,valfn,opts){
  const conNegativos = !!(opts && opts.conNegativos);
  const m=new Map(); ev.forEach(e=>m.set(e[key],(m.get(e[key])||0)+valfn(e)));
  return [...m.entries()].filter(x=>conNegativos ? x[1]!==0 : x[1]>0).sort((a,b)=>b[1]-a[1]);
}

// barras horizontales (mejor que un donut para comparar magnitudes)
function barH(id,pairs,unit,color){
  const el=fresh(id);
  if(!pairs.length){ return state.charts[id]=new Chart(el,{type:'bar',
    data:{labels:[''],datasets:[{data:[0],backgroundColor:cssv('--bd')}]},
    options:{responsive:true,maintainAspectRatio:false,indexAxis:'y',
      plugins:{legend:{display:false},centerText:false,tooltip:{enabled:false}},
      scales:{x:{display:false},y:{display:false}}}}); }
  const mut=cssv('--mut'), grid=hexA(cssv('--bd'),.6);
  return state.charts[id]=new Chart(el,{type:'bar',
    data:{labels:pairs.map(p=>p[0]),datasets:[{label:unit,data:pairs.map(p=>p[1]),
      backgroundColor:c=>hGrad(c.chart,hexA(color,.5),color),hoverBackgroundColor:color,
      borderRadius:6,maxBarThickness:30}]},
    options:{responsive:true,maintainAspectRatio:false,indexAxis:'y',
      plugins:{legend:{display:false},centerText:false,
        tooltip:{callbacks:{label:c=>' '+F.format(c.parsed.x)+' '+unit}}},
      scales:{x:{ticks:{color:mut,font:{family:MONO,size:10}},grid:{color:grid},border:{display:false},beginAtZero:true},
        y:{ticks:{color:cssv('--tx2'),font:{family:MONO,size:11}},grid:{display:false},border:{display:false}}}}});
}

// Neto por herramienta, de TODAS las fuentes (la salida a fichero también ahorra) y con signo:
// una herramienta que devuelve más de lo que ahorra sale a la izquierda del 0 (REQ-004).
function drawToolDonut(ev){ barH('toolDonut',agg(ev,'tool',e=>acct(e).net,{conNegativos:true}),'tok',cssv('--acc')); }
function drawModelBar(ev){ barH('modelBar',agg(ev,'model',()=>1),'llamadas',cssv('--violet')); }

// Local vs remoto: dónde corrió la INFERENCIA de cada delegación. Los eventos anteriores a
// que se registrara el campo salen como "n/d" en vez de asumirse locales.
function drawSrcDonut(ev){
  const pairs=agg(ev,'source',()=>1); const el=fresh('srcDonut');
  const total=pairs.reduce((a,p)=>a+p[1],0);
  const pathN=(pairs.find(p=>p[0]==='path')||[,0])[1];
  const pct=total?Math.round(100*pathN/total):0;
  const colFor=l=>l==='path'?cssv('--acc'):l==='inline'?cssv('--mut'):cssv('--blue');
  if(!pairs.length){ return state.charts.srcDonut=new Chart(el,{type:'doughnut',
    data:{labels:['sin datos'],datasets:[{data:[1],backgroundColor:[cssv('--bd')],borderWidth:0}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'70%',plugins:{legend:{display:false},centerText:false}}}); }
  state.charts.srcDonut=new Chart(el,{type:'doughnut',
    data:{labels:pairs.map(p=>labelFor('source', p[0])),datasets:[{data:pairs.map(p=>p[1]),
      backgroundColor:pairs.map(p=>colFor(p[0])),borderColor:cssv('--panel'),borderWidth:3,hoverOffset:6}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'70%',
      plugins:{centerText:{text:F.format(pct)+' %',sub:'por ruta',color:cssv('--acc')},
        legend:{position:'bottom',labels:{color:cssv('--mut'),boxWidth:9,boxHeight:9,usePointStyle:true,pointStyle:'circle',padding:14,font:{size:11}}},
        tooltip:{callbacks:{label:c=>' '+c.label+': '+F.format(c.parsed)+' llamadas'}}}}});
}

// Espera frente a lentitud (REQ-027). `slowMark` marca una llamada que generó por debajo de la
// velocidad normal de su modelo: «lento ×0,37». Sin `slow`, nada. Funciones puras: las corre node.
function slowMark(e){
  if(!e || e.slow!==true || e.pace_rel===null || e.pace_rel===undefined) return '';
  return 'lento ×' + fmtNum(e.pace_rel, 2);
}
// La espera (turno, plaza, cola de llama-swap, carga) y la inferencia, por separado. Sin
// `inference_ms` (backend sin `timings`), nada: no se inventa un reparto.
function waitInferenceText(e){
  if(!e || e.inference_ms===null || e.inference_ms===undefined) return '';
  return 'espera ' + fmtSeg(e.wait_ms) + ' · inferencia ' + fmtSeg(e.inference_ms);
}

function drawActivity(ev){
  document.getElementById('actCount').textContent=plural(ev.length,'llamada','llamadas');
  const pager=document.getElementById('pager');
  if(!ev.length){
    document.getElementById('activity').innerHTML='<tbody><tr><td class="empty">Sin actividad en el rango seleccionado.</td></tr></tbody>';
    pager.style.display='none'; return;
  }
  const pages=Math.max(1,Math.ceil(ev.length/PAGE));
  state.page=Math.min(Math.max(state.page,0),pages-1);
  const rows=ev.slice(state.page*PAGE,state.page*PAGE+PAGE);
  let h='<thead><tr><th>Hora</th><th>Tool</th><th>Modelo</th><th>Input</th><th>Cómputo</th><th>Chars in→out</th><th>Latencia</th><th>OK</th></tr></thead><tbody>';
  rows.forEach(e=>{ const time=fmtLocalTs(e.ts);   // hora LOCAL, el log guarda UTC
    const org=e.backend||'unknown';
    const orgTxt=org==='remote'?'Remoto':org==='local'?'Local':'Sin dato';   // = LABELS.origin
    // `chunks` del log son LLAMADAS al backend, no trozos: el título decía otra cosa que el dato
    const chunks=e.chunks?`<span class="chunkchip" title="Gastó ${e.chunks} llamadas al backend (troceado)">${e.chunks}×</span>`:'';
    // Hubo salto: respondió un respaldo. Se marca para que nadie lea esta fila como del modelo pedido.
    const fb=(e.model_requested && e.routing!=='affinity')?`<span class="chunkchip fbchip" title="Respondió ${e.model} en lugar de ${e.model_requested} (${e.fallback_reason||e.fallback_class||'sin causa'})">↪ ${e.model_requested}</span>`:'';
    const causa=(e.ok===false&&e.error_class)?` title="causa: ${e.error_class}"`:'';
    const split=waitInferenceText(e), slow=slowMark(e);
    const timings=split?`<div class="mut" style="font-size:10px">${escHooks(split)}</div>`:'';
    const slowChip=slow?`<span class="chunkchip slowchip" title="Generó a ${escHooks(fmtNum(e.tok_s,1))} tok/s, por debajo de la velocidad normal de ${e.model}">${escHooks(slow)}</span>`:'';
    h+=`<tr><td class="mono" title="${e.ts||''}">${time}</td><td><span class="badge">${e.tool}</span>${chunks}</td>
      <td><span class="badge model">${e.model}</span>${fb}</td>
      <td><span class="src ${e.source}">${e.source}</span></td>
      <td><span class="org ${org}" title="${e.backend_host||'sin dato'}">${orgTxt}</span></td>
      <td class="mono">${F.format(e.chars_in||0)} <span class="flow">→</span> ${F.format(e.chars_out||0)}</td>
      <td class="mono">${escHooks(fmtSeg(e.latency_ms))}${slowChip}${timings}</td>
      <td><span class="dot ${e.ok===false?'err':'ok'}"${causa}></span></td></tr>`; });
  document.getElementById('activity').innerHTML=h+'</tbody>';
  pager.style.display = pages>1?'':'none';
  document.getElementById('pgInfo').innerHTML='<b>'+(state.page+1)+'</b> / '+pages;
  document.getElementById('pgPrev').disabled = state.page===0;
  document.getElementById('pgNext').disabled = state.page>=pages-1;
}

// tooltips didácticos
const tt=document.getElementById('tt');
function bindTips(){
  document.querySelectorAll('[data-tip]').forEach(el=>{
    el.onmouseenter=()=>{ tt.textContent=el.dataset.tip; tt.style.opacity=1; tt.style.transform='translateY(0)';
      const r=el.getBoundingClientRect(); tt.style.left=Math.min(r.left,innerWidth-286)+'px'; tt.style.top=(r.bottom+9)+'px'; };
    el.onmouseleave=()=>{ tt.style.opacity=0; tt.style.transform='translateY(3px)'; };
  });
}

// controles
document.getElementById('range').onchange=e=>{
  state.range=e.target.value; state.page=0;
  const custom = state.range==='custom';
  document.getElementById('rangeFrom').style.display = custom?'':'none';
  document.getElementById('rangeTo').style.display = custom?'':'none';
  if(!custom) fetchData();
};
document.getElementById('rangeFrom').onchange=()=>{ if(state.range==='custom'){ state.page=0; fetchData(); } };
document.getElementById('rangeTo').onchange=()=>{ if(state.range==='custom'){ state.page=0; fetchData(); } };
document.getElementById('reload').onclick=()=>{ fetchData(); sondearAhora(); pollSystem(); fetchStatus(); };
document.getElementById('theme').onclick=()=>{
  const cur=document.documentElement.getAttribute('data-theme');
  const nx=cur==='dark'?'light':'dark'; document.documentElement.setAttribute('data-theme',nx);
  try{localStorage.setItem('ld-theme',nx);}catch(e){} applyDefaults(); render();
};
document.getElementById('auto').onclick=e=>{ state.auto=!state.auto; e.currentTarget.classList.toggle('on',state.auto); };
// Interruptor «Pruebas»: apagado por defecto (D2); se recuerda por navegador, como el tema.
function pintarTests(){
  const b = document.getElementById('tests');
  b.classList.toggle('on', state.tests); b.setAttribute('aria-pressed', String(state.tests));
}
try{ state.tests = localStorage.getItem('ld-tests') === '1'; }catch(e){ state.tests = false; }
pintarTests();
document.getElementById('tests').onclick=()=>{
  state.tests = !state.tests; pintarTests();
  try{ localStorage.setItem('ld-tests', state.tests ? '1' : '0'); }catch(e){}
  fetchData();
};
document.getElementById('pgPrev').onclick=()=>{ state.page--; drawActivity(state.events); };
document.getElementById('pgNext').onclick=()=>{ state.page++; drawActivity(state.events); };
const helpDlg=document.getElementById('helpDlg');
document.getElementById('help').onclick=()=>helpDlg.showModal();
document.getElementById('helpClose').onclick=()=>helpDlg.close();
helpDlg.addEventListener('click',e=>{ if(e.target===helpDlg) helpDlg.close(); });
// Diálogo de información de coste, cuota e imágenes. Cada ⓘ abre el mismo diálogo en su sección;
// Esc lo cierra (es un <dialog> modal) y el foco vuelve al botón que lo abrió.
const infoDlg=document.getElementById('infoDlg');
const INFO_GRUPOS = {
  coste:{titulo:'Coste, cuota e imágenes', icono:ICON.cost, color:'var(--amber)'},
  hooks:{titulo:'Sugerencias de los hooks', icono:ICON.info, color:'var(--amber)'},
  sistema:{titulo:'Sistema', icono:ICON.gen, color:'var(--amber)'},
  tests:{titulo:'Pruebas', icono:ICON.info, color:'var(--amber)'},
};
function openInfo(grupo, seccion){
  const g = INFO_GRUPOS[grupo] || INFO_GRUPOS.coste;
  document.getElementById('infoDlgTitle').textContent = g.titulo;
  const ico = document.getElementById('infoDlgIco'); ico.innerHTML = g.icono; ico.style.setProperty('--kc', g.color);
  infoDlg.querySelectorAll('section[data-group]').forEach(s => { s.hidden = s.dataset.group !== grupo; });
  infoDlg.showModal();
  const sec = seccion && document.getElementById(seccion);
  const primera = infoDlg.querySelector('section[data-group="' + grupo + '"]');
  if(sec && sec !== primera) sec.scrollIntoView({block:'start'}); else infoDlg.scrollTop = 0;
}
document.querySelectorAll('.ibtn[data-group]').forEach(b=>{
  b.innerHTML=ICON.info;
  b.onclick=()=>openInfo(b.dataset.group, b.dataset.section);
});
document.getElementById('infoDlgClose').onclick=()=>infoDlg.close();
infoDlg.addEventListener('click',e=>{ if(e.target===infoDlg) infoDlg.close(); });
try{const th=localStorage.getItem('ld-theme'); if(th) document.documentElement.setAttribute('data-theme',th);}catch(e){}
applyDefaults();
setInterval(()=>{ if(state.auto) fetchData(); },15000);
setInterval(pollSystem,5000);
setInterval(fetchStatus,60000);
// El indicador de actividad y el "hace Ns" del panel se repintan cada segundo aunque el
// auto-refresco esté apagado: "EN VIVO -> EN REPOSO" y "hace 8s -> hace 9s" son transiciones
// por PASO DEL TIEMPO, no por llegada de datos.
setInterval(()=>{ updateLive(); renderInflight(); },1000);
// Los sondeos se pausan con la pestaña oculta; al volver, refresca ya en vez de esperar al
// siguiente tick (antes se veía el estado congelado de hace horas).
document.addEventListener('visibilitychange',()=>{
  if(document.visibilityState==='visible'){ sondearAhora(); pollSystem(); if(state.auto) fetchData(); }
});
fetchData();
fetchStatus();
// Los sondeos de 2 s se encadenan solos (REQ-026): aquí solo se lanza la primera vuelta.
sondearAhora();
pollSystem();
</script>
</body>
</html>"""


if __name__ == "__main__":
    _port = int(os.environ.get("PORT") or os.environ.get("METRICS_PORT") or str(config.WEB_PORT))
    _reload = os.environ.get("METRICS_RELOAD") == "1"
    print(f"local-delegate metrics -> http://{config.WEB_HOST}:{_port}  (reload={_reload})")
    if _reload:
        uvicorn.run(
            "local_delegate.web.metrics:app",
            host=config.WEB_HOST,
            port=_port,
            reload=True,
            log_level="warning",
        )
    else:
        uvicorn.run(app, host=config.WEB_HOST, port=_port, log_level="warning")
