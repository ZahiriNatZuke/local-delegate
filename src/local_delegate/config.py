"""config.py — configuración por variables de entorno, sin rutas hardcodeadas.

local-delegate es un cliente GENÉRICO de cualquier endpoint OpenAI-compatible
(llama-swap, Ollama, LM Studio, vLLM…). Todo se configura por variables de entorno
con defaults sensatos y multiplataforma. El log de uso vive en el directorio de datos
del usuario (vía ``platformdirs``), nunca en una ruta absoluta de una máquina concreta.

Los defaults del catálogo de modelos son solo eso, *defaults documentados*: apuntan a
los ids de un setup de referencia con llama-swap. Cámbialos por env para tu backend
(p. ej. ``LOCAL_DELEGATE_MODEL_MECHANICAL=llama3.1`` con Ollama).
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "local-delegate"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


# --- Endpoint OpenAI-compatible ---------------------------------------------
BASE_URL = _env("LOCAL_DELEGATE_BASE_URL", "http://127.0.0.1:9292/v1").rstrip("/")
API_KEY = _env("LOCAL_DELEGATE_API_KEY", "")  # opcional; algunos endpoints lo exigen
HTTP_TIMEOUT = float(_env("LOCAL_DELEGATE_TIMEOUT", "180"))


# --- Log de uso/ahorro (JSONL) ----------------------------------------------
def _default_log() -> Path:
    return Path(user_data_dir(APP_NAME, appauthor=False)) / "usage.jsonl"


_log_env = os.environ.get("LOCAL_DELEGATE_LOG")
USAGE_LOG: Path = Path(_log_env) if _log_env else _default_log()


# --- Catálogo de modelos (roles configurables, defaults documentados) -------
MODEL_MECHANICAL = _env(
    "LOCAL_DELEGATE_MODEL_MECHANICAL", "gemma3-4b"
)  # clasificar, extraer, resumen corto
MODEL_LONG = _env("LOCAL_DELEGATE_MODEL_LONG", "llama31-8b")  # documentos largos (ctx amplio)
MODEL_CODE = _env("LOCAL_DELEGATE_MODEL_CODE", "qwen25-coder-14b")  # código / boilerplate
MODEL_FAST = _env("LOCAL_DELEGATE_MODEL_FAST", "qwen35-2b")  # ultrarrápido / trivial
ALLOWED_MODELS: set[str] = {MODEL_MECHANICAL, MODEL_LONG, MODEL_CODE, MODEL_FAST}

# Umbral para elegir el modelo "largo" vs "mecánico" en tools que enrutan por tamaño.
LONG_INPUT_CHARS = _env_int("LOCAL_DELEGATE_LONG_INPUT_CHARS", 6000)

# Tope de entrada por modelo (evita desbordar el ctx del backend).
_MAX_CHARS_DEFAULT = 20000
MAX_CHARS: dict[str, int] = {
    MODEL_MECHANICAL: _env_int("LOCAL_DELEGATE_MAX_CHARS_MECHANICAL", 20000),
    MODEL_LONG: _env_int("LOCAL_DELEGATE_MAX_CHARS_LONG", 48000),
    MODEL_CODE: _env_int("LOCAL_DELEGATE_MAX_CHARS_CODE", 20000),
    MODEL_FAST: _env_int("LOCAL_DELEGATE_MAX_CHARS_FAST", 12000),
}


def max_chars_for(model: str) -> int:
    """Tope de caracteres de entrada para un modelo (default si no está en el catálogo)."""
    return MAX_CHARS.get(model, _MAX_CHARS_DEFAULT)


# --- Web de métricas embebida -----------------------------------------------
WEB_ENABLED = _env_flag("LOCAL_DELEGATE_WEB", True)
WEB_HOST = _env("LOCAL_DELEGATE_WEB_HOST", "127.0.0.1")
WEB_PORT = _env_int("LOCAL_DELEGATE_WEB_PORT", 9393)
CHARS_PER_TOKEN = 4  # aproximación: tokens ~ chars / 4


# --- Auto-arranque del backend (opt-in, específico de llama-swap) -----------
AUTOSTART = _env_flag("LOCAL_DELEGATE_AUTOSTART", False)
