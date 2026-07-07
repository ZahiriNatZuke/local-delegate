"""metrics.py — dashboard de uso/ahorro de local-delegate.

Lee usage.jsonl (una línea por llamada al MCP, escrita por server.py) y sirve:
  GET /             -> dashboard HTML (Chart.js por CDN; filtros y agregación client-side)
  GET /api/events   -> eventos crudos (más recientes primero) + meta
  GET /api/stats    -> agregados JSON (resumen rápido, compatibilidad)
  GET /favicon.svg  -> icono de marca (chip) servido inline

Dos formas de arrancar:
  1) Automática: el MCP (server.py) llama a run_in_thread() en un hilo daemon,
     de modo que la web vive y muere con el MCP. Si el puerto ya está ocupado
     (otra instancia de Claude), no monta una segunda.
  2) Manual: ``python -m local_delegate.web.metrics``  (127.0.0.1:9393 por defecto)

Solo LEE el JSONL; no interfiere con el MCP ni con el backend.
"""

from __future__ import annotations

import json
import os
import socket
from collections import defaultdict

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .. import config

USAGE_LOG = config.USAGE_LOG
CHARS_PER_TOKEN = config.CHARS_PER_TOKEN  # aproximación: tokens ~ chars / 4
MAX_EVENTS = 5000  # tope de eventos servidos al cliente

app = FastAPI(title="local-delegate metrics")


def _load() -> list[dict]:
    """Lee usage.jsonl tolerando líneas corruptas/parciales."""
    if not USAGE_LOG.is_file():
        return []
    rows: list[dict] = []
    with USAGE_LOG.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


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
def events():
    rows = _load()
    rows.reverse()  # más recientes primero
    return JSONResponse(
        {
            "meta": {"chars_per_token": CHARS_PER_TOKEN, "log": str(USAGE_LOG), "count": len(rows)},
            "events": rows[:MAX_EVENTS],
        }
    )


@app.get("/api/stats")
def stats():
    return JSONResponse(_aggregate(_load()))


# Icono de marca: un chip/CPU (cómputo local) en verde esmeralda. SVG escalable.
FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#6ee7b7"/><stop offset="1" stop-color="#059669"/></linearGradient></defs>
<rect x="6.4" y="6.4" width="11.2" height="11.2" rx="2.6" fill="url(#g)"/>
<rect x="9.6" y="9.6" width="4.8" height="4.8" rx="1.2" fill="#0a0c11"/>
<path d="M11 11.2l1.6 1.2-1.6 1.2" stroke="#6ee7b7" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
<g stroke="url(#g)" stroke-width="1.5" stroke-linecap="round">
<path d="M9 6.4V4"/><path d="M12 6.4V3.4"/><path d="M15 6.4V4"/>
<path d="M9 17.6V20"/><path d="M12 17.6V20.6"/><path d="M15 17.6V20"/>
<path d="M6.4 9H4"/><path d="M6.4 12H3.4"/><path d="M6.4 15H4"/>
<path d="M17.6 9H20"/><path d="M17.6 12H20.6"/><path d="M17.6 15H20"/></g></svg>"""


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
.btn.icon{padding:8px 10px}
select.btn{appearance:none;padding-right:28px;
  background-image:linear-gradient(45deg,transparent 50%,var(--mut) 50%),linear-gradient(135deg,var(--mut) 50%,transparent 50%);
  background-position:calc(100% - 16px) 55%,calc(100% - 11px) 55%;background-size:5px 5px;background-repeat:no-repeat}

/* ---------- filtros ---------- */
.filters{display:flex;flex-direction:column;gap:10px;margin-bottom:20px}
.frow{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.flabel{color:var(--faint);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;
  min-width:56px;flex:0 0 auto}
.chip{border:1px solid var(--bd);background:var(--panel);color:var(--mut);border-radius:999px;
  padding:5px 12px;font-size:12px;font-weight:600;cursor:pointer;user-select:none;transition:.13s;
  display:inline-flex;align-items:center;gap:7px}
.chip::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor;opacity:.35;transition:.13s}
.chip:hover{color:var(--tx2);border-color:var(--bd2)}
.chip.on{color:var(--tx)}
.chip.on::before{opacity:1}
.chip.on.tool{background:color-mix(in srgb,var(--blue) 13%,transparent);border-color:color-mix(in srgb,var(--blue) 42%,transparent);color:var(--blue)}
.chip.on.model{background:color-mix(in srgb,var(--violet) 13%,transparent);border-color:color-mix(in srgb,var(--violet) 42%,transparent);color:var(--violet)}

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
.info{width:15px;height:15px;border-radius:50%;border:1px solid var(--faint);color:var(--faint);
  font-size:9px;font-weight:800;display:inline-flex;align-items:center;justify-content:center;cursor:help;flex:0 0 auto}
.info:hover{border-color:var(--mut);color:var(--mut)}

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

/* ---------- misc ---------- */
.explain{margin-top:16px;font-size:13px;color:var(--mut)}
.explain summary{cursor:pointer;color:var(--tx);font-weight:700;font-size:13px;list-style:none;display:flex;align-items:center;gap:8px}
.explain summary::-webkit-details-marker{display:none}
.explain summary::before{content:"?";width:18px;height:18px;border-radius:50%;flex:0 0 auto;
  display:grid;place-items:center;font-size:11px;font-weight:800;background:color-mix(in srgb,var(--acc) 16%,transparent);color:var(--acc)}
.explain p{margin:12px 0 0;line-height:1.65;max-width:78ch}
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
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <defs><linearGradient id="mg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#6ee7b7"/><stop offset="1" stop-color="#059669"/></linearGradient></defs>
          <rect x="6.4" y="6.4" width="11.2" height="11.2" rx="2.6" fill="url(#mg)"/>
          <rect x="9.6" y="9.6" width="4.8" height="4.8" rx="1.2" fill="#0a0c11"/>
          <path d="M11 11.2l1.6 1.2-1.6 1.2" stroke="#6ee7b7" stroke-width="1" stroke-linecap="round" stroke-linejoin="round"/>
          <g stroke="url(#mg)" stroke-width="1.5" stroke-linecap="round">
            <path d="M9 6.4V4"/><path d="M12 6.4V3.4"/><path d="M15 6.4V4"/>
            <path d="M9 17.6V20"/><path d="M12 17.6V20.6"/><path d="M15 17.6V20"/>
            <path d="M6.4 9H4"/><path d="M6.4 12H3.4"/><path d="M6.4 15H4"/>
            <path d="M17.6 9H20"/><path d="M17.6 12H20.6"/><path d="M17.6 15H20"/></g>
        </svg>
      </span>
      <div class="brand-txt">
        <div class="brand-name">local<b>·</b>delegate</div>
        <div class="brand-sub">panel de ahorro</div>
      </div>
      <span class="live" id="live" title="Estado de los datos"><span class="live-dot"></span><span id="liveTxt">EN VIVO</span></span>
    </div>
    <div class="controls">
      <select id="range" class="btn" title="Rango temporal">
        <option value="all">Todo el histórico</option>
        <option value="1">Últimas 24 h</option>
        <option value="7">Últimos 7 días</option>
        <option value="30">Últimos 30 días</option>
      </select>
      <button id="auto" class="btn on" title="Auto-refresco cada 15 s">↻ Auto</button>
      <button id="reload" class="btn icon" title="Refrescar ahora" aria-label="Refrescar">⟳</button>
      <button id="theme" class="btn icon" title="Tema claro / oscuro" aria-label="Cambiar tema">◐</button>
    </div>
  </header>

  <div class="filters" id="filters"></div>

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
  </div>

  <details class="explain card">
    <summary>¿Cómo se calcula el ahorro?</summary>
    <p><b>Tokens de contexto conservados</b> = suma de los caracteres de entrada leídos <i>server-side</i>
    (llamadas con <span class="src path">path</span>) ÷ 4. Ese contenido lo leyó el MCP en tu máquina y
    <b>nunca entró a la ventana de contexto de Claude</b>: es cuota que no gastaste. Las llamadas
    <span class="src inline">inline</span> ya viajaron por tu contexto, así que no cuentan como ahorro.</p>
    <p><b>Tokens generados en local</b> = caracteres de salida ÷ 4: trabajo de generación que hicieron
    los modelos locales en vez de Claude. La aproximación es ~4 chars/token.</p>
  </details>

  <footer id="foot"></footer>
</div>

<div class="tt" id="tt"></div>
<script>
const CPT = 4, F = new Intl.NumberFormat('es');
const state = {events:[], tools:new Set(), models:new Set(), range:'all', auto:true, charts:{}};
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
  save:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.9 12a8.9 8.9 0 1 1-3.6-7.2"/><path d="M9 12l2.5 2.5L21 5"/></svg>',
  calls:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 3 14h7l-1 8 10-12h-7z"/></svg>',
  gen:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/><circle cx="12" cy="12" r="3.2"/></svg>',
  lat:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2.5M9 2h6"/></svg>',
  err:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.6 1.8 18a1.7 1.7 0 0 0 1.5 2.6h17.4A1.7 1.7 0 0 0 22.2 18L13.7 3.6a1.7 1.7 0 0 0-2.9 0z"/><path d="M12 9v4M12 17h.01"/></svg>',
};

async function fetchData(){
  try{
    const r = await fetch('/api/events'); const j = await r.json();
    state.events = j.events||[]; state.meta = j.meta||{};
    buildFilters(); render(); updateLive();
    const cnt = F.format(state.meta.count||0);
    document.getElementById('foot').textContent =
      (state.meta.log||'') + '   ·   ' + cnt + ' eventos   ·   ~' + CPT + ' chars/token   ·   local·delegate';
  }catch(e){
    document.getElementById('kpis').innerHTML='<div class="card empty">No se pudo leer <b>/api/events</b>. ¿El MCP está corriendo?</div>';
    document.getElementById('live').classList.add('stale');
    document.getElementById('liveTxt').textContent='SIN DATOS';
  }
}

function updateLive(){
  const live=document.getElementById('live'), txt=document.getElementById('liveTxt');
  if(!state.events.length){ live.classList.add('stale'); txt.textContent='SIN DATOS'; return; }
  const last=Date.parse(state.events[0].ts); const mins=isFinite(last)?(Date.now()-last)/6e4:1e9;
  if(mins>30){ live.classList.add('stale'); txt.textContent='EN REPOSO'; }
  else{ live.classList.remove('stale'); txt.textContent='EN VIVO'; }
}

function uniq(key){ return [...new Set(state.events.map(e=>e[key]))].filter(Boolean).sort(); }

function buildFilters(){
  if(state._built) return;
  const box = document.getElementById('filters');
  const mk = (val,cls) => `<span class="chip on ${cls}" data-${cls}="${val}">${val}</span>`;
  let h = '<div class="frow"><span class="flabel">Tools</span>';
  uniq('tool').forEach(t=>{ state.tools.add(t); h+=mk(t,'tool'); });
  h += '</div><div class="frow"><span class="flabel">Modelos</span>';
  uniq('model').forEach(m=>{ state.models.add(m); h+=mk(m,'model'); });
  h += '</div>';
  box.innerHTML = h;
  box.querySelectorAll('.chip').forEach(c=>c.addEventListener('click',()=>{
    const isTool = c.dataset.tool!==undefined;
    const set = isTool?state.tools:state.models; const v = isTool?c.dataset.tool:c.dataset.model;
    if(set.has(v)) set.delete(v); else set.add(v);
    c.classList.toggle('on'); render();
  }));
  state._built = true;
}

function filtered(){
  const now = Date.now();
  const days = state.range==='all'?null:parseInt(state.range,10);
  return state.events.filter(e=>{
    if(!state.tools.has(e.tool)) return false;
    if(!state.models.has(e.model)) return false;
    if(days){ const t = Date.parse(e.ts); if(isFinite(t) && (now-t) > days*864e5) return false; }
    return true;
  });
}

function kpiCard(o){
  const i = o.tip?`<span class="info" data-tip="${o.tip}">i</span>`:'';
  const ico = o.icon?`<span class="k-ico" style="--kc:${o.kc||'var(--mut)'}">${o.icon}</span>`:'';
  const unit = o.unit?`<span class="unit">${o.unit}</span>`:'';
  return `<div class="card ${o.hero?'hero':''}">${o.hero?'<div class="spark"><canvas id="spark"></canvas></div>':''}
    <div class="k-top">${ico}<div class="k-lbl">${o.lbl} ${i}</div></div>
    <div class="k-val num">${o.val}${unit}</div>
    <div class="k-hint">${o.hint||''}</div></div>`;
}

function render(){
  const ev = filtered();
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
       tip:'Número de invocaciones a tools locales en el rango y filtros activos.'})
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
  state.charts.spark = new Chart(el,{type:'line',
    data:{labels:days.map(d=>d[0]).length?days.map(d=>d[0]):[''],datasets:[{data:data.length?data:[0],
      borderColor:cssv('--acc'),borderWidth:2,pointRadius:0,tension:.4,fill:true,
      backgroundColor:c=>vGrad(c.chart,hexA(cssv('--acc'),0),hexA(cssv('--acc'),.32))}]},
    options:{responsive:true,maintainAspectRatio:false,animation:{duration:800},
      plugins:{legend:{display:false},tooltip:{enabled:false},centerText:false},
      scales:{x:{display:false},y:{display:false}}}});
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
  const rows=ev.slice(0,30);
  document.getElementById('actCount').textContent=F.format(ev.length)+' llamadas';
  if(!rows.length){ document.getElementById('activity').innerHTML='<tbody><tr><td class="empty">Sin datos para los filtros actuales.</td></tr></tbody>'; return; }
  let h='<thead><tr><th>Hora</th><th>Tool</th><th>Modelo</th><th>Origen</th><th class="mono">Chars in→out</th><th class="mono">Latencia</th><th>OK</th></tr></thead><tbody>';
  rows.forEach(e=>{ const time=(e.ts||'').replace('T',' ').replace(/(\+.*|Z)$/,'').slice(5,16);
    h+=`<tr><td class="mono">${time}</td><td><span class="badge">${e.tool}</span></td>
      <td><span class="badge model">${e.model}</span></td>
      <td><span class="src ${e.source}">${e.source}</span></td>
      <td class="mono">${F.format(e.chars_in||0)} <span class="flow">→</span> ${F.format(e.chars_out||0)}</td>
      <td class="mono">${F.format(e.latency_ms||0)} ms</td>
      <td><span class="dot ${e.ok?'ok':'err'}"></span></td></tr>`; });
  document.getElementById('activity').innerHTML=h+'</tbody>';
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
document.getElementById('range').onchange=e=>{state.range=e.target.value;render();};
document.getElementById('reload').onclick=fetchData;
document.getElementById('theme').onclick=()=>{
  const cur=document.documentElement.getAttribute('data-theme');
  const nx=cur==='dark'?'light':'dark'; document.documentElement.setAttribute('data-theme',nx);
  try{localStorage.setItem('ld-theme',nx);}catch(e){} applyDefaults(); render();
};
document.getElementById('auto').onclick=e=>{ state.auto=!state.auto; e.currentTarget.classList.toggle('on',state.auto); };
try{const th=localStorage.getItem('ld-theme'); if(th) document.documentElement.setAttribute('data-theme',th);}catch(e){}
applyDefaults();
setInterval(()=>{ if(state.auto) fetchData(); },15000);
fetchData();
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
