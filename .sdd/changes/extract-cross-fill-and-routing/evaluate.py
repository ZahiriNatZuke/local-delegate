"""Scores the live outputs against the hand-annotated answers and runs the detector on them.

Research script of the SDD `extract-cross-fill-and-routing` (#586); not part of the product.
Run from this folder:  python evaluate.py   (writes outputs/evaluation.json and prints the tables)
"""

from __future__ import annotations

import json
import sys
from itertools import combinations
from pathlib import Path

import detector

_bounded = detector._bounded
_leaves = detector._leaves
detect = detector.detect
is_marker = detector.is_marker
norm_value = detector.norm_value
words = detector.words

HERE = Path(__file__).parent
RUNS = ["g3-extract", "g3-proxy", "g4-proxy", "g4-extract"]
VARIANTS = ["strict", "loose", "partial"]


def text_of(value) -> str:
    """One normalized string with every leaf of the answer."""
    return norm_value(" | ".join(_leaves(value)))


def is_null(value) -> bool:
    return value is None or value == [] or value == {} or is_marker(value)


def has(text: str, piece: str) -> bool:
    return _bounded(norm_value(piece), text)


def as_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(norm_value(value).replace(" ", ""))
        except ValueError:
            return None
    return None


def is_correct(value, spec: dict) -> bool:
    text = text_of(value)
    if spec.get("null"):
        if is_null(value):
            return True
        return any(has(text, piece) for piece in spec.get("also_ok", []))
    if is_null(value):
        return False
    if "bool" in spec:
        return value is spec["bool"] or text in ({"true", "si", "yes"} if spec["bool"] else {"false", "no"})
    if "number" in spec:
        number = as_number(value)
        return number is not None and abs(number - spec["number"]) < 1e-9
    if "exact_any" in spec:
        return text in spec["exact_any"]
    if any(has(text, piece) for piece in spec.get("none", [])):
        return False
    if "all" in spec and not all(has(text, piece) for piece in spec["all"]):
        return False
    return not ("any" in spec and not any(has(text, piece) for piece in spec["any"]))


def classify(value, spec: dict, rows: dict, own: str | None) -> tuple[str, str | None]:
    """(`correct` | `crossed` | `missed` | `invented`, the foreign row the value came from)."""
    if is_correct(value, spec):
        return "correct", None
    if is_null(value):
        return "missed", None
    text = text_of(value)
    in_own = own is not None and any(has(text, cell) for cell in rows.get(own, []))
    for label, cells in rows.items():
        if label != own and not in_own and any(has(text, cell) for cell in cells):
            return "crossed", label
    return "invented", None


def shared_fields(fields: list[str]) -> int:
    """How many requested fields share a content word with another requested field."""
    bags = {name: words(name) for name in fields}
    return sum(any(bags[a] & bags[b] for b in fields if b != a) for a in fields)


def has_table(source: str) -> bool:
    low = source.lower()
    if "<table" in low or "<tr" in low:
        return True
    lines = source.split("\n")
    for index, line in enumerate(lines[:-1]):
        nxt = lines[index + 1].strip()
        if line.count("|") >= 2 and "--" in nxt and not nxt.strip("|:- \t"):
            return True
    return False


def main() -> int:
    manifest = json.loads((HERE / "cases" / "cases.json").read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in manifest["cases"]}
    sources = {cid: (HERE / "cases" / case["file"]).read_text(encoding="utf-8") for cid, case in cases.items()}
    report: dict = {"runs": {}, "detector": {}, "swap_control": {}, "routing": {}}

    # 1. Accuracy and crossings per run and per case.
    per_key: dict[str, dict] = {}
    for run in RUNS:
        outputs = json.loads((HERE / "outputs" / f"{run}.json").read_text(encoding="utf-8"))
        totals = {"cases": 0, "keys": 0, "correct": 0, "crossed": 0, "missed": 0, "invented": 0}
        rows_out = {}
        for cid, data in outputs.items():
            if cid.startswith("_"):
                continue
            case = cases[cid]
            verdicts = {}
            for name in case["fields"]:
                kind, row = classify(data.get(name), case["expected"][name], case["rows"], case["own"].get(name))
                verdicts[name] = {"verdict": kind, "value": data.get(name), **({"from_row": row} if row else {})}
                totals[kind] += 1
                totals["keys"] += 1
                per_key[f"{run}/{cid}/{name}"] = verdicts[name]
            totals["cases"] += 1
            rows_out[cid] = verdicts
        report["runs"][run] = {"totals": totals, "cases": rows_out}

    # 2. Detector on the real outputs: flagged keys against the hand classification.
    for variant in VARIANTS:
        report["detector"][variant] = {}
    for run in RUNS:
        outputs = json.loads((HERE / "outputs" / f"{run}.json").read_text(encoding="utf-8"))
        tally = {v: {"tp": [], "fp": [], "fn": [], "negatives": 0} for v in VARIANTS}
        for cid, data in outputs.items():
            if cid.startswith("_"):
                continue
            case = cases[cid]
            flags = detect(sources[cid], case["fields"], data)
            for name in case["fields"]:
                verdict = per_key[f"{run}/{cid}/{name}"]["verdict"]
                for variant in VARIANTS:
                    flagged = name in flags[variant]
                    where = f"{cid}/{name}"
                    if verdict == "crossed":
                        tally[variant]["tp" if flagged else "fn"].append(where)
                    else:
                        tally[variant]["negatives"] += 1
                        if flagged:
                            tally[variant]["fp"].append(f"{where} ({verdict}; fila «{flags[variant][name]['row']}»)")
        for variant in VARIANTS:
            report["detector"][variant][run] = tally[variant]

    # 3. Positive control: swap two correct values that come from different rows; the detector has
    #    to flag both. Built on the answers that are right, so nothing here depends on a model.
    for variant in VARIANTS:
        report["swap_control"][variant] = {"pairs": 0, "keys": 0, "flagged": 0, "missed": []}
    seen = set()
    for run in RUNS:
        outputs = json.loads((HERE / "outputs" / f"{run}.json").read_text(encoding="utf-8"))
        for cid, data in outputs.items():
            if cid.startswith("_"):
                continue
            case = cases[cid]
            good = [
                n for n in case["fields"]
                if per_key[f"{run}/{cid}/{n}"]["verdict"] == "correct" and case["own"].get(n) and not is_null(data.get(n))
            ]
            for a, b in combinations(good, 2):
                if case["own"][a] == case["own"][b] or text_of(data[a]) == text_of(data[b]):
                    continue
                key = (cid, a, b, text_of(data[a]), text_of(data[b]))
                if key in seen:
                    continue
                seen.add(key)
                swapped = {**data, a: data[b], b: data[a]}
                flags = detect(sources[cid], case["fields"], swapped)
                for variant in VARIANTS:
                    control = report["swap_control"][variant]
                    control["pairs"] += 1
                    for name in (a, b):
                        control["keys"] += 1
                        if name in flags[variant]:
                            control["flagged"] += 1
                        else:
                            control["missed"].append(f"{cid}/{name} <- {b if name == a else a}")

    # 4. Routing rules: what each one would send to `long`, against where gemma3-4b crossed.
    g3 = report["runs"]["g3-extract"]["cases"]
    routing_rows = []
    for cid, case in cases.items():
        source = sources[cid]
        crossed = None
        if cid in g3:
            crossed = sum(v["verdict"] == "crossed" for v in g3[cid].values())
        routing_rows.append(
            {
                "case": cid,
                "bytes": len(source.encode("utf-8")),
                "table": has_table(source),
                "fields": len(case["fields"]),
                "shared_fields": shared_fields(case["fields"]),
                "g3_crossed": crossed,
                "g3_wrong": None if cid not in g3 else sum(v["verdict"] != "correct" for v in g3[cid].values()),
            }
        )
    report["routing"]["cases"] = routing_rows
    small = [r for r in routing_rows if r["g3_crossed"] is not None]
    rules = {
        "table": lambda r: r["table"],
        "shared>=2": lambda r: r["shared_fields"] >= 2,
        "shared>=3": lambda r: r["shared_fields"] >= 3,
        "shared>=4": lambda r: r["shared_fields"] >= 4,
        "table or shared>=3": lambda r: r["table"] or r["shared_fields"] >= 3,
        "table and shared>=2": lambda r: r["table"] and r["shared_fields"] >= 2,
        "table and fields>=5": lambda r: r["table"] and r["fields"] >= 5,
    }
    report["routing"]["rules"] = {}
    bad = [r for r in small if r["g3_crossed"]]
    clean = [r for r in small if not r["g3_crossed"]]
    for label, rule in rules.items():
        report["routing"]["rules"][label] = {
            "fires": sum(map(rule, small)),
            "of": len(small),
            "crossing_cases_caught": sum(map(rule, bad)),
            "crossing_cases": len(bad),
            "crossed_keys_caught": sum(r["g3_crossed"] for r in bad if rule(r)),
            "crossed_keys": sum(r["g3_crossed"] for r in bad),
            "clean_cases_upgraded": sum(map(rule, clean)),
            "clean_cases": len(clean),
            "missed": [r["case"] for r in bad if not rule(r)],
        }

    # 5. The same detector without the long-cell guard (how it was before the first run).
    guard = detector.LONG_CELL_CHARS
    detector.LONG_CELL_CHARS = None
    report["detector_without_long_cell_guard"] = {}
    for variant in VARIANTS:
        counts = {"tp": 0, "fp": [], "fn": 0}
        for run in RUNS:
            outputs = json.loads((HERE / "outputs" / f"{run}.json").read_text(encoding="utf-8"))
            for cid, data in outputs.items():
                if cid.startswith("_"):
                    continue
                flags = detect(sources[cid], cases[cid]["fields"], data)[variant]
                for name in cases[cid]["fields"]:
                    crossed = per_key[f"{run}/{cid}/{name}"]["verdict"] == "crossed"
                    if crossed:
                        counts["tp" if name in flags else "fn"] += 1
                    elif name in flags:
                        counts["fp"].append(f"{run}/{cid}/{name}")
        report["detector_without_long_cell_guard"][variant] = counts
    detector.LONG_CELL_CHARS = guard

    (HERE / "outputs" / "evaluation.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n"
    )

    out = sys.stdout
    out.reconfigure(encoding="utf-8")
    print("== aciertos por corrida ==")
    for run in RUNS:
        print(run, report["runs"][run]["totals"])
    print("== claves no acertadas ==")
    for where, verdict in per_key.items():
        if verdict["verdict"] != "correct":
            print(" ", where, verdict["verdict"], json.dumps(verdict["value"], ensure_ascii=False), verdict.get("from_row", ""))
    print("== detector ==")
    for variant in VARIANTS:
        for run in RUNS:
            t = report["detector"][variant][run]
            print(f" {variant:8} {run:11} VP={len(t['tp'])} FP={len(t['fp'])} FN={len(t['fn'])} negativos={t['negatives']}")
            for kind in ("tp", "fp", "fn"):
                for item in t[kind]:
                    print(f"      {kind.upper()} {item}")
    print("== detector sin la guarda de celda larga ==")
    for variant in VARIANTS:
        c = report["detector_without_long_cell_guard"][variant]
        print(f" {variant:8} VP={c['tp']} FP={len(c['fp'])} FN={c['fn']}", c["fp"] if variant == "strict" else "")
    print("== control positivo (intercambio de dos valores correctos) ==")
    for variant in VARIANTS:
        c = report["swap_control"][variant]
        print(f" {variant:8} pares={c['pairs']} claves={c['keys']} marcadas={c['flagged']}")
        by_case: dict[str, int] = {}
        for item in c["missed"]:
            by_case[item.split("/")[0]] = by_case.get(item.split("/")[0], 0) + 1
        print("      sin marcar, por caso:", by_case)
    print("== enrutado ==")
    for r in routing_rows:
        print(" ", r)
    for label, r in report["routing"]["rules"].items():
        print(f" {label:22}", {k: v for k, v in r.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
