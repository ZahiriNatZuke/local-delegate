"""Every build carries the mod (SDD claude-plugin-and-mods, batch build-mod-in-build).

``register.js`` is generated from ``mod/*.js`` and not committed. The hatchling hook in
``hatch_build.py`` builds it on every wheel build. This test runs ``uv build`` (sdist, then the
wheel FROM the sdist, as PyPI and ``uv tool install .`` do), so the ``register.js`` that may sit in
the working tree cannot leak into the wheel: the sdist must not carry it, and the wheel must.
"""

from __future__ import annotations

import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = "local_delegate/resources/claude-plugin/local-delegate"

if not (ROOT / "scripts").is_dir():
    pytest.skip(
        "scripts/ no está en el árbol (sdist): esta prueba construye desde el repositorio",
        allow_module_level=True,
    )

UV = shutil.which("uv")


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> tuple[Path, Path]:
    if UV is None:
        pytest.skip("uv no está en PATH")
    out = tmp_path_factory.mktemp("dist")
    result = subprocess.run(
        [UV, "build", "--out-dir", str(out), str(ROOT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    (sdist,) = out.glob("*.tar.gz")
    (wheel,) = out.glob("*.whl")
    return sdist, wheel


def test_sdist_carries_what_regenerates_the_mod(built):
    sdist, _ = built
    with tarfile.open(sdist) as tar:
        names = {n.split("/", 1)[1] for n in tar.getnames() if "/" in n}
    for need in (
        "hatch_build.py",
        "_build_mod.py",
        f"src/{PLUGIN}/mod/common.js",
        f"src/{PLUGIN}/mod/commands.js",
        f"src/{PLUGIN}/mod/pinned-tools.js",
        f"src/{PLUGIN}/mod/i18n/es.json",
    ):
        assert need in names, f"falta {need} en el sdist"
    # The wheel's register.js must come from the hook, not from a file shipped in the sdist.
    assert f"src/{PLUGIN}/register.js" not in names
    assert not any(n.startswith("scripts/") for n in names), "scripts/ no va en el sdist"


def test_wheel_built_from_sdist_carries_register_js_with_its_pieces(built):
    _, wheel = built
    with zipfile.ZipFile(wheel) as zf:
        names = set(zf.namelist())
        assert f"{PLUGIN}/register.js" in names, "la rueda salió sin el mod"
        text = zf.read(f"{PLUGIN}/register.js").decode("utf-8")
    assert "// --- mod/commands.js" in text
    assert "// --- mod/pinned-tools.js" in text
    assert "register_commands(on, options)" in text
    assert "register_pinned_tools(on, options)" in text
    assert "_build_mod.py" not in names and "hatch_build.py" not in names
