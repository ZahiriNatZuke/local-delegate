"""T7, REQ-038: score the live test of the routing, run by the daemon inside a test window.

Run from the change folder:

    python -I gate/score_live.py outputs/live-answers.json outputs/live-log-rows.jsonl

`live-answers.json` maps each case id of `cases/cases.json` (all 26) to the object
`local_extract` returned, in the order they were called. `live-log-rows.jsonl` holds the rows of
the usage log for the window (`tool: local_extract`, same order; nothing else). Writes
`outputs/live-score.json`, prints the summary and exits 1 if a criterion fails.
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

MECHANICAL, LONG = "gemma3-4b", "gemma4-26b-a4b"
CROSSED_WITH_G3 = {"01", "02", "06", "12", "21", "22", "23", "26"}


def main() -> int:
    answers = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows = [row for row in rows if row.get("tool") == "local_extract"]
    cases = {c["id"]: c for c in json.loads((CHANGE / "cases" / "cases.json").read_text(encoding="utf-8"))["cases"]}
    order = [cid for cid in answers if not cid.startswith("_")]
    if sorted(order) != sorted(cases) or len(rows) != len(order):
        raise SystemExit(f"cases {len(order)} / rows {len(rows)}: expected 26 and 26")
    table, problems = [], []
    for cid, row in zip(order, rows, strict=True):
        case, answer = cases[cid], answers[cid] or {}
        meta = answer.get("_local_delegate", {}) if isinstance(answer, dict) else {}
        group = "large" if case.get("large") else ("table" if case["has_table"] else "no_table")
        verdicts = {
            name: evaluate.classify(answer.get(name), case["expected"][name], case["rows"], case["own"].get(name))[0]
            for name in case["fields"]
        }
        reason_answer = (meta.get("role_reason") or {}).get("reason")
        entry = {
            "case": cid,
            "group": group,
            "model": row.get("model"),
            "role_reason_answer": reason_answer,
            "role_reason_log": row.get("role_reason"),
            "crossed": sum(v == "crossed" for v in verdicts.values()),
            "failed": sum(v != "correct" for v in verdicts.values()),
            "error_or_raw": "error" in meta or "raw" in meta,
            "inference_ms": row.get("inference_ms"),
            "verdicts": verdicts,
        }
        table.append(entry)
        if group == "no_table" and (entry["model"] != MECHANICAL or reason_answer or entry["role_reason_log"]):
            problems.append(f"{cid}: without a table it must stay on {MECHANICAL} with no role_reason")
        if group == "table" and (entry["model"] != LONG or reason_answer != "table" or entry["role_reason_log"] != "table"):
            problems.append(f"{cid}: a small table must go to {LONG} with role_reason table (answer and log)")
        if group == "large" and (entry["model"] != LONG or reason_answer or entry["role_reason_log"]):
            problems.append(f"{cid}: a large input stays on {LONG} with no role_reason")
        if entry["error_or_raw"]:
            problems.append(f"{cid}: error/raw in the answer")
    crossed_cases = [r["case"] for r in table if r["case"][:2] in CROSSED_WITH_G3 and r["crossed"]]
    if len(crossed_cases) > 1:
        problems.append(f"crossed in {len(crossed_cases)} of the 8 that crossed with {MECHANICAL}: {crossed_cases}")
    table_inference = [r["inference_ms"] for r in table if r["group"] == "table" and r["inference_ms"] is not None]
    summary = {
        "cases": len(table),
        "crossed_cases_of_the_8": crossed_cases,
        "error_or_raw": [r["case"] for r in table if r["error_or_raw"]],
        "table_inference_ms_median": statistics.median(table_inference) if table_inference else None,
        "problems": problems,
        "pass": not problems,
    }
    (CHANGE / "outputs" / "live-score.json").write_text(
        json.dumps({"summary": summary, "cases": table}, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    for r in table:
        print(r["case"][:2], r["group"], r["model"], r["role_reason_answer"], r["role_reason_log"], r["crossed"], r["failed"], r["inference_ms"])
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
