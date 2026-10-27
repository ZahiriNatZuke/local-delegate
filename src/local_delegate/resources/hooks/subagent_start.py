#!/usr/bin/env python3
"""Hook SubagentStart: le recuerda a cada subagente que cargue las tools local_* (issue #443).

Las tools `local_*` son diferidas: un subagente no las ve hasta hacer `ToolSearch`, y sin un motivo
claro nunca da ese paso (dos revisores midieron 26 `Grep` + 16 `Read` y 0 `local_*`). Claude Code
anade `additionalContext` al principio de la conversacion del subagente, antes de su primer prompt.

Solo aconseja: SubagentStart no puede bloquear. No escribe telemetria (el evento no es una lectura
ni un prompt, y las metricas no lo esperan). Sale con 0 siempre, tambien con la entrada rota.
"""

from __future__ import annotations

import json
import sys

from hook_common import backend_down, enabled, hook_text


def main() -> None:
    if not enabled() or backend_down():
        # Con el corte por backend inalcanzable abierto (issue #436) las local_* responderian que
        # el backend no esta: recordarle al subagente que las cargue solo le haria perder turnos.
        return
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except (OSError, ValueError, AttributeError):
        return
    if not isinstance(payload, dict):
        return
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SubagentStart",
                    "additionalContext": hook_text("subagent.start"),
                }
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Silencio intencionado: un recordatorio perdido no rompe nada; un hook que falla, si.
        pass
