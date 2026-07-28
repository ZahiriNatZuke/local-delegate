#!/usr/bin/env python3
"""Hook PreToolUse (matcher: Bash) para local-delegate.

Detecta antes de ejecutar comandos de lint/test/build que suelen ser ruidosos. Sugiere redirigir
la salida a un fichero y resumirla con local_lint_summary. NUNCA bloquea.

Instalar en settings.json (ver docs/recipes/claude-code-hooks.md):

  "hooks": {
    "PreToolUse": [
      {"matcher": "Bash", "hooks": [
        {"type": "command", "command": "python", "args": ["/ruta/a/suggest_lint_summary.py"]}
      ]}
    ]
  }
"""

from __future__ import annotations

import json
import re
import sys

from hook_common import emit, record

_CMD_RE = re.compile(r"\b(lint|test|tsc|build|pytest|clippy|biome)\b", re.IGNORECASE)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    command = (payload.get("tool_input") or {}).get("command", "") or ""
    if not _CMD_RE.search(command):
        record("PreToolUse", suggested=False, category="bash", command_chars=len(command))
        return

    context = (
        "Este comando puede producir salida larga. Si no necesitas verla completa, redirigela a "
        "un archivo y usa local_lint_summary(path=...) para traer solo el resumen al contexto."
    )
    emit("PreToolUse", context, category="lint", command_chars=len(command))


if __name__ == "__main__":
    main()
