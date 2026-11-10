"""Gate T1, batch 5 (REQ-001, REQ-003, REQ-006): `local_extract` with gemma4-26b-a4b, second process.

Launched by a temporary copy of the daemon's secure launcher (scheduled task), with the published
package (`uv tool` Python, same version as the daemon) and this environment, set by the launcher:
`LOCAL_DELEGATE_LONG_INPUT_CHARS=0` (every input goes to the `long` role), temporary
`LOCAL_DELEGATE_LOG_DIR`/`LOCAL_DELEGATE_LOG`, `LOCAL_DELEGATE_WEB_PORT=9394`, no
`LLAMASWAP_CONFIG`, `LOCAL_DELEGATE_TURN_URL=http://127.0.0.1:9393/`.

Usage: pythonw run_g4.py <change_dir> <out_dir>
1. One small call without a table (validation); writes <out_dir>/validation.json.
2. Waits for <out_dir>/go.flag (or stop.flag), at most 15 minutes.
3. The 16 small table cases of REQ-001, one at a time, 3 s apart; writes <out_dir>/g4.json after each.
Never prints or stores any credential; exceptions go to <out_dir>/errors.txt.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

CASES = [
    "01-pricing-table-en", "02-pricing-table-en-3fields", "06-limits-table-es",
    "07-gateway-table-en", "08-managed-service-es", "09-allowances-table-en", "10-spec-sheet-en",
    "11-ficha-suministro-es", "12-capabilities-repeated-en", "17-plans-transposed-en",
    "21-pricing-table-en-near-miss", "22-limits-table-es-near-miss",
    "23-managed-service-es-near-miss", "24-allowances-table-en-near-miss",
    "25-gateway-table-en-near-miss", "26-plans-transposed-en-near-miss",
]  # fmt: skip
WAIT_S = 15 * 60
GAP_S = 3.0


def write(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
    tmp.replace(path)


def main() -> int:
    change, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    errors = out / "errors.txt"
    try:
        from local_delegate import __version__, config, server
    except Exception:
        errors.write_text(traceback.format_exc(), encoding="utf-8")
        return 2
    env_view = {
        "version": __version__,
        "LONG_INPUT_CHARS": config.LONG_INPUT_CHARS,
        "LOG_DIR": str(config.LOG_DIR),
        "USAGE_LOG": str(config.USAGE_LOG),
        "WEB_PORT": config.WEB_PORT,
        "TURN_URL": config.TURN_URL,
        "LLAMASWAP_CONFIG_set": bool(os.environ.get("LLAMASWAP_CONFIG")),
        "remote_web_token_set": bool(os.environ.get("LOCAL_DELEGATE_REMOTE_WEB_TOKEN")),
        "python": sys.executable,
    }
    started = time.time()
    try:
        answer = server.local_extract(fields=["name", "city"], text="Ana vive en Holguín y trabaja en una panadería.")
        validation = {"env": env_view, "answer": answer, "wall_s": round(time.time() - started, 3)}
    except Exception:
        validation = {"env": env_view, "exception": traceback.format_exc()}
    write(out / "validation.json", validation)

    deadline = time.time() + WAIT_S
    while time.time() < deadline:
        if (out / "stop.flag").exists():
            return 0
        if (out / "go.flag").exists():
            break
        time.sleep(1.0)
    else:
        return 3

    manifest = json.loads((change / "cases" / "cases.json").read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in manifest["cases"]}
    results: dict = {"_run": {"env": env_view, "started_epoch": time.time()}}
    for index, cid in enumerate(CASES):
        if (out / "stop.flag").exists():
            break
        if index:
            time.sleep(GAP_S)
        case = cases[cid]
        path = str((change / "cases" / case["file"]).resolve())
        t0 = time.time()
        try:
            answer = server.local_extract(fields=case["fields"], path=path)
            results[cid] = {"answer": answer, "wall_s": round(time.time() - t0, 3), "start_epoch": t0}
        except Exception:
            results[cid] = {"exception": traceback.format_exc(), "wall_s": round(time.time() - t0, 3), "start_epoch": t0}
        write(out / "g4.json", results)
    results["_run"]["finished_epoch"] = time.time()
    write(out / "g4.json", results)
    (out / "done.flag").write_text("done", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
