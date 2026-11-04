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


def long_prompt(mid: str, table: dict | None = None) -> dict | None:
    """Los precios del tramo de prompt largo del modelo, o `None` si su precio no depende de eso.

    `{"above_tokens", "input", "w5m", "w1h", "cache_read", "output"}`: una petición cuyo prompt
    (entrada + escrituras + lecturas de caché) pasa de `above_tokens` paga estos precios en vez de
    los de `entry` (Claude Haiku 5.5). Búsqueda exacta tras normalizar, como `entry`.
    """
    tiers = (table if table is not None else load_prices()).get("long_prompt") or {}
    return tiers.get(normalize_id(mid))


def _row_cost(row: dict, p: dict, table: dict, write_price: str) -> float:
    cost = (
        (row.get("inputTokens") or 0) * p["input"]
        + (row.get("cacheReadInputTokens") or 0) * p["cache_read"]
        + (row.get("outputTokens") or 0) * p["output"]
        + (row.get("cacheCreationInputTokens") or 0) * p[write_price]
    ) / 1e6
    return cost + (row.get("webSearchRequests") or 0) * table["web_search_per_1000"] / 1000


def _judge(row: dict, table: dict) -> str | None:
    cost = row.get("costUSD") or 0.0
    if cost < MIN_JUDGED_COST:
        return None
    p = entry(row["model"], table)
    if p is None:
        return "unpriced"
    # Claude Code no dice qué parte de la escritura fue a 5 min y cuál a 1 h: la banda va de
    # toda a 5 min a toda a 1 h.
    low = _row_cost(row, p, table, "w5m")
    # Con tramo de prompt largo, la fila suma peticiones de los dos tramos sin decir cuántas de
    # cada uno: el techo es todo al precio del tramo largo.
    high = _row_cost(row, long_prompt(row["model"], table) or p, table, "w1h")
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


def priced_verdict(results: list[str | None]) -> str:
    """El veredicto solo con las filas que tienen precio: las `unpriced` se cuentan aparte.

    `fail` si alguna fila salió `outside`, o si hubo filas sin precio y ninguna con precio que las
    compense (nada avala la tabla). Sin filas juzgadas (todas por debajo de `MIN_JUDGED_COST`),
    `pass`, como `verdict`.
    """
    if "outside" in results:
        return "fail"
    if "unpriced" in results and "inside" not in results:
        return "fail"
    return "pass"
