"""Humo de B3: instala los hooks en un HOME temporal y lanza el comando registrado TAL CUAL
en sh, cmd y PowerShell, con language.json en `en` y en `es`. No toca ~/.claude real."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from local_delegate import install as inst

root = Path(tempfile.mkdtemp(prefix="b3-smoke-", dir=sys.argv[1]))
home = root / "home"
data = root / "data"
data.mkdir(parents=True)
opts = inst.Options(
    home=home,
    components={"hooks"},
    targets={"claude"},
    python_exe=Path(sys.executable).as_posix(),
    use_cli=False,
    enable_read_hook=True,
)
assert inst.apply(inst.plan_install(opts), dry_run=False, out=lambda *_a: None) == 0
settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
commands = {
    (g.get("matcher") or ev): g["hooks"][0]["command"]
    for ev, groups in settings["hooks"].items()
    for g in groups
}
doc = root / "notes.md"
doc.write_text("x" * 40_000, encoding="utf-8")
inputs = {
    "Read": {"tool_input": {"file_path": str(doc)}, "session_id": "smoke"},
    "UserPromptSubmit": {"prompt": "resume este log", "session_id": "smoke"},
}
env = {k: v for k, v in os.environ.items() if not k.startswith(("LOCAL_DELEGATE_", "LD_HOOK_"))}
env["LOCAL_DELEGATE_LOG_DIR"] = str(data)
shells = {
    "sh": lambda c: ["C:/Program Files/Git/bin/sh.exe", "-c", c],
    "cmd": lambda c: "cmd /c " + c,
    "powershell": lambda c: [
        "powershell",
        "-NoProfile",
        "-Command",
        "& " + c if c.startswith('"') else c,
    ],
}
ok = True
for lang in ("en", "es"):
    (data / "language.json").write_text(json.dumps({"lang": lang}), encoding="utf-8")
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
                text = json.loads(out)["hookSpecificOutput"]["additionalContext"]
            except (ValueError, KeyError):
                text = f"<sin salida> rc={run.returncode} err={run.stderr[-300:]!r}"
                ok = False
            ascii_ok = run.stdout.isascii()
            ok = ok and ascii_ok
            print(
                f"[{lang}] {name:16} {shell:10} rc={run.returncode} ascii={ascii_ok} :: {text[:90]}"
            )
print("command Read:", commands["Read"])
print("RESULT:", "OK" if ok else "FAIL")
