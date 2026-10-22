#!/usr/bin/env python3
"""Hook PreToolUse de las tools de local-delegate: anota quien pide cada delegacion.

Antes se llamaba `anotar_llamada.py`; `install` retira la copia y el registro viejos (REQ-012).

No avisa ni bloquea: deja una nota (`hook_common.record_call`) con `agent_id`, `agent_type`,
`effort`, `transcript_path` y `session_key`, que el servidor recoge por `tool_use_id` al escribir la
linea del log de uso. El modelo de quien llama no viene en la entrada del hook; el servidor lo saca
del transcript que apunta la nota. `session_key` es la clave de un solo sentido del `session_id`
(`hook_common.session_key`): con ella `/api/stats?session=` da el ahorro de una sesion para la
barra de estado del mod (REQ-017 de claude-plugin-and-mods). El id en claro nunca se guarda.

No imprime nada y sale con 0 siempre, tambien con la entrada rota: perder una nota deja la
delegacion para el relleno a posteriori; romper la llamada no tiene arreglo.
"""

from __future__ import annotations

import json
import sys

from hook_common import record_call


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except (OSError, ValueError, AttributeError):
        return
    if isinstance(hook_input, dict):
        record_call(hook_input)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Silencio intencionado: este hook solo anota y nunca puede bloquear ni romper la
        # llamada de Claude Code; cualquier fallo se traga y el proceso sale con 0.
        pass
    sys.exit(0)
