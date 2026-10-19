"""Judges every answer of a window and checks the criterion frozen in `manifest.json`.

es/en windows: `scripts/judge_response_language.py` (prose-only judge, unchanged). FR window:
`fr_judge.py`. Images are judged against an empty document (as in `evidence/live-036/judge.sh`).
Writes `answers/<window>/judge.jsonl` and prints one line per tool with the counts and PASS/FAIL.

    python judge_samples.py --window ES
"""

import argparse
import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import detect_language
import fr_judge
import judge_response_language


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", required=True, choices=["ES", "EN", "FR"])
    args = parser.parse_args()
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    requested = manifest["windows"][args.window]["requested"]
    repeat = manifest["repeat"]
    folder = HERE / "answers" / args.window
    words = detect_language.load_function_words()
    fr_words = fr_judge.load_words()
    rows = []
    for c in (c for c in manifest["calls"] if c["window"] == args.window):
        doc_path = ROOT / c["document"]
        document = (
            ""
            if doc_path.suffix == ".png"
            else doc_path.read_text(encoding="utf-8", errors="replace")
        )
        for rep in range(1, repeat + 1):
            answer = folder / f"{c['id']}-r{rep}.txt"
            if not answer.exists():
                rows.append({"id": c["id"], "rep": rep, "tool": c["tool"], "verdict": "missing"})
                continue
            text = answer.read_text(encoding="utf-8", errors="replace")
            if text.lstrip().startswith("[local-delegate error"):
                verdict = {"verdict": "error"}
            elif requested == "fr":
                verdict = fr_judge.judge(text, document, fr_words)
            else:
                j = judge_response_language.judge(text, document, requested, words=words)._asdict()
                j.pop("judged_text")
                verdict = j
            rows.append(
                {"id": c["id"], "rep": rep, "tool": c["tool"], "chars": len(text), **verdict}
            )
    with (folder / "judge.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    ok = True
    by_tool = collections.defaultdict(list)
    for r in rows:
        by_tool[r["tool"]].append(r["verdict"])
    for tool, verdicts in by_tool.items():
        counts = collections.Counter(verdicts)
        share = counts["requested"] / len(verdicts)
        opposite = counts["opposite"] + counts["other"]
        passed = share >= 0.90 and opposite == 0
        ok &= passed
        print(
            f"{args.window} {tool}: {counts['requested']}/{len(verdicts)} requested "
            f"({share:.0%}), {dict(counts)} -> {'PASS' if passed else 'FAIL'}"
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
