"""Gate T1, REQ-001 and REQ-003: score the gemma4-26b-a4b batch of the second process.

Run from the change folder:  python -I gate/score_g4.py <out_dir_of_run_g4> <temp_usage_log>
Copies the answers and the temporary log rows into outputs/gate-g4-research.json and scores them
with the research's own `evaluate.classify` (same hand annotation as the four recorded runs).
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHANGE = HERE.parent
sys.path.insert(0, str(CHANGE))

import evaluate  # noqa: E402

CROSSED_WITH_G3 = ["01-pricing-table-en", "02-pricing-table-en-3fields", "06-limits-table-es",
                   "12-capabilities-repeated-en", "21-pricing-table-en-near-miss",
                   "22-limits-table-es-near-miss", "23-managed-service-es-near-miss",
                   "26-plans-transposed-en-near-miss"]  # fmt: skip
CLEAN_WITH_G3 = ["07-gateway-table-en", "08-managed-service-es", "09-allowances-table-en",
                 "10-spec-sheet-en", "11-ficha-suministro-es", "17-plans-transposed-en",
                 "24-allowances-table-en-near-miss", "25-gateway-table-en-near-miss"]  # fmt: skip


def main() -> int:
    out_dir, temp_log = Path(sys.argv[1]), Path(sys.argv[2])
    run = json.loads((out_dir / "g4.json").read_text(encoding="utf-8"))
    validation = json.loads((out_dir / "validation.json").read_text(encoding="utf-8"))
    log_rows = [json.loads(line) for line in temp_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    manifest = json.loads((CHANGE / "cases" / "cases.json").read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in manifest["cases"]}
    order = [k for k in run if not k.startswith("_")]
    batch_rows = log_rows[1:]  # row 0 is the validation call
    if len(batch_rows) != len(order):
        raise SystemExit(f"rows {len(batch_rows)} != cases {len(order)}")
    table = []
    for cid, row in zip(order, batch_rows, strict=True):
        case = cases[cid]
        entry = run[cid]
        answer = entry.get("answer") or {}
        meta = answer.get("_local_delegate", {}) if isinstance(answer, dict) else {}
        verdicts = {}
        for name in case["fields"]:
            kind, from_row = evaluate.classify(answer.get(name), case["expected"][name], case["rows"], case["own"].get(name))
            verdicts[name] = {"verdict": kind, "value": answer.get(name), **({"from_row": from_row} if from_row else {})}
        table.append(
            {
                "case": cid,
                "group": "crossed_with_g3" if cid in CROSSED_WITH_G3 else "clean_with_g3",
                "keys": len(case["fields"]),
                "correct": sum(v["verdict"] == "correct" for v in verdicts.values()),
                "crossed": sum(v["verdict"] == "crossed" for v in verdicts.values()),
                "failed": sum(v["verdict"] != "correct" for v in verdicts.values()),
                "error_or_raw": bool("exception" in entry or "error" in meta or "raw" in meta),
                "inference_ms": row.get("inference_ms"),
                "latency_ms": row.get("latency_ms"),
                "model": row.get("model"),
                "remote_turn": row.get("remote_turn"),
                "json_schema": row.get("json_schema"),
                "chars_in": row.get("chars_in"),
                "verdicts": verdicts,
            }
        )
    crossed_cases = [r["case"] for r in table if r["group"] == "crossed_with_g3" and r["crossed"]]
    clean_failed = sum(r["failed"] for r in table if r["group"] == "clean_with_g3")
    clean_keys = sum(r["keys"] for r in table if r["group"] == "clean_with_g3")
    errors = [r["case"] for r in table if r["error_or_raw"]]
    inference = [r["inference_ms"] for r in table]
    summary = {
        "cases": len(table),
        "models": sorted({r["model"] for r in table}),
        "crossed_group_cases_that_crossed": crossed_cases,
        "crossed_group_crossed_keys": sum(r["crossed"] for r in table if r["group"] == "crossed_with_g3"),
        "crossed_group_failed_keys": sum(r["failed"] for r in table if r["group"] == "crossed_with_g3"),
        "clean_group_failed_keys": clean_failed,
        "clean_group_keys": clean_keys,
        "error_or_raw_cases": errors,
        "inference_ms_median": statistics.median(inference),
        "inference_ms_min": min(inference),
        "inference_ms_max": max(inference),
        "criteria": {
            "crossed_in_at_most_1_of_8": len(crossed_cases) <= 1,
            "clean_failed_at_most_1_of_44": clean_failed <= 1 and clean_keys == 44,
            "no_error_or_raw": not errors,
            "median_inference_at_most_6500_ms": statistics.median(inference) <= 6500,
        },
    }
    report = {
        "_run": {
            "model": "gemma4-26b-a4b",
            "role": "long (LOCAL_DELEGATE_LONG_INPUT_CHARS=0)",
            "via": "server.local_extract(path=...) en un segundo proceso del paquete publicado 0.50.0, unido al turno del daemon (REQ-006)",
            "env": run["_run"]["env"],
        },
        "validation": validation,
        "validation_log_row": log_rows[0],
        "summary": summary,
        "cases": table,
        "answers": {cid: run[cid] for cid in order},
        "log_rows": batch_rows,
    }
    (CHANGE / "outputs" / "gate-g4-research.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n"
    )
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    for r in table:
        bad = {k: v for k, v in r["verdicts"].items() if v["verdict"] != "correct"}
        print(r["case"], r["group"], r["keys"], r["correct"], r["crossed"], r["failed"], r["inference_ms"], r["error_or_raw"], json.dumps(bad, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
