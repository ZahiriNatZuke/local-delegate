"""Cotejo de la tabla de precios contra el coste que calcula Claude Code (REQ-013/REQ-014).

Solo lectura. Lee las líneas `cost-state` de ~/.claude/projects y devuelve SOLO conteos: ni ids de
sesión, ni rutas, ni texto. Implementa la regla de REQ-013 y REQ-014 tal cual:

- fila = (sesión, startTime, modelo) de la ÚLTIMA línea `cost-state` de esa clave por posición en
  el fichero (el total de una clave nunca baja en orden de aparición: comprobado, 153 de 153);
- id normalizado: sin `[1m]` y sin sufijo de fecha `-AAAAMMDD`; búsqueda por id EXACTO;
- banda = [todo a 5 min, todo a 1 h] + búsqueda web, ± máx($0,005; 0,5 %);
- filas con costUSD < $0,05 no se juzgan.

Además corre los mutantes que cita la spec, sobre las mismas filas.

Uso: python -I cotejo.py [--precios precios.json]
"""

import argparse
import copy
import glob
import io
import json
import os
import re
import sys
from pathlib import Path

# Solo un TextIOWrapper sabe reconfigurarse; si la salida es otra cosa (un pytest que la
# captura, un StringIO) se deja como está.
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8")

aqui = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("--precios", default=os.path.join(aqui, "precios.json"))
a = ap.parse_args()
TABLA = json.loads(Path(a.precios).read_text(encoding="utf-8"))


def normaliza(mid):
    mid = mid.replace("[1m]", "")
    return re.sub(r"-\d{8}$", "", mid)


# ---------- filas ----------
R = os.path.expanduser("~/.claude/projects")
ultimas = {}  # (sesion, startTime) -> (orden, modelUsage)
orden = 0
for f in sorted(glob.glob(os.path.join(R, "**", "*.jsonl"), recursive=True)):
    with open(f, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"cost-state"' not in line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("type") != "cost-state":
                continue
            orden += 1
            ultimas[(r.get("sessionId"), r.get("startTime"))] = (orden, r.get("modelUsage") or {})

filas = []
for _, mu in ultimas.values():
    for mid, u in mu.items():
        filas.append((mid, u))


def juzga(tabla, filas):
    res = {
        "juzgadas": 0,
        "dentro": 0,
        "fuera": 0,
        "sin_precio": 0,
        "no_juzgadas": 0,
        "modelos_sin_precio": set(),
        "fuera_por_modelo": {},
    }
    for mid, u in filas:
        coste = u.get("costUSD") or 0.0
        if coste < 0.05:
            res["no_juzgadas"] += 1
            continue
        res["juzgadas"] += 1
        p = tabla["modelos"].get(normaliza(mid))
        if p is None:
            res["sin_precio"] += 1
            res["modelos_sin_precio"].add(normaliza(mid))
            continue
        base = (
            (u.get("inputTokens") or 0) * p["entrada"]
            + (u.get("cacheReadInputTokens") or 0) * p["lectura"]
            + (u.get("outputTokens") or 0) * p["salida"]
        ) / 1e6
        base += (u.get("webSearchRequests") or 0) * tabla["busqueda_web_por_1000"] / 1000
        cc = u.get("cacheCreationInputTokens") or 0
        lo, hi = base + cc * p["w5m"] / 1e6, base + cc * p["w1h"] / 1e6
        tol = max(0.005, 0.005 * coste)
        if lo - tol <= coste <= hi + tol:
            res["dentro"] += 1
        else:
            res["fuera"] += 1
            k = normaliza(mid)
            res["fuera_por_modelo"][k] = res["fuera_por_modelo"].get(k, 0) + 1
    res["modelos_sin_precio"] = sorted(res["modelos_sin_precio"])
    res["veredicto"] = "pasa" if res["fuera"] == 0 and res["sin_precio"] == 0 else "falla"
    return res


out = {
    "lineas_cost_state": orden,
    "claves_sesion": len(ultimas),
    "filas_modelo_sesion": len(filas),
    "real": juzga(TABLA, filas),
}

# sin búsqueda web (la regla del script viejo e10b.py, para explicar el 104/108)
t = copy.deepcopy(TABLA)
t["busqueda_web_por_1000"] = 0
out["real_sin_busqueda_web"] = {
    k: v
    for k, v in juzga(t, filas).items()
    if k in ("juzgadas", "dentro", "fuera", "fuera_por_modelo")
}

# ---------- mutantes ----------
mutantes = {}
t = copy.deepcopy(TABLA)
del t["modelos"]["claude-opus-5"]
mutantes["quitar claude-opus-5"] = t
for campo, f in [
    ("lectura", 0.8),
    ("lectura", 1.25),
    ("salida", 0.8),
    ("salida", 1.25),
    ("w5m", 1.25),
    ("w5m", 0.8),
    ("entrada", 1.25),
    ("w1h", 1.25),
    ("w1h", 0.8),
]:
    t = copy.deepcopy(TABLA)
    t["modelos"]["claude-opus-5-5"][campo] *= f
    mutantes[f"claude-opus-5-5 {campo} x{f}"] = t
out["mutantes"] = {}
for nombre, t in mutantes.items():
    r = juzga(t, filas)
    out["mutantes"][nombre] = {
        "fuera": r["fuera"],
        "sin_precio": r["sin_precio"],
        "veredicto": r["veredicto"],
    }
print(json.dumps(out, ensure_ascii=False, indent=1))
