"""local-delegate — MCP que delega tareas mecánicas texto->texto a un LLM local.

Cliente genérico de cualquier endpoint OpenAI-compatible (llama-swap, Ollama,
LM Studio, vLLM). Ver README para configuración.
"""

from __future__ import annotations

from .entrypoint import main
from .version import get_version

__all__ = ["main"]

# Derivado, nunca escrito a mano: estuvo clavado en "0.10.0" hasta la 0.19.0 porque
# `scripts/bump_version.py` sube la versión en pyproject.toml, en las dos de server.json y en
# uv.lock, y este atributo no estaba en esa lista. Sale de la misma llamada que el servidor MCP
# declara en el handshake `initialize` y que el `--version` del CLI, así que los tres canales
# públicos no pueden discrepar: solo hay un dato, en `version.py`.
__version__ = get_version()
