"""autostart.py — arranque OPCIONAL de un backend local (opt-in).

Desactivado por defecto (``LOCAL_DELEGATE_AUTOSTART=0``). El paquete asume que tu
endpoint OpenAI-compatible ya está corriendo. Este módulo es una comodidad para quien
use **llama-swap** y quiera que el MCP lo levante solo; es específico de ese backend.
Para Ollama / LM Studio / vLLM, arranca el servicio por tu cuenta.

Config por entorno:
  LLAMASWAP_EXE     ruta al ejecutable (si no, se busca ``llama-swap`` en el PATH)
  LLAMASWAP_CONFIG  ruta al config.yaml de llama-swap (opcional)
  LLAMASWAP_LISTEN  host:puerto en que escucha llama-swap (default 127.0.0.1:9292)
  LLAMASWAP_WATCH_CONFIG  1 añade -watch-config si hay config (default 0)
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from . import config


def _backend_up() -> bool:
    """True si el endpoint OpenAI-compatible responde a /models."""
    try:
        with httpx.Client(timeout=2.0) as c:
            return c.get(f"{config.BASE_URL}/models").is_success
    except httpx.HTTPError:
        return False


def _find_exe() -> str | None:
    for cand in (os.environ.get("LLAMASWAP_EXE", ""), "llama-swap"):
        if cand and (cand == "llama-swap" or Path(cand).is_file()):
            return cand
    return None


def ensure_backend(wait: float = 0.0) -> bool:
    """Si el backend no responde, intenta arrancar llama-swap como proceso independiente.

    Idempotente: si ya está arriba no hace nada. Con varias instancias del MCP la primera
    gana el puerto y las demás ven que ya está arriba. Devuelve True si acaba escuchando.
    Solo se invoca cuando ``LOCAL_DELEGATE_AUTOSTART`` está activo.
    """
    if _backend_up():
        return True
    exe = _find_exe()
    if exe:
        listen = os.environ.get("LLAMASWAP_LISTEN", "127.0.0.1:9292")
        cfg = os.environ.get("LLAMASWAP_CONFIG", "")
        args = [exe]
        if cfg:
            args += ["--config", cfg]
            watch = os.environ.get("LLAMASWAP_WATCH_CONFIG", "0").strip().lower()
            if watch not in {"0", "false", "no", "off", ""}:
                args += ["-watch-config"]
        args += ["--listen", listen]
        flags = 0
        if sys.platform == "win32":
            # CREATE_NO_WINDOW da a llama-swap una consola OCULTA que sus hijos (p. ej.
            # nvidia-smi para el GPU monitoring) heredan -> sin ventana emergente. No usar
            # DETACHED_PROCESS: sin consola, nvidia-smi crearía su propia ventana huérfana.
            # Sigue sobreviviendo al MCP porque Windows no mata a los hijos al salir el padre.
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            subprocess.Popen(
                args,
                creationflags=flags,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError:
            return _backend_up()
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if _backend_up():
            return True
        time.sleep(1.0)
    return _backend_up()
