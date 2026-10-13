"""Puntos de calibración de la cuota y su criterio (REQ-051 a REQ-057), en funciones puras.

Port de `insumos/scripts/calibracion.py` y `criterio.py`. Lo usan el comando
`recompute-cost` (que saca los puntos de los transcripts y del registro del statusline) y el
panel (que solo aplica `status` sobre `cost-aggregates.json`, sin leer `~/.claude`).

Un punto es un dict `{"source": "statusline"|"rejection", "type", "start", "end", "delta_pct",
"delta_usd", "C", "marks", "unpriced_requests"}` con fechas ISO en UTC. Sin ids de sesión. Las
marcas y los motivos de descarte son valores de máquina en inglés (REQ-033); el panel y el resumen
de `recompute-cost` los pintan en palabras.
"""

from __future__ import annotations

import itertools
import json
import math
import statistics
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from . import legacy_names

TYPES = ("five_hour", "seven_day")
DURATION = {"five_hour": timedelta(hours=5), "seven_day": timedelta(days=7)}
RESET_FIELD = {"five_hour": "five_reset", "seven_day": "seven_reset"}

VALIDITY = timedelta(days=60)
MIN_DELTA = 10
THRESHOLD = 0.25
MIN_POINTS = 3

MARK_LOW_BOUND = "low_bound"
MARK_CHECK_ONLY = "check_only"
MARK_OTHER_SURFACES = "low_bound_if_other_surfaces"
MARK_RESET = "reset"

REJECTION_WARNING = (
    "la calibración da menos capacidad que un rechazo observado: probable uso en otras superficies"
)
NO_DATA = "no hay datos de calibración en esta máquina"
NO_STATUSLINE = "no hay registro del statusline en esta máquina: no se puede calibrar"


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat()


def _instant(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def empty_discards() -> dict[str, Counter]:
    return {kind: Counter() for kind in TYPES}


# --- REQ-051: rechazos, solo de comprobación -----------------------------------------------


def rejection_points(
    rejections: dict[tuple[str, object], datetime],
    requests: Iterable[tuple[datetime, object, float | None]],
) -> list[dict]:
    """Un punto por `(rateLimitType, resetsAt)`, de `resetsAt − duración` al PRIMER rechazo.

    Δ% = 100; Δ$ = coste a precio de lista de las peticiones de ese intervalo; marcas `low_bound` y
    `check_only`; cuenta las peticiones sin precio.
    """
    requests = list(requests)
    points = []
    for (kind, reset), first in sorted(rejections.items(), key=lambda x: str(x[0])):
        if kind not in DURATION or isinstance(reset, bool) or not isinstance(reset, (int, float)):
            continue
        try:
            start = datetime.fromtimestamp(reset, UTC) - DURATION[kind]
        except (OverflowError, OSError, ValueError):
            continue
        inside = [c for (t, _s, c) in requests if start <= t <= first]
        dollars = sum(c for c in inside if c is not None)
        points.append(
            {
                "source": "rejection",
                "type": kind,
                "start": _iso(start),
                "end": _iso(first),
                "delta_pct": 100,
                "delta_usd": round(dollars, 2),
                "C": round(dollars, 2),
                "marks": [MARK_LOW_BOUND, MARK_CHECK_ONLY],
                "unpriced_requests": sum(1 for c in inside if c is None),
            }
        )
    return points


# --- REQ-052 y REQ-054: el registro del statusline ------------------------------------------


def _valid_pct(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 100


def sanitize(lines: Iterable[str]) -> tuple[dict[str, list], set, dict[str, Counter]]:
    """Las filas útiles del registro por tipo, las sesiones que aparecen y los descartes.

    Una línea ilegible (o sin `ts`) es `corrupt_line` en los dos tipos; un % fuera de
    [0, 100] o no numérico es `out_of_range` en su tipo (REQ-054, REQ-061). Cada fila va como
    `(t, sesión, %, reset, cost_usd)`, ordenada por `t`.
    """
    discards = empty_discards()
    rows: list[tuple[datetime, dict]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            r = None
        t = _instant(r.get("ts")) if isinstance(r, dict) else None
        if t is None:
            for kind in TYPES:
                discards[kind]["corrupt_line"] += 1
            continue
        rows.append((t, r))
    rows.sort(key=lambda x: x[0])
    sessions = {r.get("session_id") for _, r in rows}
    by_type: dict[str, list] = {kind: [] for kind in TYPES}
    for t, r in rows:
        for kind in TYPES:
            v = r.get(kind)
            if not _valid_pct(v):
                discards[kind]["out_of_range"] += 1
                continue
            by_type[kind].append(
                (t, r.get("session_id"), v, r.get(RESET_FIELD[kind]), r.get("cost_usd"))
            )
    return by_type, sessions, discards


def _is_number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def statusline_points(
    by_type: dict[str, list],
    log_sessions: set,
    requests: Iterable[tuple[datetime, object, float | None]],
) -> tuple[list[dict], dict[str, Counter]]:
    """Como mucho un punto por (tipo, reset), con los siete pasos de REQ-052."""
    requests = list(requests)
    points: list[dict] = []
    discards = empty_discards()
    for kind in TYPES:
        groups: dict[object, dict[object, list]] = {}
        for t, session, v, reset, cost in by_type.get(kind, []):
            groups.setdefault(reset, {}).setdefault(session, []).append((t, v, cost))
        for by_session in groups.values():
            # El par: primera y última fila de UNA sesión; la de mayor Δ%, con empate la que
            # empieza antes.
            best = None
            for xs in by_session.values():
                d = xs[-1][1] - xs[0][1]
                if best is None or d > best[0] or (d == best[0] and xs[0][0] < best[1][0][0]):
                    best = (d, xs)
            delta, xs = best
            if delta < MIN_DELTA:
                discards[kind]["small_delta"] += 1
                continue
            ta, tb = xs[0][0], xs[-1][0]
            dollars, resets = 0.0, 0
            for ys in by_session.values():
                for (_t0, _v0, c0), (t1, _v1, c1) in itertools.pairwise(ys):
                    if not (ta < t1 <= tb) or not _is_number(c0) or not _is_number(c1):
                        continue
                    if c1 >= c0:
                        dollars += c1 - c0
                    else:
                        dollars += c1  # `/clear`: el incremento es el valor nuevo
                        resets += 1
            if dollars <= 0:
                discards[kind]["no_local_use"] += 1
                continue
            if any(ta < t <= tb and s not in log_sessions for (t, s, _c) in requests):
                discards[kind]["contaminated"] += 1
                continue
            points.append(
                {
                    "source": "statusline",
                    "type": kind,
                    "start": _iso(ta),
                    "end": _iso(tb),
                    "delta_pct": delta,
                    "delta_usd": round(dollars, 2),
                    "C": round(dollars * 100 / delta, 2),
                    "marks": [MARK_OTHER_SURFACES] + ([MARK_RESET] if resets else []),
                    "unpriced_requests": None,
                }
            )
    return points, discards


# --- REQ-061: un punto mal formado en `cost-aggregates.json` se salta -------------------------

SOURCES = ("statusline", "rejection")


def well_formed(p: object) -> bool:
    """Si el punto tiene todo lo que leen `drop_overlapping` y `status`. El JSON lo escribe solo
    el comando, pero alguien puede editarlo a mano: un punto roto no debe tumbar el panel."""
    if not isinstance(p, dict) or p.get("source") not in SOURCES or p.get("type") not in TYPES:
        return False
    if _instant(p.get("start")) is None or _instant(p.get("end")) is None:
        return False
    delta, c = p.get("delta_pct"), p.get("C")
    if not (_is_number(delta) and math.isfinite(delta)) or not (_is_number(c) and math.isfinite(c)):
        return False
    # La capacidad del statusline divide en la dispersión: tiene que ser positiva.
    return c > 0 if p["source"] == "statusline" else c >= 0


def split_malformed(points: Iterable[object]) -> tuple[list[dict], dict[str, Counter]]:
    """Los puntos bien formados y los descartes: cada punto roto es `corrupt_line` en su tipo, o
    en los dos si el tipo tampoco se lee (la misma convención que `sanitize`)."""
    good: list[dict] = []
    discards = empty_discards()
    for p in points:
        if well_formed(p):
            good.append(p)
            continue
        kind = p.get("type") if isinstance(p, dict) else None
        for t in [kind] if kind in TYPES else TYPES:
            discards[t]["corrupt_line"] += 1
    return good, discards


# --- REQ-053: ventanas que no se solapan ------------------------------------------------------


def drop_overlapping(points: list[dict]) -> tuple[list[dict], dict[str, Counter]]:
    """Entre puntos de la misma fuente y tipo cuyos intervalos se solapan, se queda el de mayor
    Δ% (con empate, el más reciente); los otros son `overlapping`."""
    discards = empty_discards()
    accepted: list[dict] = []
    # Mayor Δ% primero y, dentro del mismo Δ%, el más reciente.
    ordered = sorted(points, key=lambda p: (-p["delta_pct"], -_instant(p["end"]).timestamp()))
    for p in ordered:
        start, end = _instant(p["start"]), _instant(p["end"])
        clashes = any(
            q["source"] == p["source"]
            and q["type"] == p["type"]
            and start < _instant(q["end"])
            and _instant(q["start"]) < end
            for q in accepted
        )
        if clashes:
            if p["type"] in discards:
                discards[p["type"]]["overlapping"] += 1
            continue
        accepted.append(p)
    accepted.sort(key=lambda p: (p["source"], p["type"], p["end"], p["start"]))
    return accepted, discards


# --- REQ-054 y REQ-057: vigencia y reinicio -------------------------------------------------


def current_points(points: Iterable[dict], now: datetime, reset: str | None = None) -> list[dict]:
    """Los puntos con `end` de hace 60 días o menos y no anterior al reinicio a mano."""
    since = _instant(reset) if reset else None
    out = []
    for p in points:
        end = _instant(p.get("end"))
        if end is None or now - end > VALIDITY:
            continue
        if since is not None and end < since:
            continue
        out.append(p)
    return out


# --- REQ-055 y REQ-056: criterio y deriva -----------------------------------------------------


def dispersion(cs: list[float]) -> float:
    """Mediana, sobre los puntos, de |C_i − mediana(C_j≠i)| / mediana(C_j≠i)."""
    errors = []
    for i, c in enumerate(cs):
        m = statistics.median(cs[:i] + cs[i + 1 :])
        errors.append(abs(c - m) / m)
    return statistics.median(errors)


def drift(cs: list[float]) -> int | None:
    """Índice del primer punto vigente tras la última deriva, o `None` si no la hubo.

    Con un tramo que empieza en `s`, hay deriva en el par (j−1, j) si el tramo tiene al menos 3
    puntos antes de j−1 y los dos se alejan más del 25 % de su mediana, EN EL MISMO SENTIDO.
    """
    s, drifted = 0, False
    for j in range(len(cs)):
        if j - 1 - s < MIN_POINTS:
            continue
        m = statistics.median(cs[s : j - 1])
        d1, d2 = (cs[j - 1] - m) / m, (cs[j] - m) / m
        if abs(d1) > THRESHOLD and abs(d2) > THRESHOLD and (d1 > 0) == (d2 > 0):
            s, drifted = j - 1, True
    return s if drifted else None


def _pct(x: float) -> str:
    return f"{x * 100:.1f}".replace(".", ",") + " %"


def criterion(cs: list[float]) -> dict:
    """Estado de un tipo a partir de las capacidades de sus puntos del statusline vigentes, en
    orden cronológico (REQ-055 y REQ-056)."""
    k = drift(cs)
    if k is not None:
        cs = cs[k:]
    r: dict = {"drift": k is not None, "points": len(cs)}
    if len(cs) >= 2:
        r["dispersion"] = round(dispersion(cs), 3)
    if len(cs) < MIN_POINTS:
        r.update(
            status="uncalibrated",
            reason=f"faltan {MIN_POINTS - len(cs)} puntos del statusline",
        )
        return r
    d = dispersion(cs)
    if d >= THRESHOLD:
        r.update(status="uncalibrated", reason=f"dispersión {_pct(d)} ≥ 25 %")
        return r
    r.update(status="calibrated", median_C=statistics.median(cs))
    return r


# --- Lo que pinta el panel --------------------------------------------------------------------


def status(aggregates: dict | None, now: datetime) -> dict[str, dict]:
    """Por tipo: estado, puntos vigentes, rechazos, dispersión, descartes, deriva, reinicio y qué
    falta (REQ-059), o la capacidad si está calibrado (REQ-060) y el aviso de REQ-058.

    Aplica la vigencia AL LEER (REQ-054): un punto caduca aunque el JSON no se regenere.
    """
    if not isinstance(aggregates, dict):
        return {
            kind: {
                "status": "uncalibrated",
                "reason": NO_DATA,
                "points": 0,
                "rejection_points": 0,
                "discards": {},
                "drift": False,
                "reset": None,
            }
            for kind in TYPES
        }
    # Quien llama suele traerlos ya traducidos (`recompute.read_aggregates`); si no, se traducen
    # aquí, para que un lector no dependa de por dónde le llegó el fichero (REQ-006).
    aggregates = legacy_names.normalize_cost_aggregates(aggregates)
    raw = aggregates.get("points")
    points, broken = split_malformed(raw if isinstance(raw, list) else [])
    resets = aggregates.get("resets") or {}
    sources = aggregates.get("sources") or {}
    all_discards = aggregates.get("discards")
    if not isinstance(all_discards, dict):
        all_discards = {}
    out: dict[str, dict] = {}
    for kind in TYPES:
        reset = resets.get(kind) if isinstance(resets, dict) else None
        of_type = [p for p in points if p.get("type") == kind]
        sl = [p for p in of_type if p.get("source") == "statusline"]
        valid = sorted(current_points(sl, now, reset), key=lambda p: p["end"])
        rejections_valid = current_points(
            [p for p in of_type if p.get("source") == "rejection"], now
        )
        previous = all_discards.get(kind)
        discards = dict(previous) if isinstance(previous, dict) else {}
        if broken[kind]["corrupt_line"]:
            discards["corrupt_line"] = (
                discards.get("corrupt_line", 0) + broken[kind]["corrupt_line"]
            )
        without_reset = len(current_points(sl, now))
        if len(sl) > without_reset:
            discards["expired"] = discards.get("expired", 0) + len(sl) - without_reset
        if without_reset > len(valid):
            discards["reset"] = discards.get("reset", 0) + without_reset - len(valid)
        r = criterion([float(p["C"]) for p in valid])
        r.update(
            rejection_points=len(rejections_valid),
            discards=discards,
            reset=reset,
        )
        if r["status"] == "calibrated" and any(
            r["median_C"] < float(p["C"]) for p in rejections_valid
        ):
            r["warning"] = REJECTION_WARNING
        if isinstance(sources, dict) and sources and r["status"] != "calibrated":
            # REQ-061: sin fuentes en esta máquina, el bloque lo dice en vez de «faltan k».
            if not sources.get("statusline") and not sources.get("transcripts"):
                r["reason"] = NO_DATA
            elif not sources.get("statusline"):
                r["reason"] = NO_STATUSLINE
        out[kind] = r
    return out
