"""legacy_names.py — equivalencias viejo→nuevo de los datos ya escritos (D2 del SDD).

Los datos que el paquete y los hooks escribieron con nombres en español (log de uso, estado de
enfriamiento, telemetría de hooks, cachés de atribución y coste…) se leen **para siempre** en el
formato viejo, y no se reescriben en el sitio. Este módulo es la única tabla de equivalencias:
todo lector del paquete traduce por aquí, y los hooks llevan en `hook_common.py` solo las
equivalencias que leen ellos, atadas a esta por un test de igualdad.

Cada ola del frente A añade las tablas de su formato (A2 la telemetría de hooks y los nombres en
disco; A3 el log de uso; A4 el enfriamiento…).

Forma de cada formato en `FORMATS`:

- `keys`: `{clave_vieja: clave_nueva}`;
- `values`: `{clave_nueva: {valor_viejo: valor_nuevo}}`, para los valores de enumeración.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

FORMATS: dict[str, dict[str, dict[str, Any]]] = {
    # Telemetría de hooks (`LD_HOOK_TELEMETRY_LOG`). `oferta` ya no la escribe nadie: solo se lee.
    "hook_telemetry": {
        "keys": {
            "motivo": "reason",
            "bloqueo": "block",
            "camino": "route",
            "rutas": "paths",
            "oferta": "offer",
        },
        "values": {
            "reason": {
                "acotada": "bounded",
                "codigo": "code",
                "pequeno": "small",
                "backend_ausente": "backend_missing",
                "modelo_enfriado": "model_cooled",
                "prosa_grande": "large_prose",
                "no_es_volcado": "not_a_dump",
                "sin_fichero": "no_file",
                "no_es_prosa": "not_prose",
                "bloqueo_apagado": "block_off",
                "mcp_ajeno": "foreign_mcp",
            },
            "block": {
                "encendido": "on",
                "apagado_fichero": "off_file",
                "apagado_variable": "off_variable",
            },
        },
    },
}

#: Ficheros en disco que comparten los hooks y el daemon, como `(viejo, nuevo)` (REQ-012). Se
#: escribe solo el nuevo y se leen los dos. `hook_common.FILE_NAMES` es su copia (los hooks no
#: importan el paquete) y `tests/test_hook_legacy_names.py` exige que sean iguales.
FILE_NAMES: dict[str, tuple[str, str]] = {
    "switch_file": ("local-delegate-bloqueo-apagado", "local-delegate-block-off"),
    "block_notes": ("local-delegate-bloqueos.jsonl", "local-delegate-blocks.jsonl"),
    "call_notes_dir": ("local-delegate-llamadas", "local-delegate-calls"),
    "health_prefix": ("local-delegate-salud-", "local-delegate-health-"),
}

#: Valores que el panel recibe de `/api/hooks` y que su diccionario de etiquetas tiene que entender
#: también en el formato viejo (REQ-009). El servidor lo inyecta en el HTML: el JS no copia la tabla.
#: Además de los motivos persistidos, van los cubos que fabricaba el propio servidor en español.
PANEL_VALUE_ALIASES: dict[str, dict[str, str]] = {
    "hookReason": {
        **FORMATS["hook_telemetry"]["values"]["reason"],
        "avisó": "suggested",
        "aviso": "suggested",
        "sin registrar": "unrecorded",
    },
    "hookCategory": {"sin categoría": "no_category"},
}


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
