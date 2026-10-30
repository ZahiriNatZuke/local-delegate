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
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCREENSHOT = ROOT / "docs" / "assets" / "dashboard.png"
MANIFEST = ROOT / "docs" / "assets" / "dashboard.json"
# Las dos capturas del README: la oscura (la de siempre) y la clara, que sirve `<picture>`.
SCREENSHOT_BY_THEME = {
    "dark": ROOT / "docs" / "assets" / "dashboard.png",
    "light": ROOT / "docs" / "assets" / "dashboard-light.png",
}
SCRIPT = ROOT / "scripts" / "dev" / "capture_dashboard.py"
PANEL = ROOT / "src" / "local_delegate" / "web" / "metrics.py"

# Lo que el script deja pasar al servidor real, con su motivo. Es una lista corta y explícita a
# propósito: crecer aquí es una decisión, no un descuido.
PASS_TO_REAL_SERVER = {
    # La versión del badge, el catálogo de modelos y el número de tools tienen que ser los de
    # verdad — el manifiesto los usa para fechar la captura.
    "/api/status",
}

REGENERATE = (
    "Regenera la captura y su manifiesto (necesita Playwright):\n"
    '  uv run python -c "import uvicorn; from local_delegate.web import metrics; '
    "uvicorn.run(metrics.app, host='127.0.0.1', port=9494)\"\n"
    "  uv run python scripts/dev/capture_dashboard.py --url http://127.0.0.1:9494/\n"
    "  uv run python scripts/dev/capture_dashboard.py --url http://127.0.0.1:9494/ --theme light\n"
    "Contra el repo, no contra el daemon del 9393: ese sirve la versión que tenga instalada."
)


def _manifest(png: Path = SCREENSHOT) -> dict:
    manifest = png.with_suffix(".json")
    if not manifest.is_file():
        pytest.fail(f"falta {manifest.relative_to(ROOT)}, que declara la captura.\n{REGENERATE}")
    return json.loads(manifest.read_text(encoding="utf-8"))


def _declared_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


@pytest.mark.parametrize("theme", sorted(SCREENSHOT_BY_THEME))
def test_the_manifest_describes_the_screenshot_in_the_repo(theme):
    """El hash del manifiesto es el del PNG real: nadie cambió la imagen por su cuenta."""
    png = SCREENSHOT_BY_THEME[theme]
    manifest = _manifest(png)
    assert png.is_file(), f"falta {png.relative_to(ROOT)}"
    blob = png.read_bytes()

    real = hashlib.sha256(blob).hexdigest()
    assert manifest["sha256"] == real, (
        f"la captura no es la que declara el manifiesto "
        f"(declarado {manifest['sha256'][:16]}…, real {real[:16]}…).\n{REGENERATE}"
    )
    assert manifest["bytes"] == len(blob)
    assert manifest["file"] == png.name
    assert manifest.get("theme") == theme, (
        f"{png.name} no se generó en tema {theme}: el panel sigue al sistema y Chromium\n"
        f"headless se presenta como claro si no se fija `color_scheme`.\n{REGENERATE}"
    )


@pytest.mark.parametrize("theme", sorted(SCREENSHOT_BY_THEME))
def test_the_screenshot_shows_the_current_project_version(theme):
    """La imagen luce el badge de versión: si el proyecto avanzó, la captura caducó."""
    manifest = _manifest(SCREENSHOT_BY_THEME[theme])
    version = _declared_version()
    assert manifest["version"] == version, (
        f"la captura se generó con la {manifest['version']} y el proyecto va por la {version}, "
        f"así que el badge del header enseña una versión que ya no es.\n{REGENERATE}"
    )


@pytest.mark.parametrize("theme", sorted(SCREENSHOT_BY_THEME))
def test_the_screenshot_is_in_the_language_of_the_readme(theme):
    """Desde la 0.36.0 el panel sigue al idioma del navegador, y Chromium sin `locale` dice
    `en-US`: la captura salía en inglés en un README en español. El manifiesto guarda el
    `<html lang>` de la página capturada."""
    assert _manifest(SCREENSHOT_BY_THEME[theme]).get("lang") == "es", (
        "la captura del README (en español) no se generó con el panel en español.\n" + REGENERATE
    )


def test_the_screenshot_does_not_publish_real_data_through_an_unmocked_endpoint():
    """Todo `/api/*` que la página pide o está mockeado, o está en la lista de los que pasan.

    Este es el fallo que motivó la comprobación: `/api/hooks` y `/api/stats` no estaban en los
    mocks, llegaban al servidor real y la captura publicaba la telemetría y los KPIs de quien la
    regeneraba. No saltó a la vista porque **dependía del entorno**: sin
    `LD_HOOK_TELEMETRY_LOG` la tarjeta de hooks se esconde sola, así que el escape era invisible
    para quien no tuviera la variable puesta.

    Se comparan los endpoints que la página **pide** —no los que el servidor expone— porque solo
    puede filtrar lo que el navegador llega a preguntar.
    """
    requested = set(re.findall(r"fetch\('(/api/[a-z/]+)", PANEL.read_text(encoding="utf-8")))
    mocked = set(
        re.findall(r"^\s*'(/api/[a-z/]+)':", SCRIPT.read_text(encoding="utf-8"), re.MULTILINE)
    )

    # Control positivo: si un refactor cambia la forma de pedir o de mockear, estas dos búsquedas
    # devolverían conjuntos vacíos y el test pasaría sin haber comprobado nada.
    assert len(requested) >= 6, f"la extracción de endpoints no encontró casi nada: {requested}"
    assert "/api/events" in mocked, f"la extracción de mocks no encontró los conocidos: {mocked}"

    leaking = requested - mocked - PASS_TO_REAL_SERVER
    assert not leaking, (
        f"la página pide {sorted(leaking)} y el script no lo intercepta, así que la captura "
        f"publicaría la respuesta real de quien la regenere.\n"
        f"Añádelo a MOCKS en {SCRIPT.relative_to(ROOT).as_posix()}, o a PASAN_AL_SERVIDOR_REAL "
        f"con su motivo si de verdad tiene que pasar."
    )


def test_the_manifest_is_not_written_by_hand():
    """El texto que explica de dónde sale el manifiesto viaja con él, no en un comentario suelto.

    Es la misma regla que el vendorizado: la fuente de verdad se explica donde vive.
    """
    manifest = _manifest()
    about = " ".join(manifest["_about"])
    assert "capture_dashboard.py" in about
    assert "/api/status" in about, (
        "el manifiesto tiene que dejar dicho que la versión sale del dashboard capturado y no de "
        "pyproject.toml, o alguien lo 'arreglará' cambiando la fuente"
    )
