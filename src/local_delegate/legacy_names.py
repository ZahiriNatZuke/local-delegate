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

#: Valores de `failures.FailureClass` (`error_class`, `fallback_class` y `affinity_dropped_class`
#: del log de uso, y `clase` de los eventos de enfriamiento). `enfriamiento` no es un miembro del
#: enum: es la clase que el daemon escribe en `fallback_class` cuando salta por un modelo enfriado.
FAILURE_CLASS_VALUES: dict[str, str] = {
    "peticion": "request",
    "capacidad_o_carga": "capacity_or_load",
    "timeout_lectura": "read_timeout",
    "configuracion": "configuration",
    "modelo": "model",
    "sin_clasificar": "unclassified",
    "enfriamiento": "cooldown",
}

#: Valores de `failures.ConnectionCause` (`connection_failure` del log de uso y `cause` de `/api/*`).
CONNECTION_CAUSE_VALUES: dict[str, str] = {
    "rechazada": "refused",
    "sin_ruta": "no_route",
    "timeout_conexion": "connect_timeout",
    "credencial": "credential",
    "sin_respuesta": "no_response",
    "respuesta_invalida": "invalid_response",
    "url_invalida": "invalid_url",
    "transporte": "transport",
    "desconocida": "unknown",
}

FORMATS: dict[str, dict[str, dict[str, Any]]] = {
    # Log de uso (`usage-*.jsonl`).
    "usage": {
        "keys": {
            "bloqueo_id": "block_id",
            "secciones": "sections",
            "fallo_conexion": "connection_failure",
        },
        "values": {
            "error_class": FAILURE_CLASS_VALUES,
            "fallback_class": FAILURE_CLASS_VALUES,
            "affinity_dropped_class": FAILURE_CLASS_VALUES,
            "connection_failure": CONNECTION_CAUSE_VALUES,
        },
    },
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
    # La causa de `/api/backend` y la clase de fallo de un evento (`cause` de `acct()`).
    "connectionCause": CONNECTION_CAUSE_VALUES,
    "failureClass": FAILURE_CLASS_VALUES,
}


def new_value(table: Mapping[str, str], value: Any) -> Any:
    """`value` en el formato nuevo si es un valor viejo de `table`; si no, tal cual."""
    if isinstance(value, str):
        return table.get(value, value)
    return value


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
