"""lint-counts: freezes the set BEFORE measuring (`plan.md`).

Writes `manifest.json` (windows R, RE plus G, GE, H, HE, M, ME copied from B2f with the same
documents and sha256) and `set.json` (per call: the 10 most named codes and files, by
`lint_patterns`, and the true count per diagnostic code where the format allows counting them with
an expression independent of the product: ruff concise, ruff full, tsc).

    uv run python build_set.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT / "src"))

from local_delegate import lint_patterns

B2F = HERE.parent / "B2f"
RUFF_LOG = HERE / "docs" / "ruff-sections.log"

#: `path:line:col: CODE message` (ruff concise, flake8).
CONCISE = re.compile(r"(?m)^(?P<file>[^\s:]+\.\w+):\d+:\d+: (?P<code>[A-Z]+\d+)\b")
#: ruff full format: `CODE message` and, on the next line, `--> path:line:col`.
FULL = re.compile(r"(?m)^(?P<code>[A-Z]+\d+) [^\n]*\n\s*--> (?P<file>[^\s:]+\.\w+):\d+")
#: tsc: `path(line,col): error TS1234:`.
TSC = re.compile(r"(?m)^(?P<file>[^\s(]+\.\w+)\(\d+,\d+\): error (?P<code>TS\d+):")


def true_counts(log: str) -> dict[str, dict] | None:
    """Per diagnostic code: its total and its count in each file. None: no countable format."""
    for pattern in (CONCISE, FULL, TSC):
        found = [(m["file"].replace("\\", "/"), m["code"]) for m in pattern.finditer(log)]
        if found:
            per = defaultdict(Counter)
            for file, code in found:
                per[code][file] += 1
            return {
                code: {"total": sum(files.values()), "per_file": dict(files)}
                for code, files in sorted(per.items())
            }
    return None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    b2f = json.loads((B2F / "manifest.json").read_text(encoding="utf-8"))
    b2f_set = {e["id"]: e for e in json.loads((B2F / "b2f-set.json").read_text("utf-8"))["entries"]}
    keep = ("G", "GE", "H", "HE", "M", "ME")
    windows = {
        "R": {"env": {}, "product": "es", "label": "lint-counts ruff sections es"},
        "RE": {
            "env": {"LOCAL_DELEGATE_LANG": "en"},
            "product": "en",
            "label": "lint-counts ruff sections en",
        },
    }
    windows.update({w: b2f["windows"][w] for w in keep})
    rel = RUFF_LOG.relative_to(ROOT).as_posix()
    calls = [
        {
            "id": "R1",
            "window": "R",
            "tool": "local_lint_summary",
            "document": rel,
            "document_sha256": sha256(RUFF_LOG),
            "requested": "es",
            "purpose": "ruff full --select ALL sections.py (live-036 row 7)",
        },
        {
            "id": "RE1",
            "window": "RE",
            "tool": "local_lint_summary",
            "document": rel,
            "document_sha256": sha256(RUFF_LOG),
            "requested": "en",
            "purpose": "ruff full --select ALL sections.py (live-036 row 7)",
        },
    ]
    calls += [c for c in b2f["calls"] if c["window"] in keep]
    manifest = {
        "frozen_at": "2026-10-18",
        "frozen_before_any_measurement_call": True,
        "derived_from": "evidence/lint-counts/build_set.py; G-ME copied from evidence/B2f",
        "windows": windows,
        "calls": calls,
    }
    entries = []
    for c in calls:
        doc = ROOT / c["document"]
        if sha256(doc) != c["document_sha256"]:
            raise SystemExit(f"{c['id']}: sha256 changed")
        log = doc.read_text(encoding="utf-8", errors="replace")
        base = b2f_set.get(c["id"], {})
        truth = true_counts(log)
        # R/RE: the criterion is the 15 DIAGNOSTIC codes (not D203/D211/D212/D213, which the log
        # names only in its "incompatible rules" warnings).
        codes = sorted(truth) if c["window"] in ("R", "RE") else base.get("top_codes")
        entries.append(
            {
                "id": c["id"],
                "top_codes": codes,
                "top_files": base.get("top_files", lint_patterns.files_by_frequency(log)[:10]),
                "true_counts": truth,
            }
        )
    dump = {"ensure_ascii": False, "indent": 1}
    (HERE / "manifest.json").write_text(json.dumps(manifest, **dump) + "\n", "utf-8")
    (HERE / "set.json").write_text(json.dumps({"entries": entries}, **dump) + "\n", "utf-8")
    for e in entries:
        tc = e["true_counts"]
        print(e["id"], "codes with truth:", len(tc) if tc else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
