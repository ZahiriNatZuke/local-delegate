"""F2-live: medians and p95 of the Bash calls with/without the plugin, plus the engine's hook times."""

import json
import math
import re
import statistics
import sys
from pathlib import Path

RUNS = Path(sys.argv[1])
HOOK_RE = re.compile(
    r"Hooks: (\w+):(\S+) \[.*?local_delegate\.hook (\S+)\].*finished with status (\d+) \((\d+)ms\)"
)


def p95(xs):
    xs = sorted(xs)
    k = max(0, math.ceil(0.95 * len(xs)) - 1)  # nearest-rank
    return xs[min(k, len(xs) - 1)]


arms = {}
hooks: dict[str, list[int]] = {}
statuses = set()
for out in sorted(RUNS.glob("*.out.txt")):
    arm = out.name.split("-")[1][0]
    line = next(
        x for x in out.read_text(encoding="utf-8", errors="replace").splitlines() if "F2BASH" in x
    )
    ms = json.loads(line.split("F2BASH ", 1)[1])["ms"]
    arms.setdefault(arm, {"warm": [], "cold": []})["cold"].append(ms[0])
    arms[arm]["warm"].extend(ms[1:])
for log in sorted(RUNS.glob("*.debug.log")):
    for m in HOOK_RE.finditer(log.read_text(encoding="utf-8", errors="replace")):
        hooks.setdefault(m.group(3), []).append(int(m.group(5)))
        statuses.add(m.group(4))

res = {}
for arm, d in arms.items():
    w = d["warm"]
    res[arm] = {
        "n_warm": len(w),
        "median": statistics.median(w),
        "p95": p95(w),
        "max": max(w),
        "cold_median": statistics.median(d["cold"]),
        "n_cold": len(d["cold"]),
    }
X = next(a for a in res if a != "N")
res["delta"] = {
    "median": res[X]["median"] - res["N"]["median"],
    "p95": res[X]["p95"] - res["N"]["p95"],
    "cold_median": res[X]["cold_median"] - res["N"]["cold_median"],
}
res["engine_hook_ms"] = {
    k: {"n": len(v), "median": statistics.median(v), "p95": p95(v), "max": max(v)}
    for k, v in hooks.items()
}
res["hook_statuses"] = sorted(statuses)
print(json.dumps(res, indent=1))
