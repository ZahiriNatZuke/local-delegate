"""lint-large-logs: freezes the set BEFORE measuring (`plan.md`).

Writes `manifest.json` (window X: four large logs chunked by the long role; windows G, M, ME copied
from `lint-counts` with the same documents and sha256) and `set.json` (per call: the 10 most named
codes and files, by `lint_patterns`, and the true counts per file computed with expressions of this
script, independent of the product: ruff concise and full, tsc, eslint stylish, pytest node ids).

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

LC = HERE.parent / "lint-counts"
B2E = HERE.parent / "B2e" / "docs"

#: `path:line:col: CODE message` (ruff concise, flake8).
CONCISE = re.compile(r"(?m)^(?P<file>[^\s:]+\.\w+):\d+:\d+: (?P<code>[A-Z]+\d+)\b")
#: ruff full format: `CODE message` and, on the next line, `--> path:line:col`.
FULL = re.compile(r"(?m)^(?P<code>[A-Z]+\d+) [^\n]*\n\s*--> (?P<file>[^\s:]+\.\w+):\d+")
#: tsc: `path(line,col): error TS1234:`.
TSC = re.compile(r"(?m)^(?P<file>[^\s(]+\.\w+)\(\d+,\d+\): error (?P<code>TS\d+):")
#: eslint stylish: a line with the absolute path, then `  line:col  severity  message  rule`.
ESLINT_FILE = re.compile(r"^/\S+\.\w+$")
ESLINT_ITEM = re.compile(r"^\s+\d+:\d+\s+(?:error|warning)\s+.*\s{2}(?P<code>[@\w/-]+)$")
#: pytest node id `path::test`.
PYTEST = re.compile(r"(?m)^(?P<file>[\w./\\-]+\.py)::(?P<test>\S+)")


def _eslint(log: str) -> list[tuple[str, str]]:
    found, current = [], None
    for line in log.splitlines():
        if ESLINT_FILE.match(line):
            current = line.split("/shop-web/shop-web/", 1)[-1]
        elif current and (m := ESLINT_ITEM.match(line)):
            found.append((current, m["code"]))
        elif not line.strip():
            current = None
    return found


def true_counts(log: str) -> dict | None:
    """`{"format", "per_file": {file: {"total", "codes": {code: n}}}, "codes": {code: total}}`."""
    for name, pattern in (("concise", CONCISE), ("full", FULL), ("tsc", TSC)):
        found = [(m["file"].replace("\\", "/"), m["code"]) for m in pattern.finditer(log)]
        if found:
            break
    else:
        name, found = "eslint", _eslint(log)
    if not found:
        nodes = {(m["file"].replace("\\", "/"), m["test"]) for m in PYTEST.finditer(log)}
        if not nodes:
            return None
        per = Counter(f for f, _ in nodes)
        return {
            "format": "pytest",
            "per_file": {f: {"total": n, "codes": {}} for f, n in sorted(per.items())},
            "codes": {},
        }
    per: dict[str, Counter] = defaultdict(Counter)
    for file, code in found:
        per[file][code] += 1
    totals = Counter(code for _, code in found)
    return {
        "format": name,
        "per_file": {
            f: {"total": sum(c.values()), "codes": dict(sorted(c.items()))}
            for f, c in sorted(per.items())
        },
        "codes": dict(sorted(totals.items())),
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    lc = json.loads((LC / "manifest.json").read_text(encoding="utf-8"))
    lc_set = {e["id"]: e for e in json.loads((LC / "set.json").read_text("utf-8"))["entries"]}
    keep = ("G", "M", "ME")
    windows = {
        "X": {"env": {}, "product": "es", "label": "lint-large-logs chunked long es"},
        **{w: lc["windows"][w] for w in keep},
    }
    large = [
        ("X1", B2E / "L1-ruff-select-all-src.txt", "ruff --select ALL concise, src/ (B2e L1)"),
        ("X2", B2E / "L3-pytest-collect-only.txt", "pytest --collect-only (B2e L3)"),
        ("X3", HERE / "docs" / "N1-eslint-stylish.txt", "eslint stylish, synthetic"),
        ("X4", HERE / "docs" / "N2-tsc.txt", "tsc, synthetic"),
    ]
    calls = [
        {
            "id": cid,
            "window": "X",
            "tool": "local_lint_summary",
            "document": doc.relative_to(ROOT).as_posix(),
            "document_sha256": sha256(doc),
            "requested": "es",
            "purpose": purpose,
        }
        for cid, doc, purpose in large
    ]
    calls += [c for c in lc["calls"] if c["window"] in keep]
    manifest = {
        "frozen_at": "2026-10-19",
        "frozen_before_any_measurement_call": True,
        "derived_from": "evidence/lint-large-logs/build_set.py; G, M, ME copied from lint-counts",
        "windows": windows,
        "calls": calls,
    }
    entries = []
    for c in calls:
        doc = ROOT / c["document"]
        if sha256(doc) != c["document_sha256"]:
            raise SystemExit(f"{c['id']}: sha256 changed")
        log = doc.read_text(encoding="utf-8", errors="replace")
        base = lc_set.get(c["id"], {})
        entries.append(
            {
                "id": c["id"],
                "top_codes": base.get("top_codes", lint_patterns.codes_by_frequency(log)[:10]),
                "top_files": base.get("top_files", lint_patterns.files_by_frequency(log)[:10]),
                "truth": true_counts(log),
            }
        )
    dump = {"ensure_ascii": False, "indent": 1}
    (HERE / "manifest.json").write_text(json.dumps(manifest, **dump) + "\n", "utf-8", newline="\n")
    (HERE / "set.json").write_text(
        json.dumps({"entries": entries}, **dump) + "\n", "utf-8", newline="\n"
    )
    for e in entries:
        t = e["truth"]
        print(e["id"], t and t["format"], t and len(t["per_file"]), t and len(t["codes"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
