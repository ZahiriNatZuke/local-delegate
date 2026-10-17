#!/usr/bin/env python3
"""Control of B2d-3: the real figures of the logs that have them are still in the answers.

The count rule must remove invented counts, not the real ones. Four logs of set 3 carry a total
line; their figures were chosen BEFORE measuring (2026-10-17) by reading the logs:

- A14 `en-log-biome-lint-nest`: "Found 125 errors.", "Found 551 warnings.", "Found 653 infos."
- A15 `en-log-ruff-concise-build-site`: "Found 10 errors."
- B31 `en-log-pytest-chunking-density`: "57 passed"
- B32 `en-log-ruff-concise-clean-watcher`: "Found 7 errors."

A figure counts as kept when it appears in the answer as a whole number: not inside a longer one
(`157`, `0.57`, `57.3`), but a full stop that ends the sentence is fine ("Pruebas superadas: 57.").
The first version used `(?![\\d.])` and rejected that full stop: B31 of the step 1 came out as not
kept (fixed 2026-10-17, test in `tests/test_lint_count_rule.py`). Only digits count: the total
line is meant to be copied, not spelled out.

An answer counts as a case kept when it keeps at least one of its figures. With repetitions, a
case is kept in a version when it is kept in the majority of them (2 of 3). A cut answer (receipt
with `finish_reason=length`) is noted and not judged, as in `measure.md`.

    # The answers of the step 1 (n=1, `live-answers/<id>.txt`), as before:
    uv run python .sdd/changes/english-names-bilingual-output/evidence/B2d-3/check_controls.py
    # One folder per version, with `<id>.txt` or `<id>-r<k>.txt` (`run_live.py --answers-dir`):
    uv run python .../B2d-3/check_controls.py --answers-dir base=.../B2d-3/runs/base \\
        --answers-dir step1=.../B2d-3/runs/step1 --answers-dir step1b=.../B2d-3/runs/step1b
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTROLS: dict[str, tuple[str, ...]] = {
    "A14": ("125", "551", "653"),
    "A15": ("10",),
    "B31": ("57",),
    "B32": ("7",),
}
#: `<id>.txt` (one run) or `<id>-r<k>.txt` (repetition k).
ANSWER_NAME = re.compile(r"(?P<id>[A-Z]\d+)(?:-r(?P<rep>\d+))?\.txt")


def kept(answer: str, figure: str) -> bool:
    return re.search(rf"(?<![\d.]){re.escape(figure)}(?!\d)(?!\.\d)", answer) is not None


def answers_in(folder: Path) -> dict[str, list[tuple[str, Path]]]:
    """Answers of a folder by call id: `[(repetition, path), ...]` sorted by repetition."""
    found: dict[str, list[tuple[str, Path]]] = {}
    for path in sorted(folder.glob("*.txt")):
        m = ANSWER_NAME.fullmatch(path.name)
        if m:
            found.setdefault(m["id"], []).append((m["rep"] or "1", path))
    for runs in found.values():
        runs.sort(key=lambda r: int(r[0]))
    return found


def check_version(folder: Path) -> dict:
    by_id = answers_in(folder)
    rows = []
    for call_id, figures in CONTROLS.items():
        runs = by_id.get(call_id, [])
        if not runs:
            rows.append({"id": call_id, "missing_answer": True, "ok": False})
            continue
        reps = []
        for rep, path in runs:
            text = path.read_text(encoding="utf-8", errors="replace")
            reps.append({"rep": rep, "kept": [f for f in figures if kept(text, f)]})
        n_kept = sum(1 for r in reps if r["kept"])
        rows.append(
            {
                "id": call_id,
                "figures": list(figures),
                "reps": reps,
                "kept_reps": n_kept,
                "runs": len(reps),
                "ok": 2 * n_kept > len(reps),
            }
        )
    cases = [r["id"] for r in rows if r["ok"]]
    return {"rows": rows, "cases_kept": cases, "controls_ok": len(cases) == len(CONTROLS)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--answers-dir",
        action="append",
        default=[],
        metavar="[NAME=]DIR",
        help="folder of answers of one version; repeat it per version (default: live-answers)",
    )
    args = parser.parse_args(argv)
    specs = args.answers_dir or [f"step1-n1={HERE / 'live-answers'}"]
    versions = {}
    for spec in specs:
        name, sep, folder = spec.partition("=")
        if not sep:
            name, folder = Path(spec).name, spec
        versions[name] = check_version(Path(folder))
    sys.stdout.reconfigure(encoding="utf-8")
    if len(versions) == 1:
        result = next(iter(versions.values()))
    else:
        result = {"versions": versions}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all(v["controls_ok"] for v in versions.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
