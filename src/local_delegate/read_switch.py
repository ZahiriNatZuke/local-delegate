"""Capa «activo» del hook de lectura: el fichero de estado `LOG_DIR/read-hook.json` (REQ-004).

El interruptor tiene dos capas, y este módulo solo es dueño de la primera:

- **Activo** (registrar y avisar): este fichero, **o** `LD_HOOK_READ_ENABLED`, **o** el argumento
  `--enabled` con el que la entrega por settings registra el script. En la entrega por plugin las
  entradas de `hooks.json` van siempre declaradas, así que el fichero sustituye a `--enabled`.
- **Bloquea**: sin cambios y fuera de aquí (`hook_common.block_state`):
  `~/.claude/local-delegate-block-off` > `LD_HOOK_READ_BLOCK`. Sus valores van a la telemetría de la
  ventana P-4 y no pueden moverse.

Contrato del fichero, que también escribe la orquestación de la entrega **sin importar este
módulo**: `{"active": true|false, "since": "<ISO 8601>"}`. Cualquier otra forma cuenta como apagado.

Es stdlib pura y barata a propósito: con la capa apagada, el hook de lectura sale después de
importar solo esto (ni `config`, que trae `platformdirs`, ni `hook_common`, que trae `urllib`). Por
eso resuelve `LOG_DIR` igual que `hook_common.log_dir` en vez de importarlo; un test ata los dos.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

#: Nombre del fichero de estado dentro de `LOG_DIR`.
FILE_NAME = "read-hook.json"

#: El argumento con el que la entrega por settings enciende el script.
ENABLED_FLAG = "--enabled"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def home(environ=None) -> Path:
    """La carpeta personal según `environ` (la variable que mira `Path.home()` en cada sistema).

    El daemon clasifica con el entorno que manda el mod, no con el suyo; sin la variable en ese
    entorno, la de este proceso (el mismo usuario)."""
    env = os.environ if environ is None else environ
    value = str(env.get("USERPROFILE" if os.name == "nt" else "HOME") or "").strip()
    return Path(value) if value else Path.home()


def log_dir(environ=None) -> Path:
    """`LOG_DIR` como lo resuelven `config.py` y `hook_common.log_dir`, según `environ`."""
    env = os.environ if environ is None else environ
    target = str(env.get("LOCAL_DELEGATE_LOG_DIR") or "").strip()
    if target:
        return Path(target)
    # Segmentos de ruta de `platformdirs`, no texto: van en variables y no en el `return`.
    if sys.platform == "win32":
        base = Path(env.get("LOCALAPPDATA") or home(env) / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = home(env) / "Library" / "Application Support"
    else:
        xdg = str(env.get("XDG_DATA_HOME") or "").strip()
        base = Path(xdg) if xdg else home(env) / ".local" / "share"
    return base / "local-delegate"


def path(environ=None) -> Path:
    """Dónde vive el fichero de estado."""
    return log_dir(environ) / FILE_NAME


def _load(environ=None) -> dict | None:
    try:
        data = json.loads(path(environ).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def active(environ=None) -> bool:
    """¿Dice el fichero que el hook de lectura está activo? Ante cualquier duda, no."""
    data = _load(environ)
    return data is not None and data.get("active") is True


def write(active: bool) -> Path:  # firma fijada por el contrato del plan
    """Escribe el estado, de forma atómica. `since` solo se mueve cuando el valor cambia."""
    from datetime import UTC, datetime

    previous = _load()
    if previous is not None and previous.get("active") is active and previous.get("since"):
        since = str(previous["since"])
    else:
        since = datetime.now(UTC).isoformat()
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{FILE_NAME}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps({"active": bool(active), "since": since}), encoding="utf-8")
    os.replace(temporary, target)
    return target


def enabled(argv: list[str] | tuple[str, ...] = (), environ: dict | None = None) -> bool:
    """La capa «activo» entera: el fichero, la variable o el argumento de settings."""
    if ENABLED_FLAG in argv:
        return True
    env = os.environ if environ is None else environ
    if str(env.get("LD_HOOK_READ_ENABLED", "")).strip().lower() in _TRUTHY:
        return True
    return active(env)
