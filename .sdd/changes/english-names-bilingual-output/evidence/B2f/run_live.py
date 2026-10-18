"""Runs one window of a live measurement against the daemon's /mcp (B2f copy: windows of B2f).

Reads `manifest.json`, checks each document's sha256, calls the tool with `path=<absolute path>`
and the default arguments, and writes the literal answer to its `answer` file (UTF-8). The
answers never go through a Claude context. Start and end timestamps (UTC) go to `live-runs.json`.

The daemon token is read from the user variable `LOCAL_DELEGATE_WEB_TOKEN` and never printed.

    uv run python run_live.py --window A
    uv run python run_live.py --window A --manifest ../B2d-3/manifest.json

`--manifest` points to another frozen manifest with the same format (B2d-3 measures only the lint
answers of set 3); `live-runs.json` goes next to the manifest used.

B2d-3 measures three versions with three repetitions each: `--answers-dir DIR` writes every answer
to `DIR/<id>-r<k>.txt` instead of the manifest's `answer` (which is left alone), `--repeat N` runs
the whole window N times (k = 1..N, in order), and `live-runs.json` goes to `DIR` with one entry
per window and repetition (`A-r1`, ...). Without `--answers-dir` the use is the same as before.

    uv run python run_live.py --window A --manifest ../B2d-3/manifest.json \\
        --answers-dir ../B2d-3/runs/base --repeat 3
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


def answer_path(call: dict, answers_dir: Path | None, rep: int) -> Path:
    """Where the answer of `call` goes: the manifest's file, or `<id>-r<rep>.txt` in a folder."""
    if answers_dir is None:
        return ROOT / call["answer"]
    return answers_dir / f"{call['id']}-r{rep}.txt"


async def run(
    window: str,
    manifest_path: Path = HERE / "manifest.json",
    answers_dir: Path | None = None,
    repeat: int = 1,
    only_tool: str | None = None,
) -> int:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    calls = [c for c in manifest["calls"] if c["window"] == window]
    if only_tool is not None:
        calls = [c for c in calls if c["tool"] == only_tool]
        if not calls:
            print(f"window {window} has no call of {only_tool}", file=sys.stderr)
            return 2
    for c in calls:
        doc = ROOT / c["document"]
        digest = hashlib.sha256(doc.read_bytes()).hexdigest()
        if digest != c["document_sha256"]:
            print(f"{c['id']}: sha256 changed for {c['document']}", file=sys.stderr)
            return 2
    headers = {"Authorization": f"Bearer {_token()}"}
    runs_path = (answers_dir or manifest_path.parent) / "live-runs.json"
    total_errors = 0
    async with (
        httpx2.AsyncClient(headers=headers, timeout=900) as client,
        streamable_http_client(URL, http_client=client) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        for rep in range(1, repeat + 1):
            started = _now()
            errors = 0
            for c in calls:
                text, is_error = await _call(session, c["tool"], (ROOT / c["document"]).resolve())
                out = answer_path(c, answers_dir, rep)
                out.parent.mkdir(parents=True, exist_ok=True)
                with out.open("w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
                errors += is_error
                print(
                    f"{c['id']} r{rep} {c['tool']} chars={len(text)} error={is_error}", flush=True
                )
            runs = json.loads(runs_path.read_text(encoding="utf-8")) if runs_path.exists() else {}
            key = window if answers_dir is None else f"{window}-r{rep}"
            if only_tool is not None:
                key += "-" + only_tool.removeprefix("local_")
            runs[key] = {
                "started": started,
                "finished": _now(),
                "calls": len(calls),
                "errors": errors,
            }
            if only_tool is not None:
                runs[key]["only_tool"] = only_tool
            runs_path.parent.mkdir(parents=True, exist_ok=True)
            runs_path.write_text(json.dumps(runs, indent=2) + "\n", encoding="utf-8", newline="\n")
            total_errors += errors
    return 1 if total_errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--window", required=True, choices=["A", "B", "G", "GE", "H", "HE", "M", "ME"]
    )
    parser.add_argument("--manifest", type=Path, default=HERE / "manifest.json")
    parser.add_argument("--answers-dir", type=Path, help="folder for <id>-r<k>.txt (B2d-3)")
    parser.add_argument("--repeat", type=int, default=1, help="runs of the whole window")
    parser.add_argument(
        "--only-tool",
        help="run only the window's calls of this tool (B2e, 2026-10-17: window C without"
        " explain_code, which does not fit in RAM; the key in live-runs.json gets the suffix)",
    )
    args = parser.parse_args()
    if args.repeat < 1 or (args.repeat > 1 and args.answers_dir is None):
        parser.error("--repeat N > 1 needs --answers-dir: the manifest has one answer per call")
    answers_dir = args.answers_dir.resolve() if args.answers_dir else None
    return asyncio.run(
        run(args.window, args.manifest.resolve(), answers_dir, args.repeat, args.only_tool)
    )


if __name__ == "__main__":
    raise SystemExit(main())
