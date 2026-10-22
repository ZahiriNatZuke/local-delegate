"""local-delegate — MCP que delega tareas mecánicas texto->texto a un LLM local.

Cliente genérico de cualquier endpoint OpenAI-compatible (llama-swap, Ollama,
LM Studio, vLLM). Ver README para configuración.

Este módulo no importa nada al cargarse, a propósito (REQ-003, decisión 4 del plan): lo carga
también cada hook del plugin (`python -I -m local_delegate.hook`), y ese camino no puede pagar el
servidor MCP ni el SDK. `main` despacha `hook` antes de importar `entrypoint`, y `__version__` se
calcula al pedirlo.
"""

from __future__ import annotations

import sys

__all__ = ["main"]


def main() -> None:
    """Punto de entrada del binario (`[project.scripts]`): `hook` primero, el resto a `entrypoint`."""
    if sys.argv[1:2] == ["hook"]:
        from .hook import run_hook

        run_hook(sys.argv[2:])  # sale siempre con 0, no vuelve
        return

    from .entrypoint import main as entrypoint_main

    entrypoint_main()


def __getattr__(name: str) -> object:
    # Derivado, nunca escrito a mano: estuvo clavado en "0.10.0" hasta la 0.19.0 porque
    # `scripts/bump_version.py` sube la versión en pyproject.toml, en las dos de server.json y en
    # uv.lock, y este atributo no estaba en esa lista. Sale de la misma llamada que el servidor MCP
    # declara en el handshake `initialize` y que el `--version` del CLI, así que los tres canales
    # públicos no pueden discrepar: solo hay un dato, en `version.py`. Es perezoso para que un hook
    # no lo pague.
    if name == "__version__":
        from .version import get_version

        value = get_version()
        globals()["__version__"] = value
        return value
    raise AttributeError(name)
