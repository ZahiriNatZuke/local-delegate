"""B2d-4, second round: fidelity per call and repetition, with the new counter and the old one.

Each cell is `new(old) [invented numbers][invented files] repeated sentences`.

    uv run python .sdd/changes/english-names-bilingual-output/evidence/B2d-4/score_round2_per_call.py round2-main round2-new
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(tags: list[str]) -> None:
    old = _load("old", HERE / "score_lint_fidelity_before.py")
    new = _load("new", ROOT / "scripts/score_lint_fidelity.py")
    manifest = json.loads((HERE / "manifest.json").read_text("utf-8"))
    docs = {
        c["id"]: (ROOT / c["document"]).read_text("utf-8", errors="replace")
        for c in manifest["calls"]
    }
    for tag in tags:
        folder = HERE / "runs" / tag
        totals = {"old": [0, 0, 0], "new": [0, 0, 0]}
        print("==", tag)
        for cid, log in docs.items():
            cells = []
            for rep in (1, 2, 3):
                answer = (folder / f"{cid}-r{rep}.txt").read_text("utf-8", errors="replace")
                o = old.count_inventions(answer, log)
                n = new.count_inventions(answer, log)
                totals["old"][rep - 1] += o["total"]
                totals["new"][rep - 1] += n["total"]
                cells.append(
                    f"{n['total']}({o['total']}) {n['invented_numbers']}{n['invented_files']}"
                    f"{len(n['repeated_sentences'])}"
                )
            print(cid, " | ".join(cells))
        mean_new = round(sum(totals["new"]) / 3, 2)
        mean_old = round(sum(totals["old"]) / 3, 2)
        print("totals new", totals["new"], mean_new, "old", totals["old"], mean_old)


if __name__ == "__main__":
    main(sys.argv[1:])
