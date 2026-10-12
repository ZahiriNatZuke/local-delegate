"""legacy_names.py — equivalencias viejo→nuevo de los datos ya escritos (D2 del SDD).

Los datos que el paquete y los hooks escribieron con nombres en español (log de uso, estado de
enfriamiento, telemetría de hooks, cachés de atribución y coste…) se leen **para siempre** en el
formato viejo, y no se reescriben en el sitio. Este módulo es la única tabla de equivalencias:
todo lector del paquete traduce por aquí, y los hooks llevan en `hook_common.py` solo las
equivalencias que leen ellos, atadas a esta por un test de igualdad.

Estado tras la ola A0: **esqueleto**. La API está fijada y las tablas vacías; cada ola del frente
A añade las de su formato (p. ej. A3 el log de uso, A4 el enfriamiento).

Forma de cada formato en `FORMATS`:

- `keys`: `{clave_vieja: clave_nueva}`;
- `values`: `{clave_nueva: {valor_viejo: valor_nuevo}}`, para los valores de enumeración.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

FORMATS: dict[str, dict[str, dict[str, Any]]] = {}


def read_key(row: Mapping[str, Any], new: str, old: str, default: Any = None) -> Any:
    """El valor de `new` en `row`, o el de `old` si la fila es del formato viejo. Gana la nueva."""
    if new in row:
        return row[new]
    if old in row:
        return row[old]
    return default


def normalize(fmt: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """Copia de `row` con claves y valores de enumeración traducidos al formato nuevo.

    Una fila ya nueva sale igual; una clave que no está en la tabla se conserva tal cual. Si la
    fila trae la clave vieja y la nueva a la vez, gana la nueva.
    """
    table = FORMATS.get(fmt, {})
    keys: Mapping[str, str] = table.get("keys", {})
    values: Mapping[str, Mapping[str, str]] = table.get("values", {})
    out: dict[str, Any] = {}
    for key, value in row.items():
        new_key = keys.get(key, key)
        if new_key != key and new_key in row:
            continue  # la clave nueva también está: manda ella
        out[new_key] = value
    for key, mapping in values.items():
        value = out.get(key)
        if isinstance(value, str) and value in mapping:
            out[key] = mapping[value]
    return out
