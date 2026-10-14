"""Fronteras de tramo de las mediciones que comparan periodos (REQ-041, plan D9).

La frontera se decide por **version**, no por fecha: los logs de la Mac se miden en la PC y cada
maquina se actualiza cuando quiere. Para `usage-*.jsonl`, la version es la clave `v` que cada fila
lleva desde F1 (el `package_version` que proponia la spec; decision del 2026-10-14): una fila escrita
por una version igual o posterior a `package_version_after` va al tramo «despues»; una fila sin
version va **siempre** al de «antes», sea cual sea su fecha (enmienda del 2026-10-12). Para la telemetria de hooks, el conjunto de
hashes del lado «despues» vive en un fichero aparte que crea la ola B3: mientras no exista, el
conjunto es vacio y todo evento cae en «antes», como hoy.

Lo lee `measure_adoption.py` (lo conecta la ola B3). Solo la biblioteca estandar.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOUNDARIES = ROOT / "scripts" / "data" / "measurement_boundaries.json"
BEFORE = "before"
AFTER = "after"
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


def load(path: Path = BOUNDARIES) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _version(text: object) -> tuple[int, int, int] | None:
    match = _VERSION.match(str(text or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def row_version(row: dict) -> str | None:
    """La version del paquete que escribio la fila: su clave `v` (desde F1)."""
    value = row.get("v")
    return str(value) if value else None


def usage_side(row: dict, boundaries: dict | None = None) -> str:
    """`before` o `after` para una fila de `usage-*.jsonl`. Nunca mira la fecha."""
    boundaries = load() if boundaries is None else boundaries
    after = _version(boundaries["package_version_after"])
    written = _version(row_version(row))
    if after is None or written is None:
        return BEFORE
    return AFTER if written >= after else BEFORE


def hook_hashes_after(boundaries: dict | None = None, root: Path = ROOT) -> dict[str, set[str]]:
    """Los hashes «despues» por script de hook. Sin el fichero (antes de B3), vacio y sin error."""
    boundaries = load() if boundaries is None else boundaries
    path = root / boundaries["hook_hashes_after"]
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {script: set(hashes) for script, hashes in data.items()}
