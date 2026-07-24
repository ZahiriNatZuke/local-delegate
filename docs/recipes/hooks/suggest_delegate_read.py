#!/usr/bin/env python3
"""Hook PreToolUse (matcher: Read) para local-delegate.

Es experimental y queda apagado por defecto tras el piloto A/B. Se activa con
LD_HOOK_READ_ENABLED=1. Usa dos bandas: LD_HOOK_READ_SUGGEST_KB (default 8 KB) y
LD_HOOK_READ_STRONG_KB (default 32 KB). Sugiere delegar transformaciones globales,
sin impedir lecturas exactas.
NUNCA bloquea la tool: siempre permissionDecision="allow". Sin dependencias (stdlib
únicamente) y multiplataforma.

Instalar en settings.json (ver docs/recipes/claude-code-hooks.md):

  "hooks": {
    "PreToolUse": [
      {"matcher": "Read", "hooks": [
        {"type": "command", "command": "python", "args": ["/ruta/a/suggest_delegate_read.py"]}
      ]}
    ]
  }
"""

from __future__ import annotations

import json
import os
import sys

from hook_common import emit, record


def main() -> None:
    if os.environ.get("LD_HOOK_READ_ENABLED", "0").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    file_path = (payload.get("tool_input") or {}).get("file_path")
    if not file_path:
        return

    try:
        suggest_kb = float(os.environ.get("LD_HOOK_READ_SUGGEST_KB", "8"))
        strong_kb = float(os.environ.get("LD_HOOK_READ_STRONG_KB", "32"))
        size_kb = os.path.getsize(file_path) / 1024
    except (OSError, ValueError):
        return

    if size_kb <= suggest_kb:
        record("PreToolUse", suggested=False, category="read", size_kb=round(size_kb, 1))
        return

    band = "strong" if size_kb > strong_kb else "suggest"
    strength = "Recomendacion fuerte" if band == "strong" else "Sugerencia"
    emit(
        "PreToolUse",
        f"{strength}: este archivo pesa {size_kb:.0f} KB. Si necesitas una transformacion "
        "global (resumen, campos, traduccion o explicacion), usa la tool local_* con path para "
        "que no entre al contexto. Leelo directamente si necesitas lineas exactas para razonar o editar.",
        category="read",
        band=band,
        size_kb=round(size_kb, 1),
    )


if __name__ == "__main__":
    main()
