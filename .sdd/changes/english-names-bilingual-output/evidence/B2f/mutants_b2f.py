"""Apply each B2f mutant (bytes, CRLF kept), run its tests, record the failing assert, restore.

Each edit must apply exactly once: one that does not is reported as "does not mutate" (a `sed`
that matches nothing mutates nothing).

    uv run --frozen python .sdd/changes/english-names-bilingual-output/evidence/B2f/mutants_b2f.py
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
T = "tests/test_lint_single_long.py::"
SERVER = "src/local_delegate/server.py"

MUTANTS = [
    (
        "1 single long call: the prompt of before",
        SERVER,
        [('    if role != "long":\r\n        return base\r\n', "    return base\r\n")],
        [
            T + "test_the_single_long_lint_call_gets_the_inventory_in_front_of_the_log[es]",
            T + "test_the_single_long_lint_call_gets_the_inventory_in_front_of_the_log[en]",
        ],
    ),
    (
        "2 single long call: no fallback",
        SERVER,
        [
            (
                "        postprocess=(lambda answer, _t: _lint_not_mentioned(answer, log))\r\n",
                "        postprocess=None\r\n",
            )
        ],
        [
            T + "test_the_single_long_lint_answer_lists_what_it_does_not_mention[es-Sin mencionar]",
            T + "test_the_single_long_lint_answer_lists_what_it_does_not_mention[en-Not mentioned]",
        ],
    ),
    (
        "3 mechanical also gets the inventory",
        SERVER,
        [('    if role != "long":\r\n        return base\r\n', "")],
        [T + "test_the_mechanical_single_call_keeps_the_prompt_of_before"],
    ),
    (
        "4 single long call: the cap of before",
        SERVER,
        [("LINT_LONG_SINGLE_TOKENS_FACTOR = 2", "LINT_LONG_SINGLE_TOKENS_FACTOR = 1")],
        [
            T + "test_the_single_long_lint_call_gets_the_inventory_in_front_of_the_log[es]",
            T + "test_the_single_long_lint_call_gets_the_inventory_in_front_of_the_log[en]",
        ],
    ),
    (
        "5 mechanical also gets the larger cap",
        SERVER,
        [
            (
                '    factor = LINT_LONG_SINGLE_TOKENS_FACTOR if role == "long" else 1',
                "    factor = LINT_LONG_SINGLE_TOKENS_FACTOR",
            )
        ],
        [T + "test_the_mechanical_single_call_keeps_the_prompt_of_before"],
    ),
]


def first_failure(output: str) -> list[str]:
    lines = output.splitlines()
    picks = [ln.strip() for ln in lines if ln.startswith((">", "E   "))]
    return picks[:4]


report = []
for name, rel, edits, tests in MUTANTS:
    path = ROOT / rel
    original = path.read_bytes()
    mutated = original
    ok = True
    for old, new in edits:
        o, n = old.encode("utf-8"), new.encode("utf-8")
        if mutated.count(o) != 1:
            ok = False
            break
        mutated = mutated.replace(o, n)
    if not ok:
        report.append({"mutant": name, "error": "edit did not apply (does not mutate)"})
        continue
    path.write_bytes(mutated)
    try:
        rows = []
        for test in tests:
            r = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x", test],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            m = re.search(r"(\d+) failed", r.stdout)
            rows.append(
                {
                    "test": test.split("::")[1],
                    "failed": int(m.group(1)) if m else 0,
                    "rc": r.returncode,
                    "fires": first_failure(r.stdout),
                }
            )
        report.append({"mutant": name, "file": rel, "results": rows})
    finally:
        path.write_bytes(original)

out = Path(__file__).with_name("mutants.json")
out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(out)
