"""F2-live, REQ-003: wall time of each plugin hook launched as the engine launches it.

python hook_latency.py <python.exe> <work_dir> <n>   ->  JSON with median/p95/max per hook and layer.
"""

import json
import math
import os
import statistics
import subprocess
import sys
import time
import uuid

PY, WORK, N = sys.argv[1], sys.argv[2], int(sys.argv[3])
tiny = os.path.join(WORK, "tiny.txt")
base = {"session_id": "f2live-latency", "transcript_path": "", "cwd": WORK}


def payload(name):
    if name == "prompt":
        return {
            **base,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Reply with the single word OK.",
        }
    if name == "record-call":
        return {
            **base,
            "hook_event_name": "PreToolUse",
            "tool_name": "mcp__local-delegate__local_status",
            "tool_input": {},
            "tool_use_id": f"toolu_f2live{uuid.uuid4().hex[:12]}",
        }
    if name == "read":
        return {
            **base,
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": tiny},
        }
    if name == "mcp-read":
        return {
            **base,
            "hook_event_name": "PreToolUse",
            "tool_name": "mcp__filesystem__read_text_file",
            "tool_input": {"path": tiny},
        }
    return {
        **base,
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "echo f2"},
    }


def p95(xs):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, math.ceil(0.95 * len(xs)) - 1))]  # nearest-rank


out = {}
for layer in ("off", "on"):
    env = {k: v for k, v in os.environ.items() if k != "LD_HOOK_READ_ENABLED"}
    if layer == "on":
        env["LD_HOOK_READ_ENABLED"] = "1"
    for name in ("prompt", "record-call", "read", "mcp-read", "shell"):
        if layer == "on" and name in ("prompt", "record-call"):
            continue  # not gated by the read layer
        ms, codes = [], set()
        for _ in range(N):
            data = json.dumps(payload(name)).encode()
            t0 = time.perf_counter()
            p = subprocess.run(
                [PY, "-I", "-m", "local_delegate.hook", name],
                input=data,
                capture_output=True,
                env=env,
                cwd=WORK,
                timeout=30,
            )
            ms.append(round((time.perf_counter() - t0) * 1000, 1))
            codes.add(p.returncode)
        out[f"{name}/{layer}"] = {
            "n": N,
            "median": statistics.median(ms),
            "p95": p95(ms),
            "max": max(ms),
            "exit_codes": sorted(codes),
        }
print(json.dumps(out, indent=1))
