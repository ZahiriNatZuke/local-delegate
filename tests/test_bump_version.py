"""Pruebas de `scripts/bump_version.py`.

El script existe para que un bump no pueda quedar a medias, así que lo que se comprueba aquí no
es solo que escriba el número nuevo: es que no reformatee los archivos, que no cambie nada más
que la versión y que se niegue a operar cuando algo no cuadra.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"

# Mismo criterio que en `test_vendor.py`: `scripts/` no viaja en el sdist, y la condición mira el
# **directorio** y no el fichero para que un borrado accidental de `bump_version.py` siga rompiendo
# la suite. A este script no lo cubre ningún workflow aparte —a diferencia de `check_vendor.py`,
# que `vendor-audit.yml` ejecuta directo—, así que su ausencia no se notaría hasta el próximo
# release.
if not SCRIPTS.is_dir():
    pytest.skip(
        "scripts/ no está en el árbol (sdist): estas pruebas necesitan el repositorio",
        allow_module_level=True,
    )


def _load_script():
    spec = importlib.util.spec_from_file_location("bump_version", SCRIPTS / "bump_version.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bump_version = _load_script()


PYPROJECT = """\
[project]
name = "local-delegate-mcp"
version = "0.11.0"
description = "Algo"

[tool.ruff]
# Una tabla posterior que también podría tener su propia clave `version`.
line-length = 100
"""

# Se conserva la tabla inline de `transport` a propósito: reserializar el JSON la expandiría.
SERVER_JSON = """\
{
  "name": "io.github.ZahiriNatZuke/local-delegate",
  "version": "0.11.0",
  "packages": [
    {
      "registryType": "pypi",
      "identifier": "local-delegate-mcp",
      "version": "0.11.0",
      "transport": { "type": "stdio" }
    }
  ]
}
"""

UV_LOCK = """\
[[package]]
name = "filelock"
version = "3.29.6"

[[package]]
name = "local-delegate-mcp"
version = "0.11.0"
source = { editable = "." }
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "server.json").write_text(SERVER_JSON, encoding="utf-8")
    (tmp_path / "uv.lock").write_text(UV_LOCK, encoding="utf-8")
    return tmp_path


def _apply(changes: dict) -> None:
    for path, (text, newline) in changes.items():
        bump_version._write(path, text, newline)


def test_lee_las_cuatro_versiones(repo: Path):
    versions = bump_version.read_versions(repo)
    assert set(versions.values()) == {"0.11.0"}
    # uv.lock es el sitio que ningún otro test cubría y el que se desfasó en la 0.8.1.
    assert versions["uv.lock"] == "0.11.0"
    assert versions["server.json (packages[0].version)"] == "0.11.0"


def test_bump_actualiza_pyproject_y_las_dos_versiones_de_server_json(repo: Path):
    _apply(bump_version.plan("0.12.0", repo))

    server = json.loads((repo / "server.json").read_text(encoding="utf-8"))
    assert server["version"] == "0.12.0"
    assert server["packages"][0]["version"] == "0.12.0"
    assert 'version = "0.12.0"' in (repo / "pyproject.toml").read_text(encoding="utf-8")


def test_bump_no_reformatea_el_resto_del_archivo(repo: Path):
    _apply(bump_version.plan("0.12.0", repo))

    text = (repo / "server.json").read_text(encoding="utf-8")
    assert '"transport": { "type": "stdio" }' in text
    assert text.count("\n") == SERVER_JSON.count("\n")

    pyproject = (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert "# Una tabla posterior" in pyproject
    assert "line-length = 100" in pyproject


def test_bump_preserva_el_terminador_de_linea_original(repo: Path):
    crlf = repo / "pyproject.toml"
    crlf.write_bytes(PYPROJECT.replace("\n", "\r\n").encode("utf-8"))

    _apply(bump_version.plan("0.12.0", repo))

    raw = crlf.read_bytes()
    assert b'version = "0.12.0"' in raw
    assert b"\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")  # ningún salto quedó suelto en LF


def test_rechaza_versiones_que_el_registro_normalizaria_distinto(repo: Path):
    for invalid in ["1.0", "v1.0.0", "1.0.0-rc1", "no-soy-una-version"]:
        with pytest.raises(bump_version.BumpError):
            bump_version.plan(invalid, repo)


def test_check_detecta_un_sitio_desfasado(repo: Path):
    # El error histórico exacto: todo bumpeado menos el lock.
    (repo / "uv.lock").write_text(
        UV_LOCK.replace('version = "0.11.0"', 'version = "0.10.0"'), encoding="utf-8"
    )

    with pytest.raises(bump_version.BumpError, match="no coinciden"):
        bump_version.check(repo)


def test_check_pasa_cuando_todo_coincide(repo: Path):
    assert bump_version.check(repo) == "0.11.0"


def test_check_pasa_sobre_el_repo_real():
    """Cubre uv.lock, que `test_release_metadata.py` no mira."""
    assert bump_version.check(ROOT)
