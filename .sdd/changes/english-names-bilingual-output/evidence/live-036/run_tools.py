"""Live pass of the 11 tools against the installed daemon (0.36.0 candidate, plan §4.3).

Calls every `local_*` tool once through the daemon's /mcp and writes each literal answer to
`answers/<lang>/<tool>.txt` (UTF-8, the home folder replaced by `~`). The answers never go
through a Claude context. A summary line per tool goes to stdout and `answers/<lang>/runs.json`.

`--lang` only names the folder: the language of the output is the daemon's (its `language.json`,
written by `install`). Inputs that are not in the repo (a ruff log, a diff) are generated into
`--inputs` first. The token comes from the user variable `LOCAL_DELEGATE_WEB_TOKEN`, exactly as
in `evidence/B2d-2/run_live.py`, and is never printed.

Before each call the free RAM is checked: under 4 GB it waits (up to 10 minutes); under 1.5 GB
it stops.

    uv run python run_tools.py --lang en --inputs <scratch dir>
"""

import argparse
import asyncio
import ctypes
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT / "scripts"))

from measure_structured_summary import URL, _token

HOME = str(Path.home())


class _MemStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def free_gb() -> float:
    status = _MemStatus()
    status.dwLength = ctypes.sizeof(_MemStatus)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return status.ullAvailPhys / 2**30


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def prepare_inputs(inputs: Path) -> dict[str, Path]:
    inputs.mkdir(parents=True, exist_ok=True)
    lint = inputs / "ruff.log"
    if not lint.exists():
        out = subprocess.run(
            [
                "uv",
                "run",
                "--no-sync",
                "ruff",
                "check",
                "--select",
                "ALL",
                "--no-cache",
                "src/local_delegate/sections.py",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        lint.write_text(out.stdout + out.stderr, encoding="utf-8")
    diff = inputs / "commit.diff"
    if not diff.exists():
        out = subprocess.run(
            ["git", "show", "--format=", "c61206d", "--", "src/local_delegate/server.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        diff.write_text(out.stdout, encoding="utf-8")
    return {"lint": lint, "diff": diff}


def calls(lang: str, files: dict[str, Path], inputs: Path) -> list[tuple[str, dict]]:
    other = "Spanish" if lang == "en" else "English"
    source_text = (
        "El daemon guarda cada delegación en un log mensual. Desde ahí el panel calcula cuánto "
        "contexto se ahorró."
        if lang == "en"
        else "The daemon saves each delegation in a monthly log. From there the panel computes "
        "how much context was saved."
    )
    target = inputs / f"model_price_{lang}.py"
    target.unlink(missing_ok=True)
    return [
        ("local_status", {}),
        ("local_summarize", {"path": str(ROOT / "docs/wiki/Daemon.md")}),
        (
            "local_classify",
            {
                "text": "The panel crashes with a 500 error when I open the cost tab.",
                "labels": ["bug", "feature request", "question"],
            },
        ),
        (
            "local_extract",
            {
                "fields": ["name", "version", "requires-python"],
                "path": str(ROOT / "pyproject.toml"),
            },
        ),
        (
            "local_boilerplate",
            {
                "spec": "A frozen dataclass ModelPrice with fields model: str, input_per_mtok: "
                "float, output_per_mtok: float, and a method cost(tokens_in, tokens_out).",
                "language": "python",
                "target": str(target),
                "overwrite": True,
            },
        ),
        (
            "local_delegate",
            {
                "task": "Convert each snake_case name to camelCase.",
                "input": "read_hook_threshold\nstructured_summary\ntest_window_stop",
                "output_format": "one name per line, nothing else",
            },
        ),
        ("local_lint_summary", {"path": str(files["lint"])}),
        ("local_commit_msg", {"path": str(files["diff"])}),
        ("local_translate", {"target_lang": other, "text": source_text}),
        ("local_explain_code", {"path": str(ROOT / "src/local_delegate/sections.py")}),
        (
            "local_describe_image",
            {
                "path": str(HERE.parent / "live-035/panel-claro.png"),
                "question": "Which language are the labels in, and what are the main figures?",
            },
        ),
    ]


async def run(lang: str, inputs: Path, only: str | None) -> int:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    files = prepare_inputs(inputs)
    out_dir = HERE / "answers" / lang
    out_dir.mkdir(parents=True, exist_ok=True)
    runs_path = out_dir / "runs.json"
    runs = json.loads(runs_path.read_text(encoding="utf-8")) if runs_path.exists() else {}
    headers = {"Authorization": f"Bearer {_token()}"}
    errors = 0
    async with (
        httpx2.AsyncClient(headers=headers, timeout=900) as client,
        streamable_http_client(URL, http_client=client) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        for tool, args in calls(lang, files, inputs):
            if only and tool != only:
                continue
            waited = 0
            while free_gb() < 4 and waited < 600:
                print(f"{tool}: free RAM {free_gb():.1f} GB < 4 GB, waiting", flush=True)
                await asyncio.sleep(30)
                waited += 30
            if free_gb() < 1.5:
                print(f"{tool}: free RAM {free_gb():.1f} GB < 1.5 GB: stopping", flush=True)
                return 3
            ram_before = round(free_gb(), 1)
            started = time.monotonic()
            res = await session.call_tool(tool, args)
            seconds = round(time.monotonic() - started, 1)
            text = "".join(getattr(c, "text", "") for c in res.content)
            text = text.replace(HOME, "~").replace(HOME.replace("\\", "/"), "~")
            (out_dir / f"{tool}.txt").write_text(text, encoding="utf-8", newline="")
            errors += bool(res.is_error)
            runs[tool] = {
                "at": _now(),
                "seconds": seconds,
                "chars": len(text),
                "error": bool(res.is_error),
                "free_ram_gb_before": ram_before,
            }
            print(
                f"{tool} error={res.is_error} chars={len(text)} {seconds}s ram={ram_before}GB",
                flush=True,
            )
            runs_path.write_text(json.dumps(runs, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", required=True, choices=["es", "en"])
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--only", help="run only this tool")
    args = parser.parse_args()
    return asyncio.run(run(args.lang, args.inputs.resolve(), args.only))


if __name__ == "__main__":
    raise SystemExit(main())
