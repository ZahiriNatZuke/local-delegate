#!/usr/bin/env python3
"""B2-affinity: checks the lint scorer of `evaluate_reevaluation.py` before it is used (plan).

The file keeps its first name; since the v2 failed its control 2 it checks the v3 (v2 without
`un`/`una`), which `use_scorer("v2")` installs ("v2" is the option name of the adjusted scorer).

1. `reference_ok` scores 1 and `reference_bad` < 1 in the 4 lint cases (v1 and v3).
2. On the frozen T6 answers (`benchmarks/afinidad-2026-10/resultados/*.jsonl`), every row where v3
   and v1 (the T6 scorer) differ is printed with both readings, for the manual review.
3. Prints, for the 16 answers of repetition 1 of the first run (role and 26B, es and en), the
   rules each scorer marks wrong, for the manual review in `scorer-v2-check.md`.

    uv run python scorer_v2_check.py > scorer-v3-check.txt
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import evaluate_reevaluation as ev

ab = ev.ab
CORPUS = ev.CORPUS


def _counts(case: dict) -> dict:
    spec = ab.LEGACY_NAMES.normalize("affinity_scorer", case.get("scorer") or case["puntuador"])
    return spec["counts"]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    data = json.loads((CORPUS / "cases.json").read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in data["cases"] if c.get("tool") == ev.TOOL}
    failures = 0
    print("## 1. References")
    for scorer in ("v1", "v2"):
        ev.use_scorer(scorer)
        for cid, c in cases.items():
            ok = ab.score_affinity(c, c["reference_ok"])
            bad = ab.score_affinity(c, c["reference_bad"])
            good = ok["quality"] == 1.0 and ok["format"] and bad["quality"] < 1.0
            failures += not good
            print(f"{scorer} {cid}: ok={ok} bad={bad} -> {'pass' if good else 'FAIL'}")
    print("\n## 2. Frozen T6 answers: v3 against v1 (T6 scorer)")
    rows = ab.read_jsonl(sorted((CORPUS / "resultados").glob("*.jsonl")))
    compared = differing = 0
    for row in rows:
        case = cases.get(str(row.get("case")))
        if case is None or row.get("outcome") != "ok" or "response" not in row:
            continue
        ev.use_scorer("v1")
        v1 = ab.score_affinity(case, row["response"], row)
        ev.use_scorer("v2")
        v2 = ab.score_affinity(case, row["response"], row)
        compared += 1
        if v1 != v2:
            differing += 1
            counts = _counts(case)
            print(f"\n### DIFFERS {row['label']} {row['case']}: v1={v1} v3={v2}")
            print(f"valid counts: {counts}")
            print(f"wrong v1: {ev._T6_RULES_WITH_WRONG_COUNT(row['response'], counts)}")
            print(f"wrong v3: {ev.rules_with_wrong_count_v2(row['response'], counts)}")
            print(row["response"])
    print(f"{compared} T6 lint rows compared, {differing} differ (each one: manual review)")
    failures += compared == 0
    print("\n## 3. Repetition 1 of the first run (for the manual review)")
    first = HERE / "first-run" / "results"
    for lang in ev.LANGUAGES:
        for model in (ev.ROLE, ev.ALTERNATIVE):
            path = first / lang / f"{model}.jsonl"
            for row in ab.read_jsonl([path]):
                if int(row["run"]) != 1:
                    continue
                counts = _counts(cases[row["case"]])
                wrong_v1 = ev._T6_RULES_WITH_WRONG_COUNT(row["response"], counts)
                wrong_v2 = ev.rules_with_wrong_count_v2(row["response"], counts)
                print(f"\n### {lang} {model} {row['case']}")
                print(f"valid counts: {counts}")
                print(f"wrong v1: {wrong_v1}  wrong v2: {wrong_v2}")
                print(ev.strip_footer(row["response"]))
    print(f"\nchecks failed: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
