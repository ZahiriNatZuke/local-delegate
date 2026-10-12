"""Lectura de los transcripts de Claude Code, SOLO para `local-delegate recalcular-coste`.

El daemon y el panel no importan este módulo (REQ-073): leer `~/.claude/projects` es cosa del
comando que lanza el usuario. Todo lo que sale de aquí son números, fechas, ids de modelo y
niveles de esfuerzo; las rutas (`path` de la tool, fichero del transcript) y los ids de sesión se
usan en memoria y no se devuelven en ninguna estructura que se escriba a disco.

Port de `insumos/scripts/atribucion_n.py` (cruce y `N`), `calibracion.py` (peticiones y rechazos)
y `cotejo.py` (`cost-state`), con las mismas reglas, para que T8 pueda comparar cifra a cifra:

- `read(root)` recorre los `*.jsonl` una sola vez y devuelve un `Index`.
- `match_lines(lines, index, since=...)` casa cada línea del log con su `tool_use` (REQ-004).
- `n_and_expiries(index, delegation)` (REQ-043) y `percentile` (interpolación lineal).
- `cost_state(index)` da las filas «modelo × sesión» para el cotejo (REQ-014).

Una línea JSON rota se salta y se cuenta (REQ-061); un fichero ilegible, también.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import precios

TOOL_PREFIX = "mcp__local-delegate__"

#: TTL de la caché de cada hilo (REQ-043): el principal escribe a 1 h, los subagentes a 5 min.
TTL_S = {"main": 3600, "subagent": 300}

#: Ventana del cruce por tiempo (REQ-004).
MARGIN_BEFORE = timedelta(seconds=1)
MARGIN_AFTER = timedelta(seconds=2)
NO_RESULT_WINDOW = timedelta(minutes=15)

#: Las seis columnas de `modelUsage` que entran en el cotejo.
CHECK_FIELDS = precios.CAMPOS_COTEJO


def parse_instant(value: object) -> datetime | None:
    """`datetime` con zona (UTC si no trae) o `None`."""
    if not isinstance(value, str) or not value:
        return None
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


@dataclass
class Delegation:
    """Un `tool_use` de una tool de local-delegate, con lo que el relleno necesita.

    `path` y `thread` (el fichero) viven solo en memoria: sirven para desempatar y para contar `N`.
    """

    tool: str
    ts_use: datetime | None
    thread: str
    kind: str
    model: str | None
    effort: str | None
    path: str | None
    bench: bool
    mid: str | None
    ts_res: datetime | None = None


@dataclass
class Thread:
    kind: str
    requests: dict[str, datetime] = field(default_factory=dict)
    compactions: list[datetime] = field(default_factory=list)


@dataclass
class Index:
    """Lo que el comando necesita de los transcripts, leído en una sola pasada."""

    delegations: dict[str, Delegation] = field(default_factory=dict)
    threads: dict[str, Thread] = field(default_factory=dict)
    #: `message.id` → (ts de su primera aparición, sesión, coste a precio de lista o `None`).
    requests: dict[str, tuple[datetime, object, float | None]] = field(default_factory=dict)
    #: (tipo, resetsAt) → primer rechazo visto (REQ-051).
    rejections: dict[tuple[str, object], datetime] = field(default_factory=dict)
    #: (sesión, startTime) → (orden, modelUsage) de la ÚLTIMA línea `cost-state` por posición.
    costs: dict[tuple[object, object], tuple[int, dict]] = field(default_factory=dict)
    files: int = 0
    unreadable_files: int = 0
    corrupt_lines: int = 0


def request_cost(message: dict) -> float | None:
    """Coste a precio de lista de una petición (USD), con la escritura a 5 min y a 1 h separadas
    según `usage.cache_creation`; `None` si el modelo no tiene precio (REQ-051)."""
    p = precios.entrada(str(message.get("model") or ""))
    if p is None:
        return None
    u = message.get("usage") if isinstance(message.get("usage"), dict) else {}
    cc = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
    w5 = cc.get("ephemeral_5m_input_tokens")
    w1 = cc.get("ephemeral_1h_input_tokens")
    if w5 is None and w1 is None:
        w5, w1 = u.get("cache_creation_input_tokens") or 0, 0
    return (
        (u.get("input_tokens") or 0) * p["entrada"]
        + (w5 or 0) * p["w5m"]
        + (w1 or 0) * p["w1h"]
        + (u.get("cache_read_input_tokens") or 0) * p["lectura"]
        + (u.get("output_tokens") or 0) * p["salida"]
    ) / 1e6


def _quota_limits(value: object) -> list:
    if isinstance(value, list):
        return value
    return [value] if isinstance(value, dict) else []


def _read_line(index: Index, r: dict, name: str, thread: Thread, bench: bool, order: list[int]):
    entry_type = r.get("type")
    if entry_type == "system" and r.get("subtype") == "compact_boundary":
        t = parse_instant(r.get("timestamp"))
        if t:
            thread.compactions.append(t)
    elif entry_type == "cost-state":
        order[0] += 1
        usage = r.get("modelUsage")
        index.costs[(r.get("sessionId"), r.get("startTime"))] = (
            order[0],
            usage if isinstance(usage, dict) else {},
        )
    elif entry_type == "assistant":
        message = r.get("message") if isinstance(r.get("message"), dict) else {}
        t = parse_instant(r.get("timestamp"))
        if message.get("model") == "<synthetic>":
            for q in _quota_limits(r.get("quotaLimits")):
                if isinstance(q, dict) and q.get("status") == "rejected" and t:
                    key = (str(q.get("rateLimitType")), q.get("resetsAt"))
                    index.rejections[key] = min(t, index.rejections.get(key, t))
            return
        mid = message.get("id") or r.get("requestId")
        if mid and t:
            thread.requests.setdefault(mid, t)
            if mid not in index.requests:
                index.requests[mid] = (t, r.get("sessionId"), request_cost(message))
        content = message.get("content")
        for block in content if isinstance(content, list) else []:
            if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                continue
            tool_name = str(block.get("name") or "")
            if not tool_name.startswith(TOOL_PREFIX):
                continue
            entry = block.get("input") if isinstance(block.get("input"), dict) else {}
            effort = r.get("effort")
            raw_path = entry.get("path")
            index.delegations[str(block.get("id"))] = Delegation(
                tool=tool_name[len(TOOL_PREFIX) :],
                ts_use=t,
                thread=name,
                kind=thread.kind,
                model=message.get("model") if isinstance(message.get("model"), str) else None,
                effort=effort if isinstance(effort, str) and effort else None,
                path=raw_path if isinstance(raw_path, str) and raw_path else None,
                bench=bench,
                mid=mid,
            )
    elif entry_type == "user":
        message = r.get("message") if isinstance(r.get("message"), dict) else {}
        content = message.get("content")
        for block in content if isinstance(content, list) else []:
            if not (isinstance(block, dict) and block.get("type") == "tool_result"):
                continue
            d = index.delegations.get(str(block.get("tool_use_id")))
            if d is not None and d.ts_res is None:
                d.ts_res = parse_instant(r.get("timestamp"))


def read(root: Path) -> Index:
    """Recorre `raiz/**/*.jsonl` (en orden de ruta) y devuelve el índice. Nunca lanza por un
    fichero o una línea: los cuenta."""
    index = Index()
    root = Path(root)
    if not root.is_dir():
        return index
    order = [0]
    for file in sorted(root.rglob("*.jsonl")):
        parts = file.relative_to(root).parts
        kind = "subagent" if "subagents" in parts[:-1] else "main"
        bench = "Temp" in parts[0] if len(parts) > 1 else False
        name = str(file)
        thread = index.threads.setdefault(name, Thread(kind=kind))
        index.files += 1
        try:
            with file.open(encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    try:
                        r = json.loads(line)
                    except ValueError:
                        index.corrupt_lines += 1
                        continue
                    if isinstance(r, dict):
                        _read_line(index, r, name, thread, bench, order)
        except OSError:
            index.unreadable_files += 1
    for thread in index.threads.values():
        thread.compactions.sort()
    return index


# --- N y caducidades (REQ-043) ---------------------------------------------------------------


def n_and_expiries(index: Index, d: Delegation) -> tuple[int, int]:
    """`N` y caducidades de una delegación, dentro de su hilo (REQ-043).

    Petición = línea `assistant` no `<synthetic>`, una por `message.id` (su primera aparición).
    `t0` = el `tool_result` (o el `tool_use` si falta). `N` = peticiones con `ts > t0`, sin la que
    lleva el `tool_use` y anteriores al primer `compact_boundary` posterior a `t0`. Caducidad =
    hueco mayor que el TTL del hilo entre `t0` y la primera, o entre dos seguidas.
    """
    thread = index.threads[d.thread]
    t0 = d.ts_res or d.ts_use
    if t0 is None:
        return 0, 0
    cutoff = next((c for c in thread.compactions if c > t0), None)
    later = sorted(
        t
        for mid, t in thread.requests.items()
        if t > t0 and (cutoff is None or t < cutoff) and mid != d.mid
    )
    ttl = TTL_S.get(d.kind, TTL_S["main"])
    previous, caducidades = t0, 0
    for t in later:
        if (t - previous).total_seconds() > ttl:
            caducidades += 1
        previous = t
    return len(later), caducidades


def percentile(values: Iterable[float], q: float) -> float | None:
    """Percentil con interpolación lineal entre rangos (la mediana de un número par de casos es la
    media de los dos centrales). `None` sin valores."""
    xs = sorted(values)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    low = int(k)
    high = min(low + 1, len(xs) - 1)
    return xs[low] + (xs[high] - xs[low]) * (k - low)


def median(values: Iterable[float]) -> float | None:
    return percentile(values, 0.5)


# --- Cruce de las líneas del log (REQ-004) ----------------------------------------------------


def _same_path(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _supports_effort(model: str) -> bool:
    e = precios.entrada(model)
    return True if e is None else bool(e.get("admite_esfuerzo", True))


def entry_for(index: Index, d: Delegation, match_kind: str) -> dict:
    """La entrada del relleno de una línea casada (REQ-005): sin rutas, ids de sesión ni texto."""
    n, cad = n_and_expiries(index, d)
    model = precios.normalizar_id(d.model) if d.model else None
    effort = d.effort
    if effort is None and model and not _supports_effort(model):
        effort = "n/a"  # Haiku 4.5: no admite esfuerzo, no es un dato que falte (REQ-003)
    entry: dict = {"match": match_kind, "bench": d.bench, "n": n, "expiries": cad}
    if model:
        entry["caller_model"] = model
    entry["caller_kind"] = d.kind
    if effort:
        entry["caller_effort"] = effort
    return entry


def _by_tool(index: Index) -> dict[str, list[tuple[str, Delegation]]]:
    groups: dict[str, list[tuple[str, Delegation]]] = {}
    for tid, d in index.delegations.items():
        if d.ts_use is not None:
            groups.setdefault(d.tool, []).append((tid, d))
    return groups


def needs_backfill(row: dict) -> bool:
    """Una línea sin `caller_model`, o a la que le falta `N` (REQ-004)."""
    return not row.get("caller_model") or row.get("n") is None


def match_lines(
    lines: Iterable[tuple[str, dict]], index: Index, *, since: datetime
) -> dict[str, dict]:
    """`{clave: entrada}` para las líneas del log con `ts >= since` que lo necesitan (REQ-004).

    `lines` son pares `(clave, fila)` con la clave de `attribution.file_keys` calculada
    sobre el fichero ENTERO. Con `tool_use_id`, el cruce es exacto. Sin él, son candidatos los
    `tool_use` de la misma tool con el `ts` de la línea en [`tool_use` − 1 s, `tool_result` + 2 s]
    (o `tool_use` + 15 min si falta el resultado); con varios, el ÚNICO desempate es el `path`
    igual. Si sigue habiendo más de uno, `ambiguous`; con ninguno, `no_match`.
    """
    groups = _by_tool(index)
    result: dict[str, dict] = {}
    for key, row in lines:
        t = parse_instant(row.get("ts"))
        if t is None or t < since or not needs_backfill(row):
            continue
        tool_use_id = row.get("tool_use_id")
        if isinstance(tool_use_id, str) and tool_use_id:
            d = index.delegations.get(tool_use_id)
            result[key] = (
                entry_for(index, d, "exact")
                if d is not None
                else {"match": "no_match", "bench": False}
            )
            continue
        candidates = []
        for _tid, d in groups.get(str(row.get("tool") or ""), []):
            end = d.ts_res or (d.ts_use + NO_RESULT_WINDOW)
            if d.ts_use - MARGIN_BEFORE <= t <= end + MARGIN_AFTER:
                candidates.append(d)
        if len(candidates) == 1:
            result[key] = entry_for(index, candidates[0], "window")
        elif len(candidates) > 1:
            same_path = [d for d in candidates if _same_path(d.path, row.get("path"))]
            if len(same_path) == 1:
                result[key] = entry_for(index, same_path[0], "window+path")
            else:
                result[key] = {"match": "ambiguous", "bench": False}
        else:
            result[key] = {"match": "no_match", "bench": False}
    return result


# --- Cotejo (REQ-014) -------------------------------------------------------------------------


def cost_state(index: Index) -> list[dict]:
    """Filas «modelo × sesión» de la ÚLTIMA línea `cost-state` por posición de cada
    `(sessionId, startTime)`: `{"modelo", <los seis campos>}`. Sin ids de sesión."""
    rows: list[dict] = []
    for _position, usage in sorted(index.costs.values(), key=lambda x: x[0]):
        for model, values in usage.items():
            if not isinstance(values, dict):
                continue
            row = {"modelo": str(model)}
            for field_name in CHECK_FIELDS:
                row[field_name] = values.get(field_name) or 0
            rows.append(row)
    return rows
