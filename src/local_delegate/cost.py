"""Densidad de Claude por evento, fusión del relleno y tramo de cobertura (coste-api-y-cuota).

Tres preguntas, un solo sitio de verdad para cada una:

- **¿Cuántos caracteres hacen un token de Claude en esta fila?** `resolve_density(event)`
  (REQ-031 a REQ-033): familia de tokenizador del modelo de quien llamó (o del respaldo), clase de
  contenido (REQ-032), columna (`read_format` si se leyó por `path`, que es lo que habría devuelto
  `Read`) y respaldo de celda en su único orden. Devuelve `c` en **centésimas** con su origen. Ni
  `server.tokens_claude` ni el JS del panel resuelven nada: solo dividen por lo que trae la fila.
- **¿Qué se sabe de quien llamó?** `merge(rows, log_dir=...)` (REQ-006): por campo, la línea del
  log manda, luego el relleno (`attribution-AAAAMM.json`) y por último el respaldo declarado
  (REQ-008). En el mismo paso añade la densidad resuelta. Copia cada fila: nunca muta las de la
  caché del lector.
- **¿En qué tramo de la barra cae?** `segment(row, now=..., cleanup_days=...)` (REQ-007).

Solo stdlib; no abre sockets ni lee `~/.claude`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import attribution, config, pricing, test_windows

# El respaldo declarado (REQ-008): el grupo más frecuente medido (135 de 149 atribuidas).
DECLARED_FALLBACK = {"model": "claude-opus-5-5", "thread": "subagent"}
THREADS = ("main", "subagent")

MARK_ASSUMED_FAMILY = "assumed_family"
MARK_FAMILY_DENSITY = "family_density"

# Clase de contenido (REQ-032): primero por la tool, luego por la extensión del `path`. La lista es
# la de `insumos/scripts/atribucion_n.py`, para que el panel y el script den lo mismo (REQ-048).
CLASS_BY_TOOL = {
    "local_lint_summary": "log",
    "local_commit_msg": "diff",
    "local_explain_code": "code",
}
_EXTENSIONS = {
    "prose": ".md .markdown .txt .rst .html .htm",
    "code": (
        ".py .js .mjs .cjs .ts .tsx .jsx .ps1 .psm1 .sh .bash .java .go .rs .c .h .cpp .cs .rb"
        " .php .css .scss .sql .kt .swift"
    ),
    "structured": ".json .jsonl .yaml .yml .toml .lock .csv .xml .ini",
    "log": ".log",
    "diff": ".diff .patch",
}
CLASS_BY_EXTENSION = {ext: kind for kind, exts in _EXTENSIONS.items() for ext in exts.split()}

# Lo que la tool devuelve a Claude (`returned`) y lo que escribe a fichero (`output`) no va
# numerado: columna `unnumbered`, y la clase depende solo de la tool (REQ-031).
_RETURNED_CLASS = {"local_extract": "structured", "local_boilerplate": "code"}
_OUTPUT_CLASS = {"local_boilerplate": "code"}

# Campos que el relleno aporta a la fila (REQ-005), en el orden en que se funden.
BACKFILL_FIELDS = (
    "caller_model",
    "caller_kind",
    "caller_effort",
    "n",
    "expiries",
    "match",
    "bench",
)

SEGMENTS = ("excluded", "at_call", "backfilled", "pending", "assumed")
_UNRECOVERABLE_MATCHES = ("ambiguous", "no_match")

_MONTH = re.compile(r"^(\d{4})-(\d{2})")


def _empty(value: object) -> bool:
    return value is None or value == ""


def is_image(event: dict) -> bool:
    """La misma regla que `server._accounting`: unidad distinta de `chars` (o el histórico de
    `local_describe_image`, anterior al campo `input_unit`)."""
    unit = event.get("input_unit") or (
        "bytes" if event.get("tool") == "local_describe_image" else "chars"
    )
    return unit != "chars"


def _extension(path: object) -> str:
    """La extensión en minúsculas, sin depender del separador del sistema donde corre el test."""
    if not isinstance(path, str):
        return ""
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    dot = name.rfind(".")
    return name[dot:].lower() if dot > 0 else ""


def content_class(event: dict) -> str:
    """`prose`, `code`, `log`, `structured`, `diff` u `other`, sin leer el texto (REQ-032)."""
    by_tool = CLASS_BY_TOOL.get(str(event.get("tool") or ""))
    if by_tool:
        return by_tool
    return CLASS_BY_EXTENSION.get(_extension(event.get("path")), "other")


def fallback() -> dict:
    """El modelo y el hilo con que se valora una delegación sin modelo (REQ-008).

    `config.COST_FALLBACK` (`modelo` o `modelo:main|subagent`; solo `modelo` = `subagent`) manda
    sobre el declarado. Un valor vacío usa el declarado; uno que no se entiende o cuyo modelo no
    está en la tabla de precios, también, pero con `fallback_invalid: True` para que se diga.
    """
    declared = dict(DECLARED_FALLBACK, fallback_invalid=False)
    value = str(config.COST_FALLBACK or "").strip()
    if value:
        model, sep, thread = value.partition(":")
        model = pricing.normalize_id(model.strip())
        thread = thread.strip() if sep else "subagent"
        if model and thread in THREADS and pricing.entry(model) is not None:
            declared = {"model": model, "thread": thread, "fallback_invalid": False}
        else:
            declared["fallback_invalid"] = True
    declared["family"] = pricing.family(declared["model"])
    return declared


def family_and_marks(model: str) -> tuple[str, list[str]]:
    """La familia de tokenizador del modelo y las marcas de supuesto que lleva (REQ-030/031)."""
    entry = pricing.entry(model) if model else None
    if entry is None:
        return "new", [MARK_ASSUMED_FAMILY]
    family = entry["family"]
    measured = pricing.load_density()["families"][family].get("measured_with", [])
    if pricing.normalize_id(model) in measured:
        return family, []
    return family, [MARK_FAMILY_DENSITY]


def _cell(family: str, kind: str, column: str) -> list:
    """`[c100, origen]` con el respaldo de celda en su único orden (REQ-031): (1) la celda exacta,
    `measured`; (2) la misma clase en la columna `unnumbered`, `unnumbered`; (3) la mayor `c` de la
    columna `unnumbered` de la familia, `conservative`. (2) y (3) dan menos tokens, nunca más."""
    table = pricing.load_density()["families"][family]
    exact = table.get(column, {})
    if kind in exact:
        return [int(exact[kind]), "measured"]
    unnumbered = table["unnumbered"]
    if kind in unnumbered:
        return [int(unnumbered[kind]), "unnumbered"]
    return [int(max(unnumbered.values())), "conservative"]


def resolve(event: dict) -> dict:
    """`density`, `family` y `marks` de la fila (REQ-033). El modelo es `caller_model` (ya
    fundido) o, si falta, el del respaldo."""
    model = event.get("caller_model") or fallback()["model"]
    family, marks = family_and_marks(str(model))
    if is_image(event):
        # La imagen sale entera del neto (REQ-038): ningún `tipo` tiene densidad.
        density: dict = {"text": None, "returned": None, "output": None}
    else:
        tool = str(event.get("tool") or "")
        column = "read_format" if event.get("source") == "path" else "unnumbered"
        density = {
            "text": _cell(family, content_class(event), column),
            "returned": _cell(family, _RETURNED_CLASS.get(tool, "prose"), "unnumbered"),
            "output": _cell(family, _OUTPUT_CLASS.get(tool, "prose"), "unnumbered"),
        }
    return {"density": density, "family": family, "marks": marks}


def resolve_density(event: dict) -> dict:
    """`{"text": [c100, origen], "returned": [...], "output": [...]}`; `None` en las tres si el
    evento es una imagen. Las reglas de REQ-031 y REQ-032 viven solo aquí."""
    return resolve(event)["density"]


def merge_row(row: dict, entry: dict | None = None, *, fallback_: dict | None = None) -> dict:
    """Una COPIA de la fila con el relleno, el respaldo y la densidad (REQ-006).

    Por campo: (1) el valor de la línea; (2) el del relleno; (3) el respaldo (solo modelo e hilo).
    `caller_origin` dice de dónde salió el modelo (`line`, `backfill` o `fallback`), que es lo que
    necesita el tramo de la barra.
    """
    out = dict(row)
    entry = entry if isinstance(entry, dict) else {}
    for field in BACKFILL_FIELDS:
        if _empty(out.get(field)) and not _empty(entry.get(field)):
            out[field] = entry[field]
    if not _empty(row.get("caller_model")):
        origin = "line"
    elif not _empty(entry.get("caller_model")):
        origin = "backfill"
    else:
        origin = "fallback"
        r = fallback_ if fallback_ is not None else fallback()
        out["caller_model"] = r["model"]
        if _empty(out.get("caller_kind")):
            out["caller_kind"] = r["thread"]
        if r.get("fallback_invalid"):
            out["fallback_invalid"] = True
    out["caller_origin"] = origin
    out.update(resolve(out))
    return out


def _month(ts: object) -> str | None:
    m = _MONTH.match(ts) if isinstance(ts, str) else None
    return f"{m.group(1)}{m.group(2)}" if m else None


def merge(rows: Iterable[dict], *, log_dir: Path) -> list[dict]:
    """Las filas de UN fichero del log, fundidas y resueltas, en su orden.

    Hay que pasarle el fichero ENTERO, antes de filtrar por rango: la clave de una línea sin
    `tool_use_id` lleva su ordinal dentro del fichero (`attribution.file_keys`). El
    relleno de cada línea se busca en `attribution-AAAAMM.json` del mes de su `ts`.
    """
    rows = list(rows)
    keys = attribution.file_keys(rows)
    by_month: dict[str | None, dict[str, dict]] = {}
    r = fallback()
    # Ventanas de prueba (test-windows-out-of-metrics, REQ-005): se estampa `test_window` en la
    # COPIA; el fichero de log no cambia. Una sola lectura (cacheada) y un solo reloj por llamada.
    windows = test_windows.load(log_dir)
    now = datetime.now(UTC)
    merged: list[dict] = []
    for row, key in zip(rows, keys, strict=True):
        month = _month(row.get("ts"))
        if month not in by_month:
            by_month[month] = attribution.read_backfill(log_dir, month) if month else {}
        out = merge_row(row, by_month[month].get(key), fallback_=r)
        if windows.windows:
            window = windows.find(row.get("ts"), now=now)
            if window:
                out["test_window"] = window
        merged.append(out)
    return merged


def in_flight_row(
    *, tool: str, source: str, path: str | None = None, input_unit: str = "chars"
) -> dict:
    """La fila de la llamada en curso, fundida como la del panel, para los mensajes a Claude
    (REQ-035): con `caller_*` si la nota del hook ya está y, si no, con el respaldo."""
    row: dict = {"tool": tool, "source": source}
    if path:
        row["path"] = path
    if input_unit != "chars":
        row["input_unit"] = input_unit
    try:
        row.update(attribution.current_call())
    except Exception:
        pass  # observar nunca rompe una tool: sin atribución, respaldo
    return merge_row(row)


def _instant(ts: object) -> datetime | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        t = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def segment(row: dict, *, now: datetime, cleanup_days: int) -> str:
    """El tramo de la barra de cobertura de una fila fundida (REQ-007), en su orden:
    `excluded`, `at_call`, `backfilled`, `pending` o `assumed`."""
    if attribution.exclusion_reason(row, {"bench": row.get("bench")}):
        return "excluded"
    origin = row.get("caller_origin")
    if origin is None:
        origin = "line" if not _empty(row.get("caller_model")) else "fallback"
    if origin == "line":
        return "at_call"
    if origin == "backfill":
        return "backfilled"
    if row.get("match") in _UNRECOVERABLE_MATCHES:
        return "assumed"
    t = _instant(row.get("ts"))
    if t is not None and now - t < timedelta(days=cleanup_days):
        return "pending"
    return "assumed"
