"""B2f: freeze the measurement set and the manifest BEFORE any measuring call.

Writes `b2f-set.json` (sha256 and, per log, the truth computed by program: the 10 most named rule
codes and files, from `lint_patterns`, which the fidelity counter shares) and `manifest.json` (the
windows and calls `run_live.py` runs).

Windows (product language `es` unless `LOCAL_DELEGATE_LANG=en`):

- G / GE: logs of 8-34 k characters, which `local_lint_summary` sends to the `long` role
  (`gemma4-26b-a4b`) in ONE call (6 000 < chars <= 48 000): the case B2f is about.
- H / HE: the small logs of the affinity corpus and two of set 2, forced to the `long` role with
  `LOCAL_DELEGATE_LONG_INPUT_CHARS=100` (the B2-affinity finding, with the production routing).
- M / ME: the same small logs with the default routing (`mechanical`, `gemma3-4b`): reference.
- A / B: the control of set 3 of B2e (A11-A15, B31-B35), as it was.

    uv run --frozen python .sdd/changes/english-names-bilingual-output/evidence/B2f/build_set.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT / "src"))

from local_delegate import lint_patterns

EV = HERE.parent
B2E = json.loads((EV / "B2e" / "manifest.json").read_text(encoding="utf-8"))
AFF = ROOT / "benchmarks" / "afinidad-2026-10" / "fuentes"

LONG = [
    ("1", ROOT / "benchmarks/catalogo-2026-09/fuentes/lint-9k.txt", "ruff concise 8.6k (C44)"),
    ("2", EV / "B2d-fix/docs-2/en-log-biome-lint.txt", "biome 18k (C43)"),
    ("3", EV / "B2d-fix/docs-3/en-log-biome-lint-nest.txt", "biome 22k (A14)"),
    ("4", HERE / "docs/G4-ruff-concise-web.txt", "ruff --select ALL concise, web/ of main"),
    ("5", HERE / "docs/G5-ruff-full-benchmark.txt", "ruff --select ALL full, benchmark.py"),
]
SMALL = [
    ("1", AFF / "resume-ruff-tres-reglas.txt", "affinity corpus: three rules"),
    ("2", AFF / "resume-ruff-docstrings.txt", "affinity corpus: docstrings"),
    ("3", AFF / "resume-ruff-cinco-reglas.txt", "affinity corpus: five rules"),
    ("4", AFF / "resume-ruff-un-solo-archivo.txt", "affinity corpus: a single file"),
    ("5", EV / "B2d-fix/docs-2/en-log-ruff-concise.txt", "ruff concise 2.6k, 17 codes"),
    ("6", EV / "B2d-fix/docs-2/en-log-tsc.txt", "tsc 1.6k"),
]
EN = {"LOCAL_DELEGATE_LANG": "en"}
FORCE_LONG = {"LOCAL_DELEGATE_LONG_INPUT_CHARS": "100"}
WINDOWS = {
    "G": ({}, "es", LONG, "B2f long single call es"),
    "GE": (EN, "en", LONG, "B2f long single call en"),
    "H": (FORCE_LONG, "es", SMALL, "B2f small logs forced to long es"),
    "HE": ({**FORCE_LONG, **EN}, "en", SMALL, "B2f small logs forced to long en"),
    "M": ({}, "es", SMALL, "B2f small logs mechanical es"),
    "ME": (EN, "en", SMALL, "B2f small logs mechanical en"),
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def main() -> None:
    entries: dict[str, dict] = {}
    calls: list[dict] = []
    windows: dict[str, dict] = {}
    for window, (env, lang, docs, label) in WINDOWS.items():
        windows[window] = {"env": env, "product": lang, "label": label}
        for n, doc, purpose in docs:
            log = doc.read_text(encoding="utf-8", errors="replace")
            cid = f"{window}{n}"
            entries[cid] = {
                "id": cid,
                "path": _rel(doc),
                "sha256": _sha(doc),
                "chars": len(log),
                "top_codes": lint_patterns.codes_by_frequency(log)[:10],
                "top_files": lint_patterns.files_by_frequency(log)[:10],
                "purpose": purpose,
            }
            calls.append(
                {
                    "id": cid,
                    "window": window,
                    "tool": "local_lint_summary",
                    "document": _rel(doc),
                    "document_sha256": _sha(doc),
                    "requested": lang,
                    "purpose": purpose,
                }
            )
    for window in ("A", "B"):
        windows[window] = B2E["windows"][window]
        calls += [c for c in B2E["calls"] if c["window"] == window]
    set_path = HERE / "b2f-set.json"
    set_path.write_text(
        json.dumps(
            {
                "frozen_at": "2026-10-18",
                "frozen_before_any_measurement_call": True,
                "entries": list(entries.values()),
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    manifest = {
        "frozen_at": "2026-10-18",
        "frozen_before_any_measurement_call": True,
        "derived_from": f"{_rel(Path(__file__))}; control A11-A15 and B31-B35 from B2e",
        "windows": windows,
        "calls": calls,
    }
    (HERE / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"{len(entries)} entries, {len(calls)} calls, windows {list(windows)}")


if __name__ == "__main__":
    main()
