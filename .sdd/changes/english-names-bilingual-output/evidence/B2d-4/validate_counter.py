"""B2d-4: the fidelity counter against a review by hand, BEFORE it is applied to the measurement.

Each row is a figure of an answer already saved (`B2d-3/runs/`, `B2d-4/runs/`) with the verdict a
person gave it by reading the log: `log` (the log writes it or supports it) or `invented`. The
script asks the counter of before (`score_lint_fidelity_before.py`, the one of `810f90a`) and the
new one (`scripts/score_lint_fidelity.py`) and prints, per row, whether each one agrees.

    uv run python .sdd/changes/english-names-bilingual-output/evidence/B2d-4/validate_counter.py
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
EVIDENCE = HERE.parent

#: (answer, figure as the answer writes it, verdict by hand, why).
ROWS = [
    ("B2d-4/runs/compact/B31-r1.txt", "41", "log", "41 tests distintos de test_chunking.py"),
    ("B2d-4/runs/compact/B31-r1.txt", "16", "log", "16 tests distintos de test_density.py"),
    ("B2d-3/runs/step1/B31-r1.txt", "41", "log", "ídem"),
    ("B2d-3/runs/step1/B31-r1.txt", "16", "log", "ídem"),
    ("B2d-3/runs/base/B31-r1.txt", "44", "invented", "test_chunking.py tiene 41"),
    ("B2d-3/runs/base/B31-r1.txt", "13", "invented", "test_density.py tiene 16"),
    ("B2d-4/runs/compact/B31-r2.txt", "57", "log", "línea de total «57 passed»"),
    (
        "B2d-4/runs/compact/A12-r2.txt",
        "6",
        "invented",
        "«6 instances»: 11 líneas system y 2 max_tokens",
    ),
    ("B2d-3/runs/step1/A15-r1.txt", "three", "invented", "el log tiene 2 D103"),
    ("B2d-3/runs/step1/A15-r1.txt", "36", "log", "línea 36 del D103"),
    ("B2d-3/runs/step1/A15-r1.txt", "nine", "invented", "el log tiene 6 T201"),
    (
        "B2d-3/runs/base/B35-r1.txt",
        "4",
        "invented",
        "«Resumen de Ruff (4 errores)»: el log no lo da",
    ),
    (
        "B2d-3/runs/base/B35-r1.txt",
        "72",
        "invented",
        "los bloques son de 45 y 40 (85 de 89 líneas)",
    ),
    (
        "B2d-4/runs/main-remeasure/A12-r1.txt",
        "19,000",
        "invented",
        "«19,000 lines»: el log tiene 15",
    ),
    ("B2d-4/runs/compact/A13-r1.txt", "0", "invented", "«0 issues»: el log no escribe ningún 0"),
    ("B2d-3/runs/step1/B33-r1.txt", "52", "log", "posición `login.page.ts(52,24)`"),
    ("B2d-3/runs/step1/B33-r1.txt", "127", "log", "posición `tech-stack.component.ts(127,5)`"),
    ("B2d-3/runs/step1/A13-r2.txt", "255", "log", "«llama-swap: v255»"),
]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    before = _load("before", HERE / "score_lint_fidelity_before.py")
    after = _load("after", ROOT / "scripts/score_lint_fidelity.py")
    manifest = json.loads((HERE / "manifest.json").read_text("utf-8"))
    docs = {c["id"]: ROOT / c["document"] for c in manifest["calls"]}
    out = []
    for answer, figure, by_hand, why in ROWS:
        text = (EVIDENCE / answer).read_text("utf-8", errors="replace")
        assert figure in text, (answer, figure)  # guard: the row looks at a figure that is there
        log = docs[Path(answer).name.split("-")[0]].read_text("utf-8", errors="replace")
        row = {"answer": answer, "figure": figure, "by_hand": by_hand, "why": why}
        for name, counter in (("before", before), ("after", after)):
            flagged = figure in counter.count_inventions(text, log)["invented_numbers"]
            row[name] = "invented" if flagged else "log"
            row[name + "_agrees"] = row[name] == by_hand
        out.append(row)
    summary = {
        name: {
            "agree": sum(r[name + "_agrees"] for r in out),
            "rows": len(out),
            "negative_control_still_invented": sum(
                r[name] == "invented" for r in out if r["by_hand"] == "invented"
            ),
            "negative_control_rows": sum(r["by_hand"] == "invented" for r in out),
        }
        for name in ("before", "after")
    }
    print(json.dumps({"rows": out, "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
