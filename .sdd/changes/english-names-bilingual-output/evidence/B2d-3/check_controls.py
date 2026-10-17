#!/usr/bin/env python3
"""Control of B2d-3: the real figures of the logs that have them are still in the answers.

The count rule must remove invented counts, not the real ones. Four logs of set 3 carry a total
line; their figures were chosen BEFORE measuring (2026-10-17) by reading the logs:

- A14 `en-log-biome-lint-nest`: "Found 125 errors.", "Found 551 warnings.", "Found 653 infos."
- A15 `en-log-ruff-concise-build-site`: "Found 10 errors."
- B31 `en-log-pytest-chunking-density`: "57 passed"
- B32 `en-log-ruff-concise-clean-watcher`: "Found 7 errors."

A figure counts as kept when it appears in the answer as a whole number (not inside a longer one).
The control passes when every answer keeps at least one of its figures; the detail goes in the JSON
for the manual review column of `live.md`. A cut answer (receipt with `finish_reason=length`) is
noted and not judged, as in `measure.md`.

    uv run python .sdd/changes/english-names-bilingual-output/evidence/B2d-3/check_controls.py
"""

from __future__ import annotations

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


def kept(answer: str, figure: str) -> bool:
    return re.search(rf"(?<![\d.]){re.escape(figure)}(?![\d.])", answer) is not None


def main() -> int:
    answers = HERE / "live-answers"
    rows = []
    for call_id, figures in CONTROLS.items():
        path = answers / f"{call_id}.txt"
        if not path.is_file():
            rows.append({"id": call_id, "missing_answer": True})
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found = [f for f in figures if kept(text, f)]
        rows.append({"id": call_id, "figures": list(figures), "kept": found, "ok": bool(found)})
    ok = all(r.get("ok") for r in rows)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"rows": rows, "controls_ok": ok}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
