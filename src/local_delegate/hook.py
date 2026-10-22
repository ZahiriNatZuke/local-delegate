"""`python -I -m local_delegate.hook <nombre>`: la orden de cada hook del plugin (vía B de T0).

Este módulo es la red: **sale siempre con 0**. Claude Code bloquea el prompt o la tool cuando un
hook sale con 2, así que ni un `sys.exit(2)` de dentro, ni una excepción, ni un import roto pueden
llegar a ese código. Con un paquete 0.39 este módulo no existe y Python sale con 1, que el motor
trata como error no bloqueante (medido en T0).

No importa nada del paquete al cargarse: el despacho (`hook_entry`) se importa dentro de la red.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable


def run(target: Callable[[], object]) -> None:
    """Ejecuta `target` y termina el proceso con 0 pase lo que pase (no vuelve nunca)."""
    try:
        target()
    except (Exception, SystemExit, KeyboardInterrupt):
        # SystemExit(2) incluido: un hook nunca bloquea
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            # una tubería cerrada no cambia el código
            pass
    # `os._exit` y no `sys.exit`: al cerrar el intérprete, un flush fallido sobre una tubería rota
    # cambiaría el código de salida a 120.
    os._exit(0)


def run_hook(argv: list[str]) -> None:
    """Despacha `hook <nombre>` dentro de la red."""

    def dispatch() -> None:
        from local_delegate.hook_entry import main

        main(argv)

    run(dispatch)


if __name__ == "__main__":
    run_hook(sys.argv[1:])
