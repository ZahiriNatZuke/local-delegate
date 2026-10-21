"""L5 live measurement: reasoning budget of the `code` role against the daemon's /mcp.

For each configuration (no role params, then `enable_thinking on` with each budget) it sets the
`code` role with `local-delegate backend-params`, calls the three `code` tools on fixed repo inputs
`--repeat` times, writes every answer to `runs/<config>/<id>-r<k>.txt` (never printed), pairs each
call with its usage-log event and appends one JSON line per call to `runs/results.jsonl`.

The original `backend-params.json` bytes are restored in a `finally`, whatever happens.

    python run_budget.py --repeat 3 --budgets 256 512 1024 2048 --reference
"""

import argparse
import ast
import asyncio
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT / "scripts"))

from measure_structured_summary import URL, _token

LOG_DIR = Path.home() / "AppData" / "Local" / "local-delegate"
PARAMS_FILE = LOG_DIR / "backend-params.json"
TIME_CAP_S = 55 * 60

BOILERPLATE_SPEC = (
    "A Python function `parse_duration(text: str) -> int` that parses a duration such as "
    "'1h30m', '45s', '2h' or '1h5m10s' into a number of seconds. Accept the units h, m and s in "
    "that order, each at most once; raise ValueError on empty input or any other format. Include "
    "type hints and a docstring. Standard library only."
)

CALLS = [
    {
        "id": "explain-json_state",
        "tool": "local_explain_code",
        "path": "src/local_delegate/json_state.py",
        "names": ["read_json", "write_json_atomic"],
    },
    {
        "id": "explain-chains",
        "tool": "local_explain_code",
        "path": "src/local_delegate/chains.py",
        "names": [
            "Chain",
            "resolve",
            "describe",
            "residents",
            "loaded_members",
            "register_loaded_provider",
            "residents_text",
        ],
    },
    {
        "id": "commit-b0ba620",
        "tool": "local_commit_msg",
        "path": ".sdd/changes/backlog-minor-leftovers/evidence/L5/inputs/b0ba620.diff",
    },
    {
        "id": "commit-a9f84e7",
        "tool": "local_commit_msg",
        "path": ".sdd/changes/backlog-minor-leftovers/evidence/L5/inputs/a9f84e7.diff",
    },
    {"id": "boilerplate-duration", "tool": "local_boilerplate"},
]

LEAK_PREFIXES = (
    "thinking process",
    "here's a thinking",
    "here is a thinking",
    "okay,",
    "ok,",
    "let me",
    "let's",
    "the user",
    "hmm",
    "wait,",
    "first,",
    "i need",
    "we need",
    "analyze",
    "analyse",
)
COMMIT_RE = re.compile(
    r"^(feat|fix|docs|chore|refactor|test|perf|build|ci|style)(\([^)]+\))?!?: \S"
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def leaks(text: str) -> bool:
    if "<think>" in text or "</think>" in text:
        return True
    return _first_line(text).lower().startswith(LEAK_PREFIXES)


def control(call: dict, text: str, is_error: bool, target: Path | None) -> tuple[bool, str]:
    """Objective quality control fixed in L5.md before measuring."""
    if is_error:
        return False, "tool_error"
    if call["tool"] == "local_boilerplate":
        if target is None or not target.exists():
            return False, "no_target"
        try:
            tree = ast.parse(target.read_text(encoding="utf-8"))
        except SyntaxError:
            return False, "syntax_error"
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        return ("parse_duration" in names), ("ok" if "parse_duration" in names else "no_function")
    if leaks(text):
        return False, "leak"
    if call["tool"] == "local_commit_msg":
        return (bool(COMMIT_RE.match(_first_line(text)))), "ok" if COMMIT_RE.match(
            _first_line(text)
        ) else "not_conventional"
    if len(text) < 200:
        return False, "short"
    if not any(re.search(rf"\b{re.escape(n)}\b", text) for n in call["names"]):
        return False, "no_identifier"
    return True, "ok"


def _usage_log() -> Path:
    return LOG_DIR / f"usage-{datetime.now(UTC):%Y%m}.jsonl"


def _new_events(log: Path, offset: int) -> list[dict]:
    if not log.exists():
        return []
    with log.open("rb") as fh:
        fh.seek(offset)
        data = fh.read().decode("utf-8", errors="replace")
    out = []
    for line in data.splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # A line still being written by the daemon: the caller retries until the event lands.
            continue
    return out


def _cli(*args: str) -> None:
    subprocess.run(["local-delegate", "backend-params", *args], check=True, capture_output=True)


def configure(budget: int | None) -> None:
    _cli("reset", "code")
    if budget is not None:
        _cli("set", "code", "reasoning_budget_tokens", str(budget))
        _cli("set", "code", "enable_thinking", "on")


EVENT_KEYS = (
    "ts",
    "tool",
    "model",
    "ok",
    "finish_reason",
    "truncated_out",
    "reasoning_chars",
    "reasoning_skipped",
    "tokens_in",
    "tokens_out",
    "latency_ms",
    "inference_ms",
    "chunks",
    "backend_params",
)


async def measure(configs: list[int | None], repeat: int, runs: Path) -> int:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    results = runs / "results.jsonl"
    started = time.monotonic()
    headers = {"Authorization": f"Bearer {_token()}"}
    async with (
        httpx2.AsyncClient(headers=headers, timeout=900) as client,
        streamable_http_client(URL, http_client=client) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        for budget in configs:
            label = "ref" if budget is None else f"b{budget}"
            configure(budget)
            for rep in range(1, repeat + 1):
                for call in CALLS:
                    if time.monotonic() - started > TIME_CAP_S:
                        print("time cap reached", flush=True)
                        return 3
                    out_dir = runs / label
                    out_dir.mkdir(parents=True, exist_ok=True)
                    target = None
                    if call["tool"] == "local_boilerplate":
                        target = out_dir / f"{call['id']}-r{rep}.py.txt"
                        args = {
                            "spec": BOILERPLATE_SPEC,
                            "language": "python",
                            "target": str(target),
                            "overwrite": True,
                        }
                    else:
                        args = {"path": str((ROOT / call["path"]).resolve())}
                    log = _usage_log()
                    offset = log.stat().st_size if log.exists() else 0
                    t0 = time.monotonic()
                    res = await session.call_tool(call["tool"], args)
                    wall_ms = int((time.monotonic() - t0) * 1000)
                    text = "".join(getattr(c, "text", "") for c in res.content)
                    is_error = bool(res.is_error)
                    (out_dir / f"{call['id']}-r{rep}.txt").write_text(
                        text, encoding="utf-8", newline=""
                    )
                    event = None
                    for _ in range(20):
                        evs = [e for e in _new_events(log, offset) if e.get("tool") == call["tool"]]
                        if evs:
                            event = evs[-1]
                            break
                        await asyncio.sleep(0.25)
                    answer = (
                        target.read_text(encoding="utf-8") if target and target.exists() else text
                    )
                    valid_ctrl, reason = control(call, text, is_error, target)
                    ev = {k: event.get(k) for k in EVENT_KEYS} if event else {}
                    clean = bool(
                        event
                        and event.get("ok") is True
                        and event.get("finish_reason") == "stop"
                        and not event.get("truncated_out")
                        and not event.get("reasoning_skipped")
                    )
                    row = {
                        "config": label,
                        "budget": budget,
                        "rep": rep,
                        "id": call["id"],
                        "tool": call["tool"],
                        "wall_ms": wall_ms,
                        "is_error": is_error,
                        "answer_chars": len(answer),
                        "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
                        "event": ev,
                        "event_clean": clean,
                        "control": reason,
                        "valid": clean and valid_ctrl,
                    }
                    with results.open("a", encoding="utf-8", newline="\n") as fh:
                        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    print(
                        f"{_now()} {label} r{rep} {call['id']} valid={row['valid']} "
                        f"finish={ev.get('finish_reason')} trunc={bool(ev.get('truncated_out'))} "
                        f"rchars={ev.get('reasoning_chars')} ctrl={reason} ms={wall_ms}",
                        flush=True,
                    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--budgets", type=int, nargs="+", default=[256, 512, 1024, 2048])
    parser.add_argument("--reference", action="store_true", help="also run with no role params")
    parser.add_argument("--runs", type=Path, default=HERE / "runs")
    args = parser.parse_args()
    runs = args.runs.resolve()
    runs.mkdir(parents=True, exist_ok=True)
    original = PARAMS_FILE.read_bytes()
    (runs / "backend-params.initial.json").write_bytes(original)
    configs: list[int | None] = ([None] if args.reference else []) + list(args.budgets)
    meta = {"started": _now(), "configs": configs, "repeat": args.repeat}
    try:
        return asyncio.run(measure(configs, args.repeat, runs))
    finally:
        PARAMS_FILE.write_bytes(original)
        restored = hashlib.sha256(PARAMS_FILE.read_bytes()).hexdigest()
        meta.update(
            finished=_now(),
            params_restored_sha256=restored,
            params_initial_sha256=hashlib.sha256(original).hexdigest(),
        )
        (runs / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        print(f"backend-params restored, equal={restored == meta['params_initial_sha256']}")


if __name__ == "__main__":
    raise SystemExit(main())
