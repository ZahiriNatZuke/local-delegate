"""B2e: freeze the chunking set and the measurement manifest BEFORE any measuring call.

Writes `chunking-set.json` (sha256 and, per entry, the truth computed by program) and
`manifest.json` (the windows and calls `run_live.py` runs). The truth does not come from the code
under test: the registered names come from a plain regex over the file, not from
`server._registered_names`; the files and codes of a log come from `lint_patterns`, which the
fidelity counter shares (decision of the user of 2026-10-17).

    uv run --frozen python .sdd/changes/english-names-bilingual-output/evidence/B2e/build_set.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT / "src"))

from local_delegate import lint_patterns

REL = HERE.relative_to(ROOT).as_posix()
B2D4 = json.loads((HERE.parent / "B2d-4" / "manifest.json").read_text(encoding="utf-8"))
TOP_LEVEL = re.compile(r"(?m)^(?:async\s+def|def|class)\s+(\w+)")
LITERAL = re.compile(r"\.add_parser\(\s*\"([^\"]+)\"")
MODULE = re.compile(r"\b(\w+)\.add_parser\(\s*sub\s*\)")
DEF_ADD_PARSER = re.compile(r"(?m)^def (add_parser)\(")

LINT = [
    ("L1", "L1-ruff-select-all-src.txt", "C", "ruff --select ALL concise over src/ of main"),
    ("L2", "L2-ci-log-with-uv-lock.txt", "C", "CI log with a uv.lock inside (dense)"),
    ("L3", "L3-pytest-collect-only.txt", "C", "pytest --collect-only (A-close-5)"),
    ("L4", "../B2d-fix/docs-2/en-log-biome-lint.txt", "F", "biome, as C43 (forced 8000)"),
    ("L5", "../../../../../benchmarks/catalogo-2026-09/fuentes/lint-9k.txt", "F", "ruff, as C44"),
]
EXPLAIN = [
    ("E1", "E1-cli.py.txt", "cli.py of main: 16 literal add_parser names plus benchmark"),
    ("E2", "E2-benchmark.py.txt", "benchmark.py of main: add_parser and its benchmark"),
    ("E3", "E3-checks.py.txt", "checks.py of main: no registrations (control)"),
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def main() -> None:
    entries, calls = [], []
    for cid, name, window, purpose in LINT:
        doc = (HERE / "docs" / name) if "/" not in name else (HERE / name)
        log = doc.read_text(encoding="utf-8", errors="replace")
        entries.append(
            {
                "id": cid,
                "tool": "local_lint_summary",
                "path": _rel(doc),
                "sha256": _sha(doc),
                "chars": len(log),
                "top_codes": lint_patterns.codes_by_frequency(log)[:10],
                "top_files": lint_patterns.files_by_frequency(log)[:10],
                "purpose": purpose,
            }
        )
        calls.append((cid, window, "local_lint_summary", doc, purpose))
    for cid, name, purpose in EXPLAIN:
        doc = HERE / "docs" / name
        code = doc.read_text(encoding="utf-8")
        registered = list(dict.fromkeys(LITERAL.findall(code) + MODULE.findall(code)))
        registered += [n for n in DEF_ADD_PARSER.findall(code) if n not in registered]
        entries.append(
            {
                "id": cid,
                "tool": "local_explain_code",
                "path": _rel(doc),
                "sha256": _sha(doc),
                "chars": len(code),
                "registered": registered,
                "top_level": list(dict.fromkeys(TOP_LEVEL.findall(code))),
                "purpose": purpose,
            }
        )
        calls.append((cid, "C", "local_explain_code", doc, purpose))
    chunking_set = {
        "frozen_at": "2026-10-17",
        "frozen_before_any_measurement_call": True,
        "entries": entries,
    }
    (HERE / "chunking-set.json").write_text(
        json.dumps(chunking_set, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {
        "frozen_at": "2026-10-17",
        "frozen_before_any_measurement_call": True,
        "derived_from": f"{REL}/build_set.py; control A11-A15 and B31-B35 from B2d-4/manifest.json",
        "windows": {
            "A": B2D4["windows"]["A"] | {"label": "B2e control A (set 3, prompt not touched)"},
            "B": B2D4["windows"]["B"] | {"label": "B2e control B (set 3, prompt not touched)"},
            "C": {"env": {}, "product": "es", "label": "B2e touched: lint and explain that chunk"},
            "F": {
                "env": {"LOCAL_DELEGATE_MAX_CHARS_LONG": "8000"},
                "product": "es",
                "label": "B2e touched: forced lint chunking (8000)",
            },
        },
        "calls": [
            {**c, "purpose": "B2e control: same prompt in main and in the branch"}
            for c in B2D4["calls"]
        ]
        + [
            {
                "id": cid,
                "window": window,
                "tool": tool,
                "document": _rel(doc),
                "document_sha256": _sha(doc),
                "purpose": purpose,
            }
            for cid, window, tool, doc, purpose in calls
        ],
    }
    (HERE / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({e["id"]: e.get("registered", e.get("top_codes")) for e in entries}))


if __name__ == "__main__":
    main()
