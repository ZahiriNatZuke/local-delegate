"""Coherencia de los metadatos de publicación.

`server.json` (descriptor del registro oficial de MCP) declara la versión por duplicado y
aparte de `pyproject.toml`. Olvidar uno de esos bumps solo se nota al publicar —cuando PyPI ya
tiene la versión y no se puede sobreescribir—, así que se comprueba en cada PR y no solo en el
workflow del tag.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

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


def test_readme_carries_the_mcp_name_marker():
    """La validación PyPI↔registro busca esta línea en el README publicado."""
    name = _server_json()["name"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"mcp-name: {name}" in readme
