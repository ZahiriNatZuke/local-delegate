#!/usr/bin/env python3
"""Hook PreToolUse (matcher: Read) para local-delegate.

Si el archivo que Claude va a leer con Read pesa más de LD_HOOK_READ_KB (default 50 KB),
sugiere delegar a local_summarize/local_extract en vez de leerlo entero al contexto.
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


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    file_path = (payload.get("tool_input") or {}).get("file_path")
    if not file_path:
        return

    try:
        threshold_kb = float(os.environ.get("LD_HOOK_READ_KB", "50"))
        size_kb = os.path.getsize(file_path) / 1024
    except (OSError, ValueError):
        return

    if size_kb <= threshold_kb:
        return

    context = (
        f"Este archivo pesa {size_kb:.0f} KB. Si solo necesitas resumen/campos, "
        "local_summarize(path=...) o local_extract(path=...) lo procesan sin gastar tu "
        "contexto (el archivo se lee server-side)."
    )
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "additionalContext": context,
                }
            }
        )
    )


if __name__ == "__main__":
    main()
