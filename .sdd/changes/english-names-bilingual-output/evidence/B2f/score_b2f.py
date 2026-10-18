"""B2f: scoring of the live measurement, fixed BEFORE measuring (plan, section B2f).

Per answer (`<runs>/<id>-r<k>.txt`) and against `b2f-set.json`:

- `codes` / `files`: the fraction of the (up to) 10 most named rule codes and files of the log that
  the answer names, as a whole token (a file by its path or its basename, after removing Markdown
  escapes). A log with no codes has `codes: null` and stays out of that mean.
- `model_codes` / `model_files`: the same, without the line the PROGRAM adds ("Sin mencionar (del
  log…" / "Not mentioned (in the log…"): what the model itself names.
- `fidelity_total`: the inventions of `scripts/score_lint_fidelity.py` (or the counter of `main`).
- `chunks`, `finish_reason` and `model` of its row in the usage log (by tool, path and the time of
  its repetition in `live-runs.json`): a row with `chunks` > 1 is not a single call.

    uv run --frozen python score_b2f.py --runs runs/main --usage-log LOG [LOG ...]
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

from local_delegate import lint_patterns

COUNTERS = {
    "new": ROOT / "scripts" / "score_lint_fidelity.py",
    "main": HERE.parent / "B2e" / "score_lint_fidelity_main.py",
}
FIDELITY_SET = HERE.parent / "B2d-2" / "fidelity-set.json"
ESCAPE = re.compile(r"\\([_*`-])")
PROGRAM_LINE = re.compile(r"(?m)^(?:Sin mencionar \(del log|Not mentioned \(in the log).*$")
GROUPS = {
    "long_es": ("G",),
    "long_en": ("GE",),
    "forced_long_es": ("H",),
    "forced_long_en": ("HE",),
    "mechanical_es": ("M",),
    "mechanical_en": ("ME",),
    "control": ("A", "B"),
}


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


def _fraction(items: list[str], text: str, named) -> float | None:
    return sum(named(i, text) for i in items) / len(items) if items else None


def _window_of(call_id: str) -> str:
    return re.match(r"[A-Z]+", call_id).group(0)


def score(runs: Path, counter: str, logs: list[Path]) -> dict:
    fid = _counter(counter)
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    entries = {
        e["id"]: e
        for e in json.loads((HERE / "b2f-set.json").read_text(encoding="utf-8"))["entries"]
    }
    control_logs = {
        e["id"]: e for e in json.loads(FIDELITY_SET.read_text(encoding="utf-8"))["logs"]
    }
    windows = json.loads((runs / "live-runs.json").read_text(encoding="utf-8"))
    rows = _rows(logs)
    out = []
    for call in manifest["calls"]:
        for key, window in sorted(windows.items()):
            if key.split("-r")[0] != call["window"]:
                continue
            rep = key.split("-r")[1]
            answer_path = runs / f"{call['id']}-r{rep}.txt"
            if not answer_path.is_file():
                continue
            raw = answer_path.read_text(encoding="utf-8")
            answer = ESCAPE.sub(r"\1", raw)
            model_only = PROGRAM_LINE.sub("", answer)
            doc = (ROOT / call["document"]).resolve()
            row = _row_for(rows, call["tool"], str(doc), window["started"], window["finished"])
            log = doc.read_text(encoding="utf-8", errors="replace")
            extra = tuple(control_logs.get(call["id"], {}).get("extra_allowed_numbers", ()))
            rec = {
                "id": call["id"],
                "window": call["window"],
                "rep": int(rep),
                "model": (row or {}).get("model"),
                "chunks": (row or {}).get("chunks", 1) if row else None,
                "finish_reason": (row or {}).get("finish_reason"),
                "program_line": bool(PROGRAM_LINE.search(answer)),
                "fidelity_total": fid.count_inventions(raw, log, extra)["total"],
            }
            entry = entries.get(call["id"])
            if entry is not None:
                codes, files = entry["top_codes"], entry["top_files"]
                rec["codes"] = _fraction(codes, answer, _named)
                rec["files"] = _fraction(files, answer, _file_named)
                rec["model_codes"] = _fraction(codes, model_only, _named)
                rec["model_files"] = _fraction(files, model_only, _file_named)
                rec["codes_missing_model"] = [c for c in codes if not _named(c, model_only)]
            out.append(rec)
    return {"runs": str(runs), "counter": counter, "rows": out, "summary": summarize(out)}


def summarize(rows: list[dict]) -> dict:
    def avg(values):
        values = [v for v in values if v is not None]
        return round(mean(values), 4) if values else None

    summary = {}
    for name, wins in GROUPS.items():
        group = [r for r in rows if r["window"] in wins]
        summary[name] = {
            "calls": len(group),
            "models": sorted({str(r["model"]) for r in group}),
            "multi_chunk": sum(bool(r["chunks"] and r["chunks"] > 1) for r in group),
            "codes": avg(r.get("codes") for r in group),
            "files": avg(r.get("files") for r in group),
            "model_codes": avg(r.get("model_codes") for r in group),
            "model_files": avg(r.get("model_files") for r in group),
            "fidelity_total": sum(r["fidelity_total"] for r in group),
            "fidelity_mean": avg(r["fidelity_total"] for r in group),
            "cut": sum(r["finish_reason"] == "length" for r in group),
            "program_line": sum(r["program_line"] for r in group),
        }
    return summary


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
        args.out.write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps(data["summary"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
