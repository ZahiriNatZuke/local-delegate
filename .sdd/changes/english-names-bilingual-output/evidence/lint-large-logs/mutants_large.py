"""lint-large-logs: the mutants of `tests/test_lint_large_logs.py` (control positive of the tests).

Each mutant edits `src/local_delegate/server.py` in place, runs the test file, records which tests
fail, and restores the file with `git checkout`. Run from the repo root, through `pesado.sh`:

    uv run --frozen python .sdd/changes/.../lint-large-logs/mutants_large.py
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
SERVER = ROOT / "src" / "local_delegate" / "server.py"
OUT = Path(__file__).resolve().parent / "mutants.json"

MUTANTS = {
    "global counts (no per-file branch in the mechanical call)": (
        'lint_patterns.per_file_code_counts(log) if role == "mechanical" else None',
        "None",
    ),
    "one entry per file (no bound in the final step, no line of the rest)": (
        "    if left_out <= 0:\n        return answer",
        "    if True:\n        return answer",
    ),
    "map of before (no prohibition of per-file figures in the map)": (
        '    return f"{head}\\n\\nResume la siguiente salida de linter/tests:\\n\\n{piece}"',
        '    return f"Resume la siguiente salida de linter/tests:\\n\\n{piece}"',
    ),
    "no prohibition in the final step of an uncountable log": (
        '" El log no da cifras por fichero: no pongas ninguna en las entradas. Las cifras por "',
        '" Las cifras por "',
    ),
}


def main() -> int:
    with SERVER.open(encoding="utf-8", newline="") as fh:
        original = fh.read()
    results = {}
    try:
        for name, (old, new) in MUTANTS.items():
            old_n, new_n = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
            if original.count(old_n) != 1:
                results[name] = {"error": f"anchor found {original.count(old_n)} times"}
                continue
            SERVER.write_text(original.replace(old_n, new_n), encoding="utf-8", newline="")
            run = subprocess.run(
                [
                    "uv",
                    "run",
                    "--frozen",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "tests/test_lint_large_logs.py",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            failed = sorted(
                line.split("::", 1)[1].split(" ", 1)[0]
                for line in run.stdout.splitlines()
                if line.startswith("FAILED ")
            )
            results[name] = {"returncode": run.returncode, "failed": failed}
            print(name, "->", failed, flush=True)
    finally:
        SERVER.write_text(original, encoding="utf-8", newline="")
    subprocess.run(["git", "diff", "--quiet", "--", str(SERVER)], cwd=ROOT, check=True)
    OUT.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
