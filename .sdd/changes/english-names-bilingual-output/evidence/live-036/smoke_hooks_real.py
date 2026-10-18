"""Live smoke of the hooks INSTALLED in the real ~/.claude (0.36.0 candidate).

Copy of `evidence/B3/smoke_installed.py` adapted to the real environment: it reads the commands
registered in ~/.claude/settings.json and runs them as they are, in sh and PowerShell, with the
real `language.json` (whatever `install` left). It only reads the settings and runs the commands:
it does not change the hooks or their configuration. The hooks' telemetry goes to a scratch file
(`LD_HOOK_TELEMETRY_LOG`), so the real adoption log gets no synthetic events.

    uv run python smoke_hooks_real.py <scratch dir>
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

scratch = Path(sys.argv[1])
scratch.mkdir(parents=True, exist_ok=True)
settings = json.loads((Path.home() / ".claude" / "settings.json").read_text(encoding="utf-8"))
commands = {
    (g.get("matcher") or ev): g["hooks"][0]["command"]
    for ev, groups in settings["hooks"].items()
    for g in groups
    if "local-delegate" in g["hooks"][0]["command"]
}
doc = scratch / "notes.md"
doc.write_text("Some prose line about the daemon.\n" * 1500, encoding="utf-8")
inputs = {
    "Read": {
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": str(doc)},
        "session_id": "smoke-live-036",
    },
    "UserPromptSubmit": {
        "hook_event_name": "UserPromptSubmit",
        "prompt": "summarize this log",
        "session_id": "smoke-live-036",
    },
}
env = dict(os.environ)
env.update(settings.get("env", {}))
env["LD_HOOK_TELEMETRY_LOG"] = str(scratch / "telemetry-smoke.jsonl")
env.pop("LOCAL_DELEGATE_LANG", None)
shells = {
    "sh": lambda c: ["C:/Program Files/Git/bin/sh.exe", "-c", c],
    "powershell": lambda c: [
        "powershell",
        "-NoProfile",
        "-Command",
        "& " + c if c.startswith('"') else c,
    ],
}
lang_file = Path(os.environ["LOCALAPPDATA"]) / "local-delegate" / "language.json"
print("language.json:", lang_file.read_text(encoding="utf-8").strip())
print("LD_HOOK_READ_BLOCK:", env.get("LD_HOOK_READ_BLOCK"))
ok = True
for name, payload in inputs.items():
    for shell, wrap in shells.items():
        run = subprocess.run(
            wrap(commands[name]),
            input=json.dumps(payload).encode(),
            capture_output=True,
            env=env,
            timeout=60,
        )
        out = run.stdout.decode("utf-8", "replace").strip()
        try:
            hso = json.loads(out)["hookSpecificOutput"]
            text = hso.get("additionalContext") or hso.get("permissionDecisionReason") or ""
            decision = hso.get("permissionDecision", "-")
        except (ValueError, KeyError):
            text, decision = f"<no output> rc={run.returncode} err={run.stderr[-300:]!r}", "?"
            ok = False
        ascii_ok = run.stdout.isascii()
        ok = ok and ascii_ok and run.returncode == 0
        print(f"{name:16} {shell:10} rc={run.returncode} ascii={ascii_ok} decision={decision}")
        print(f"    {text[:160]}")
print("RESULT:", "OK" if ok else "FAIL")
