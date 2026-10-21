"""simulated_home.py — ¿``home`` es el HOME real o uno simulado (``--home``)?

Una sola respuesta para todo el paquete. Vivía en ``install``; se movió aquí para que
``shell_profiles`` (que ``install`` importa) pueda usarla sin un import cíclico. ``install`` la
reexporta con el mismo nombre, así que ``install.is_simulated_home`` sigue valiendo.
"""

from __future__ import annotations

from pathlib import Path


def is_simulated_home(home: Path) -> bool:
    """True si ``home`` apunta fuera del HOME real: entonces no se toca nada global.

    «Global» son dos cosas distintas y las dos importan: los servicios de la máquina (lo que ya
    cuidaba ``update``) y el binario ``claude``, que con ``mcp add-json --scope user`` escribe
    **siempre** en el ``~/.claude.json`` del usuario que ejecuta, ignorando cualquier ``--home``.
    """
    try:
        return home.resolve() != Path.home().resolve()
    except OSError:
        # Una ruta irresoluble se trata como simulada: el lado seguro es no tocar lo global.
        return True
