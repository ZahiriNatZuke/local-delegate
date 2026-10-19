"""lint-large-logs: scoring of the live measurement, fixed BEFORE measuring (`plan.md`).

Per answer (`<runs>/<id>-r<k>.txt`), against `set.json`:

- `codes`, `files`, `model_codes`, `model_files`, `fidelity_total`, `finish_reason`, `chunks`,
  `model`: as `B2f/score_b2f.py` (its functions; fidelity counter `new`), plus `latency_ms`.
- `per_file_wrong`: the figures the MODEL gives per file that do not match the truth of `set.json`
  (reader of `plan.md`, independent of the product), with `per_file_checked` (figures read).

    uv run python score_large.py --runs runs/base --usage-log LOG [LOG ...] --out score-base.json
    uv run python score_large.py --check runs/x/M1-r3.txt M1      # print what the reader sees
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path
from statistics import mean, median

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


b2f = _load("score_b2f", HERE.parent / "B2f" / "score_b2f.py")
lint_patterns = b2f.lint_patterns

GROUPS = {"large_es": ("X",), "long_es_control": ("G",), "mech_es": ("M",), "mech_en": ("ME",)}

#: Lines the program or the tool add: never the model's.
NOT_MODEL = re.compile(
    r"(?m)^(?:Sin mencionar \(del log|Not mentioned \(in the log|Y otros \d+ ficheros|"
    r"And \d+ other files|\(leído server-side|\(read server-side|\[local-delegate).*$"
)
#: The line of the program with how many files have no entry: its figure is not the model's.
PROGRAM_COUNT = re.compile(r"(?m)^(?:Y otros \d+ ficheros|And \d+ other files).*$")
COUNT_WORDS = (
    r"(?:errores|error|avisos|aviso|advertencias|advertencia|veces|vez|tests|test|pruebas|prueba|"
    r"problemas|problema|instancias|instancia|ocurrencias|ocurrencia|casos|caso|diagnósticos|"
    r"diagnóstico|errors|warnings|warning|times|occurrences|occurrence|issues|issue|problems|"
    r"problem|instances|instance|diagnostics|diagnostic|hallazgos|hallazgo|fallos|fallo)"
)
#: Line numbers and coordinates, removed before reading figures.
POSITIONS = re.compile(
    r"\(\d+,\s*\d+\)|\b\d+:\d+(?::\d+)?\b|\b(?:l[íi]neas?|lines?|L)\s*\d+(?:\s*(?:,|y|and|-|–)\s*\d+)*",
    re.IGNORECASE,
)
HEADING = re.compile(r"^\s*(?:#+\s|\*\*[^*]+\*\*:?\s*$|[A-ZÁÉÍÓÚ][^:]{0,60}:\s*$)")


def _file_keys(truth_files: list[str]) -> dict[str, str]:
    """Answer token -> truth file: the full path and, when unique, the basename."""
    keys: dict[str, str] = {}
    bases: dict[str, list[str]] = {}
    for f in truth_files:
        norm = lint_patterns.norm_path(f)
        keys[norm] = f
        bases.setdefault(norm.rsplit("/", 1)[-1], []).append(f)
    for base, owners in bases.items():
        if len(owners) == 1:
            keys.setdefault(base, owners[0])
    return keys


def _files_in(line: str, keys: dict[str, str]) -> set[str]:
    found = set()
    for token in lint_patterns.FILE.findall(line):
        norm = lint_patterns.norm_path(token).removeprefix("./")
        hit = keys.get(norm)
        if hit is None:  # a suffix of a truth path ("app/util.py" for "/home/.../app/util.py")
            cands = {f for k, f in keys.items() if "/" in k and k.endswith("/" + norm)}
            hit = next(iter(cands)) if len(cands) == 1 else None
        if hit is None:
            hit = keys.get(norm.rsplit("/", 1)[-1])
        if hit is not None:
            found.add(hit)
    return found


def _code_figures(line: str, code: str) -> list[int]:
    c = re.escape(code)
    out = []
    after = re.compile(r"(?<![\w/@-])" + c + r"(?![\w/-])[\s:*()`\-–—x×=]{1,8}(\d+)\b(?!\s*%)")
    before = re.compile(r"\b(\d+)\s*(?:x|×|veces|times)?\s*[*`(]*" + c + r"(?![\w/-])")
    for pattern in (after, before):
        out += [int(n) for n in pattern.findall(line)]
    return out[:1]


def per_file_check(text: str, truth: dict | None) -> dict:
    """The reader of `plan.md`. Returns `checked`, `wrong` and the wrong items (for the record)."""
    if not truth:
        return {"checked": 0, "wrong": 0, "items": []}
    text = b2f.ESCAPE.sub(r"\1", NOT_MODEL.sub("", text))
    per_file, totals = truth["per_file"], truth["codes"]
    keys = _file_keys(list(per_file))
    codes = sorted(totals, key=len, reverse=True)
    current: str | None = None
    checked, items = 0, []
    for raw in text.splitlines():
        files = _files_in(raw, keys)
        if len(files) == 1:
            current = next(iter(files))
        elif len(files) > 1 or HEADING.match(raw):
            current = None
            continue
        line = POSITIONS.sub(" ", lint_patterns.FILE.sub(" ", raw))
        named = [
            c for c in codes if re.search(r"(?<![\w/@-])" + re.escape(c) + r"(?![\w/-])", line)
        ]
        for code in named:
            for n in _code_figures(line, code):
                checked += 1
                if current is not None:
                    ok = n == per_file[current]["codes"].get(code)
                else:
                    ok = n == totals[code] or n in {v["codes"].get(code) for v in per_file.values()}
                if not ok:
                    items.append({"file": current, "code": code, "figure": n, "line": raw[:120]})
        if current is not None and not named:
            stripped = line
            for n in re.findall(r"\b(\d+)\s+" + COUNT_WORDS + r"\b", stripped, re.IGNORECASE):
                n = int(n)
                checked += 1
                valid = {per_file[current]["total"], *per_file[current]["codes"].values()}
                if n not in valid:
                    items.append({"file": current, "code": None, "figure": n, "line": raw[:120]})
    return {"checked": checked, "wrong": len(items), "items": items}


def score(runs: Path, logs: list[Path]) -> dict:
    fid = b2f._counter("new")
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    entries = {e["id"]: e for e in json.loads((HERE / "set.json").read_text("utf-8"))["entries"]}
    windows = json.loads((runs / "live-runs.json").read_text(encoding="utf-8"))
    rows = b2f._rows(logs)
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
            model_only = b2f.PROGRAM_LINE.sub("", NOT_MODEL.sub("", answer))
            doc = (ROOT / call["document"]).resolve()
            row = b2f._row_for(rows, call["tool"], str(doc), window["started"], window["finished"])
            log = doc.read_text(encoding="utf-8", errors="replace")
            entry = entries[call["id"]]
            codes, files = entry["top_codes"], entry["top_files"]
            check = per_file_check(raw, entry["truth"])
            out.append(
                {
                    "id": call["id"],
                    "window": call["window"],
                    "rep": int(rep),
                    "model": (row or {}).get("model"),
                    "chunks": (row or {}).get("chunks", 1) if row else None,
                    "finish_reason": (row or {}).get("finish_reason"),
                    "latency_ms": (row or {}).get("latency_ms"),
                    "cut_notice": "[local-delegate" in raw
                    and "length" in raw
                    or bool(re.search(r"cortad|truncat", raw[-400:], re.IGNORECASE)),
                    "chars": len(raw),
                    "fidelity_total": fid.count_inventions(PROGRAM_COUNT.sub("", raw), log, ())[
                        "total"
                    ],
                    "codes": b2f._fraction(codes, answer, b2f._named),
                    "files": b2f._fraction(files, answer, b2f._file_named),
                    "model_codes": b2f._fraction(codes, model_only, b2f._named),
                    "model_files": b2f._fraction(files, model_only, b2f._file_named),
                    "per_file_checked": check["checked"],
                    "per_file_wrong": check["wrong"],
                    "per_file_items": check["items"],
                }
            )
    return {"runs": str(runs), "rows": out, "summary": summarize(out)}


def summarize(rows: list[dict]) -> dict:
    def avg(values):
        values = [v for v in values if v is not None]
        return round(mean(values), 4) if values else None

    summary = {}
    for name, wins in GROUPS.items():
        group = [r for r in rows if r["window"] in wins]
        if not group:
            continue
        lat = [r["latency_ms"] for r in group if r["latency_ms"] is not None]
        summary[name] = {
            "calls": len(group),
            "models": sorted({str(r["model"]) for r in group}),
            "multi_chunk": sum(bool(r["chunks"] and r["chunks"] > 1) for r in group),
            "codes": avg(r["codes"] for r in group),
            "files": avg(r["files"] for r in group),
            "model_codes": avg(r["model_codes"] for r in group),
            "model_files": avg(r["model_files"] for r in group),
            "fidelity_mean": avg(r["fidelity_total"] for r in group),
            "cut": sum(r["finish_reason"] == "length" for r in group),
            "answers_per_file_wrong": sum(r["per_file_wrong"] > 0 for r in group),
            "per_file_wrong": sum(r["per_file_wrong"] for r in group),
            "per_file_checked": sum(r["per_file_checked"] for r in group),
            "latency_median_s": round(median(lat) / 1000, 1) if lat else None,
            "chars_median": median(r["chars"] for r in group),
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path)
    parser.add_argument("--usage-log", type=Path, nargs="+")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--check", nargs=2, metavar=("ANSWER", "ID"))
    args = parser.parse_args()
    if args.check:
        entries = {
            e["id"]: e for e in json.loads((HERE / "set.json").read_text("utf-8"))["entries"]
        }
        text = Path(args.check[0]).read_text(encoding="utf-8")
        print(
            json.dumps(
                per_file_check(text, entries[args.check[1]]["truth"]), ensure_ascii=False, indent=1
            )
        )
        return 0
    data = score(args.runs.resolve(), args.usage_log)
    if args.out:
        args.out.write_text(
            json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
        )
    print(json.dumps(data["summary"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
