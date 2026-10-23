"""F4-live: medians and p95 of the Bash calls with/without the read mod, by half, plus heartbeats."""

import json
import math
import os
import re
import statistics
import sys
from pathlib import Path

RUNS = Path(sys.argv[1])
BEATS = Path(os.path.expanduser("~/.claude/plugins/data/local-delegate-local-delegate/heartbeats"))
HOOK_RE = re.compile(r"Hooks: (\w+):(\S+) \[(.*?)\].*?finished with status (\d+) \((\d+)ms\)")


def p95(xs):
    xs = sorted(xs)
    return xs[min(max(0, math.ceil(0.95 * len(xs)) - 1), len(xs) - 1)]


def stats(xs):
    return {"n": len(xs), "median": statistics.median(xs), "p95": p95(xs), "max": max(xs)}


arms: dict = {}
beats = []
for out in sorted(RUNS.glob("*.out.txt")):
    arm = out.name.split("-")[1][0]
    line = next(
        x for x in out.read_text(encoding="utf-8", errors="replace").splitlines() if "F4BASH" in x
    )
    d = json.loads(line.split("F4BASH ", 1)[1])
    a = arms.setdefault(arm, {})
    for ms, kind in zip(d["ms"], d["kinds"]):
        a.setdefault(kind, []).append(ms)
    hb = BEATS / f"{d['sid']}.json"
    beat = json.loads(hb.read_text(encoding="utf-8")) if hb.exists() else {}
    active = beat.get("read_mod_active")
    ok = (active is True) if arm == "C" else (active is not True)
    beats.append(
        {"run": out.name.split(".")[0], "sid": d["sid"], "read_mod_active": active, "ok": ok}
    )

res = {}
for arm, a in arms.items():
    res[arm] = {"warm_all": stats([x for k, v in a.items() if k != "cold" for x in v])}
    res[arm].update({("cold" if k == "cold" else f"warm_{k}"): stats(v) for k, v in a.items()})
res["delta_C_minus_S"] = {
    k: {
        "median": res["C"][k]["median"] - res["S"][k]["median"],
        "p95": res["C"][k]["p95"] - res["S"][k]["p95"],
    }
    for k in res["C"]
}
hooks: dict = {}
for log in sorted(RUNS.glob("*.debug.log")):
    arm = log.name.split("-")[1][0]
    for m in HOOK_RE.finditer(log.read_text(encoding="utf-8", errors="replace")):
        if m.group(1) in ("PreToolUse", "PostToolUse"):
            name = m.group(3).rsplit("/", 1)[-1].rsplit(" ", 1)[-1]
            hooks.setdefault(f"{arm}:{m.group(1)}:{name}", []).append(int(m.group(5)))
res["engine_hook_ms"] = {k: stats(v) for k, v in sorted(hooks.items())}
res["heartbeats"] = beats
res["heartbeats_all_ok"] = all(b["ok"] for b in beats)
print(json.dumps(res, indent=1))
