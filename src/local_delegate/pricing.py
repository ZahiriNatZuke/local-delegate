"""Tablas de precios y de densidad del paquete, y el cotejo puro contra lo que cobra Claude Code.

Una sola pregunta: cuánto cuesta un token de cada modelo de Claude y si esa tabla cuadra con lo
que calcula Claude Code. Las dos tablas viajan dentro del paquete (`resources/data/`) y se leen
con `importlib.resources`: **nada de red** al cargarlas (REQ-012). Las mantiene al día el
vigilante semanal del CI, no este módulo.

- `normalize_id` quita `[1m]` y el sufijo de fecha `-AAAAMMDD` (REQ-011).
- `entry` busca por id **exacto** tras normalizar: `claude-opus-5` nunca toma el precio de
  `claude-opus-5-5`. Un id sin entrada es «sin precio» (`None`), nunca 0 ni el de un parecido.
- `check_rows` y `verdict` implementan REQ-013 tal cual (port de
  `insumos/scripts/cotejo.py:juzga`, con la búsqueda web incluida).

Las tablas devueltas están en caché y se comparten: quien quiera variarlas (un test, un mutante)
trabaja sobre una copia.
"""

from __future__ import annotations

import functools
import json
import re
from importlib.resources import files

# Los seis campos de una fila «modelo × sesión» de `cost-state`, con sus nombres de Claude Code.
CHECK_FIELDS = (
    "inputTokens",
    "cacheCreationInputTokens",
    "cacheReadInputTokens",
    "outputTokens",
    "webSearchRequests",
    "costUSD",
)

# Por debajo de este coste una fila no se juzga: el redondeo de Claude Code pesa más que la tabla.
MIN_JUDGED_COST = 0.05

_DATE_SUFFIX = re.compile(r"-\d{8}$")


def _read_table(name: str) -> dict:
    resource = files("local_delegate").joinpath("resources", "data", name)
    return json.loads(resource.read_text(encoding="utf-8"))


@functools.cache
def load_prices() -> dict:
    """La tabla de precios del paquete (`resources/data/prices.json`). No abre sockets."""
    return _read_table("prices.json")


@functools.cache
def load_density() -> dict:
    """La tabla de densidad del paquete (`resources/data/density.json`). No abre sockets."""
    return _read_table("density.json")


def normalize_id(mid: str) -> str:
    """El id sin `[1m]` y sin sufijo de fecha: `claude-haiku-4-5-20251001` → `claude-haiku-4-5`."""
    return _DATE_SUFFIX.sub("", mid.replace("[1m]", ""))


def entry(mid: str, table: dict | None = None) -> dict | None:
    """La entrada de precios del modelo, buscada por id exacto tras normalizar; `None` si no hay.

    Con `table=None` usa la del paquete.
    """
    models = (table if table is not None else load_prices())["models"]
    return models.get(normalize_id(mid))


def family(mid: str, table: dict | None = None) -> str | None:
    """La familia de tokenizador del modelo (`new` | `previous`), o `None` si no está en la tabla."""
    e = entry(mid, table)
    return e["family"] if e is not None else None


def _judge(row: dict, table: dict) -> str | None:
    cost = row.get("costUSD") or 0.0
    if cost < MIN_JUDGED_COST:
        return None
    p = entry(row["model"], table)
    if p is None:
        return "unpriced"
    base = (
        (row.get("inputTokens") or 0) * p["input"]
        + (row.get("cacheReadInputTokens") or 0) * p["cache_read"]
        + (row.get("outputTokens") or 0) * p["output"]
    ) / 1e6
    base += (row.get("webSearchRequests") or 0) * table["web_search_per_1000"] / 1000
    cache_write = row.get("cacheCreationInputTokens") or 0
    # Claude Code no dice qué parte de la escritura fue a 5 min y cuál a 1 h: la banda va de
    # toda a 5 min a toda a 1 h.
    low = base + cache_write * p["w5m"] / 1e6
    high = base + cache_write * p["w1h"] / 1e6
    tolerance = max(0.005, 0.005 * cost)
    return "inside" if low - tolerance <= cost <= high + tolerance else "outside"


def check_rows(rows: list[dict], table: dict) -> list[str | None]:
    """Juzga cada fila «modelo × sesión» contra la tabla (REQ-013). Función pura.

    Cada fila es un dict con `model` (el id tal como lo escribe Claude Code) y los seis campos de
    `CHECK_FIELDS`. Devuelve, en el mismo orden, `inside`, `outside`, `unpriced`, o `None` para
    las filas de menos de `MIN_JUDGED_COST`, que no se juzgan.
    """
    return [_judge(row, table) for row in rows]


def verdict(results: list[str | None]) -> str:
    """`fail` si al menos una fila salió `outside` o `unpriced`; si no, `pass`."""
    bad = {"outside", "unpriced"}
    return "fail" if any(r in bad for r in results) else "pass"
