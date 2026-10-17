"""Runs one window of the B2d-2 live measurement against the daemon's /mcp.

Reads `manifest.json`, checks each document's sha256, calls the tool with `path=<absolute path>`
and the default arguments, and writes the literal answer to its `answer` file (UTF-8). The
answers never go through a Claude context. Start and end timestamps (UTC) go to `live-runs.json`.

The daemon token is read from the user variable `LOCAL_DELEGATE_WEB_TOKEN` and never printed.

    uv run python run_live.py --window A
    uv run python run_live.py --window A --manifest ../B2d-3/manifest.json

`--manifest` points to another frozen manifest with the same format (B2d-3 measures only the lint
answers of set 3); `live-runs.json` goes next to the manifest used.
"""

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT / "scripts"))

from measure_structured_summary import URL, _token


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


async def _call(session, tool: str, path: Path) -> tuple[str, bool]:
    res = await session.call_tool(tool, {"path": str(path)})
    return "".join(getattr(c, "text", "") for c in res.content), bool(res.is_error)


async def run(window: str, manifest_path: Path = HERE / "manifest.json") -> int:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    calls = [c for c in manifest["calls"] if c["window"] == window]
    for c in calls:
        doc = ROOT / c["document"]
        digest = hashlib.sha256(doc.read_bytes()).hexdigest()
        if digest != c["document_sha256"]:
            print(f"{c['id']}: sha256 changed for {c['document']}", file=sys.stderr)
            return 2
    started = _now()
    errors = 0
    headers = {"Authorization": f"Bearer {_token()}"}
    async with (
        httpx2.AsyncClient(headers=headers, timeout=900) as client,
        streamable_http_client(URL, http_client=client) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        for c in calls:
            text, is_error = await _call(session, c["tool"], (ROOT / c["document"]).resolve())
            out = ROOT / c["answer"]
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w", encoding="utf-8", newline="") as fh:
                fh.write(text)
            errors += is_error
            print(f"{c['id']} {c['tool']} chars={len(text)} error={is_error}", flush=True)
    runs_path = manifest_path.parent / "live-runs.json"
    runs = json.loads(runs_path.read_text(encoding="utf-8")) if runs_path.exists() else {}
    runs[window] = {"started": started, "finished": _now(), "calls": len(calls), "errors": errors}
    runs_path.write_text(json.dumps(runs, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", required=True, choices=["A", "B", "C"])
    parser.add_argument("--manifest", type=Path, default=HERE / "manifest.json")
    args = parser.parse_args()
    return asyncio.run(run(args.window, args.manifest.resolve()))


if __name__ == "__main__":
    raise SystemExit(main())
