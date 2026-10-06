#!/usr/bin/env python3
"""Hook PreToolUse de las tools de local-delegate: anota quien pide cada delegacion.

No avisa ni bloquea: deja una nota (`hook_common.anotar_llamada`) con `agent_id`, `agent_type`,
`effort` y `transcript_path`, que el servidor recoge por `tool_use_id` al escribir la linea del log
de uso. El modelo de quien llama no viene en la entrada del hook; el servidor lo saca del
transcript que apunta la nota.

No imprime nada y sale con 0 siempre, tambien con la entrada rota: perder una nota deja la
delegacion para el relleno a posteriori; romper la llamada no tiene arreglo.
"""

from __future__ import annotations

import json
import sys

from hook_common import anotar_llamada


def main() -> None:
    try:
        entrada = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except (OSError, ValueError, AttributeError):
        return
    if isinstance(entrada, dict):
        anotar_llamada(entrada)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
