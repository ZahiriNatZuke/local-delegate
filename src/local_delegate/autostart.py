"""autostart.py — arranque OPCIONAL de un backend local (opt-in).

Desactivado por defecto (``LOCAL_DELEGATE_AUTOSTART=0``). El paquete asume que tu
endpoint OpenAI-compatible ya está corriendo. Este módulo es una comodidad para quien
use **llama-swap** y quiera que el MCP lo levante solo; es específico de ese backend.
Para Ollama / LM Studio / vLLM, arranca el servicio por tu cuenta.

Config por entorno:
  LLAMASWAP_EXE     ruta ABSOLUTA al ejecutable (si no, se busca ``llama-swap`` en las carpetas
                    absolutas del PATH, nunca en el directorio actual)
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

import httpx2

from . import config, i18n


def _backend_up() -> bool:
    """True si el endpoint OpenAI-compatible responde a /models."""
    try:
        with httpx2.Client(timeout=2.0) as c:
            return c.get(f"{config.BASE_URL}/models", headers=config.backend_headers()).is_success
    except httpx2.HTTPError:
        return False


def which_absolute(name: str) -> str | None:
    """Absolute path of ``name`` searched ONLY in the absolute folders of ``PATH``.

    Neither ``Popen`` with a bare name nor ``shutil.which`` are safe on Windows: both look in the
    current directory first (``which`` skips it only when ``NoDefaultCurrentDirectoryInExePath``
    is set, and only from Python 3.12), so a ``llama-swap.exe`` shipped in a cloned repo would run
    with the user's rights. Relative ``PATH`` entries (``.``, empty) are skipped for the same
    reason; the current folder is searched only when it is in ``PATH`` as an absolute path.
    """
    if os.path.dirname(name):
        return None
    exts = [""]
    if sys.platform == "win32" and not Path(name).suffix:
        suffixes = os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD"
        exts = [ext for ext in suffixes.split(os.pathsep) if ext]
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        folder = Path(entry.strip().strip('"'))
        if not entry.strip() or not folder.is_absolute():
            continue
        for ext in exts:
            cand = folder / (name + ext)
            if cand.is_file() and (sys.platform == "win32" or os.access(cand, os.X_OK)):
                return str(cand)
    return None


def configured_exe_problem() -> str | None:
    """Warning text if ``LLAMASWAP_EXE`` is set but is not an absolute path to an existing file."""
    configured = config.llamaswap_exe()
    if not configured:
        return None
    path = Path(configured)
    if path.is_absolute() and path.is_file():
        return None
    return i18n.t("common.autostart.exe_invalid", path=configured)


def _find_exe() -> str | None:
    """Absolute path of llama-swap: ``LLAMASWAP_EXE`` if valid, else the ``PATH``; never a bare name.

    A set but invalid ``LLAMASWAP_EXE`` gives None (no fallback to ``PATH``): whoever set it meant
    that binary, and running another one silently would hide the mistake.
    """
    configured = config.llamaswap_exe()
    if configured:
        return None if configured_exe_problem() else str(Path(configured))
    return which_absolute("llama-swap")


def ensure_backend(wait: float = 0.0) -> bool:
    """Si el backend no responde, intenta arrancar llama-swap como proceso independiente.

    Idempotente: si ya está arriba no hace nada. Con varias instancias del MCP la primera
    gana el puerto y las demás ven que ya está arriba. Devuelve True si acaba escuchando.
    Solo se invoca cuando ``LOCAL_DELEGATE_AUTOSTART`` está activo.
    """
    if _backend_up():
        return True
    problem = configured_exe_problem()
    if problem:
        print(problem, file=sys.stderr)
    exe = _find_exe()
    if exe:
        listen = config.llamaswap_listen()
        cfg = config.llamaswap_config_path()
        args = [exe]
        if cfg:
            args += ["--config", cfg]
            if config.llamaswap_watch_config():
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
