"""Controls of `fr_judge.py` (no model calls; the French texts come from fr_control_positive.py).

Negative: the 44 B2d-2 answers (es/en) and the 30 answers of the ES window must never come out
`fr` (`requested`). Positive: the 8 French translations in `fr-control/` must come out `fr`.
Writes `fr-control-negative.jsonl` and `fr-control-positive.jsonl` and prints the counts.
"""

import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[4]
sys.path[:0] = [str(HERE), str(ROOT / "scripts"), str(ROOT / "src")]

import fr_judge

EV = HERE.parent


def _doc(path: str) -> str:
    p = ROOT / path
    return "" if not path or p.suffix == ".png" else p.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    words = fr_judge.load_words()
    b2d2 = json.loads((EV / "B2d-2/manifest.json").read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in b2d2["calls"]}
    ours = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    negative = []
    for c in b2d2["calls"]:
        text = (ROOT / c["answer"]).read_text(encoding="utf-8", errors="replace")
        negative.append({"id": c["id"], **fr_judge.judge(text, _doc(c["document"]), words)})
    for c in (c for c in ours["calls"] if c["window"] == "ES"):
        for rep in (1, 2, 3):
            text = (HERE / f"answers/ES/{c['id']}-r{rep}.txt").read_text(encoding="utf-8")
            negative.append(
                {"id": f"{c['id']}-r{rep}", **fr_judge.judge(text, _doc(c["document"]), words)}
            )
    positive = []
    for f in sorted((HERE / "fr-control").glob("*.txt")):
        doc = by_id[f.stem]["document"] if f.stem in by_id else ""
        positive.append(
            {"id": f.stem, **fr_judge.judge(f.read_text(encoding="utf-8"), _doc(doc), words)}
        )
    for name, rows in (("negative", negative), ("positive", positive)):
        with (HERE / f"fr-control-{name}.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(name, len(rows), dict(collections.Counter((r["verdict"], r["lang"]) for r in rows)))
    neg_ok = all(r["verdict"] != "requested" for r in negative)
    pos_ok = all(r["verdict"] == "requested" for r in positive)
    print(f"negative {'PASS' if neg_ok else 'FAIL'}, positive {'PASS' if pos_ok else 'FAIL'}")
    return 0 if neg_ok and pos_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
