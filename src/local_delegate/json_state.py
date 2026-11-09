"""Ficheros JSON compartidos entre procesos: leer sin romper y escribir sin mezclar.

Los usan `inflight.json` (delegaciones en curso de todas las sesiones) y el estado de enfriamiento.
Viven aquí, y no copiados en cada uno, porque el cuidado que llevan —temporal con el pid en el
nombre, antivirus de Windows que no deja borrar— se aprendió a golpes y dos copias se separarían
solas.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict:
    """El objeto JSON del fichero, o `{}` si no existe, no se puede leer o no es un objeto."""
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json_atomic(path: Path, data: dict) -> None:
    # El temporal lleva el pid en el nombre: varios procesos MCP (cada sesión de Claude en
    # stdio, más el daemon) escriben este mismo archivo, y un ".tmp" compartido hacía que
    # dos escrituras simultáneas se pisaran el temporal y publicaran contenido mezclado o
    # perdido — entradas fantasma / delegaciones que nunca aparecían en "En curso".
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    finally:
        try:
            tmp.unlink(missing_ok=True)  # si replace() funcionó ya no existe
        except OSError:
            # Estamos en el `finally`: si el temporal no se deja borrar (en Windows lo típico es un
            # antivirus con el archivo abierto), tragarse el error es obligatorio. Lanzar aquí
            # taparía la excepción real que venga del try y dejaría un fallo mucho más difícil de
            # leer que un .tmp huérfano.
            pass


# --- Leer antes de fundir ---------------------------------------------------------------------
#
# Quien funde lo nuevo con lo que ya hay y reescribe el fichero no puede tomar «no se pudo leer»
# por «está vacío»: un antivirus o un indexador con el fichero abierto un instante bastaba para que
# `recompute-cost` reescribiera el relleno y los agregados solo con lo nuevo, y lo que ya no se
# puede reconstruir (transcripts borrados, reinicios puestos a mano) se perdía sin aviso.

#: Intentos de lectura antes de rendirse, con una espera que se dobla (0,1 + 0,2 + 0,4 + 0,8 s).
READ_ATTEMPTS = 5
READ_FIRST_DELAY_S = 0.1

_sleep = time.sleep


class UnreadableStateError(OSError):
    """Un fichero que existe y no se pudo leer: quien iba a fundirlo y reescribirlo no lo hace.

    Lleva el `errno` y el `strerror` del último fallo y, como `filename`, solo el NOMBRE del fichero
    (sin la carpeta): el mensaje llega a la terminal y no debe llevar rutas.
    """


@dataclass(frozen=True)
class Previous:
    """Lo que había antes de escribir: no existe, existe y se leyó, o existe y está dañado."""

    exists: bool
    data: Any = None
    damaged: bool = False


def read_before_merge(path: Path) -> Previous:
    """Lee `path` para fundir con él. Reintenta los `OSError`; si no lo logra, lanza.

    «No existe» no es un fallo (`Previous(exists=False)`). Un contenido que no es UTF-8 o no es
    JSON sale como `damaged=True`: no se va a arreglar reintentando.
    """
    last: OSError | None = None
    for attempt in range(READ_ATTEMPTS):
        try:
            with Path(path).open("rb") as f:
                raw = f.read()
        except FileNotFoundError:
            return Previous(exists=False)
        except OSError as exc:
            last = exc
            if attempt + 1 < READ_ATTEMPTS:
                _sleep(READ_FIRST_DELAY_S * 2**attempt)
            continue
        try:
            return Previous(exists=True, data=json.loads(raw.decode("utf-8")))
        except ValueError:  # también `UnicodeDecodeError`
            return Previous(exists=True, damaged=True)
    assert last is not None
    # `str(last)` llevaría la ruta entera: si no hay `strerror`, el del `errno` o nada.
    reason = last.strerror or (os.strerror(last.errno) if last.errno else type(last).__name__)
    raise UnreadableStateError(last.errno, reason, Path(path).name) from last


def set_aside(path: Path, now: datetime | None = None) -> Path:
    """Copia byte a byte un fichero dañado a `<nombre>.damaged-<AAAAMMDDTHHMMSSZ>` y la devuelve.

    Se copia, no se mueve: el original sigue en su sitio hasta que lo reemplace la escritura
    atómica, y quien lo lea mientras tanto ve lo mismo que antes. El nombre no acaba en `.json`
    para que ningún lector lo tome por uno de los suyos.
    """
    path = Path(path)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    copy = path.with_name(f"{path.name}.damaged-{stamp}")
    shutil.copyfile(path, copy)
    return copy
