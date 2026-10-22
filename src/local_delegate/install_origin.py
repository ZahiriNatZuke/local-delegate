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
from collections.abc import Callable
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
