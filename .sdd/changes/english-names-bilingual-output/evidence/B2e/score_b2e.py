"""B2e: scoring of the live measurement, fixed BEFORE measuring (plan, section B2e).

Per answer (`<runs>/<id>-r<k>.txt`) and against `chunking-set.json`:

- lint (L1-L5): how many of the 10 most frequent rule codes and files of the log it names (as a
  fraction of the ones the log has, up to 10: L3, a `pytest --collect-only`, has no codes and is
  left out of the codes mean), and `fidelity_total` with the counter given (`--counter`);
- explain (E1-E3): the fraction of registered names and of top-level names it names, and
  whether E1 names `doctor` and `benchmark`;
- every touched call: `chunks` and `finish_reason` of its row in the usage log, matched by tool,
  path and the time window of its repetition in `live-runs.json`. An entry with `chunks` <= 1 is
  not judged (`judged: false`).

The control calls (A11-A15, B31-B35) get only `fidelity_total` and the cut.

A name counts as named when it appears as a whole token (not inside a longer identifier); a file
when its path or its basename does, after removing Markdown escapes (`build\\_corpus.py`).

    uv run --frozen python score_b2e.py --runs runs/main --counter main --usage-log LOG [LOG ...]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from local_delegate import lint_patterns

COUNTERS = {
    "new": ROOT / "scripts" / "score_lint_fidelity.py",
    "main": HERE / "score_lint_fidelity_main.py",
}
FIDELITY_SET = HERE.parent / "B2d-2" / "fidelity-set.json"
ESCAPE = re.compile(r"\\([_*`-])")


def _counter(name: str):
    spec = importlib.util.spec_from_file_location(f"fid_{name}", COUNTERS[name])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _named(token: str, text: str) -> bool:
    return re.search(r"(?<![\w-])" + re.escape(token) + r"(?![\w-])", text) is not None


def _file_named(path: str, text: str) -> bool:
    norm = lint_patterns.norm_path(text)
    p = lint_patterns.norm_path(path).lstrip("./")
    base = p.rsplit("/", 1)[-1]
    return p in norm or re.search(r"(?<![\w.-])" + re.escape(base) + r"(?!\w)", norm) is not None


def _rows(logs: list[Path]) -> list[dict]:
    out = []
    for log in logs:
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def _row_for(rows: list[dict], tool: str, path: str, since: str, until: str) -> dict | None:
    target = lint_patterns.norm_path(path)
    found = [
        r
        for r in rows
        if r.get("tool") == tool
        and lint_patterns.norm_path(r.get("path", "")) == target
        and since[:19] <= r["ts"][:19] <= until[:19]
    ]
    return found[-1] if found else None


def score(runs: Path, counter: str, logs: list[Path]) -> dict:
    fid = _counter(counter)
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    entries = {
        e["id"]: e
        for e in json.loads((HERE / "chunking-set.json").read_text(encoding="utf-8"))["entries"]
    }
    control_logs = {
        e["id"]: e for e in json.loads(FIDELITY_SET.read_text(encoding="utf-8"))["logs"]
    }
    windows = json.loads((runs / "live-runs.json").read_text(encoding="utf-8"))
    rows = _rows(logs)
    out = []
    for call in manifest["calls"]:
        for key, window in sorted(windows.items()):
            if not key.startswith(call["window"] + "-r"):
                continue
            # `run_live.py --only-tool` (2026-10-17) writes `C-r1-lint_summary` and covers only
            # the calls of that tool: its time window does not hold the others.
            if window.get("only_tool") not in (None, call["tool"]):
                continue
            rep = key.split("-r")[1].split("-")[0]
            answer_path = runs / f"{call['id']}-r{rep}.txt"
            if not answer_path.is_file():
                continue
            answer = ESCAPE.sub(r"\1", answer_path.read_text(encoding="utf-8"))
            doc = (ROOT / call["document"]).resolve()
            row = _row_for(rows, call["tool"], str(doc), window["started"], window["finished"])
            rec = {
                "id": call["id"],
                "rep": int(rep),
                "chunks": (row or {}).get("chunks", 1) if row else None,
                "finish_reason": (row or {}).get("finish_reason"),
                "steps": (row or {}).get("steps"),
            }
            raw = answer_path.read_text(encoding="utf-8")
            if call["tool"] == "local_lint_summary":
                log = doc.read_text(encoding="utf-8", errors="replace")
                extra = tuple(control_logs.get(call["id"], {}).get("extra_allowed_numbers", ()))
                rec["fidelity_total"] = fid.count_inventions(raw, log, extra)["total"]
            entry = entries.get(call["id"])
            if entry is not None:
                rec["judged"] = bool(rec["chunks"] and rec["chunks"] > 1)
                if entry["tool"] == "local_lint_summary":
                    codes, files = entry["top_codes"], entry["top_files"]
                    rec["codes"] = (
                        sum(_named(c, answer) for c in codes) / len(codes) if codes else None
                    )
                    rec["files"] = sum(_file_named(f, answer) for f in files) / len(files)
                    rec["codes_missing"] = [c for c in codes if not _named(c, answer)]
                else:
                    reg, top = entry["registered"], entry["top_level"]
                    rec["registered"] = (
                        sum(_named(n, answer) for n in reg) / len(reg) if reg else None
                    )
                    rec["registered_missing"] = [n for n in reg if not _named(n, answer)]
                    rec["top_level"] = sum(_named(n, answer) for n in top) / len(top)
                    if call["id"] == "E1":
                        rec["doctor_and_benchmark"] = _named("doctor", answer) and _named(
                            "benchmark", answer
                        )
            out.append(rec)
    return {"runs": str(runs), "counter": counter, "rows": out, "summary": summarize(out)}


def summarize(rows: list[dict]) -> dict:
    def avg(values):
        values = [v for v in values if v is not None]
        return round(mean(values), 4) if values else None

    lint = [r for r in rows if r["id"].startswith("L")]
    explain = [r for r in rows if r["id"].startswith("E")]
    control = [r for r in rows if r["id"][0] in "AB"]
    return {
        "lint_codes_mean": avg(r["codes"] for r in lint),
        "lint_files_mean": avg(r["files"] for r in lint),
        "lint_fidelity_mean": avg(r["fidelity_total"] for r in lint),
        "lint_cut": sum(r["finish_reason"] == "length" for r in lint),
        "lint_calls": len(lint),
        "not_judged": sorted({f"{r['id']}-r{r['rep']}" for r in lint + explain if not r["judged"]}),
        "E1_doctor_and_benchmark": [
            r.get("doctor_and_benchmark") for r in explain if r["id"] == "E1"
        ],
        "E1_E2_registered_mean": avg(r["registered"] for r in explain if r["id"] in ("E1", "E2")),
        "E3_top_level_mean": avg(r["top_level"] for r in explain if r["id"] == "E3"),
        "explain_top_level_mean": avg(r["top_level"] for r in explain),
        "control_fidelity_total": sum(r["fidelity_total"] for r in control),
        "control_cut": sum(r["finish_reason"] == "length" for r in control),
        "control_calls": len(control),
        "explain_cut": sum(r["finish_reason"] == "length" for r in explain),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--counter", choices=sorted(COUNTERS), default="new")
    parser.add_argument("--usage-log", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    data = score(args.runs.resolve(), args.counter, args.usage_log)
    text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(json.dumps(data["summary"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
