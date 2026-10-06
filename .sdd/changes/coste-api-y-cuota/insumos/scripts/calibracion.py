# ruff: noqa: SIM115, FURB162, RUF007  (script de evidencia desechable del SDD, no es producto)
"""Puntos de calibración de la cuota (REQ-051 a REQ-054) y estado según el criterio (REQ-055 y REQ-056).

Solo lectura. Lee los rechazos de cuota de ~/.claude/projects y el registro del statusline
~/.claude/cuota-statusline.jsonl. Devuelve SOLO agregados: por punto, tipo, inicio, fin, Δ%, Δ$,
C, fuente, marcas y descartes por motivo. Ningún id de sesión, ruta ni texto.

Uso: python -I calibracion.py [--hoy 2026-10-06T23:59:59+00:00] [--hasta 2026-10-06T15:00:30+00:00]
"""

import argparse
import collections
import datetime as dt
import glob
import json
import os
import re
import sys

aqui = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
sys.path.insert(0, aqui)
import criterio

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

ap = argparse.ArgumentParser()
ap.add_argument("--hoy", default=None)
ap.add_argument(
    "--hasta", default=None, help="corta los datos en esta hora (el registro crece en vivo)"
)
a = ap.parse_args()
HOY = dt.datetime.fromisoformat(a.hoy) if a.hoy else dt.datetime.now(dt.UTC)
HASTA = dt.datetime.fromisoformat(a.hasta) if a.hasta else None
PRECIOS = json.load(open(os.path.join(aqui, "precios.json"), encoding="utf-8"))["modelos"]
DUR = {"five_hour": dt.timedelta(hours=5), "seven_day": dt.timedelta(days=7)}
VIGENCIA = dt.timedelta(days=60)
DELTA_MIN = 10


def p_ts(s):
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
    except ValueError:
        return None


def normaliza(mid):
    return re.sub(r"-\d{8}$", "", (mid or "").replace("[1m]", ""))


# ---------- peticiones de los transcripts (para Δ$ de rechazos y para la contaminación) ----------
RAIZ = os.path.expanduser("~/.claude/projects")
peticiones = {}  # message.id -> (ts, sesion, coste o None)
rechazos = {}  # (tipo, resetsAt) -> primer ts de rechazo
for f in glob.glob(os.path.join(RAIZ, "**", "*.jsonl"), recursive=True):
    for line in open(f, encoding="utf-8", errors="replace"):
        if '"assistant"' not in line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("type") != "assistant":
            continue
        msg = r.get("message") or {}
        t = p_ts(r.get("timestamp"))
        if msg.get("model") == "<synthetic>":
            for q in (
                (r.get("quotaLimits") or [])
                if isinstance(r.get("quotaLimits"), list)
                else [r.get("quotaLimits") or {}]
            ):
                if (
                    isinstance(q, dict)
                    and q.get("status") == "rejected"
                    and q.get("rateLimitType") in DUR
                    and t
                ):
                    k = (q["rateLimitType"], q.get("resetsAt"))
                    rechazos[k] = min(t, rechazos.get(k, t))
            continue
        mid = msg.get("id") or r.get("requestId")
        if not mid or mid in peticiones or not t or (HASTA and t > HASTA):
            continue
        u = msg.get("usage") or {}
        p = PRECIOS.get(normaliza(msg.get("model")))
        coste = None
        if p:
            cc = u.get("cache_creation") or {}
            w5 = cc.get("ephemeral_5m_input_tokens")
            w1 = cc.get("ephemeral_1h_input_tokens")
            if w5 is None and w1 is None:
                w5, w1 = u.get("cache_creation_input_tokens") or 0, 0
            coste = (
                (u.get("input_tokens") or 0) * p["entrada"]
                + (w5 or 0) * p["w5m"]
                + (w1 or 0) * p["w1h"]
                + (u.get("cache_read_input_tokens") or 0) * p["lectura"]
                + (u.get("output_tokens") or 0) * p["salida"]
            ) / 1e6
        peticiones[mid] = (t, r.get("sessionId"), coste)

puntos, descartes = [], collections.Counter()

# ---------- REQ-051: un punto por (tipo, resetsAt) ----------
for (tipo, reset), primero in sorted(rechazos.items(), key=lambda x: str(x[0])):
    fin_v = dt.datetime.fromtimestamp(reset, dt.UTC)
    ini = fin_v - DUR[tipo]
    dentro = [c for (t, s, c) in peticiones.values() if ini <= t <= primero]
    sin_precio = sum(1 for c in dentro if c is None)
    dolar = sum(c for c in dentro if c is not None)
    puntos.append(
        {
            "fuente": "rechazo",
            "tipo": tipo,
            "inicio": ini.isoformat(),
            "fin": primero.isoformat(),
            "delta_pct": 100,
            "delta_usd": round(dolar, 2),
            "C": round(dolar, 2),
            "peticiones": len(dentro),
            "peticiones_sin_precio": sin_precio,
            "marcas": ["cota_baja", "solo_comprobacion"],
        }
    )

# ---------- REQ-052: un punto por (tipo, reset) del statusline ----------
F = os.path.expanduser("~/.claude/cuota-statusline.jsonl")
filas = []
if os.path.exists(F):
    for line in open(F, encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            descartes["linea_corrupta"] += 1
            continue
        t = p_ts(r.get("ts"))
        if t is None:
            descartes["sin_ts"] += 1
            continue
        if HASTA and t > HASTA:
            continue
        filas.append((t, r))
filas.sort(key=lambda x: x[0])
sesiones_registro = {r.get("session_id") for _, r in filas}
effort = collections.Counter(
    "con_effort" if r.get("effort") is not None else "sin_effort" for _, r in filas
)
for tipo, campo_reset in (("five_hour", "five_reset"), ("seven_day", "seven_reset")):
    grupos = collections.defaultdict(lambda: collections.defaultdict(list))
    for t, r in filas:
        v = r.get(tipo)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 100:
            descartes[f"{tipo}:pct_invalido"] += 1
            continue
        grupos[r.get(campo_reset)][r.get("session_id")].append((t, v, r.get("cost_usd")))
    for reset, por_sesion in grupos.items():
        # el par más ancho: primera y última fila de una misma sesión; desempate, la que empieza antes
        mejor = None
        for xs in por_sesion.values():
            d = xs[-1][1] - xs[0][1]
            if mejor is None or d > mejor[0] or (d == mejor[0] and xs[0][0] < mejor[1][0][0]):
                mejor = (d, xs)
        d, xs = mejor
        if d < DELTA_MIN:
            descartes[f"{tipo}:delta_pequeno"] += 1
            continue
        ta, tb = xs[0][0], xs[-1][0]
        dolar, reinicios = 0.0, 0
        for ys in por_sesion.values():
            for (t0, _, c0), (t1, _, c1) in zip(ys, ys[1:]):
                if (
                    not (ta < t1 <= tb)
                    or not isinstance(c1, (int, float))
                    or not isinstance(c0, (int, float))
                ):
                    continue
                if c1 >= c0:
                    dolar += c1 - c0
                else:
                    dolar += c1
                    reinicios += 1
        if dolar <= 0:
            descartes[f"{tipo}:sin_uso_local"] += 1
            continue
        ajenas = [
            c for (t, s, c) in peticiones.values() if ta < t <= tb and s not in sesiones_registro
        ]
        if ajenas:
            descartes[f"{tipo}:contaminado"] += 1
            puntos.append(
                {
                    "fuente": "statusline",
                    "tipo": tipo,
                    "inicio": ta.isoformat(),
                    "fin": tb.isoformat(),
                    "delta_pct": d,
                    "delta_usd": round(dolar, 2),
                    "C": round(dolar * 100 / d, 2),
                    "descartado": "contaminado",
                    "peticiones_ajenas": len(ajenas),
                    "usd_ajenas_precio_lista": round(sum(c for c in ajenas if c), 2),
                }
            )
            continue
        puntos.append(
            {
                "fuente": "statusline",
                "tipo": tipo,
                "inicio": ta.isoformat(),
                "fin": tb.isoformat(),
                "delta_pct": d,
                "delta_usd": round(dolar, 2),
                "C": round(dolar * 100 / d, 2),
                "marcas": ["cota_baja_si_hubo_otras_superficies"]
                + (["reinicio"] if reinicios else []),
            }
        )

# ---------- REQ-054/055: vigencia y criterio, por tipo ----------
estado = {}
for tipo in DUR:
    vig = [
        p
        for p in puntos
        if p["tipo"] == tipo
        and p["fuente"] == "statusline"
        and "descartado" not in p
        and HOY - dt.datetime.fromisoformat(p["fin"]) <= VIGENCIA
    ]
    vig.sort(key=lambda p: p["fin"])
    estado[tipo] = (
        criterio.evalua([p["C"] for p in vig])
        if vig
        else {"estado": "sin calibrar", "motivo": "faltan 3 puntos del statusline"}
    )
    estado[tipo]["puntos_statusline_vigentes"] = len(vig)
    estado[tipo]["puntos_rechazo"] = sum(
        1 for p in puntos if p["tipo"] == tipo and p["fuente"] == "rechazo"
    )
print(
    json.dumps(
        {
            "filas_statusline": len(filas),
            "sesiones_en_registro": len(sesiones_registro),
            "effort_en_registro": dict(effort),
            "puntos": puntos,
            "descartes": dict(descartes),
            "estado": estado,
        },
        ensure_ascii=False,
        indent=1,
    )
)
