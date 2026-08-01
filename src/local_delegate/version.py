"""De dónde sale la versión del paquete. Un módulo hoja, y por una razón concreta.

Este dato lo necesitan **cuatro** sitios que no se conocen entre sí: el handshake `initialize` del
servidor MCP, el `/api/daemon` del daemon, el `__version__` del paquete y el `--version` del CLI.
Vivía dentro de `server.py`, que es el módulo más pesado del paquete —arrastra el SDK, httpx2 y
filelock—, y eso obligaba a cualquiera que solo quisiera el número a importarlo entero.

El caso que lo destapó es el `--version` del CLI: `server.main()` importa `cli` en cuanto hay
argumentos, así que un `cli` que importara `server` cerraba un **ciclo de importación**. Diferir el
import lo escondía sin quitarlo —el grafo seguía teniendo el ciclo, y un analizador estático lo ve—
y sobre todo dejaba el acoplamiento puesto para el siguiente que tocara el orden de los imports.

Aquí no hay ciclo posible: este módulo no importa nada del paquete.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

_CACHE: str | None = None


def get_version() -> str:
    """Versión instalada del paquete, o ``0.0.0`` si no se puede saber.

    Se cachea porque lo consulta el arranque del servidor y cada respuesta de `/api/daemon`, y
    leer la metadata del paquete toca disco.

    El `0.0.0` no es un placeholder perezoso: es lo que corresponde cuando se ejecuta desde el
    árbol de fuentes sin instalar, y decir eso es más honesto que inventar un número o reventar.
    """
    global _CACHE
    if _CACHE is None:
        try:
            _CACHE = _pkg_version("local-delegate-mcp")
        except PackageNotFoundError:
            _CACHE = "0.0.0"
    return _CACHE
