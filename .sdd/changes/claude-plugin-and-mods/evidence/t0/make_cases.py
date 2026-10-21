"""T0 (claude-plugin-and-mods): generate one throwaway plugin per (case, event) for the B-1 table.

Usage: python make_cases.py <t0_dir>

<t0_dir> must already contain `env039/` (a venv with local-delegate-mcp==0.39.0). The script:
- drops the probe modules into env039's site-packages (wrapper and raw variants);
- expects `envb2/`: a venv whose base Python was deleted (see below);
- writes `plugins/<case>-<event>/` with `.claude-plugin/plugin.json` and `hooks/hooks.json`;
- writes `cases.json` (case metadata used by run_cases.ps1).
Nothing outside <t0_dir> is touched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

T0 = Path(sys.argv[1]).resolve()
ENV = T0 / "env039"
SITE = ENV / "Lib" / "site-packages"
MARKERS = T0 / "markers"
PLUGINS = T0 / "plugins"


def fwd(p: Path) -> str:
    return str(p).replace("\\", "/")


EXE039 = fwd(ENV / "Scripts" / "local-delegate.exe")
PY039 = fwd(ENV / "Scripts" / "python.exe")
MISSING_EXE = fwd(T0 / "does-not-exist" / "local-delegate.exe")
MISSING_PY = fwd(T0 / "does-not-exist" / "python.exe")
BROKEN_PY = fwd(T0 / "envb2" / "Scripts" / "python.exe")

# Probe modules. Each one leaves a marker so the table can tell "ran and passed" from "never ran".
MARK = (
    "import os, sys, pathlib\n"
    f"_M = pathlib.Path({fwd(MARKERS)!r})\n"
    "def mark(name):\n"
    "    _M.mkdir(parents=True, exist_ok=True)\n"
    "    (_M / (name + '-' + (sys.argv[1] if len(sys.argv) > 1 else 'x') + '.txt')).write_text('ran')\n"
)
MODULES = {
    # Raw: what an unwrapped module would do. Positive control for the wrapper cases.
    "t0_raw_exit2": MARK + "mark('raw_exit2')\nsys.exit(2)\n",
    # Wrapper pattern the future local_delegate.hook must follow: everything inside, always exit 0.
    "t0_wrap_exit2": MARK
    + (
        "def _inner():\n"
        "    sys.exit(2)\n"
        "def main():\n"
        "    try:\n"
        "        _inner()\n"
        "    except BaseException:\n"
        "        pass\n"
        "    mark('wrap_exit2')\n"
        "    sys.exit(0)\n"
        "main()\n"
    ),
    "t0_wrap_raise": MARK
    + (
        "def _inner():\n"
        "    raise RuntimeError('boom')\n"
        "def main():\n"
        "    try:\n"
        "        _inner()\n"
        "    except BaseException:\n"
        "        pass\n"
        "    mark('wrap_raise')\n"
        "    sys.exit(0)\n"
        "main()\n"
    ),
    # Sanity: hook that runs and allows. Proves "pass" is observable.
    "t0_ok": MARK + "mark('ok')\nsys.exit(0)\n",
}
for name, body in MODULES.items():
    (SITE / f"{name}.py").write_text(body, encoding="utf-8")

# Broken env: `envb2/` is a venv built on a private uv Python (UV_PYTHON_INSTALL_DIR=<t0>/pyhome)
# whose base install was then deleted. Editing `home` in a copy of env039 does NOT reproduce it: the
# Windows venv launcher still found the shared uv Python (measured, exit 0).


def exec_hook(command: str, args: list[str], on_failure: str | None = None) -> dict:
    h = {"type": "command", "command": command, "args": args, "timeout": 30}
    if on_failure:
        h["onFailure"] = on_failure
    return h


def shell_hook(cmdline: str) -> dict:
    return {"type": "command", "command": cmdline, "timeout": 30}


def py(mod: str, interp: str = PY039) -> tuple[str, list[str]]:
    return interp, ["-I", "-m", mod]


# case id -> (via, description, expected, builder(event_arg) -> hook dict)
CASES: dict[str, tuple[str, str, str, object]] = {
    # Controls
    "ctl-pos": (
        "control+",
        "0.39 exe `hook <ev>` exec, no onFailure",
        "block",
        lambda ev: exec_hook(EXE039, ["hook", ev]),
    ),
    "ctl-ok": (
        "control",
        "hook that exits 0 (t0_ok)",
        "pass",
        lambda ev: exec_hook(PY039, ["-I", "-m", "t0_ok", ev]),
    ),
    "ctl-raw2": (
        "control+",
        "unwrapped module exits 2 (t0_raw_exit2)",
        "block",
        lambda ev: exec_hook(PY039, ["-I", "-m", "t0_raw_exit2", ev]),
    ),
    # Via A: onFailure continue
    "a-039": (
        "A",
        "0.39 exe `hook <ev>` + onFailure=continue",
        "pass",
        lambda ev: exec_hook(EXE039, ["hook", ev], "continue"),
    ),
    "a-missing": (
        "A",
        "missing exe + onFailure=continue",
        "pass",
        lambda ev: exec_hook(MISSING_EXE, ["hook", ev], "continue"),
    ),
    "a-exit2": (
        "A",
        "exe exits 2 on purpose + onFailure=continue",
        "pass",
        lambda ev: exec_hook(PY039, ["-I", "-m", "t0_raw_exit2", ev], "continue"),
    ),
    # Via B: interpreter -I -m
    "b-039": (
        "B",
        "env 0.39 python -I -m local_delegate.hook <ev>",
        "pass",
        lambda ev: exec_hook(PY039, ["-I", "-m", "local_delegate.hook", ev]),
    ),
    "b-missing": (
        "B",
        "missing interpreter",
        "pass",
        lambda ev: exec_hook(MISSING_PY, ["-I", "-m", "local_delegate.hook", ev]),
    ),
    "b-broken": (
        "B",
        "venv with base Python deleted (pyvenv.cfg home gone)",
        "pass",
        lambda ev: exec_hook(BROKEN_PY, ["-I", "-m", "local_delegate.hook", ev]),
    ),
    "b-wrap2": (
        "B",
        "wrapper with sys.exit(2) inside",
        "pass",
        lambda ev: exec_hook(PY039, ["-I", "-m", "t0_wrap_exit2", ev]),
    ),
    "b-wraperr": (
        "B",
        "wrapper with exception inside",
        "pass",
        lambda ev: exec_hook(PY039, ["-I", "-m", "t0_wrap_raise", ev]),
    ),
    # Via C: shell form with || exit 0
    "c-039": (
        "C",
        'shell: "0.39 exe" hook <ev> || exit 0',
        "pass",
        lambda ev: shell_hook(f'"{EXE039}" hook {ev} || exit 0'),
    ),
    "c-missing": (
        "C",
        "shell: missing exe || exit 0",
        "pass",
        lambda ev: shell_hook(f'"{MISSING_EXE}" hook {ev} || exit 0'),
    ),
    "c-exit2": (
        "C",
        "shell: exe exits 2 || exit 0",
        "pass",
        lambda ev: shell_hook(f'"{PY039}" -I -m t0_raw_exit2 {ev} || exit 0'),
    ),
}

EVENTS = {"ups": ("UserPromptSubmit", None, "prompt"), "read": ("PreToolUse", "Read", "read")}

PLUGINS.mkdir(parents=True, exist_ok=True)
meta = []
for cid, (via, desc, expected, build) in CASES.items():
    for ev, (event, matcher, arg) in EVENTS.items():
        name = f"t0-{cid}-{ev}"
        root = PLUGINS / name
        (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        (root / "hooks").mkdir(parents=True, exist_ok=True)
        (root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": name, "version": "0.0.1", "description": "T0 probe"}, indent=2),
            encoding="utf-8",
        )
        entry: dict = {"hooks": [build(arg)]}
        if matcher:
            entry["matcher"] = matcher
        (root / "hooks" / "hooks.json").write_text(
            json.dumps({"hooks": {event: [entry]}}, indent=2), encoding="utf-8"
        )
        meta.append(
            {
                "case": cid,
                "event": ev,
                "via": via,
                "desc": desc,
                "expected": expected,
                "plugin": fwd(root),
            }
        )
(T0 / "cases.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
print(f"{len(meta)} plugins written under {fwd(PLUGINS)}")
