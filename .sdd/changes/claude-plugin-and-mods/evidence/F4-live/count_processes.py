"""F4-live: $.process.run launched by the local-delegate mod during each timed Bash call, by half."""

import json
import re
import statistics
import sys
from pathlib import Path

RUNS = Path(sys.argv[1])
KINDS = ["cold"] + ["skip", "code", "prose"] * 5
CALL = re.compile(r"\$\.tool\.call \(drv2?\): Bash \(")
EXIT = re.compile(r"\$\.process\.run \(local-delegate\): .* exited (\d+) in (\d+)ms")
SETTLED = re.compile(r"local-delegate@local-delegate tool\.call settled in ([\d.]+)ms")
out = {}
for log in sorted(RUNS.glob("*.debug.log")):
    arm = log.name.split("-")[1][0]
    idx = -1
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if CALL.search(line):
            idx += 1
            continue
        if idx < 0 or idx >= len(KINDS):
            continue
        a = out.setdefault(arm, {}).setdefault(KINDS[idx], {"calls": 0, "proc": [], "settled": []})
        m = EXIT.search(line)
        if m:
            a["proc"].append(int(m.group(2)))
        m = SETTLED.search(line)
        if m:
            a["settled"].append(float(m.group(1)))
            a["calls"] += 1
res = {}
for arm, kinds in out.items():
    for kind, a in kinds.items():
        res[f"{arm}:{kind}"] = {
            "calls": a["calls"],
            "processes": len(a["proc"]),
            "process_ms_median": statistics.median(a["proc"]) if a["proc"] else None,
            "process_ms_max": max(a["proc"]) if a["proc"] else None,
            "mod_hook_settled_ms_median": statistics.median(a["settled"]) if a["settled"] else None,
        }
print(json.dumps(res, indent=1))
