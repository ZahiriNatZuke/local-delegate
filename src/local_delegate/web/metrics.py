"""metrics.py — dashboard de uso/ahorro de local-delegate.

Lee los usage-YYYYMM.jsonl rotados por mes (+ el usage.jsonl legado si existe) y sirve:
  GET /               -> dashboard HTML (Chart.js por CDN; rango temporal server-side)
  GET /api/events     -> eventos en [from, to] (más recientes primero) + meta
  GET /api/stats      -> agregados JSON del mismo rango
  GET /api/inflight   -> delegaciones en curso EN ESTE PROCESO (ver limitación abajo)
  GET /api/backend    -> proxy best-effort de /running de llama-swap
  GET /api/status     -> versión del MCP, modelos del backend (/v1/models), catálogo y tools
  GET /api/system     -> RAM/VRAM de sistema + consumo por proceso (best-effort, ver sysinfo)
  GET /favicon.svg    -> icono de marca (chip) servido inline

`from`/`to` son ISO 8601 (fecha u datetime); sin parámetros, por defecto los últimos 30 días.
Solo se abren los archivos cuyo mes interseca el rango pedido — releer un rango de un mes no
recorre el histórico completo. Cache en memoria por archivo (mtime+size); solo el archivo del
mes actual cambia entre refrescos.

Limitación de /api/inflight: solo ve las llamadas en vuelo del PROCESO que sirve esta web (el
MCP que la arrancó). Si tienes varias instancias de Claude con su propio MCP, cada una sirve su
propia web y su propio /api/inflight — no hay estado compartido entre procesos.

Dos formas de arrancar:
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
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import httpx
import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .. import config, server
from . import sysinfo

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
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + (month == 12), (month % 12) + 1, 1, tzinfo=timezone.utc)
    return start, end


def _parse_ts(ts) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_range_param(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _resolve_range(from_: str | None, to_: str | None) -> tuple[datetime, datetime]:
    """Sin from/to -> últimos 30 días. Con solo uno de los dos, el otro se abre hasta el límite."""
    range_from = _parse_range_param(from_)
    range_to = _parse_range_param(to_)
    if range_from is None and range_to is None:
        range_to = datetime.now(timezone.utc)
        range_from = range_to - timedelta(days=30)
    elif range_to is None:
        range_to = datetime.now(timezone.utc)
    elif range_from is None:
        range_from = datetime(2000, 1, 1, tzinfo=timezone.utc)
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
        for r in file_rows:
            t = _parse_ts(r.get("ts"))
            if t is None or t < range_from or t > range_to:
                continue
            rows.append(r)
    return rows, files_read


def _aggregate(rows: list[dict]) -> dict:
    by_tool: dict[str, dict] = defaultdict(
        lambda: {
            "calls": 0,
            "chars_in": 0,
            "chars_out": 0,
            "latency_ms": 0,
            "errors": 0,
            "saved_chars": 0,
        }
    )
    by_model: dict[str, dict] = defaultdict(lambda: {"calls": 0, "chars_in": 0, "chars_out": 0})
    total = {"calls": 0, "chars_in": 0, "chars_out": 0, "errors": 0, "chars_in_path": 0}

    for r in rows:
        tool = str(r.get("tool", "?"))
        model = str(r.get("model", "?"))
        ci = int(r.get("chars_in", 0) or 0)
        co = int(r.get("chars_out", 0) or 0)
        lat = int(r.get("latency_ms", 0) or 0)
        ok = bool(r.get("ok", True))
        is_path = r.get("source") == "path"

        t = by_tool[tool]
        t["calls"] += 1
        t["chars_in"] += ci
        t["chars_out"] += co
        t["latency_ms"] += lat
        if not ok:
            t["errors"] += 1
        if is_path:
            t["saved_chars"] += ci
        m = by_model[model]
        m["calls"] += 1
        m["chars_in"] += ci
        m["chars_out"] += co

        total["calls"] += 1
        total["chars_in"] += ci
        total["chars_out"] += co
        if not ok:
            total["errors"] += 1
        if is_path:
            total["chars_in_path"] += ci

    tools = [
        {
            "tool": name,
            "calls": t["calls"],
            "chars_in": t["chars_in"],
            "chars_out": t["chars_out"],
            "errors": t["errors"],
            "tokens_saved": t["saved_chars"] // CHARS_PER_TOKEN,
            "avg_latency_ms": round(t["latency_ms"] / t["calls"]) if t["calls"] else 0,
        }
        for name, t in sorted(by_tool.items(), key=lambda kv: -kv[1]["saved_chars"])
    ]
    models = [
        {"model": n, **v} for n, v in sorted(by_model.items(), key=lambda kv: -kv[1]["calls"])
    ]

    return {
        "total": total,
        "tokens_context_saved": total["chars_in_path"] // CHARS_PER_TOKEN,
        "tokens_generated_local": total["chars_out"] // CHARS_PER_TOKEN,
        "by_tool": tools,
        "by_model": models,
    }


@app.get("/api/events")
def events(from_: str | None = Query(None, alias="from"), to: str | None = Query(None)):
    range_from, range_to = _resolve_range(from_, to)
    rows, files_read = _load(range_from, range_to)
    rows.reverse()  # más recientes primero
    return JSONResponse(
        {
            "meta": {
                "chars_per_token": CHARS_PER_TOKEN,
                "log_dir": str(config.LOG_DIR),
                "count": len(rows),
                "files_read": files_read,
                "range_from": range_from.isoformat(),
                "range_to": range_to.isoformat(),
            },
            "events": rows[:MAX_EVENTS],
        }
    )


@app.get("/api/stats")
def stats(from_: str | None = Query(None, alias="from"), to: str | None = Query(None)):
    range_from, range_to = _resolve_range(from_, to)
    rows, _files_read = _load(range_from, range_to)
    return JSONResponse(_aggregate(rows))


@app.get("/api/inflight")
def inflight():
    """Delegaciones en curso en ESTE proceso (ver limitación en el docstring del módulo)."""
    return JSONResponse({"inflight": server.inflight_snapshot()})


@app.get("/api/backend")
def backend():
    """Proxy best-effort de GET {base sin /v1}/running de llama-swap (timeout 1s)."""
    base = config.BASE_URL[: -len("/v1")] if config.BASE_URL.endswith("/v1") else config.BASE_URL
    try:
        with httpx.Client(timeout=1.0) as c:
            r = c.get(f"{base}/running")
            if not r.is_success:
                return JSONResponse({"available": False})
            data = r.json()
    except (httpx.HTTPError, ValueError):
        return JSONResponse({"available": False})
    running = data.get("running") if isinstance(data, dict) else None
    return JSONResponse({"available": True, "running": running or []})


@app.get("/api/status")
def status():
    """Identidad y disponibilidad: versión del MCP, modelos reales del backend, catálogo, tools.

    Los modelos salen de GET {BASE_URL}/models (lo que el backend de verdad expone), no del
    log de eventos — así el dashboard enseña también los modelos aún sin uso registrado.
    """
    backend_up = False
    model_ids: list[str] = []
    try:
        with httpx.Client(timeout=2.0) as c:
            r = c.get(f"{config.BASE_URL}/models")
            r.raise_for_status()
            model_ids = sorted(m.get("id", "?") for m in r.json().get("data", []))
            backend_up = True
    except (httpx.HTTPError, ValueError):
        pass
    catalog = [
        {"role": "mechanical", "label": "mecánico", "model": config.MODEL_MECHANICAL},
        {"role": "long", "label": "largo", "model": config.MODEL_LONG},
        {"role": "code", "label": "código", "model": config.MODEL_CODE},
        {"role": "fast", "label": "rápido", "model": config.MODEL_FAST},
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
            "backend": {"available": backend_up, "models": model_ids},
            "catalog": catalog,
            "tools": tools,
            "log_dir": str(config.LOG_DIR),
        }
    )


@app.get("/api/system")
def system():
    """RAM/VRAM de sistema y consumo por proceso del backend local (best-effort)."""
    return JSONResponse(
        {
            "ram": sysinfo.ram_stats(),
            "vram": sysinfo.vram_stats(),
            "processes": sysinfo.interesting_processes(),
        }
    )


# Icono de marca: un chip/CPU (cómputo local) en verde esmeralda con doble chevrón » de
# delegación en el núcleo. Solo 2 pines gruesos por lado y cuerpo al ~62% del viewBox:
# silueta simple que se lee nítida incluso a 16px de favicon.
FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="none">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#6ee7b7"/><stop offset="1" stop-color="#059669"/></linearGradient></defs>
<g stroke="#10b981" stroke-width="2.6" stroke-linecap="round">
<path d="M12 5.6V2.6"/><path d="M20 5.6V2.6"/>
<path d="M12 26.4v3"/><path d="M20 26.4v3"/>
<path d="M5.6 12H2.6"/><path d="M5.6 20H2.6"/>
<path d="M26.4 12h3"/><path d="M26.4 20h3"/></g>
<rect x="6" y="6" width="20" height="20" rx="6.5" fill="url(#g)"/>
<rect x="9" y="9" width="14" height="14" rx="4.4" fill="#0a0c11"/>
<path d="M11.4 11.4 16 16l-4.6 4.6" stroke="#6ee7b7" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M18.9 13.4 21.5 16l-2.6 2.6" stroke="#34d399" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" opacity=".65"/>
</svg>"""


@app.get("/favicon.svg")
def favicon():
    return Response(FAVICON, media_type="image/svg+xml")


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML


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
<meta name="description" content="Uso y ahorro de cuota de las delegaciones a modelos locales de local-delegate.">
<meta name="theme-color" content="#0a0c11">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
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
}
[data-theme=light]{
  --bg:#f6f8fc; --bg2:#eef2f8; --panel:#ffffff; --panel2:#f4f7fb; --bd:#e4e9f1; --bd2:#d4dbe6;
  --tx:#0e1526; --tx2:#33405a; --mut:#64748b; --faint:#94a3b8;
  --glow:rgba(5,150,105,.10);
  --shadow:0 1px 2px rgba(15,23,42,.06),0 12px 28px -10px rgba(15,23,42,.14);
  --shadow-h:0 1px 2px rgba(15,23,42,.08),0 20px 40px -12px rgba(15,23,42,.2);
}
*{box-sizing:border-box}
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
.live-dot{width:7px;height:7px;border-radius:50%;background:var(--acc);box-shadow:0 0 0 0 var(--acc);animation:pulse 2s infinite}
.live.stale .live-dot{background:var(--mut);animation:none}
@keyframes pulse{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--acc) 70%,transparent)}
  70%{box-shadow:0 0 0 6px transparent}100%{box-shadow:0 0 0 0 transparent}}
.controls{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.btn{background:var(--panel);border:1px solid var(--bd);color:var(--tx2);border-radius:10px;
  padding:8px 12px;font-size:13px;cursor:pointer;font-weight:600;font-family:var(--sans);
  display:inline-flex;align-items:center;gap:6px;transition:.14s}
.btn:hover{border-color:var(--bd2);color:var(--tx);background:var(--panel2)}
.btn.on{border-color:color-mix(in srgb,var(--acc) 55%,transparent);color:var(--acc);
  background:color-mix(in srgb,var(--acc) 10%,transparent)}
.btn.icon{padding:8px 9px}
.btn svg{width:16px;height:16px;display:block;flex:0 0 auto}
.ver{font-family:var(--mono);font-size:10px;font-weight:700;color:var(--acc);
  background:color-mix(in srgb,var(--acc) 10%,transparent);
  border:1px solid color-mix(in srgb,var(--acc) 30%,transparent);
  border-radius:6px;padding:2px 6px;margin-left:8px;vertical-align:2px;letter-spacing:.02em}
select.btn{appearance:none;padding-right:28px;
  background-image:linear-gradient(45deg,transparent 50%,var(--mut) 50%),linear-gradient(135deg,var(--mut) 50%,transparent 50%);
  background-position:calc(100% - 16px) 55%,calc(100% - 11px) 55%;background-size:5px 5px;background-repeat:no-repeat}

/* ---------- grid + cards ---------- */
.grid{display:grid;gap:16px}
.kpis{grid-template-columns:1.7fr 1fr 1fr 1fr 1fr}
@media(max-width:1040px){.kpis{grid-template-columns:1fr 1fr 1fr}}
@media(max-width:720px){.kpis{grid-template-columns:1fr 1fr}}
@media(max-width:460px){.kpis{grid-template-columns:1fr}}
.card{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--bd);
  border-radius:16px;padding:17px 18px;box-shadow:var(--shadow);transition:transform .16s,border-color .16s,box-shadow .16s}
.card:hover{border-color:var(--bd2)}
.chartcard:hover{transform:translateY(-2px);box-shadow:var(--shadow-h)}
.hero{position:relative;overflow:hidden;grid-row:span 1;
  background:
    radial-gradient(120% 140% at 100% 0,color-mix(in srgb,var(--acc) 20%,transparent),transparent 55%),
    linear-gradient(180deg,var(--panel),var(--panel2));
  border-color:color-mix(in srgb,var(--acc) 30%,var(--bd))}
.hero::after{content:"";position:absolute;inset:0;pointer-events:none;
  background:radial-gradient(80% 60% at 90% 10%,color-mix(in srgb,var(--acc) 10%,transparent),transparent 60%)}
.hero .spark{position:absolute;inset:auto 0 0 0;height:52px;opacity:.7;pointer-events:none}
.k-top{display:flex;align-items:center;gap:6px}
.k-ico{width:26px;height:26px;flex:0 0 auto;display:grid;place-items:center;border-radius:8px;
  background:color-mix(in srgb,var(--kc,var(--mut)) 15%,transparent);color:var(--kc,var(--mut))}
.k-ico svg{width:15px;height:15px}
.k-lbl{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.055em;font-weight:700}
.k-val{font-size:31px;font-weight:700;letter-spacing:-.02em;margin-top:12px;line-height:1;color:var(--tx)}
.hero .k-val{font-size:42px;color:var(--acc);position:relative;z-index:1;
  text-shadow:0 2px 20px color-mix(in srgb,var(--acc) 40%,transparent)}
.k-val .unit{font-size:15px;font-weight:600;color:var(--mut);margin-left:5px;letter-spacing:0}
.hero .k-val .unit{color:color-mix(in srgb,var(--acc) 75%,var(--mut))}
.k-hint{color:var(--mut);font-size:11.5px;margin-top:9px;position:relative;z-index:1;display:flex;align-items:center;gap:6px}
.k-hint .num{color:var(--tx2)}
.info{width:14px;height:14px;color:var(--faint);cursor:help;flex:0 0 auto;display:inline-flex;transition:.13s}
.info svg{width:100%;height:100%;display:block}
.info:hover{color:var(--tx2)}

.cols{grid-template-columns:1.5fr 1fr;margin-top:16px}
.cols2{grid-template-columns:1fr 1fr;margin-top:16px}
@media(max-width:880px){.cols,.cols2{grid-template-columns:1fr}}
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
td.mono,th.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.badge{display:inline-block;padding:3px 9px;border-radius:7px;font-size:11.5px;font-weight:600;font-family:var(--mono);
  background:color-mix(in srgb,var(--blue) 14%,transparent);color:var(--blue)}
.badge.model{background:color-mix(in srgb,var(--violet) 14%,transparent);color:var(--violet)}
.src{font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:6px;letter-spacing:.03em;text-transform:uppercase}
.src.path{background:color-mix(in srgb,var(--acc) 16%,transparent);color:var(--acc)}
.src.inline{background:color-mix(in srgb,var(--mut) 16%,transparent);color:var(--mut)}
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
.mrow{display:flex;align-items:center;gap:10px;padding:8px 2px;border-bottom:1px dashed color-mix(in srgb,var(--bd) 75%,transparent)}
.mrow:last-child{border-bottom:0}
.mdot{width:8px;height:8px;border-radius:50%;background:var(--faint);opacity:.55;flex:0 0 auto;transition:.2s}
.mdot.ready{background:var(--acc);opacity:1;box-shadow:0 0 8px color-mix(in srgb,var(--acc) 60%,transparent)}
.mdot.starting{background:var(--amber);opacity:1;box-shadow:0 0 8px color-mix(in srgb,var(--amber) 60%,transparent)}
.mname{font-family:var(--mono);font-size:12.5px;font-weight:600;color:var(--tx)}
.mrole{font-size:9.5px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;padding:2px 7px;border-radius:6px;
  background:color-mix(in srgb,var(--violet) 13%,transparent);color:var(--violet)}
.mstate{margin-left:auto;font-size:11px;color:var(--mut);font-family:var(--mono)}
.subh{font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);margin:14px 0 6px}
.toolchips{display:flex;flex-wrap:wrap;gap:6px}
.tchip{font-family:var(--mono);font-size:10.5px;color:var(--mut);border:1px solid var(--bd);border-radius:7px;padding:3px 8px;cursor:default;transition:.13s}
.tchip:hover{color:var(--acc);border-color:color-mix(in srgb,var(--acc) 40%,transparent)}
.ifrow{display:flex;align-items:center;gap:9px;padding:6px 2px;font-size:12.5px;color:var(--tx2)}
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
.proc{width:100%;border-collapse:collapse;font-size:12px}
.proc th,.proc td{padding:6px 8px;border-bottom:1px solid color-mix(in srgb,var(--bd) 75%,transparent);text-align:right;white-space:nowrap}
.proc th:first-child,.proc td:first-child{text-align:left}
.proc thead th{color:var(--faint);font-weight:700;font-size:10px;text-transform:uppercase;letter-spacing:.05em}
.proc tbody tr:last-child td{border-bottom:0}
.proc td{color:var(--tx2)}
.selfchip{font-size:9.5px;font-weight:700;padding:1.5px 6px;border-radius:5px;margin-left:6px;letter-spacing:.04em;
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

/* ---------- misc ---------- */
.empty{color:var(--mut);padding:30px;text-align:center;font-size:13px}
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
      <span class="mark">
        <svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
          <defs><linearGradient id="mg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#6ee7b7"/><stop offset="1" stop-color="#059669"/></linearGradient></defs>
          <g stroke="#10b981" stroke-width="2.6" stroke-linecap="round">
            <path d="M12 5.6V2.6"/><path d="M20 5.6V2.6"/>
            <path d="M12 26.4v3"/><path d="M20 26.4v3"/>
            <path d="M5.6 12H2.6"/><path d="M5.6 20H2.6"/>
            <path d="M26.4 12h3"/><path d="M26.4 20h3"/></g>
          <rect x="6" y="6" width="20" height="20" rx="6.5" fill="url(#mg)"/>
          <rect x="9" y="9" width="14" height="14" rx="4.4" fill="#0a0c11"/>
          <path d="M11.4 11.4 16 16l-4.6 4.6" stroke="#6ee7b7" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M18.9 13.4 21.5 16l-2.6 2.6" stroke="#34d399" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" opacity=".65"/>
        </svg>
      </span>
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
      <div class="panel-h"><h2>Backend local</h2><span id="backendPill" class="pill down">sin datos</span></div>
      <div id="modelsBody"><div class="empty" style="padding:16px">Consultando el backend…</div></div>
      <div class="subh" id="inflightHead">En curso</div>
      <div id="inflightBody"></div>
      <div class="subh">Tools MCP disponibles <span id="toolsCount" class="num" style="color:var(--tx2)"></span></div>
      <div class="toolchips" id="toolsBody"><span class="tchip">…</span></div>
    </div>
    <div class="card" style="--hc:var(--amber)">
      <div class="panel-h"><h2>Sistema</h2><span class="mut" id="gpuUtil"></span></div>
      <div id="metersBody"><div class="empty" style="padding:16px">Leyendo métricas…</div></div>
      <div class="subh">Procesos del backend</div>
      <div style="overflow-x:auto"><table class="proc" id="procTable"></table></div>
    </div>
  </div>

  <div class="grid kpis" id="kpis"></div>

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

  <div class="grid cols2">
    <div class="card chartcard" style="--hc:var(--violet)">
      <div class="panel-h"><h2>Llamadas por modelo</h2><span class="mut">llamadas</span></div>
      <div class="cbox donut"><canvas id="modelBar"></canvas></div>
    </div>
    <div class="card chartcard" style="--hc:var(--acc)">
      <div class="panel-h"><h2>Origen del input</h2><span class="mut">path = ahorro real</span></div>
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
    <p><b>Tokens de contexto conservados</b> = suma de los caracteres de entrada leídos <i>server-side</i>
    (llamadas con <span class="src path">path</span>) ÷ 4. Ese contenido lo leyó el MCP en tu máquina y
    <b>nunca entró a la ventana de contexto de Claude</b>: es cuota que no gastaste. Las llamadas
    <span class="src inline">inline</span> ya viajaron por tu contexto, así que no cuentan como ahorro.</p>
    <p><b>Tokens generados en local</b> = caracteres de salida ÷ 4: trabajo de generación que hicieron
    los modelos locales en vez de Claude.</p>
    <div class="frm">tokens ≈ caracteres ÷ 4 &nbsp;·&nbsp; ahorro real = solo llamadas con <b>source=path</b></div>
  </div>
</dialog>

<div class="tt" id="tt"></div>
<script>
const CPT = 4, F = new Intl.NumberFormat('es'), PAGE = 10;
const state = {events:[], range:'today', auto:true, charts:{},
  page:0, status:null, running:{}, backendUp:undefined};
const cssv = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const tok = c => Math.round(c/CPT);
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

// texto central en donuts
Chart.register({ id:'centerText',
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
  Chart.defaults.font.family=SANS; Chart.defaults.font.size=11;
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
  err:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.6 1.8 18a1.7 1.7 0 0 0 1.5 2.6h17.4A1.7 1.7 0 0 0 22.2 18L13.7 3.6a1.7 1.7 0 0 0-2.9 0z"/><path d="M12 9v4M12 17h.01"/></svg>',
  info:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 11.2V16"/><path d="M12 8h.01"/></svg>',
};

// Presets de rango -> {from, to} ISO. 'custom' lee los <input type=date>.
function computeRange(preset){
  const now = new Date();
  if(preset==='today'){
    const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
    return {from:start.toISOString(), to:now.toISOString()};
  }
  if(preset==='7') return {from:new Date(now-7*864e5).toISOString(), to:now.toISOString()};
  if(preset==='30') return {from:new Date(now-30*864e5).toISOString(), to:now.toISOString()};
  if(preset==='prev-month'){
    const y=now.getUTCFullYear(), m=now.getUTCMonth();
    const start=new Date(Date.UTC(y, m-1, 1)), end=new Date(Date.UTC(y, m, 1));
    return {from:start.toISOString(), to:end.toISOString()};
  }
  if(preset==='all') return {from:'2000-01-01T00:00:00Z', to:now.toISOString()};
  if(preset==='custom'){
    const f=document.getElementById('rangeFrom').value, t=document.getElementById('rangeTo').value;
    return {from:f?new Date(f+'T00:00:00Z').toISOString():null, to:t?new Date(t+'T23:59:59Z').toISOString():null};
  }
  return {from:null, to:null};
}

async function fetchData(){
  try{
    const {from, to} = computeRange(state.range);
    const qs = new URLSearchParams();
    if(from) qs.set('from', from);
    if(to) qs.set('to', to);
    const r = await fetch('/api/events?' + qs.toString()); const j = await r.json();
    state.events = j.events||[]; state.meta = j.meta||{};
    render(); updateLive();
    const cnt = F.format(state.meta.count||0);
    const filesN = (state.meta.files_read||[]).length;
    document.getElementById('foot').textContent =
      (state.meta.log_dir||'') + '   ·   ' + cnt + ' eventos   ·   ' + filesN + ' archivo(s) leído(s)   ·   ~' + CPT + ' chars/token   ·   local·delegate';
  }catch(e){
    document.getElementById('kpis').innerHTML='<div class="card empty">No se pudo leer <b>/api/events</b>. ¿El MCP está corriendo?</div>';
    document.getElementById('live').classList.add('stale');
    document.getElementById('liveTxt').textContent='SIN DATOS';
  }
}

// --- Backend local: /api/status (identidad, 1x/min) + /api/backend (montados, 2s) ---
async function fetchStatus(){
  try{
    const r = await fetch('/api/status'); const j = await r.json();
    state.status = j;
    if(j.version){ const v=document.getElementById('ver'); v.textContent='v'+j.version; v.style.display=''; }
    renderBackend(); renderTools();
  }catch(e){ /* el panel de backend es opcional: si falla, la web sigue funcionando */ }
}

function roleLabels(model){
  return ((state.status||{}).catalog||[]).filter(c=>c.model===model).map(c=>c.label);
}

function renderBackend(){
  const st = state.status; if(!st) return;
  const up = state.backendUp!==undefined ? state.backendUp : !!(st.backend&&st.backend.available);
  const pill = document.getElementById('backendPill');
  pill.className = 'pill '+(up?'up':'down');
  pill.textContent = up?'conectado':'caído';
  pill.title = st.base_url||'';
  const models = [...(((st.backend)||{}).models||[])];
  (st.catalog||[]).forEach(c=>{ if(!models.includes(c.model)) models.push(c.model); });
  const body = document.getElementById('modelsBody');
  if(!models.length){
    body.innerHTML = '<div class="empty" style="padding:16px">El backend no expone modelos ('+(st.base_url||'?')+').</div>';
    return;
  }
  body.innerHTML = models.map(m=>{
    const run = state.running[m];
    const cls = run==='ready'?'ready':(run?'starting':'');
    const stateTxt = run==='ready'?'montado':(run||'frío');
    const roles = roleLabels(m).map(l=>`<span class="mrole">${l}</span>`).join('');
    return `<div class="mrow"><span class="mdot ${cls}"></span><span class="mname">${m}</span>${roles}<span class="mstate">${stateTxt}</span></div>`;
  }).join('');
}

function renderTools(){
  const tools = ((state.status||{}).tools)||[];
  document.getElementById('toolsCount').textContent = tools.length?('('+tools.length+')'):'';
  document.getElementById('toolsBody').innerHTML = tools.length
    ? tools.map(t=>`<span class="tchip" title="${(t.summary||'').replace(/"/g,'&quot;')}">${t.name}</span>`).join('')
    : '<span class="tchip">sin datos</span>';
}

async function pollInflight(){
  if(document.visibilityState!=='visible') return;
  try{
    const [ir, br] = await Promise.all([fetch('/api/inflight'), fetch('/api/backend')]);
    const ij = await ir.json(), bj = await br.json();
    state.backendUp = !!bj.available;
    state.running = {};
    if(bj.available) (bj.running||[]).forEach(m=>{ if(m.model) state.running[m.model]=m.state||'ready'; });
    renderBackend();
    const items = ij.inflight||[];
    document.getElementById('inflightBody').innerHTML = items.length
      ? items.map(it=>`<div class="ifrow"><span class="spin"></span><span class="badge">${it.tool}</span>
          <span class="badge model">${it.model}</span>
          <span class="num" style="color:var(--mut)">${it.elapsed_s}s · ${F.format(it.chars_in||0)} chars</span></div>`).join('')
      : '<div class="ifrow" style="color:var(--faint)">Sin delegaciones en curso</div>';
  }catch(e){ /* el panel de inflight es opcional: si falla, la web sigue funcionando */ }
}

// --- Sistema: /api/system (RAM/VRAM + procesos, 5s) ---
function fmtMB(mb){ return mb>=1024 ? (mb/1024).toFixed(1)+' GiB' : F.format(Math.round(mb))+' MiB'; }
function meterHTML(lbl,valTxt,pct){
  const col = pct>=88?'var(--danger)':pct>=70?'var(--amber)':'var(--acc)';
  return `<div class="meter-lbl"><span>${lbl}</span><span class="meter-val"><b>${valTxt}</b> · ${pct}%</span></div>
    <div class="meter" style="--mc:${col}"><i style="width:${Math.min(100,pct)}%"></i></div>`;
}
async function pollSystem(){
  if(document.visibilityState!=='visible') return;
  try{
    const r = await fetch('/api/system'); const j = await r.json();
    let h = '';
    if(j.ram) h += meterHTML('RAM de sistema', j.ram.used_gb.toFixed(1)+' / '+j.ram.total_gb.toFixed(1)+' GiB', j.ram.pct);
    if(j.vram) h += meterHTML('VRAM', (j.vram.used_mb/1024).toFixed(1)+' / '+(j.vram.total_mb/1024).toFixed(1)+' GiB', j.vram.pct);
    document.getElementById('metersBody').innerHTML = h || '<div class="empty" style="padding:16px">Métricas de sistema no disponibles en esta plataforma.</div>';
    document.getElementById('gpuUtil').textContent = j.vram ? 'GPU '+j.vram.gpu_util_pct+'%' : '';
    const procs = j.processes||[];
    const tbl = document.getElementById('procTable');
    if(!procs.length){
      tbl.innerHTML='<tbody><tr><td style="color:var(--faint);border:0">Ningún proceso del backend detectado.</td></tr></tbody>';
    }else{
      tbl.innerHTML = '<thead><tr><th>Proceso</th><th>PID</th><th>RAM</th><th>VRAM</th></tr></thead><tbody>'
        + procs.map(p=>`<tr><td style="font-family:var(--mono)">${p.name}${p.self?'<span class="selfchip">MCP</span>':''}</td>
            <td class="mono">${p.pid}</td><td class="mono">${fmtMB(p.ram_mb||0)}</td>
            <td class="mono">${p.vram_mb!=null?fmtMB(p.vram_mb):'—'}</td></tr>`).join('')
        + '</tbody>';
    }
  }catch(e){ /* el panel de sistema es opcional: si falla, la web sigue funcionando */ }
}

function updateLive(){
  const live=document.getElementById('live'), txt=document.getElementById('liveTxt');
  if(!state.events.length){ live.classList.add('stale'); txt.textContent='SIN DATOS'; return; }
  const last=Date.parse(state.events[0].ts); const mins=isFinite(last)?(Date.now()-last)/6e4:1e9;
  if(mins>30){ live.classList.add('stale'); txt.textContent='EN REPOSO'; }
  else{ live.classList.remove('stale'); txt.textContent='EN VIVO'; }
}

function kpiCard(o){
  const i = o.tip?`<span class="info" data-tip="${o.tip}">${ICON.info}</span>`:'';
  const ico = o.icon?`<span class="k-ico" style="--kc:${o.kc||'var(--mut)'}">${o.icon}</span>`:'';
  const unit = o.unit?`<span class="unit">${o.unit}</span>`:'';
  return `<div class="card ${o.hero?'hero':''}">${o.hero?'<div class="spark"><canvas id="spark"></canvas></div>':''}
    <div class="k-top">${ico}<div class="k-lbl">${o.lbl} ${i}</div></div>
    <div class="k-val num">${o.val}${unit}</div>
    <div class="k-hint">${o.hint||''}</div></div>`;
}

function render(){
  // el rango temporal ya lo aplicó el servidor (/api/events?from=&to=)
  const ev = state.events;
  const savedChars = ev.filter(e=>e.source==='path').reduce((a,e)=>a+(e.chars_in||0),0);
  const genChars = ev.reduce((a,e)=>a+(e.chars_out||0),0);
  const errs = ev.filter(e=>!e.ok).length;
  const lat = ev.length? Math.round(ev.reduce((a,e)=>a+(e.latency_ms||0),0)/ev.length):0;
  const errPct = ev.length? (100*errs/ev.length).toFixed(1):'0.0';
  const pathCalls = ev.filter(e=>e.source==='path').length;

  document.getElementById('kpis').innerHTML =
    kpiCard({hero:true,icon:ICON.save,kc:'var(--acc)',val:'~'+F.format(tok(savedChars)),unit:'tok',
       lbl:'Contexto conservado',hint:'<span class="num">'+F.format(savedChars)+'</span> chars leídos server-side',
       tip:'Suma de chars_in de llamadas con source=path, ÷4. Contenido que el MCP leyó en tu máquina y nunca entró al contexto de Claude.'})
    + kpiCard({icon:ICON.calls,kc:'var(--blue)',val:F.format(ev.length),lbl:'Delegaciones',
       hint:'<span class="num">'+F.format(pathCalls)+'</span> con ahorro real',
       tip:'Número de invocaciones a tools locales en el rango seleccionado.'})
    + kpiCard({icon:ICON.gen,kc:'var(--violet)',val:'~'+F.format(tok(genChars)),unit:'tok',lbl:'Generado en local',
       hint:'salida de los modelos',tip:'Caracteres de salida ÷4: generación que hicieron los modelos locales en vez de Claude.'})
    + kpiCard({icon:ICON.lat,kc:'var(--amber)',val:F.format(lat),unit:'ms',lbl:'Latencia media',
       hint:'incluye carga de modelo',tip:'Promedio de latency_ms. La 1ª llamada a cada modelo paga la carga en VRAM vía llama-swap.'})
    + kpiCard({icon:ICON.err,kc:errs?'var(--danger)':'var(--acc)',val:errPct,unit:'%',lbl:'Tasa de error',
       hint:'<span class="num">'+F.format(errs)+'</span> fallos',tip:'Porcentaje de llamadas con ok=false.'});

  drawSpark(ev); drawTs(ev); drawToolDonut(ev); drawModelBar(ev); drawSrcDonut(ev); drawActivity(ev);
  bindTips();
}

function byDay(ev){
  const m = new Map();
  ev.forEach(e=>{ const d=(e.ts||'').slice(0,10); if(!d) return;
    const cur=m.get(d)||{saved:0,calls:0}; if(e.source==='path') cur.saved+=e.chars_in||0; cur.calls++; m.set(d,cur); });
  return [...m.entries()].sort((a,b)=>a[0]<b[0]?-1:1);
}

function fresh(id){ if(state.charts[id]) state.charts[id].destroy(); return document.getElementById(id); }

function drawSpark(ev){
  const el=document.getElementById('spark'); if(!el) return;
  if(state.charts.spark) state.charts.spark.destroy();
  const days=byDay(ev); let acc=0; const data=days.map(([,v])=>{acc+=tok(v.saved);return acc;});
  const dmax=Math.max(1,...data);  // ancla el 0 al borde inferior: sin ahorro la linea no cruza el texto
  state.charts.spark = new Chart(el,{type:'line',
    data:{labels:days.map(d=>d[0]).length?days.map(d=>d[0]):[''],datasets:[{data:data.length?data:[0],
      borderColor:cssv('--acc'),borderWidth:2,pointRadius:0,tension:.4,fill:true,
      backgroundColor:c=>vGrad(c.chart,hexA(cssv('--acc'),0),hexA(cssv('--acc'),.32))}]},
    options:{responsive:true,maintainAspectRatio:false,animation:{duration:800},
      plugins:{legend:{display:false},tooltip:{enabled:false},centerText:false},
      scales:{x:{display:false},y:{display:false,min:0,suggestedMax:dmax}}}});
}

function drawTs(ev){
  const days=byDay(ev);
  const acc=cssv('--acc'), blue=cssv('--blue'), grid=hexA(cssv('--bd'),.6), mut=cssv('--mut');
  state.charts.tsChart = new Chart(fresh('tsChart'),{
    data:{labels:days.map(d=>d[0]),datasets:[
      {type:'bar',label:'tokens ahorrados',data:days.map(d=>tok(d[1].saved)),order:2,
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

function agg(ev,key,valfn){
  const m=new Map(); ev.forEach(e=>m.set(e[key],(m.get(e[key])||0)+valfn(e)));
  return [...m.entries()].filter(x=>x[1]>0).sort((a,b)=>b[1]-a[1]);
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

function drawToolDonut(ev){ barH('toolDonut',agg(ev.filter(e=>e.source==='path'),'tool',e=>tok(e.chars_in||0)),'tok',cssv('--acc')); }
function drawModelBar(ev){ barH('modelBar',agg(ev,'model',()=>1),'llamadas',cssv('--violet')); }

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
    data:{labels:pairs.map(p=>p[0]),datasets:[{data:pairs.map(p=>p[1]),
      backgroundColor:pairs.map(p=>colFor(p[0])),borderColor:cssv('--panel'),borderWidth:3,hoverOffset:6}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'70%',
      plugins:{centerText:{text:pct+'%',sub:'path',color:cssv('--acc')},
        legend:{position:'bottom',labels:{color:cssv('--mut'),boxWidth:9,boxHeight:9,usePointStyle:true,pointStyle:'circle',padding:14,font:{size:11}}},
        tooltip:{callbacks:{label:c=>' '+c.label+': '+F.format(c.parsed)+' llamadas'}}}}});
}

function drawActivity(ev){
  document.getElementById('actCount').textContent=F.format(ev.length)+' llamadas';
  const pager=document.getElementById('pager');
  if(!ev.length){
    document.getElementById('activity').innerHTML='<tbody><tr><td class="empty">Sin actividad en el rango seleccionado.</td></tr></tbody>';
    pager.style.display='none'; return;
  }
  const pages=Math.max(1,Math.ceil(ev.length/PAGE));
  state.page=Math.min(Math.max(state.page,0),pages-1);
  const rows=ev.slice(state.page*PAGE,state.page*PAGE+PAGE);
  let h='<thead><tr><th>Hora</th><th>Tool</th><th>Modelo</th><th>Origen</th><th class="mono">Chars in→out</th><th class="mono">Latencia</th><th>OK</th></tr></thead><tbody>';
  rows.forEach(e=>{ const time=(e.ts||'').replace('T',' ').replace(/(\+.*|Z)$/,'').slice(5,16);
    h+=`<tr><td class="mono">${time}</td><td><span class="badge">${e.tool}</span></td>
      <td><span class="badge model">${e.model}</span></td>
      <td><span class="src ${e.source}">${e.source}</span></td>
      <td class="mono">${F.format(e.chars_in||0)} <span class="flow">→</span> ${F.format(e.chars_out||0)}</td>
      <td class="mono">${F.format(e.latency_ms||0)} ms</td>
      <td><span class="dot ${e.ok?'ok':'err'}"></span></td></tr>`; });
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
document.getElementById('reload').onclick=()=>{ fetchData(); pollInflight(); pollSystem(); fetchStatus(); };
document.getElementById('theme').onclick=()=>{
  const cur=document.documentElement.getAttribute('data-theme');
  const nx=cur==='dark'?'light':'dark'; document.documentElement.setAttribute('data-theme',nx);
  try{localStorage.setItem('ld-theme',nx);}catch(e){} applyDefaults(); render();
};
document.getElementById('auto').onclick=e=>{ state.auto=!state.auto; e.currentTarget.classList.toggle('on',state.auto); };
document.getElementById('pgPrev').onclick=()=>{ state.page--; drawActivity(state.events); };
document.getElementById('pgNext').onclick=()=>{ state.page++; drawActivity(state.events); };
const helpDlg=document.getElementById('helpDlg');
document.getElementById('help').onclick=()=>helpDlg.showModal();
document.getElementById('helpClose').onclick=()=>helpDlg.close();
helpDlg.addEventListener('click',e=>{ if(e.target===helpDlg) helpDlg.close(); });
try{const th=localStorage.getItem('ld-theme'); if(th) document.documentElement.setAttribute('data-theme',th);}catch(e){}
applyDefaults();
setInterval(()=>{ if(state.auto) fetchData(); },15000);
setInterval(pollInflight,2000);
setInterval(pollSystem,5000);
setInterval(fetchStatus,60000);
fetchData();
fetchStatus();
pollInflight();
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
