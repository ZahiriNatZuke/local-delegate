"""Ficheros JSON compartidos entre procesos: leer sin romper y escribir sin mezclar.

Los usan `inflight.json` (delegaciones en curso de todas las sesiones) y el estado de enfriamiento.
Viven aquí, y no copiados en cada uno, porque el cuidado que llevan —temporal con el pid en el
nombre, antivirus de Windows que no deja borrar— se aprendió a golpes y dos copias se separarían
solas.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def leer_json(path: Path) -> dict:
    """El objeto JSON del fichero, o `{}` si no existe, no se puede leer o no es un objeto."""
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def escribir_json_atomico(path: Path, data: dict) -> None:
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
