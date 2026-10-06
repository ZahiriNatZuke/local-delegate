"""Puntos de calibración de la cuota y su criterio (REQ-051 a REQ-057), en funciones puras.

Port de `insumos/scripts/calibracion.py` y `criterio.py`. Lo usan el comando
`recalcular-coste` (que saca los puntos de los transcripts y del registro del statusline) y el
panel (que solo aplica `estado` sobre `coste-agregados.json`, sin leer `~/.claude`).

Un punto es un dict `{"fuente": "statusline"|"rechazo", "tipo", "inicio", "fin", "delta_pct",
"delta_usd", "C", "marcas", "peticiones_sin_precio"}` con fechas ISO en UTC. Sin ids de sesión.
"""

from __future__ import annotations

import itertools
import json
import math
import statistics
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

TIPOS = ("five_hour", "seven_day")
DURACION = {"five_hour": timedelta(hours=5), "seven_day": timedelta(days=7)}
CAMPO_RESET = {"five_hour": "five_reset", "seven_day": "seven_reset"}

VIGENCIA = timedelta(days=60)
DELTA_MINIMO = 10
UMBRAL = 0.25
MIN_PUNTOS = 3

MARCA_COTA_BAJA = "cota baja"
MARCA_SOLO_COMPROBACION = "solo comprobación"
MARCA_OTRAS_SUPERFICIES = "cota baja si hubo uso en otras superficies"
MARCA_REINICIO = "reinicio"

AVISO_RECHAZO = (
    "la calibración da menos capacidad que un rechazo observado: probable uso en otras superficies"
)
SIN_DATOS = "no hay datos de calibración en esta máquina"
SIN_STATUSLINE = "no hay registro del statusline en esta máquina: no se puede calibrar"


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat()


def _instante(valor: object) -> datetime | None:
    if not isinstance(valor, str) or not valor:
        return None
    try:
        t = datetime.fromisoformat(valor)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def descartes_vacios() -> dict[str, Counter]:
    return {tipo: Counter() for tipo in TIPOS}


# --- REQ-051: rechazos, solo de comprobación -----------------------------------------------


def puntos_de_rechazo(
    rechazos: dict[tuple[str, object], datetime],
    peticiones: Iterable[tuple[datetime, object, float | None]],
) -> list[dict]:
    """Un punto por `(rateLimitType, resetsAt)`, de `resetsAt − duración` al PRIMER rechazo.

    Δ% = 100; Δ$ = coste a precio de lista de las peticiones de ese intervalo; marcas «cota baja» y
    «solo comprobación»; cuenta las peticiones sin precio.
    """
    peticiones = list(peticiones)
    puntos = []
    for (tipo, reset), primero in sorted(rechazos.items(), key=lambda x: str(x[0])):
        if tipo not in DURACION or isinstance(reset, bool) or not isinstance(reset, (int, float)):
            continue
        try:
            inicio = datetime.fromtimestamp(reset, UTC) - DURACION[tipo]
        except (OverflowError, OSError, ValueError):
            continue
        dentro = [c for (t, _s, c) in peticiones if inicio <= t <= primero]
        dolar = sum(c for c in dentro if c is not None)
        puntos.append(
            {
                "fuente": "rechazo",
                "tipo": tipo,
                "inicio": _iso(inicio),
                "fin": _iso(primero),
                "delta_pct": 100,
                "delta_usd": round(dolar, 2),
                "C": round(dolar, 2),
                "marcas": [MARCA_COTA_BAJA, MARCA_SOLO_COMPROBACION],
                "peticiones_sin_precio": sum(1 for c in dentro if c is None),
            }
        )
    return puntos


# --- REQ-052 y REQ-054: el registro del statusline ------------------------------------------


def _pct_valido(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 100


def sanear(lineas: Iterable[str]) -> tuple[dict[str, list], set, dict[str, Counter]]:
    """Las filas útiles del registro por tipo, las sesiones que aparecen y los descartes.

    Una línea ilegible (o sin `ts`) es `linea_corrupta` en los dos tipos; un % fuera de
    [0, 100] o no numérico es `fuera_de_rango` en su tipo (REQ-054, REQ-061). Cada fila va como
    `(t, sesión, %, reset, cost_usd)`, ordenada por `t`.
    """
    descartes = descartes_vacios()
    filas: list[tuple[datetime, dict]] = []
    for linea in lineas:
        if not linea.strip():
            continue
        try:
            r = json.loads(linea)
        except ValueError:
            r = None
        t = _instante(r.get("ts")) if isinstance(r, dict) else None
        if t is None:
            for tipo in TIPOS:
                descartes[tipo]["linea_corrupta"] += 1
            continue
        filas.append((t, r))
    filas.sort(key=lambda x: x[0])
    sesiones = {r.get("session_id") for _, r in filas}
    por_tipo: dict[str, list] = {tipo: [] for tipo in TIPOS}
    for t, r in filas:
        for tipo in TIPOS:
            v = r.get(tipo)
            if not _pct_valido(v):
                descartes[tipo]["fuera_de_rango"] += 1
                continue
            por_tipo[tipo].append(
                (t, r.get("session_id"), v, r.get(CAMPO_RESET[tipo]), r.get("cost_usd"))
            )
    return por_tipo, sesiones, descartes


def _numero(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def puntos_del_statusline(
    por_tipo: dict[str, list],
    sesiones_registro: set,
    peticiones: Iterable[tuple[datetime, object, float | None]],
) -> tuple[list[dict], dict[str, Counter]]:
    """Como mucho un punto por (tipo, reset), con los siete pasos de REQ-052."""
    peticiones = list(peticiones)
    puntos: list[dict] = []
    descartes = descartes_vacios()
    for tipo in TIPOS:
        grupos: dict[object, dict[object, list]] = {}
        for t, sesion, v, reset, coste in por_tipo.get(tipo, []):
            grupos.setdefault(reset, {}).setdefault(sesion, []).append((t, v, coste))
        for por_sesion in grupos.values():
            # El par: primera y última fila de UNA sesión; la de mayor Δ%, con empate la que
            # empieza antes.
            mejor = None
            for xs in por_sesion.values():
                d = xs[-1][1] - xs[0][1]
                if mejor is None or d > mejor[0] or (d == mejor[0] and xs[0][0] < mejor[1][0][0]):
                    mejor = (d, xs)
            delta, xs = mejor
            if delta < DELTA_MINIMO:
                descartes[tipo]["delta_pequeno"] += 1
                continue
            ta, tb = xs[0][0], xs[-1][0]
            dolar, reinicios = 0.0, 0
            for ys in por_sesion.values():
                for (_t0, _v0, c0), (t1, _v1, c1) in itertools.pairwise(ys):
                    if not (ta < t1 <= tb) or not _numero(c0) or not _numero(c1):
                        continue
                    if c1 >= c0:
                        dolar += c1 - c0
                    else:
                        dolar += c1  # `/clear`: el incremento es el valor nuevo
                        reinicios += 1
            if dolar <= 0:
                descartes[tipo]["sin_uso_local"] += 1
                continue
            if any(ta < t <= tb and s not in sesiones_registro for (t, s, _c) in peticiones):
                descartes[tipo]["contaminado"] += 1
                continue
            puntos.append(
                {
                    "fuente": "statusline",
                    "tipo": tipo,
                    "inicio": _iso(ta),
                    "fin": _iso(tb),
                    "delta_pct": delta,
                    "delta_usd": round(dolar, 2),
                    "C": round(dolar * 100 / delta, 2),
                    "marcas": [MARCA_OTRAS_SUPERFICIES] + ([MARCA_REINICIO] if reinicios else []),
                    "peticiones_sin_precio": None,
                }
            )
    return puntos, descartes


# --- REQ-061: un punto mal formado en `coste-agregados.json` se salta -------------------------

FUENTES = ("statusline", "rechazo")


def bien_formado(p: object) -> bool:
    """Si el punto tiene todo lo que leen `quitar_solapados` y `estado`. El JSON lo escribe solo
    el comando, pero alguien puede editarlo a mano: un punto roto no debe tumbar el panel."""
    if not isinstance(p, dict) or p.get("fuente") not in FUENTES or p.get("tipo") not in TIPOS:
        return False
    if _instante(p.get("inicio")) is None or _instante(p.get("fin")) is None:
        return False
    delta, c = p.get("delta_pct"), p.get("C")
    if not (_numero(delta) and math.isfinite(delta)) or not (_numero(c) and math.isfinite(c)):
        return False
    # La capacidad del statusline divide en la dispersión: tiene que ser positiva.
    return c > 0 if p["fuente"] == "statusline" else c >= 0


def separar_mal_formados(puntos: Iterable[object]) -> tuple[list[dict], dict[str, Counter]]:
    """Los puntos bien formados y los descartes: cada punto roto es `linea_corrupta` en su tipo, o
    en los dos si el tipo tampoco se lee (la misma convención que `sanear`)."""
    buenos: list[dict] = []
    descartes = descartes_vacios()
    for p in puntos:
        if bien_formado(p):
            buenos.append(p)
            continue
        tipo = p.get("tipo") if isinstance(p, dict) else None
        for t in [tipo] if tipo in TIPOS else TIPOS:
            descartes[t]["linea_corrupta"] += 1
    return buenos, descartes


# --- REQ-053: ventanas que no se solapan ------------------------------------------------------


def quitar_solapados(puntos: list[dict]) -> tuple[list[dict], dict[str, Counter]]:
    """Entre puntos de la misma fuente y tipo cuyos intervalos se solapan, se queda el de mayor
    Δ% (con empate, el más reciente); los otros son `solapado`."""
    descartes = descartes_vacios()
    aceptados: list[dict] = []
    # Mayor Δ% primero y, dentro del mismo Δ%, el más reciente.
    orden = sorted(puntos, key=lambda p: (-p["delta_pct"], -_instante(p["fin"]).timestamp()))
    for p in orden:
        ini, fin = _instante(p["inicio"]), _instante(p["fin"])
        choca = any(
            q["fuente"] == p["fuente"]
            and q["tipo"] == p["tipo"]
            and ini < _instante(q["fin"])
            and _instante(q["inicio"]) < fin
            for q in aceptados
        )
        if choca:
            if p["tipo"] in descartes:
                descartes[p["tipo"]]["solapado"] += 1
            continue
        aceptados.append(p)
    aceptados.sort(key=lambda p: (p["fuente"], p["tipo"], p["fin"], p["inicio"]))
    return aceptados, descartes


# --- REQ-054 y REQ-057: vigencia y reinicio -------------------------------------------------


def vigentes(puntos: Iterable[dict], ahora: datetime, reinicio: str | None = None) -> list[dict]:
    """Los puntos con `fin` de hace 60 días o menos y no anterior al reinicio a mano."""
    desde = _instante(reinicio) if reinicio else None
    salida = []
    for p in puntos:
        fin = _instante(p.get("fin"))
        if fin is None or ahora - fin > VIGENCIA:
            continue
        if desde is not None and fin < desde:
            continue
        salida.append(p)
    return salida


# --- REQ-055 y REQ-056: criterio y deriva -----------------------------------------------------


def dispersion(cs: list[float]) -> float:
    """Mediana, sobre los puntos, de |C_i − mediana(C_j≠i)| / mediana(C_j≠i)."""
    errores = []
    for i, c in enumerate(cs):
        m = statistics.median(cs[:i] + cs[i + 1 :])
        errores.append(abs(c - m) / m)
    return statistics.median(errores)


def deriva(cs: list[float]) -> int | None:
    """Índice del primer punto vigente tras la última deriva, o `None` si no la hubo.

    Con un tramo que empieza en `s`, hay deriva en el par (j−1, j) si el tramo tiene al menos 3
    puntos antes de j−1 y los dos se alejan más del 25 % de su mediana, EN EL MISMO SENTIDO.
    """
    s, hubo = 0, False
    for j in range(len(cs)):
        if j - 1 - s < MIN_PUNTOS:
            continue
        m = statistics.median(cs[s : j - 1])
        d1, d2 = (cs[j - 1] - m) / m, (cs[j] - m) / m
        if abs(d1) > UMBRAL and abs(d2) > UMBRAL and (d1 > 0) == (d2 > 0):
            s, hubo = j - 1, True
    return s if hubo else None


def _pct(x: float) -> str:
    return f"{x * 100:.1f}".replace(".", ",") + " %"


def criterio(cs: list[float]) -> dict:
    """Estado de un tipo a partir de las capacidades de sus puntos del statusline vigentes, en
    orden cronológico (REQ-055 y REQ-056)."""
    k = deriva(cs)
    if k is not None:
        cs = cs[k:]
    r: dict = {"deriva": k is not None, "puntos": len(cs)}
    if len(cs) >= 2:
        r["dispersion"] = round(dispersion(cs), 3)
    if len(cs) < MIN_PUNTOS:
        r.update(
            estado="sin calibrar",
            motivo=f"faltan {MIN_PUNTOS - len(cs)} puntos del statusline",
        )
        return r
    d = dispersion(cs)
    if d >= UMBRAL:
        r.update(estado="sin calibrar", motivo=f"dispersión {_pct(d)} ≥ 25 %")
        return r
    r.update(estado="calibrado", mediana_C=statistics.median(cs))
    return r


# --- Lo que pinta el panel --------------------------------------------------------------------


def estado(agregados: dict | None, ahora: datetime) -> dict[str, dict]:
    """Por tipo: estado, puntos vigentes, rechazos, dispersión, descartes, deriva, reinicio y qué
    falta (REQ-059), o la capacidad si está calibrado (REQ-060) y el aviso de REQ-058.

    Aplica la vigencia AL LEER (REQ-054): un punto caduca aunque el JSON no se regenere.
    """
    if not isinstance(agregados, dict):
        return {
            tipo: {
                "estado": "sin calibrar",
                "motivo": SIN_DATOS,
                "puntos": 0,
                "puntos_rechazo": 0,
                "descartes": {},
                "deriva": False,
                "reinicio": None,
            }
            for tipo in TIPOS
        }
    crudos = agregados.get("puntos")
    puntos, rotos = separar_mal_formados(crudos if isinstance(crudos, list) else [])
    reinicios = agregados.get("reinicios") or {}
    fuentes = agregados.get("fuentes") or {}
    todos_descartes = agregados.get("descartes")
    if not isinstance(todos_descartes, dict):
        todos_descartes = {}
    salida: dict[str, dict] = {}
    for tipo in TIPOS:
        reinicio = reinicios.get(tipo) if isinstance(reinicios, dict) else None
        del_tipo = [p for p in puntos if p.get("tipo") == tipo]
        sl = [p for p in del_tipo if p.get("fuente") == "statusline"]
        vig = sorted(vigentes(sl, ahora, reinicio), key=lambda p: p["fin"])
        rech = vigentes([p for p in del_tipo if p.get("fuente") == "rechazo"], ahora)
        previos = todos_descartes.get(tipo)
        descartes = dict(previos) if isinstance(previos, dict) else {}
        if rotos[tipo]["linea_corrupta"]:
            descartes["linea_corrupta"] = (
                descartes.get("linea_corrupta", 0) + rotos[tipo]["linea_corrupta"]
            )
        sin_reinicio = len(vigentes(sl, ahora))
        if len(sl) > sin_reinicio:
            descartes["caducado"] = descartes.get("caducado", 0) + len(sl) - sin_reinicio
        if sin_reinicio > len(vig):
            descartes["reinicio"] = descartes.get("reinicio", 0) + sin_reinicio - len(vig)
        r = criterio([float(p["C"]) for p in vig])
        r.update(
            puntos_rechazo=len(rech),
            descartes=descartes,
            reinicio=reinicio,
        )
        if r["estado"] == "calibrado" and any(r["mediana_C"] < float(p["C"]) for p in rech):
            r["aviso"] = AVISO_RECHAZO
        if isinstance(fuentes, dict) and fuentes and r["estado"] != "calibrado":
            # REQ-061: sin fuentes en esta máquina, el bloque lo dice en vez de «faltan k».
            if not fuentes.get("statusline") and not fuentes.get("transcripts"):
                r["motivo"] = SIN_DATOS
            elif not fuentes.get("statusline"):
                r["motivo"] = SIN_STATUSLINE
        salida[tipo] = r
    return salida
