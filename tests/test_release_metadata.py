"""Coherencia de los metadatos de publicación.

`server.json` (descriptor del registro oficial de MCP) declara la versión por duplicado y
aparte de `pyproject.toml`. Olvidar uno de esos bumps solo se nota al publicar —cuando PyPI ya
tiene la versión y no se puede sobreescribir—, así que se comprueba en cada PR y no solo en el
workflow del tag.
"""

from __future__ import annotations

import json
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _pyproject() -> dict:
    with (ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)


def _server_json() -> dict:
    return json.loads((ROOT / "server.json").read_text(encoding="utf-8"))


def test_server_json_version_matches_pyproject():
    version = _pyproject()["project"]["version"]
    server = _server_json()
    assert server["version"] == version
    assert [p["version"] for p in server["packages"]] == [version]


def test_server_json_points_at_the_published_pypi_package():
    package = _server_json()["packages"][0]
    assert package["registryType"] == "pypi"
    assert package["identifier"] == _pyproject()["project"]["name"]


def test_registry_description_fits_the_registry_limit():
    """El registro rechaza descripciones de más de 100 caracteres."""
    assert len(_server_json()["description"]) <= 100


def test_el_paquete_no_declara_su_version_a_mano():
    """`__version__` estuvo clavado en "0.10.0" hasta la 0.19.0 — nueve releases mintiendo.

    `scripts/bump_version.py` sube la versión en los cuatro sitios que conoce (pyproject.toml, las
    dos de server.json, uv.lock) y ese atributo no estaba en la lista, así que nadie lo tocaba
    nunca. No lo lee nadie *dentro* del repo, pero es el dato que consulta quien importa el
    paquete. Que hoy sea derivado no impide que mañana alguien vuelva a escribir un literal: esto
    lo impide.
    """
    import local_delegate

    esperada = _pyproject()["project"]["version"]
    instalada = metadata.version(_pyproject()["project"]["name"])

    # Se distinguen los dos fallos posibles: si la metadata instalada tampoco coincide con
    # pyproject.toml, el desfase es del entorno (bump sin reinstalar) y `__init__.py` no tiene
    # culpa. Mandar a mirar el fichero equivocado es justo el error que este repo persigue.
    if instalada != esperada:
        pytest.skip(
            f"el paquete instalado declara {instalada} y pyproject.toml {esperada}: "
            "el entorno está desincronizado, reinstala con `uv sync` antes de creerte este test"
        )

    assert local_delegate.__version__ == esperada, (
        f"local_delegate.__version__ dice {local_delegate.__version__!r} y pyproject.toml "
        f"{esperada!r}. Mira src/local_delegate/__init__.py: el atributo tiene que derivarse "
        "de la metadata del paquete, no escribirse a mano — bump_version.py no lo bumpea."
    )


def test_readme_carries_the_mcp_name_marker():
    """La validación PyPI↔registro busca esta línea en el README publicado."""
    name = _server_json()["name"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"mcp-name: {name}" in readme
