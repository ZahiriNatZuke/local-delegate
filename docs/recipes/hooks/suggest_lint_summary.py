#!/usr/bin/env python3
"""Hook PostToolUse (matcher: Bash) para local-delegate.

Si un comando de lint/test/build produjo una salida larga (> LD_HOOK_BASH_LINES líneas,
default 120), sugiere volcarla a fichero y resumirla con local_lint_summary en vez de
dejar que la salida cruda quede en el contexto. NUNCA bloquea: solo añade
additionalContext. Sin dependencias (stdlib únicamente) y multiplataforma.

Instalar en settings.json (ver docs/recipes/claude-code-hooks.md):

  "hooks": {
    "PostToolUse": [
      {"matcher": "Bash", "hooks": [
        {"type": "command", "command": "python", "args": ["/ruta/a/suggest_lint_summary.py"]}
      ]}
    ]
  }
"""

from __future__ import annotations

import json
import os
import re
import sys

_CMD_RE = re.compile(r"\b(lint|test|tsc|build|pytest|clippy|biome)\b", re.IGNORECASE)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    command = (payload.get("tool_input") or {}).get("command", "") or ""
    if not _CMD_RE.search(command):
        return

    stdout = (payload.get("tool_response") or {}).get("stdout", "") or ""
    try:
        threshold = int(os.environ.get("LD_HOOK_BASH_LINES", "120"))
    except ValueError:
        threshold = 120
    if stdout.count("\n") < threshold:
        return

    context = (
        "La salida de este comando es larga. Vuélcala a un archivo y usa "
        "local_lint_summary(path=...) para resumirla sin gastar tu contexto."
    )
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": context,
                }
            }
        )
    )


if __name__ == "__main__":
    main()
