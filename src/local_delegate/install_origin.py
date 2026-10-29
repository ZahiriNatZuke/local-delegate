"""install_origin.py — how the running package is installed: editable, `uv tool` or other.

A leaf module on purpose: it imports nothing from this package. It used to live in ``update``,
and ``claude_plugin`` (which the ``doctor`` checks import) reached it through ``update``, which
imports ``checks``: an import cycle (CodeQL ``py/cyclic-import``, PR #400). ``update`` re-exports
everything here, so its callers and the tests that double ``update.install_kind`` keep working.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

PACKAGE = "local-delegate-mcp"

EDITABLE = "editable"  # el código sale de un repo clonado
UV_TOOL = "uv-tool"  # instalado con `uv tool install`
OTHER = "other"  # pip, pipx, conda… no lo sabemos, y no lo adivinamos


# --- Instalación editable (PEP 610) -------------------------------------------
def editable_origin() -> Path | None:
    """Directorio del que se sirve el paquete si la instalación es **editable**, o None.

    Por PEP 610: ``direct_url.json`` con ``dir_info.editable`` verdadero. Importa porque en una
    instalación editable reiniciar el daemon **no cambia la versión** —el código sale del
    repo—, y quien actualiza esperaría lo contrario.
    """
    try:
        distribution = metadata.Distribution.from_name(PACKAGE)
        raw = distribution.read_text("direct_url.json")
    except Exception:  # PackageNotFoundError o metadatos ausentes: no es editable que sepamos
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not data.get("dir_info", {}).get("editable"):
        return None
    url = str(data.get("url", ""))
    if url.startswith("file://"):
        from urllib.parse import unquote, urlparse

        path = unquote(urlparse(url).path)
        if sys.platform == "win32" and re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
        return Path(path)
    return Path(url) if url else None


# --- Cómo está instalado esto -------------------------------------------------
def install_kind(editable: Callable[[], Path | None] | None = None) -> str:
    """Cómo está instalado el paquete **que se está ejecutando**.

    El matiz de «que se está ejecutando» es el importante: en una máquina pueden convivir la
    instalación de ``uv tool`` y una editable del repo, y de hecho conviven en la de desarrollo.
    Responder por la que no corre sería el mismo falso diagnóstico que ya costó caro aquí con el
    backend en 401.

    ``uv tool`` deja un ``uv-receipt.toml`` en la raíz del entorno; el ``.venv`` de un repo no lo
    tiene. Se mira ese fichero y no ``uv tool dir``, ni ``UV_TOOL_DIR``, ni una ruta por sistema
    operativo: es una lectura local que responde igual en los tres, sin depender de que ``uv``
    esté en el PATH de este proceso.

    ``editable`` replaces ``editable_origin``: ``update`` passes its own, so a test that doubles
    ``update.editable_origin`` still changes the answer of ``update.install_kind``.
    """
    if (editable or editable_origin)():
        # Gana sobre cualquier otra cosa: es lo que gobierna de dónde sale el código.
        return EDITABLE
    try:
        # `sys.prefix` se lee AQUÍ y no en una constante del módulo: capturado al importar, un
        # test no podría doblarlo y estaría comprobando la máquina en la que corre.
        receipt = Path(sys.prefix) / "uv-receipt.toml"
        text = receipt.read_text(encoding="utf-8", errors="replace")
    except Exception:  # no existe, no se puede leer, sys.prefix raro… nada que afirmar
        return OTHER
    # Basta con que nombre nuestro paquete: parsear el TOML sería precisión que no hace falta
    # para responder «¿este entorno es el nuestro?». `local-delegate-mcp` es distintivo de sobra;
    # con un nombre corto esta comparación por subcadena daría falsos positivos.
    return UV_TOOL if PACKAGE in text else OTHER


# --- Instalación de `uv tool` fijada a una versión (issue #488) ------------------
# Con `uv tool install "local-delegate-mcp==X.Y.Z"` uv guarda la fijación en el receipt, y
# `uv tool upgrade` responde «Nothing to upgrade» con código 0: el consejo de siempre no mueve
# nada. Lo que sí la mueve es `uv tool install <paquete>@latest`, que además quita la fijación.

# Only safe tokens reach a command we print: a receipt is a local file, but the hint is meant to
# be pasted into a shell, so anything odd in it means «not recognized», never «print it as is».
_SAFE_VERSION = re.compile(r"^[0-9][0-9A-Za-z.+!_-]*$")
_SAFE_EXTRA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# A shell command, not prose: same treatment as `update.UV_TOOL_UPGRADE`.
UV_TOOL_INSTALL_LATEST = "uv tool install {target}"


@dataclass(frozen=True)
class UvToolPin:
    """An exact pin found in the `uv tool` receipt: the version and the extras installed."""

    version: str
    extras: tuple[str, ...] = ()


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def uv_tool_pin() -> UvToolPin | None:
    """The exact version the `uv tool` install is pinned to, or None.

    None also covers every case where the receipt is missing, unreadable or has a shape this
    does not recognize: then the usual advice (`uv tool upgrade`) stays. Never raises.
    """
    try:
        receipt = Path(sys.prefix) / "uv-receipt.toml"
        data = tomllib.loads(receipt.read_text(encoding="utf-8"))
        requirements = data["tool"]["requirements"]
        ours = [
            entry
            for entry in requirements
            if isinstance(entry, dict) and _canonical(str(entry.get("name", ""))) == PACKAGE
        ]
        if len(ours) != 1:
            return None
        spec = ours[0].get("specifier")
        if not isinstance(spec, str):
            return None
        spec = spec.strip()
        if "," in spec:
            return None
        if spec.startswith("==="):
            version = spec[3:].strip()
        elif spec.startswith("=="):
            version = spec[2:].strip()
        else:
            return None  # `>=`, `~=`, `<`…: a range that `uv tool upgrade` can still move
        if not _SAFE_VERSION.match(version):  # also rejects `==0.45.*`
            return None
        raw_extras = ours[0].get("extras", [])
        if not isinstance(raw_extras, list):
            return None
        extras = tuple(str(extra) for extra in raw_extras)
        if not all(_SAFE_EXTRA.match(extra) for extra in extras):
            return None
        return UvToolPin(version, extras)
    except Exception:  # sin receipt, TOML roto, claves ausentes, tipos raros: nada que afirmar
        return None


def uv_tool_reinstall_command(pin: UvToolPin) -> str:
    """`uv tool install <paquete>[extras]@latest`: the command that moves a pinned install.

    The extras go in: dropping `[llamaswap]` would reinstall without the backend it was installed
    with. Quoted only when there are extras, because the brackets are a glob in zsh.
    """
    if not pin.extras:
        return UV_TOOL_INSTALL_LATEST.format(target=f"{PACKAGE}@latest")
    return UV_TOOL_INSTALL_LATEST.format(target=f'"{PACKAGE}[{",".join(pin.extras)}]@latest"')
