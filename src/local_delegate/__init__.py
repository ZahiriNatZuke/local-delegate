"""local-delegate — MCP que delega tareas mecánicas texto->texto a un LLM local.

Cliente genérico de cualquier endpoint OpenAI-compatible (llama-swap, Ollama,
LM Studio, vLLM). Ver README para configuración.
"""

from __future__ import annotations

from .server import main

__all__ = ["main"]
__version__ = "0.10.0"
