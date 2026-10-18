"""B2e: negative and positive controls of the fidelity counter on REAL logs of the B2e set.

Negative control: figures and files that no log writes, added to a real answer, must count as
invented with both counters (a counter that can only say "fine" is not a control). Positive
controls: the four cases fixed in `374a77f`, built on the same real logs, where the corrected
counter must accept a figure or file the log does write.

    uv run --frozen python counter_controls.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT / "src"))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OLD = _load("fid_main", HERE / "score_lint_fidelity_main.py")
NEW = _load("fid_new", ROOT / "scripts" / "score_lint_fidelity.py")
L2 = (HERE / "docs" / "L2-ci-log-with-uv-lock.txt").read_text(encoding="utf-8")
L5 = (ROOT / "benchmarks" / "catalogo-2026-09" / "fuentes" / "lint-9k.txt").read_text(
    encoding="utf-8"
)
ANSWER = (HERE / "runs" / "main-s2" / "L2-r1.txt").read_text(encoding="utf-8")
TSC = "src/app/main.ts(52,24): error TS2345: Argument of type 'x' is not assignable.\n"

CASES = [
    # (name, answer, log, key, token, expected invented by the corrected counter)
    ("negative: Found 7777 errors", ANSWER + "\nFound 7777 errors.", L2, "n", "7777", True),
    ("negative: 4321 packages", ANSWER + "\nSe resolvieron 4321 paquetes.", L2, "n", "4321", True),
    (
        "negative: invented file",
        ANSWER + "\nFalla `scripts/no_such_file.py`.",
        L2,
        "f",
        "scripts/no_such_file.py",
        True,
    ),
    # Words go up to twenty (`NUMBER_WORDS`) and every real log of the set writes all of 1-20
    # somewhere, so the word case uses a one-line log without a 12.
    (
        "negative: number word",
        "Hay doce avisos de T201.",
        "a.py:3:9: T201 `print` found\n",
        "w",
        "doce",
        True,
    ),
    (
        "positive: escaped underscore",
        r"Falla `scripts/build\_corpus.py`.",
        L2,
        "f",
        r"scripts/build\_corpus.py",
        False,
    ),
    ("positive: tsc position", "Error en la línea 52, columna 24.", TSC, "n", "52", False),
    ("positive: version v", "Versión 255.", "systemd v255 (255.4-1)\n", "n", "255", False),
    ("positive: word over a column", "nine instances of T201.", L5, "w", "nine", True),
]


def _hit(result: dict, key: str, token: str) -> bool:
    if key == "f":
        bag = [t.replace("\\", "") for t in result["invented_files"]]
        return token.replace("\\", "") in bag
    return token.lower() in [t.lower() for t in result["invented_numbers"]]


def main() -> int:
    out, bad = [], 0
    for name, answer, log, key, token, expected in CASES:
        old = _hit(OLD.count_inventions(answer, log), key, token)
        new = _hit(NEW.count_inventions(answer, log), key, token)
        ok = new == expected
        bad += not ok
        out.append({"case": name, "old": old, "new": new, "expected_new": expected, "ok": ok})
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
