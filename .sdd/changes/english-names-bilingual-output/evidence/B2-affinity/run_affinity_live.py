#!/usr/bin/env python3
"""B2-affinity: one live window of the lint affinity re-evaluation, through the daemon's /mcp.

Calls the REAL `local_lint_summary` of the running daemon (production prompt, temperature and
caps) on the 4 lint cases of the frozen affinity corpus (`benchmarks/afinidad-2026-10`), with
`path=` so the logs never go through a Claude context. The daemon must have been restarted with
`LOCAL_DELEGATE_MODEL_MECHANICAL=<model>` and `LOCAL_DELEGATE_FALLBACK=0` (and, for `en`,
`LOCAL_DELEGATE_LANG=en`): the caller (`b2affinity-measure.ps1`) does that.

Per window: one warm-up call (discarded), then `--repeat` repetitions of the 4 cases. Afterwards
the daemon's usage log lines written during the window are matched one to one, in file order, with
the calls: every line must be `local_lint_summary`, served by `<model>`, without routing or
fallback (foreign lines = 0, or the window fails). The result rows go to
`<results>/<lang>/<model>.jsonl` in the benchmark format that `analyze_benchmark.result_of` reads
(`schema_version` 2, `label`, `case`, `run`, `outcome`, `response`, `latency_ms`, ...), with the
latency of the usage log (the same path for every model).

    uv run python run_affinity_live.py --model gemma3-4b --lang es --repeat 3
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT / "scripts"))

from measure_structured_summary import URL, _token

CORPUS = ROOT / "benchmarks" / "afinidad-2026-10"
TARGET = CORPUS / "reevaluation-0.36.0"
TOOL = "local_lint_summary"
MODELS = ("gemma3-4b", "qwen35-2b", "gemma4-26b-a4b", "qwen36-35b-a3b")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def lint_cases() -> list[dict]:
    data = json.loads((CORPUS / "cases.json").read_text(encoding="utf-8"))
    cases = [c for c in data["cases"] if c.get("tool") == TOOL]
    for c in cases:
        source = CORPUS / "fuentes" / c["source_file"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != c["source_sha256"]:
            raise SystemExit(f"{c['id']}: sha256 of {source.name} changed")
    return cases


def usage_log() -> Path:
    from local_delegate import config

    return config.LOG_DIR / f"usage-{datetime.now(UTC):%Y%m}.jsonl"


async def _run_calls(cases: list[dict], repeat: int) -> list[dict]:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    plan = [("warmup", cases[0], 0)] + [
        ("case", c, rep) for rep in range(1, repeat + 1) for c in cases
    ]
    calls: list[dict] = []
    headers = {"Authorization": f"Bearer {_token()}"}
    async with (
        httpx2.AsyncClient(headers=headers, timeout=900) as client,
        streamable_http_client(URL, http_client=client) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        for kind, case, rep in plan:
            path = (CORPUS / "fuentes" / case["source_file"]).resolve()
            started = time.monotonic()
            res = await session.call_tool(TOOL, {"path": str(path), "max_words": 200})
            wall_ms = (time.monotonic() - started) * 1000
            text = "".join(getattr(c, "text", "") for c in res.content)
            calls.append(
                {
                    "kind": kind,
                    "case": case["id"],
                    "run": rep,
                    "is_error": bool(res.is_error),
                    "response": text,
                    "response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "wall_ms": round(wall_ms, 1),
                }
            )
            print(f"{kind} {case['id']} r{rep} chars={len(text)} error={res.is_error}", flush=True)
    return calls


def _log_lines(log: Path, offset: int) -> list[dict]:
    with log.open("rb") as fh:
        fh.seek(offset)
        raw = fh.read().decode("utf-8")
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=MODELS)
    parser.add_argument("--lang", required=True, choices=("es", "en"))
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--results", type=Path, default=TARGET / "results")
    args = parser.parse_args()
    cases = lint_cases()
    log = usage_log()
    offset = log.stat().st_size if log.exists() else 0
    started = _now()
    calls = asyncio.run(_run_calls(cases, args.repeat))
    finished = _now()
    time.sleep(1.0)  # the usage log line is written right after the answer
    lines = _log_lines(log, offset)
    problems: list[str] = []
    if len(lines) != len(calls):
        problems.append(f"{len(lines)} usage log lines for {len(calls)} calls (foreign lines?)")
    for call, line in zip(calls, lines, strict=False):
        if line.get("tool") != TOOL:
            problems.append(f"{call['case']} r{call['run']}: log line of {line.get('tool')}")
        if line.get("model") != args.model:
            problems.append(f"{call['case']} r{call['run']}: served by {line.get('model')}")
        for key in ("routing", "fallback_reason", "model_requested"):
            if line.get(key) not in (None, args.model):
                problems.append(f"{call['case']} r{call['run']}: {key}={line.get(key)}")
        call["log"] = {
            k: line.get(k)
            for k in (
                "ts",
                "model",
                "latency_ms",
                "ok",
                "chars_out",
                "finish_reason",
                "tokens_out",
                "truncated_out",
                "routing",
                "v",
            )
        }
    out_dir = args.results / args.lang
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for call in calls:
        if call["kind"] != "case":
            continue
        line = call.get("log") or {}
        ok = not call["is_error"] and bool(line.get("ok"))
        rows.append(
            {
                "schema_version": 2,
                "label": args.model,
                "case": call["case"],
                "run": call["run"],
                "outcome": "ok" if ok else "error",
                "response": call["response"],
                "response_chars": len(call["response"]),
                "response_sha256": call["response_sha256"],
                "latency_ms": line.get("latency_ms"),
                "wall_ms": call["wall_ms"],
                "thermal_state": "warm",
                "finish_reason": line.get("finish_reason"),
                "tokens_out": line.get("tokens_out"),
                "served_model": line.get("model"),
                "language": args.lang,
                "package_version": line.get("v"),
            }
        )
    target = out_dir / f"{args.model}.jsonl"
    with target.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    windows_path = args.results / "windows.json"
    windows = json.loads(windows_path.read_text(encoding="utf-8")) if windows_path.exists() else {}
    windows[f"{args.lang}/{args.model}"] = {
        "started": started,
        "finished": finished,
        "calls": len(calls),
        "log_lines": len(lines),
        "warmup": calls[0].get("log"),
        "problems": problems,
    }
    windows_path.write_text(
        json.dumps(windows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    for p in problems:
        print(f"PROBLEM: {p}", file=sys.stderr)
    print(f"{len(rows)} rows -> {target}; problems={len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
