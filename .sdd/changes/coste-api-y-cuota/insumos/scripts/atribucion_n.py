# ruff: noqa: SIM115, FURB162  (script de evidencia desechable del SDD, no es producto)
"""Atribución por delegación, N y coste equivalente (REQ-001 a REQ-008, REQ-031 y REQ-040 a REQ-048 de la spec).

Solo lectura. Lee el log de uso de local-delegate y los transcripts de ~/.claude/projects y
devuelve SOLO agregados: conteos, percentiles y sumas. Las rutas (`path`) se comparan en memoria
y se descartan; no se imprime ningún id de sesión, ruta ni texto.

Implementa las reglas de la spec tal cual:
- casamiento log -> `tool_use` (REQ-004): misma tool y `ts` del log en [tool_use − 1 s,
  tool_result + 2 s]; con varios candidatos, el ÚNICO desempate es `path` igual; si sigue sin
  quedar uno, «ambiguo».
- N y caducidades (REQ-043): ver `n_y_caducidades`.
- tokens de Claude (REQ-030 a REQ-032): densidad por familia de tokenizador y clase de contenido,
  formato `Read` si la entrada fue por `path`, con los dos respaldos ordenados.
- coste (REQ-041): cota baja = T·P_w(hilo); estimación = T·(P_w·(1+cad) + (N−cad)·P_r).

Uso: python -I atribucion_n.py [--desde 2026-09-06T00:00:00+00:00] [--hasta 2026-10-06T14:30:00+00:00]
La ventana por defecto deja fuera las pruebas con `claude -p` del 2026-10-06 desde las 14:30Z.
Reproducible mientras existan los transcripts: Claude Code los borra a los 30 días.
"""

import argparse
import collections
import datetime as dt
import glob
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

aqui = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("--desde", default="2026-09-06T00:00:00+00:00")
ap.add_argument("--hasta", default="2026-10-06T14:30:00+00:00")
a = ap.parse_args()
DESDE, HASTA = dt.datetime.fromisoformat(a.desde), dt.datetime.fromisoformat(a.hasta)
PRECIOS = json.load(open(os.path.join(aqui, "precios.json"), encoding="utf-8"))["modelos"]
DENS = json.load(open(os.path.join(aqui, "densidad.json"), encoding="utf-8"))["familias"]
PREF = "mcp__local-delegate__"
CLIENTES_EXCLUIDOS = {"codex-mcp-client": "no_es_claude", "mcp": "pruebas"}
RESPALDO = ("claude-opus-5-5", "subagente")


def p_ts(s):
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
    except ValueError:
        return None


def normaliza(mid):
    return re.sub(r"-\d{8}$", "", (mid or "").replace("[1m]", ""))


# ---------- clase de contenido (REQ-032): tool primero, luego extensión ----------
POR_TOOL = {"local_lint_summary": "log", "local_commit_msg": "diff", "local_explain_code": "codigo"}
POR_EXT = {}
for c, exts in {
    "prosa": ".md .markdown .txt .rst .html .htm",
    "codigo": ".py .js .mjs .cjs .ts .tsx .jsx .ps1 .psm1 .sh .bash .java .go .rs .c .h .cpp .cs .rb .php .css .scss .sql .kt .swift",
    "estructurado": ".json .jsonl .yaml .yml .toml .lock .csv .xml .ini",
    "log": ".log",
    "diff": ".diff .patch",
}.items():
    for e in exts.split():
        POR_EXT[e] = c


def clase(tool, path):
    if tool in POR_TOOL:
        return POR_TOOL[tool]
    ext = os.path.splitext(path or "")[1].lower()
    return POR_EXT.get(ext, "otro")


def clase_devuelto(tool):
    return {"local_extract": "estructurado", "local_boilerplate": "codigo"}.get(tool, "prosa")


def c100(familia, cl, numerado):
    """Densidad en centésimas, con los respaldos de REQ-031 en este orden:
    (1) la celda exacta; (2) la misma clase sin numerar; (3) la mayor densidad sin numerar de la
    familia (la que menos tokens da). Devuelve (valor, origen)."""
    f = DENS[familia]
    if numerado and cl in f["formato_read"]:
        return f["formato_read"][cl], "medida"
    if cl in f["sin_numerar"]:
        return f["sin_numerar"][cl], "medida" if not numerado else "sin_numerar"
    return max(f["sin_numerar"].values()), "conservadora"


def tokens_claude(chars, familia, cl, numerado):
    v, origen = c100(familia, cl, numerado)
    return chars * 100 // v, origen


# ---------- 1. log de uso ----------
L = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~/.local/share")), "local-delegate"
)
usos = []
for f in sorted(glob.glob(os.path.join(L, "usage-*.jsonl"))):
    for line in open(f, encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        t = p_ts(r.get("ts"))
        if t is None or not (DESDE <= t < HASTA):
            continue
        usos.append(
            {
                "ts": t,
                "tool": r.get("tool"),
                "client": r.get("client") or "<sin client>",
                "path": r.get("path"),
                "source": r.get("source"),
                "chars_in": r.get("chars_in") or 0,
                "chars_out": r.get("chars_out") or 0,
                "ok": r.get("ok"),
                "output_to_file": bool(r.get("output_to_file")),
            }
        )

# ---------- 2. transcripts ----------
RAIZ = os.path.expanduser("~/.claude/projects")
deleg, hilos = {}, {}
ficheros = glob.glob(os.path.join(RAIZ, "**", "*.jsonl"), recursive=True)
for f in ficheros:
    fn = f.replace(os.sep, "/")
    kind = "subagente" if "/subagents/" in fn else "principal"
    banco = "Temp" in fn.split("/projects/")[1].split("/")[0]
    reqs, compact = {}, []
    for line in open(f, encoding="utf-8", errors="replace"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        ty = r.get("type")
        if ty == "system" and r.get("subtype") == "compact_boundary":
            t = p_ts(r.get("timestamp"))
            if t:
                compact.append(t)
        elif ty == "assistant":
            msg = r.get("message") or {}
            if msg.get("model") == "<synthetic>":
                continue
            t = p_ts(r.get("timestamp"))
            mid = msg.get("id") or r.get("requestId")
            if mid and mid not in reqs and t:
                reqs[mid] = t
            for c in msg.get("content") or []:
                if (
                    isinstance(c, dict)
                    and c.get("type") == "tool_use"
                    and str(c.get("name", "")).startswith(PREF)
                ):
                    inp = c.get("input") if isinstance(c.get("input"), dict) else {}
                    deleg[c.get("id")] = {
                        "tool": c["name"][len(PREF) :],
                        "ts_use": t,
                        "ts_res": None,
                        "file": f,
                        "kind": kind,
                        "model": msg.get("model"),
                        "effort": r.get("effort"),
                        "path": inp.get("path"),
                        "banco": banco,
                        "mid": mid,
                    }
        elif ty == "user":
            cont = (r.get("message") or {}).get("content")
            if isinstance(cont, list):
                for c in cont:
                    if (
                        isinstance(c, dict)
                        and c.get("type") == "tool_result"
                        and c.get("tool_use_id") in deleg
                    ):
                        d = deleg[c["tool_use_id"]]
                        if d["ts_res"] is None:
                            d["ts_res"] = p_ts(r.get("timestamp"))
    hilos[f] = {"reqs": sorted(reqs.items(), key=lambda x: x[1]), "compact": sorted(compact)}


def n_y_caducidades(d):
    """REQ-043. Hilo = el fichero del transcript (principal o subagente). Petición = línea
    `assistant` no sintética, una por `message.id` (su primera aparición). t0 = el `tool_result`
    de la delegación (si falta, su `tool_use`). N = peticiones del hilo con ts > t0, sin contar la
    que lleva el `tool_use`, y anteriores al primer `compact_boundary` posterior a t0.
    Caducidad = hueco > TTL del hilo (300 s subagente, 3600 s principal) entre t0 y la primera
    petición posterior o entre dos posteriores seguidas."""
    h = hilos[d["file"]]
    t0 = d["ts_res"] or d["ts_use"]
    corte = next((c for c in h["compact"] if c > t0), None)
    post = [
        t for mid, t in h["reqs"] if t > t0 and (corte is None or t < corte) and mid != d["mid"]
    ]
    ttl = 300 if d["kind"] == "subagente" else 3600
    prev, cad = t0, 0
    for t in post:
        if (t - prev).total_seconds() > ttl:
            cad += 1
        prev = t
    return len(post), cad


# ---------- 3. casar ----------
por_tool = collections.defaultdict(list)
for tid, d in deleg.items():
    if d["ts_use"]:
        por_tool[d["tool"]].append(tid)
UN_S = dt.timedelta(seconds=1)
casado = {}
estados = collections.Counter()
por_cliente = collections.Counter()
for i, u in enumerate(usos):
    cands = []
    for tid in por_tool.get(u["tool"], []):
        d = deleg[tid]
        fin = d["ts_res"] or (d["ts_use"] + dt.timedelta(minutes=15))
        if d["ts_use"] - UN_S <= u["ts"] <= fin + 2 * UN_S:
            cands.append(tid)
    if len(cands) > 1:
        mismo = [
            t
            for t in cands
            if u["path"]
            and deleg[t]["path"]
            and os.path.normcase(os.path.normpath(deleg[t]["path"]))
            == os.path.normcase(os.path.normpath(u["path"]))
        ]
        estado = "unico_tras_path" if len(mismo) == 1 else "ambiguo"
        cands = mismo if len(mismo) == 1 else cands
    else:
        estado = "unico" if cands else "ninguno"
    estados[estado] += 1
    por_cliente[(u["client"], estado)] += 1
    if estado in ("unico", "unico_tras_path"):
        casado[i] = cands[0]


def pct(xs, q):
    """Percentil con interpolación lineal entre rangos (el de numpy por defecto)."""
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


cc = sum(v for (c, e), v in por_cliente.items() if c == "claude-code")
cc_unico = sum(
    v
    for (c, e), v in por_cliente.items()
    if c == "claude-code" and e in ("unico", "unico_tras_path")
)
out = {
    "ventana": [a.desde, a.hasta],
    "lineas_log": len(usos),
    "transcripts": len(ficheros),
    "casamiento": dict(estados),
    "casamiento_por_cliente": {f"{c} | {e}": v for (c, e), v in sorted(por_cliente.items())},
    "claude_code_unico_%": round(100 * cc_unico / cc, 1) if cc else None,
}

# ---------- 4. eventos de texto por path que cuentan (regla del hermano) ----------
cobertura = collections.Counter()
eventos = []
for i, u in enumerate(usos):
    if u["ok"] is False or u["output_to_file"] or u["tool"] == "local_describe_image":
        continue
    if not (u["source"] == "path" or (u["source"] is None and u["path"])):
        continue
    if u["client"] in CLIENTES_EXCLUIDOS:
        cobertura["excluido:" + CLIENTES_EXCLUIDOS[u["client"]]] += 1
        continue
    tid = casado.get(i)
    if tid and deleg[tid]["banco"]:
        cobertura["excluido:pruebas"] += 1
        continue
    if tid:
        d = deleg[tid]
        n, cad = n_y_caducidades(d)
        modelo, hilo, src = normaliza(d["model"]), d["kind"], "relleno"
    else:
        modelo, hilo, src = RESPALDO[0], RESPALDO[1], "supuesto"
        n, cad = None, 0
    cobertura[src] += 1
    eventos.append(
        {
            "u": u,
            "modelo": modelo,
            "hilo": hilo,
            "n": n,
            "cad": cad,
            "src": src,
            "effort": deleg[tid]["effort"] if tid else None,
        }
    )
out["cobertura_eventos_texto_path"] = dict(cobertura)

# N por grupo (modelo, hilo) y declarado por hilo, solo con casos atribuidos
grupos = collections.defaultdict(list)
for e in eventos:
    if e["n"] is not None:
        grupos[(e["modelo"], e["hilo"])].append(e["n"])
out["N_por_grupo"] = {
    f"{m} | {h}": {
        "casos": len(v),
        "p10": pct(v, 0.1),
        "p25": pct(v, 0.25),
        "mediana": pct(v, 0.5),
        "p75": pct(v, 0.75),
        "p90": pct(v, 0.9),
    }
    for (m, h), v in sorted(grupos.items())
}
por_hilo = collections.defaultdict(list)
for (m, h), v in grupos.items():
    por_hilo[h] += v
N_DECL = {h: pct(v, 0.5) for h, v in por_hilo.items()}
out["N_declarado_por_hilo (mediana)"] = {h: [N_DECL[h], len(por_hilo[h])] for h in por_hilo}
out["esfuerzo_de_los_atribuidos"] = dict(
    collections.Counter(str(e["effort"]) for e in eventos if e["src"] == "relleno")
)

# ---------- 5. coste ----------
esc = collections.Counter()
origen_dens = collections.Counter()
sin_precio = collections.Counter()
for e in eventos:
    u = e["u"]
    p = PRECIOS.get(e["modelo"])
    familia = p["familia"] if p else "nueva"
    t_in, o1 = tokens_claude(u["chars_in"], familia, clase(u["tool"], u["path"]), True)
    t_out, _ = tokens_claude(u["chars_out"], familia, clase_devuelto(u["tool"]), False)
    origen_dens[o1] += 1
    T = (t_in - t_out) / 1e6  # MTok netos de Claude
    esc["MTok_netos_densidad"] += T
    esc["MTok_netos_chars4"] += (u["chars_in"] // 4 - u["chars_out"] // 4) / 1e6
    if not p:
        sin_precio[e["modelo"]] += 1
        continue
    pw = p["w5m"] if e["hilo"] == "subagente" else p["w1h"]
    n = e["n"] if e["n"] is not None else N_DECL.get(e["hilo"], 0)
    esc["cota_baja"] += T * pw
    esc["estimacion"] += T * (pw * (1 + e["cad"]) + (n - e["cad"]) * p["lectura"])
    esc[f"estimacion | {e['modelo']} | {e['hilo']}"] += T * (
        pw * (1 + e["cad"]) + (n - e["cad"]) * p["lectura"]
    )
    # comparaciones
    P55 = PRECIOS["claude-opus-5-5"]
    esc["solo_respaldo_opus55_subagente_N_declarado"] += T * (
        P55["w5m"] + N_DECL["subagente"] * P55["lectura"]
    )
    esc["spec_anterior_cota_baja_opus55_5m_c2.2"] += (
        (u["chars_in"] - u["chars_out"]) / 2.2 / 1e6 * P55["w5m"]
    )
    esc["spec_anterior_opus55_5m_N49.5_c2.1"] += (
        (u["chars_in"] - u["chars_out"]) / 2.1 / 1e6 * (P55["w5m"] + 49.5 * P55["lectura"])
    )
    if e["modelo"] == "claude-opus-5" and e["hilo"] == "principal":
        # sensibilidad: el mismo grupo con el precio de Opus 5.5 que supuso el insumo
        esc["estimacion | opus-5 principal con precio de opus-5-5"] += T * (
            P55["w1h"] * (1 + e["cad"]) + (n - e["cad"]) * P55["lectura"]
        )
# Reproducción exacta del insumo con SU filtro (todos los casados no-banco con `path`, sin excluir
# fallos ni salida a fichero), para comprobar que el cruce de datos es el mismo.
P55 = PRECIOS["claude-opus-5-5"]
rep = collections.Counter()
for i, tid in casado.items():
    d, u = deleg[tid], usos[i]
    if d["banco"] or u["path"] is None:
        continue
    n, cad = n_y_caducidades(d)
    m = normaliza(d["model"])
    pm = P55 if m in ("claude-opus-5", "claude-opus-4-8") else PRECIOS[m]
    pw = pm["w5m"] if d["kind"] == "subagente" else pm["w1h"]
    tv = max(0, u["chars_in"] - u["chars_out"]) / 4 / 1e6
    rep["casos"] += 1
    rep["B"] += tv * (pw * (1 + cad) + (n - cad) * pm["lectura"])
    rep["spec_REQ022"] += tv * (P55["w5m"] + 49.5 * P55["lectura"])
out["reproduccion_exacta_insumo"] = {k: round(v, 2) for k, v in rep.items()}
out["origen_densidad"] = dict(origen_dens)
out["eventos_sin_precio"] = dict(sin_precio)
out["usd"] = {k: round(v, 2) for k, v in sorted(esc.items())}
print(json.dumps(out, ensure_ascii=False, indent=1))
