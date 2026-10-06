"""Tablas de precios y de densidad del paquete, y el cotejo puro contra lo que cobra Claude Code.

Una sola pregunta: cuánto cuesta un token de cada modelo de Claude y si esa tabla cuadra con lo
que calcula Claude Code. Las dos tablas viajan dentro del paquete (`resources/datos/`) y se leen
con `importlib.resources`: **nada de red** al cargarlas (REQ-012). Las mantiene al día el
vigilante semanal del CI, no este módulo.

- `normalizar_id` quita `[1m]` y el sufijo de fecha `-AAAAMMDD` (REQ-011).
- `entrada` busca por id **exacto** tras normalizar: `claude-opus-5` nunca toma el precio de
  `claude-opus-5-5`. Un id sin entrada es «sin precio» (`None`), nunca 0 ni el de un parecido.
- `cotejar` y `veredicto` implementan REQ-013 tal cual (port de
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
CAMPOS_COTEJO = (
    "inputTokens",
    "cacheCreationInputTokens",
    "cacheReadInputTokens",
    "outputTokens",
    "webSearchRequests",
    "costUSD",
)

# Por debajo de este coste una fila no se juzga: el redondeo de Claude Code pesa más que la tabla.
COSTE_MINIMO_JUZGABLE = 0.05

_SUFIJO_FECHA = re.compile(r"-\d{8}$")


def _leer_tabla(nombre: str) -> dict:
    recurso = files("local_delegate").joinpath("resources", "datos", nombre)
    return json.loads(recurso.read_text(encoding="utf-8"))


@functools.cache
def cargar_precios() -> dict:
    """La tabla de precios del paquete (`resources/datos/precios.json`). No abre sockets."""
    return _leer_tabla("precios.json")


@functools.cache
def cargar_densidad() -> dict:
    """La tabla de densidad del paquete (`resources/datos/densidad.json`). No abre sockets."""
    return _leer_tabla("densidad.json")


def normalizar_id(mid: str) -> str:
    """El id sin `[1m]` y sin sufijo de fecha: `claude-haiku-4-5-20251001` → `claude-haiku-4-5`."""
    return _SUFIJO_FECHA.sub("", mid.replace("[1m]", ""))


def entrada(mid: str, tabla: dict | None = None) -> dict | None:
    """La entrada de precios del modelo, buscada por id exacto tras normalizar; `None` si no hay.

    Con `tabla=None` usa la del paquete.
    """
    modelos = (tabla if tabla is not None else cargar_precios())["modelos"]
    return modelos.get(normalizar_id(mid))


def familia(mid: str, tabla: dict | None = None) -> str | None:
    """La familia de tokenizador del modelo (`nueva` | `anterior`), o `None` si no está en la tabla."""
    e = entrada(mid, tabla)
    return e["familia"] if e is not None else None


def _juzgar(fila: dict, tabla: dict) -> str | None:
    coste = fila.get("costUSD") or 0.0
    if coste < COSTE_MINIMO_JUZGABLE:
        return None
    p = entrada(fila["modelo"], tabla)
    if p is None:
        return "sin_precio"
    base = (
        (fila.get("inputTokens") or 0) * p["entrada"]
        + (fila.get("cacheReadInputTokens") or 0) * p["lectura"]
        + (fila.get("outputTokens") or 0) * p["salida"]
    ) / 1e6
    base += (fila.get("webSearchRequests") or 0) * tabla["busqueda_web_por_1000"] / 1000
    escritura = fila.get("cacheCreationInputTokens") or 0
    # Claude Code no dice qué parte de la escritura fue a 5 min y cuál a 1 h: la banda va de
    # toda a 5 min a toda a 1 h.
    bajo = base + escritura * p["w5m"] / 1e6
    alto = base + escritura * p["w1h"] / 1e6
    tolerancia = max(0.005, 0.005 * coste)
    return "dentro" if bajo - tolerancia <= coste <= alto + tolerancia else "fuera"


def cotejar(filas: list[dict], tabla: dict) -> list[str | None]:
    """Juzga cada fila «modelo × sesión» contra la tabla (REQ-013). Función pura.

    Cada fila es un dict con `modelo` (el id tal como lo escribe Claude Code) y los seis campos de
    `CAMPOS_COTEJO`. Devuelve, en el mismo orden, `dentro`, `fuera`, `sin_precio`, o `None` para
    las filas de menos de `COSTE_MINIMO_JUZGABLE`, que no se juzgan.
    """
    return [_juzgar(fila, tabla) for fila in filas]


def veredicto(resultados: list[str | None]) -> str:
    """`falla` si al menos una fila salió `fuera` o `sin_precio`; si no, `pasa`."""
    malas = {"fuera", "sin_precio"}
    return "falla" if any(r in malas for r in resultados) else "pasa"
