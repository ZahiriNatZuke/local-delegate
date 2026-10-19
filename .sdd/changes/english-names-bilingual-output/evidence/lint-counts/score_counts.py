"""lint-counts: scoring of the live measurement, fixed BEFORE measuring (`plan.md`).

Per answer (`<runs>/<id>-r<k>.txt`), against `set.json`:

- `codes`, `files`, `model_codes`, `fidelity_total`, `finish_reason`, `chunks`: the same as
  `B2f/score_b2f.py` (its functions, imported).
- `wrong_counts` / `no_count`: for the logs with `true_counts` (ruff concise, ruff full, tsc), the
  codes of the truth that the MODEL names (without the program's "not mentioned" line) with a figure
  outside `{total} ∪ {count in each file}`, and those it names with no figure. Figures are read with
  the v3 reading of `B2-affinity/evaluate_reevaluation.py` (no line numbers nor coordinates, number
  words as digits, sentence by sentence). `missing_codes`: the codes of `top_codes` the model does
  not name.

    uv run python score_counts.py --runs runs/main --out score-main.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
USAGE_LOG = Path.home() / "AppData" / "Local" / "local-delegate" / "usage-202610.jsonl"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


b2f = _load("score_b2f", HERE.parent / "B2f" / "score_b2f.py")
v3 = _load("evaluate_reevaluation", HERE.parent / "B2-affinity" / "evaluate_reevaluation.py")
ab = v3.ab

GROUPS = {
    "ruff_es": ("R",),
    "ruff_en": ("RE",),
    "long_es": ("G",),
    "long_en": ("GE",),
    "forced_long_es": ("H",),
    "forced_long_en": ("HE",),
    "mechanical_es": ("M",),
    "mechanical_en": ("ME",),
}


def figures_by_code(text: str, codes: set[str]) -> dict[str, list[int]]:
    """The figures the text gives to each code of `codes` (v3 reading, per sentence)."""
    numbers: dict[str, list[int]] = {code: [] for code in codes}
    for line in v3.strip_footer(text).splitlines():
        for sentence in v3._SENTENCE.split(line):
            sentence = v3._clean(sentence)
            found = [c for c in ab._RULE_CODE.finditer(sentence) if c.group() in numbers]
            if len(found) == 1:
                rest = sentence[: found[0].start()] + " " + sentence[found[0].end() :]
                numbers[found[0].group()] += [int(n) for n in ab._BARE_INTEGER.findall(rest)]
                continue
            every = list(ab._RULE_CODE.finditer(sentence))
            if not every:
                continue
            # Several codes in one sentence: the figure goes on the side the sentence uses. With
            # a figure before the first code ("6 errores de … (D101) y 3 errores de … (D102)"),
            # each code takes the figures between the previous code and itself; otherwise, v3's
            # reading (the figures after it, up to the next code). Positive control: the Spanish
            # answer of live-036, where v3 gave D101 the 3 of D102 (`count-scorer-check.md`).
            before = bool(ab._BARE_INTEGER.findall(sentence[: every[0].start()]))
            for i, code in enumerate(every):
                if code.group() not in numbers:
                    continue
                if before:
                    start = every[i - 1].end() if i else 0
                    span = sentence[start : code.start()]
                else:
                    end = every[i + 1].start() if i + 1 < len(every) else len(sentence)
                    span = sentence[code.end() : end]
                numbers[code.group()] += [int(n) for n in ab._BARE_INTEGER.findall(span)]
    return numbers


def count_check(model_text: str, truth: dict[str, dict]) -> dict:
    """Wrong figures and codes without figure, over the codes of `truth` the model names."""
    named = {code for code in truth if b2f._named(code, model_text)}
    figures = figures_by_code(model_text, named)
    wrong, bare = [], []
    for code in sorted(named):
        valid = {truth[code]["total"], *truth[code]["per_file"].values()}
        if not figures[code]:
            bare.append(code)
        elif not set(figures[code]) <= valid and sum(figures[code]) not in valid:
            # The sum is accepted too: a code split in two entries by message ("1 … (RUF002)",
            # "1 … (RUF002)") with 2 in the log is not a wrong figure.
            wrong.append(f"{code}:{sorted(set(figures[code]))}!={sorted(valid)}")
    return {"named_truth_codes": len(named), "wrong_counts": wrong, "no_count": bare}


def score(runs: Path) -> dict:
    fid = b2f._counter("new")
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    entries = {e["id"]: e for e in json.loads((HERE / "set.json").read_text("utf-8"))["entries"]}
    windows = json.loads((runs / "live-runs.json").read_text(encoding="utf-8"))
    rows = b2f._rows([USAGE_LOG])
    out = []
    for call in manifest["calls"]:
        for key, window in sorted(windows.items()):
            if key.split("-r")[0] != call["window"]:
                continue
            rep = key.split("-r")[1]
            path = runs / f"{call['id']}-r{rep}.txt"
            if not path.is_file():
                continue
            raw = path.read_text(encoding="utf-8")
            answer = b2f.ESCAPE.sub(r"\1", raw)
            model_only = b2f.PROGRAM_LINE.sub("", answer)
            doc = (ROOT / call["document"]).resolve()
            row = b2f._row_for(rows, call["tool"], str(doc), window["started"], window["finished"])
            log = doc.read_text(encoding="utf-8", errors="replace")
            entry = entries[call["id"]]
            codes, files = entry["top_codes"] or [], entry["top_files"] or []
            rec = {
                "id": call["id"],
                "window": call["window"],
                "rep": int(rep),
                "model": (row or {}).get("model"),
                "chunks": (row or {}).get("chunks", 1) if row else None,
                "finish_reason": (row or {}).get("finish_reason"),
                "fidelity_total": fid.count_inventions(raw, log)["total"],
                "codes": b2f._fraction(codes, answer, b2f._named),
                "files": b2f._fraction(files, answer, b2f._file_named),
                "model_codes": b2f._fraction(codes, model_only, b2f._named),
                "missing_codes": [c for c in codes if not b2f._named(c, model_only)],
            }
            if entry["true_counts"]:
                rec.update(count_check(model_only, entry["true_counts"]))
            out.append(rec)
    return {"runs": str(runs), "rows": out, "summary": summarize(out)}


def summarize(rows: list[dict]) -> dict:
    def avg(values):
        values = [v for v in values if v is not None]
        return round(mean(values), 4) if values else None

    summary = {}
    for name, wins in GROUPS.items():
        group = [r for r in rows if r["window"] in wins]
        counted = [r for r in group if "wrong_counts" in r]
        summary[name] = {
            "calls": len(group),
            "models": sorted({str(r["model"]) for r in group}),
            "multi_chunk": sum(bool(r["chunks"] and r["chunks"] > 1) for r in group),
            "codes": avg(r["codes"] for r in group),
            "files": avg(r["files"] for r in group),
            "model_codes": avg(r["model_codes"] for r in group),
            "fidelity_mean": avg(r["fidelity_total"] for r in group),
            "cut": sum(r["finish_reason"] == "length" for r in group),
            "wrong_counts": sum(len(r["wrong_counts"]) for r in counted),
            "no_count": sum(len(r["no_count"]) for r in counted),
            "answers_with_wrong_counts": sum(bool(r["wrong_counts"]) for r in counted),
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    data = score(args.runs.resolve())
    if args.out:
        text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
        args.out.write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps(data["summary"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
