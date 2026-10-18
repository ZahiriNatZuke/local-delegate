"""Apply each B2e mutant (bytes, CRLF kept), run its tests, record the failing assert, restore.

Each edit must apply exactly once: one that does not is reported as "does not mutate" (a `sed`
that matches nothing mutates nothing).

    uv run --frozen python .sdd/changes/english-names-bilingual-output/evidence/B2e/mutants_b2e.py
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
T = "tests/test_combining_chunks.py::"
SERVER = "src/local_delegate/server.py"
FID = "scripts/score_lint_fidelity.py"

MUTANTS = [
    (
        "1 explain: the inventory of today",
        SERVER,
        [
            (
                "        registered = _format_registered(registrations, inventory_cap)\r\n",
                '        registered = ""\r\n',
            )
        ],
        [T + "test_the_explain_reduce_inventory_names_the_registered_subcommands"],
    ),
    (
        "2 lint: the default reduce",
        SERVER,
        [
            (
                (
                    "            reduce_system=system,\r\n            build_reduce=_build_reduce,\r\n"
                    "            max_tokens_for=_lint_chunk_max_tokens,\r\n"
                ),
                "            max_tokens_for=_lint_chunk_max_tokens,\r\n",
            )
        ],
        [
            T + "test_the_chunked_lint_reduce_keeps_the_lint_format[es]",
            T + "test_the_chunked_lint_reduce_keeps_the_lint_format[en]",
        ],
    ),
    (
        "3 steps: one step only",
        SERVER,
        [("        steps.append(\r\n", "        steps.clear()\r\n        steps.append(\r\n")],
        [T + "test_the_chunked_log_records_every_step_without_its_text"],
    ),
    (
        "4 dump: never written",
        SERVER,
        [
            (
                "    if dump_dir:\r\n        _dump_chunk_notes(",
                "    if False:\r\n        _dump_chunk_notes(",
            )
        ],
        [T + "test_the_dump_writes_each_step_with_its_text_to_a_local_file"],
    ),
    (
        "5 counter: no Markdown unescaping",
        FID,
        [('    return MARKDOWN_ESCAPE.sub(r"\\1", text)\n', "    return text\n")],
        [T + "test_a_markdown_escaped_underscore_is_the_file_of_the_log"],
    ),
    (
        "6 counter: no (N,M) figures",
        FID,
        [("    numbers |= {n for pair in TSC_POSITION.findall(log) for n in pair}\n", "")],
        [T + "test_a_tsc_position_gives_two_figures"],
    ),
    (
        "7 counter: no v versions",
        FID,
        [("    numbers |= {_norm_number(n) for n in VERSION.findall(log)}\n", "")],
        [T + "test_a_version_with_v_is_its_figure"],
    ),
    (
        "8 counter: words lean on every figure",
        FID,
        [
            (
                '    word_allowed = set(facts["word_numbers"])',
                '    word_allowed = set(facts["numbers"])',
            )
        ],
        [T + "test_a_number_word_does_not_lean_on_a_line_or_column"],
    ),
    (
        "9 lint fallback: no 'not mentioned' line (2026-10-17)",
        SERVER,
        [
            (
                (
                    "            final_max_tokens_for=_lint_final_max_tokens,\r\n"
                    "            postprocess=_add_not_mentioned,\r\n"
                ),
                "            final_max_tokens_for=_lint_final_max_tokens,\r\n",
            )
        ],
        [
            T + "test_the_chunked_lint_answer_lists_what_it_does_not_mention[es-Sin mencionar]",
            T + "test_the_chunked_lint_answer_lists_what_it_does_not_mention[en-Not mentioned]",
        ],
    ),
    (
        "10 lint final cap: the old cap (2026-10-18)",
        SERVER,
        [("            final_max_tokens_for=_lint_final_max_tokens,\r\n", "")],
        [
            T + "test_only_the_final_steps_of_the_chunked_lint_get_the_larger_cap",
        ],
    ),
    (
        "11 explain fallback: no 'not mentioned' line (2026-10-18)",
        SERVER,
        [
            (
                (
                    "            pieces=_code_pieces(content, budget),\r\n"
                    "            postprocess=_add_not_mentioned,\r\n"
                ),
                "            pieces=_code_pieces(content, budget),\r\n",
            )
        ],
        [
            T
            + "test_the_chunked_explanation_lists_the_registered_names_it_omits"
            + "[es-Sin mencionar (los registra el fichero]",
            T
            + "test_the_chunked_explanation_lists_the_registered_names_it_omits"
            + "[en-Not mentioned (registered by]",
        ],
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
