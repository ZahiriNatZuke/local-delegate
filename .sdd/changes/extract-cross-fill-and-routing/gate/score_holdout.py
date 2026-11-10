"""Gate T1, REQ-004 pass 2 and REQ-005: score gemma3-4b on the holdout and run the frozen detector.

Run from the change folder:  python -I gate/score_holdout.py
A key is `correct` when its value matches the hand answer after normalizing (numbers compared as
numbers, `null` only against `null`). A wrong value equal to another requested key's hand answer
is `crossed`; any other wrong value is listed for a hand verdict (`MANUAL`, below).
Writes outputs/gate-g3-holdout-score.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHANGE = HERE.parent
sys.path.insert(0, str(HERE))

import detector_frozen as det  # noqa: E402

#: Hand verdicts for wrong values that the automatic rule cannot place (filled after reading them).
MANUAL: dict[str, str] = {
    # Hand verdicts, written after reading each source (holdout/inputs).
    "c08/fleet_size": "correct_unit_dropped",  # 22 for «22 vans»: own row, unit left out
    "c12/descuento": "correct_unit_dropped",  # 10 for «10 %»: own row, unit left out
    "c22/seeds_optional": "correct_bool",  # true for «yes»: own row
    "c19/basic_plus_support": "incomplete_or_other_row",  # «email»: part of the own cell «email and chat», and the whole cell of the Basic row (claimed by basic_storage)
    "c20/precio_rebajado_pantalon_m": "neighbour_cell_unrequested",  # empty cell filled with 39,90, the «precio» column of the same row; nobody asked for it
}


def norm(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(int(value)) if float(value).is_integer() else repr(float(value))
    text = det.norm_value(str(value))
    try:
        number = float(text.replace(",", ".").replace(" ", ""))
    except ValueError:
        return text
    return str(int(number)) if number.is_integer() else repr(number)


def main() -> int:
    holdout = json.loads((CHANGE / "holdout" / "cases.json").read_text(encoding="utf-8"))
    outputs = json.loads((CHANGE / "outputs" / "gate-g3-holdout.json").read_text(encoding="utf-8"))
    totals: dict[str, int] = {"keys": 0, "correct": 0, "crossed": 0, "error_or_raw": 0}
    per_case = {}
    flags_on_clean = []
    flags_on_crossed = []
    crossed_unflagged = []
    for case in holdout["cases"]:
        data = outputs[case["id"]]
        meta = data.get("_local_delegate", {})
        if "error" in meta or "raw" in meta:
            totals["error_or_raw"] += 1
        source = (CHANGE / "holdout" / case["input"]).read_text(encoding="utf-8")
        strict = det.detect(source, case["fields"], data)["strict"]
        verdicts = {}
        for key in case["fields"]:
            totals["keys"] += 1
            got, want = norm(data.get(key)), norm(case["expected"].get(key))
            where = f"{case['id']}/{key}"
            if got == want:
                verdict = "correct"
            elif where in MANUAL:
                verdict = MANUAL[where]
            elif got is not None and any(
                got == norm(case["expected"].get(other)) for other in case["fields"] if other != key
            ):
                verdict = "crossed"
            else:
                verdict = "other_wrong"
            totals[verdict] = totals.get(verdict, 0) + 1
            verdicts[key] = {"verdict": verdict, "value": data.get(key), "expected": case["expected"].get(key)}
            if key in strict:
                verdicts[key]["flag"] = strict[key]
                (flags_on_crossed if verdict == "crossed" else flags_on_clean).append(f"{where} ({verdict}; fila «{strict[key]['row']}»)")
            elif verdict == "crossed":
                crossed_unflagged.append(where)
        per_case[case["id"]] = {"format": case["format"], "verdicts": verdicts}
    report = {
        "detector_sha256": __import__("hashlib").sha256((HERE / "detector_frozen.py").read_bytes()).hexdigest(),
        "totals": totals,
        "flags_on_keys_without_cross": flags_on_clean,
        "flags_on_crossed_keys": flags_on_crossed,
        "crossed_unflagged": crossed_unflagged,
        "per_case": per_case,
    }
    (CHANGE / "outputs" / "gate-g3-holdout-score.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n"
    )
    sys.stdout.reconfigure(encoding="utf-8")
    print("totals", totals)
    print("flags on keys without cross", flags_on_clean)
    print("flags on crossed", flags_on_crossed)
    print("crossed unflagged", crossed_unflagged)
    for cid, case in per_case.items():
        for key, v in case["verdicts"].items():
            if v["verdict"] != "correct":
                print(" ", cid, key, v["verdict"], json.dumps(v["value"], ensure_ascii=False), "expected", json.dumps(v["expected"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
