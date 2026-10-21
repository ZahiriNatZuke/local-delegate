"""T0 (claude-plugin-and-mods): driver mod that fires a real Read tool call without a model turn.

Usage: python make_driver.py <t0_dir>

Writes <t0_dir>/plugins/t0-driver/: a mod with the command `/t0read`, whose `command.run` hook calls
`$.tool.call({ tool: 'Read', file_path: <t0>/work/sentinel.txt })`. Per the mods types, that call
"runs through every hook but the calling one, the permission check, then the tool", so a plugin's
PreToolUse hook on Read sees it. The run_cases controls (0.39 exe and raw exit 2 must block; a hook
that exits 0 must pass) prove whether this path discriminates. No login is needed.
"""

import json
import sys
from pathlib import Path

T0 = Path(sys.argv[1]).resolve()
root = T0 / "plugins" / "t0-driver"
(root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
(root / "hooks").mkdir(parents=True, exist_ok=True)
(root / ".claude-plugin" / "plugin.json").write_text(
    json.dumps(
        {
            "name": "t0-driver",
            "version": "0.0.1",
            "description": "T0 Read driver",
            "author": {"name": "t0"},
        },
        indent=2,
    ),
    encoding="utf-8",
)
(root / "hooks" / "hooks.json").write_text(
    json.dumps({"modules": ["./register.js"]}, indent=2), encoding="utf-8"
)
sentinel = str(T0 / "work" / "sentinel.txt").replace("\\", "/")
(root / "hooks" / "register.js").write_text(
    "export function register(on) {\n"
    "  on('session.start', async ($, e, next) => {\n"
    "    await $.command.register({ name: 't0read', description: 'T0: fire a Read tool call' })\n"
    "    return next(e)\n"
    "  })\n"
    "  on('command.run', { command: 't0read' }, async ($) => {\n"
    "    try {\n"
    f"      const r = await $.tool.call({{ tool: 'Read', file_path: {sentinel!r} }})\n"
    "      return { text: 'T0READ OK ' + JSON.stringify(r).slice(0, 600) }\n"
    "    } catch (err) {\n"
    "      return { text: 'T0READ ERR ' + String(err).slice(0, 600) }\n"
    "    }\n"
    "  })\n"
    "}\n",
    encoding="utf-8",
)
print("driver ok")
