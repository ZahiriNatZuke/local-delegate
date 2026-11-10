"""Gate T1, steps without a backend (REQ-004 pass 1, quotas, REQ-007, frozen-version sanity check).

Run from the change folder:  python -I gate/gate_offline.py
Writes outputs/gate-offline.json. Uses the frozen copy `gate/detector_frozen.py` (byte-identical to
`detector.py`, sha256 recorded in verification.md); nothing here tunes the detector.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHANGE = HERE.parent
REPO = CHANGE.parents[2]
sys.path.insert(0, str(HERE))

import detector_frozen as det  # noqa: E402

QUOTA_MIN = {
    "repeated_number_synonym_label": 2,
    "substring_of_other_key_row": 2,
    "long_cell_short_word": 2,
    "plural_ies_en": 2,
    "plural_es_es": 2,
    "similar_keys_table": 4,
    "json_prose": 2,
    "label_sentence_lines": 2,
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def has_table(source: str) -> bool:
    """Copy of `evaluate.has_table` (the prototype rule REQ-007 asks for)."""
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
    report: dict = {"detector_sha256": sha(HERE / "detector_frozen.py"), "long_cell_chars": det.LONG_CELL_CHARS}
    holdout = json.loads((CHANGE / "holdout" / "cases.json").read_text(encoding="utf-8"))

    # --- REQ-004 pass 1: frozen strict detector on the hand-annotated answers (no model).
    pairs = 0
    non_null = 0
    flags_expected = []
    control = {"crossed_keys": 0, "flagged": 0, "missed": [], "extra_flags": []}
    langs = set()
    per_case = {}
    for case in holdout["cases"]:
        source = (CHANGE / "holdout" / case["input"]).read_text(encoding="utf-8")
        langs.add(case["language"])
        pairs += len(case["fields"])
        non_null += sum(case["expected"].get(k) is not None for k in case["fields"])
        strict = det.detect(source, case["fields"], case["expected"])["strict"]
        for key, hit in strict.items():
            flags_expected.append({"case": case["id"], "key": key, **hit, "value": case["expected"].get(key)})
        crossed = case.get("crossed") or {}
        cflags = det.detect(source, case["fields"], crossed["answer"])["strict"] if crossed else {}
        for key in crossed.get("crossed_keys", {}):
            control["crossed_keys"] += 1
            if key in cflags:
                control["flagged"] += 1
            else:
                control["missed"].append(f"{case['id']}/{key}")
        for key in cflags:
            if key not in crossed.get("crossed_keys", {}):
                control["extra_flags"].append(f"{case['id']}/{key}")
        per_case[case["id"]] = {
            "format": case["format"],
            "language": case["language"],
            "keys": len(case["fields"]),
            "has_table": has_table(source),
            "flags_on_expected": sorted(strict),
            "control_flagged": sorted(cflags),
        }
    report["pass1"] = {
        "cases": len(holdout["cases"]),
        "pairs": pairs,
        "non_null_values": non_null,
        "languages": sorted(langs),
        "flags": flags_expected,
        "per_case": per_case,
    }
    report["positive_control_on_crossed_answers"] = control

    # --- Quotas, counted by program on the hand answers: the quota's key has the stated value.
    quotas: dict[str, dict] = {}
    for case in holdout["cases"]:
        for quota in case["quotas"]:
            entry = quotas.setdefault(quota["quota"], {"cases": set(), "entries": 0, "value_mismatch": []})
            entry["cases"].add(case["id"])
            entry["entries"] += 1
            if "value" in quota and det.norm_value(str(case["expected"].get(quota["key"]))) != det.norm_value(quota["value"]):
                entry["value_mismatch"].append(f"{case['id']}/{quota['key']}")
            for key in quota.get("keys", []) + quota.get("prose_keys", []) + ([quota["key"]] if "key" in quota else []):
                if key not in case["fields"]:
                    entry["value_mismatch"].append(f"{case['id']}/{key} not requested")
    report["quotas"] = {
        name: {
            "cases": sorted(v["cases"]),
            "case_count": len(v["cases"]),
            "entries": v["entries"],
            "minimum": QUOTA_MIN.get(name),
            "meets_minimum": None if name not in QUOTA_MIN else len(v["cases"]) >= QUOTA_MIN[name],
            "problems": v["value_mismatch"],
        }
        for name, v in sorted(quotas.items())
    }
    report["quotas_missing"] = sorted(set(QUOTA_MIN) - set(quotas))
    # Long-cell quota: length of the own cell (the expected value) after normalizing.
    report["long_cell_lengths"] = {
        f"{c['id']}/{q['key']}": len(det.norm_value(str(c["expected"][q["key"]])))
        for c in holdout["cases"]
        for q in c["quotas"]
        if q["quota"] == "long_cell_short_word"
    }

    # --- Sanity: the frozen copy reproduces the research verdict on the four recorded runs.
    research = json.loads((CHANGE / "cases" / "cases.json").read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in research["cases"]}
    evaluation = json.loads((CHANGE / "outputs" / "evaluation.json").read_text(encoding="utf-8"))
    sanity = {}
    for run in ("g3-extract", "g3-proxy", "g4-proxy", "g4-extract"):
        outputs = json.loads((CHANGE / "outputs" / f"{run}.json").read_text(encoding="utf-8"))
        flagged = []
        for cid, data in outputs.items():
            if cid.startswith("_"):
                continue
            src = (CHANGE / "cases" / cases[cid]["file"]).read_text(encoding="utf-8")
            flagged += [f"{cid}/{k}" for k in det.detect(src, cases[cid]["fields"], data)["strict"]]
        recorded = evaluation["detector"]["strict"][run]
        sanity[run] = {
            "flagged_now": sorted(flagged),
            "recorded_tp_fp": sorted(recorded["tp"] + [x.split(" ")[0] for x in recorded["fp"]]),
        }
        sanity[run]["identical"] = sanity[run]["flagged_now"] == sanity[run]["recorded_tp_fp"]
    report["sanity_recorded_runs"] = sanity

    # --- REQ-007: prototype `has_table` on the frozen corpus sources.
    fuentes = REPO / "benchmarks" / "catalogo-2026-09" / "fuentes"
    req7 = {}
    for path in sorted(fuentes.iterdir()):
        if path.suffix.lower() == ".png":
            continue
        req7[path.name] = has_table(path.read_text(encoding="utf-8", errors="replace"))
    report["req007_has_table"] = req7

    out = CHANGE / "outputs" / "gate-offline.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
    sys.stdout.reconfigure(encoding="utf-8")
    print("detector sha256", report["detector_sha256"])
    print("pass1", {k: v for k, v in report["pass1"].items() if k != "per_case"})
    print("control", control)
    for name, q in report["quotas"].items():
        print("quota", name, q["case_count"], q["entries"], q["minimum"], q["meets_minimum"], q["problems"])
    print("quotas missing", report["quotas_missing"])
    print("long cells", report["long_cell_lengths"])
    print("sanity", {k: v["identical"] for k, v in sanity.items()})
    print("req007", req7)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
