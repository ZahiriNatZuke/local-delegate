"""Utilidades stdlib para hooks consultivos de local-delegate.

La telemetria es opt-in y nunca escribe prompts, comandos ni paths: solo evento, categoria,
tamaño y banda. El log se activa con ``LD_HOOK_TELEMETRY_LOG``.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path


def record(event: str, **metadata: object) -> None:
    destination = os.environ.get("LD_HOOK_TELEMETRY_LOG", "").strip()
    if not destination:
        return
    payload = {"ts": datetime.now(UTC).isoformat(), "event": event, **metadata}
    try:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass


def emit(event: str, context: str, **metadata: object) -> None:
    record(event, suggested=True, **metadata)
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": context,
                }
            },
            ensure_ascii=False,
        )
    )
