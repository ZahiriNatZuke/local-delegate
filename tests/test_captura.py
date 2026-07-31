"""La captura del README no puede quedarse vieja en silencio.

`docs/wiki/Publishing.md` pedía regenerarla **con palabras** y nadie lo verificaba: de las 25
releases del proyecto, solo 5 la regeneraron en su commit de tag, y la 0.16.0 se publicó con el
badge del header diciendo `v0.15.0`.

Aquí se comprueban las dos mitades, las dos deterministas y sin red:

- **Integridad:** el `sha256` del manifiesto es el del PNG que hay en el repo. Si la imagen cambió
  y el manifiesto no, algo se regeneró a mano y no por el script.
- **Actualidad:** la versión del manifiesto es la de `pyproject.toml`. Si no lo es, la imagen
  enseña un badge que ya no corresponde.

Lo que **no** se comprueba, a propósito: si el diseño del dashboard cambió. Exigiría hashear
`web/metrics.py`, que se toca por razones que no afectan al aspecto, y un check que grita en falso
acaba ignorado. Ese caso queda como riesgo aceptado, igual que los PNG de marca y la `og-image`.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
CAPTURA = RAIZ / "docs" / "assets" / "dashboard.png"
MANIFIESTO = RAIZ / "docs" / "assets" / "dashboard.json"

REGENERAR = (
    "Regenera la captura y su manifiesto (necesita Playwright):\n"
    '  uv run python -c "import uvicorn; from local_delegate.web import metrics; '
    "uvicorn.run(metrics.app, host='127.0.0.1', port=9494)\"\n"
    "  uv run python scripts/dev/capture_dashboard.py --url http://127.0.0.1:9494/\n"
    "Contra el repo, no contra el daemon del 9393: ese sirve la versión que tenga instalada."
)


def _manifiesto() -> dict:
    if not MANIFIESTO.is_file():
        pytest.fail(f"falta {MANIFIESTO.relative_to(RAIZ)}, que declara la captura.\n{REGENERAR}")
    return json.loads(MANIFIESTO.read_text(encoding="utf-8"))


def _version_declarada() -> str:
    datos = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    return datos["project"]["version"]


def test_el_manifiesto_describe_la_captura_que_hay_en_el_repo():
    """El hash del manifiesto es el del PNG real: nadie cambió la imagen por su cuenta."""
    manifiesto = _manifiesto()
    assert CAPTURA.is_file(), f"falta {CAPTURA.relative_to(RAIZ)}"
    blob = CAPTURA.read_bytes()

    real = hashlib.sha256(blob).hexdigest()
    assert manifiesto["sha256"] == real, (
        f"la captura no es la que declara el manifiesto "
        f"(declarado {manifiesto['sha256'][:16]}…, real {real[:16]}…).\n{REGENERAR}"
    )
    assert manifiesto["bytes"] == len(blob)
    assert manifiesto["file"] == CAPTURA.name


def test_la_captura_ensena_la_version_actual_del_proyecto():
    """La imagen luce el badge de versión: si el proyecto avanzó, la captura caducó."""
    manifiesto = _manifiesto()
    version = _version_declarada()
    assert manifiesto["version"] == version, (
        f"la captura se generó con la {manifiesto['version']} y el proyecto va por la {version}, "
        f"así que el badge del header enseña una versión que ya no es.\n{REGENERAR}"
    )


def test_el_manifiesto_no_se_escribe_a_mano():
    """El texto que explica de dónde sale el manifiesto viaja con él, no en un comentario suelto.

    Es la misma regla que el vendorizado: la fuente de verdad se explica donde vive.
    """
    manifiesto = _manifiesto()
    acerca = " ".join(manifiesto["_acerca_de"])
    assert "capture_dashboard.py" in acerca
    assert "/api/status" in acerca, (
        "el manifiesto tiene que dejar dicho que la versión sale del dashboard capturado y no de "
        "pyproject.toml, o alguien lo 'arreglará' cambiando la fuente"
    )
