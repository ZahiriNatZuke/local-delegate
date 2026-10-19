"""Runs one window of the REQ-028 closing samples against the daemon's /mcp.

Same client as `evidence/B2d-2/run_live.py`: reads `manifest.json`, checks each document's
sha256, calls the tool with `path=<absolute path>` and the default arguments, and writes the
literal answer to `answers/<window>/<id>-r<k>.txt` (UTF-8). The answers never go through a
Claude context. Start and end timestamps (UTC) go to `answers/<window>/live-runs.json`.

The language is the daemon's: before calling anything, `local_status` must report the window's
`requested` language as the model response language, or the run stops (exit 3). The daemon is
never restarted from here.

    python run_samples.py --window ES --repeat 3
"""

import argparse
import asyncio
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT / "scripts"))

from measure_structured_summary import URL, _token

RESPONSE_LANGUAGE = re.compile(r"(?:Idioma de respuesta del modelo|Model response language): (\S+)")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


async def run(window: str, repeat: int) -> int:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    requested = manifest["windows"][window]["requested"]
    calls = [c for c in manifest["calls"] if c["window"] == window]
    for c in calls:
        digest = hashlib.sha256((ROOT / c["document"]).read_bytes()).hexdigest()
        if digest != c["document_sha256"]:
            print(f"{c['id']}: sha256 changed for {c['document']}", file=sys.stderr)
            return 2
    out_dir = HERE / "answers" / window
    out_dir.mkdir(parents=True, exist_ok=True)
    runs_path = out_dir / "live-runs.json"
    headers = {"Authorization": f"Bearer {_token()}"}
    total_errors = 0
    async with (
        httpx2.AsyncClient(headers=headers, timeout=900) as client,
        streamable_http_client(URL, http_client=client) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        status = await session.call_tool("local_status", {})
        status_text = "".join(getattr(c, "text", "") for c in status.content)
        found = RESPONSE_LANGUAGE.search(status_text)
        effective = found.group(1) if found else None
        print(f"daemon response language: {effective} (window wants {requested})", flush=True)
        if effective != requested:
            return 3
        for rep in range(1, repeat + 1):
            started = _now()
            errors = 0
            for c in calls:
                res = await session.call_tool(
                    c["tool"], {"path": str((ROOT / c["document"]).resolve())}
                )
                text = "".join(getattr(part, "text", "") for part in res.content)
                out = out_dir / f"{c['id']}-r{rep}.txt"
                with out.open("w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
                errors += bool(res.is_error)
                print(
                    f"{c['id']} r{rep} {c['tool']} chars={len(text)} error={res.is_error}",
                    flush=True,
                )
            runs = json.loads(runs_path.read_text(encoding="utf-8")) if runs_path.exists() else {}
            runs[f"{window}-r{rep}"] = {
                "started": started,
                "finished": _now(),
                "calls": len(calls),
                "errors": errors,
                "daemon_response_language": effective,
            }
            runs_path.write_text(json.dumps(runs, indent=2) + "\n", encoding="utf-8", newline="\n")
            total_errors += errors
    return 1 if total_errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", required=True, choices=["ES", "EN", "FR"])
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    return asyncio.run(run(args.window, args.repeat))


if __name__ == "__main__":
    raise SystemExit(main())
