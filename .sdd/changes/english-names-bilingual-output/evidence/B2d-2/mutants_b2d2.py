"""Apply each B2d-2 mutant (bytes, CRLF kept), run its test, record the failing assert, restore."""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\Projects\local-delegate")
T = "tests/test_lossless_summary_output.py::"
SERVER = "src/local_delegate/server.py"
SECTIONS = "src/local_delegate/sections.py"
FID = "scripts/score_lint_fidelity.py"
JUDGE = "scripts/judge_response_language.py"

MUTANTS = [
    (
        "1a lint single cap of today",
        SERVER,
        [("max_tokens=_lint_max_tokens(max_words),", "max_tokens=int(max_words * 2) + 96,")],
        [T + "test_the_single_lint_call_asks_for_the_new_cap"],
    ),
    (
        "1b lint chunk without its own cap",
        SERVER,
        [("            max_tokens_for=_lint_chunk_max_tokens,\r\n", "")],
        [
            T + "test_every_step_of_the_chunked_lint_asks_for_the_new_cap",
            T + "test_the_other_tools_keep_the_shared_chunk_cap",
        ],
    ),
    (
        "2a complete counts empty without looking at the document",
        SECTIONS,
        [
            (
                "    empty = [k for k in emp.empty if k not in empty_in_document]\n",
                "    empty = list(emp.empty)\n",
            )
        ],
        [
            T + "test_a_section_empty_in_the_document_is_not_reported_as_not_summarized",
            T + "test_a_section_with_content_left_empty_is_still_reported",
        ],
    ),
    (
        "2b span measured with the heading",
        SECTIONS,
        [
            (
                "        return self.size if self.body_size is None else self.body_size\n",
                "        return self.size\n",
            )
        ],
        [T + "test_the_words_follow_the_body_not_the_heading"],
    ),
    (
        "2c old allocate_by_size",
        SECTIONS,
        [
            (
                "    return [max(1, base + (remainder * t) // size_sum) if t > 0 else 0 for t in sizes]\n",
                "    return [max(1, base + (remainder * t) // size_sum) for t in sizes]\n",
            )
        ],
        [T + "test_allocate_by_size_gives_0_words_to_a_span_without_body"],
    ),
    (
        "3 truncation condition of today",
        SECTIONS,
        [
            (
                "    if truncated and lines and _is_cut_heading(lines[-1], expected):\n",
                "    if truncated and lines and heading_lines(lines[-1]):\n",
            )
        ],
        [
            T + "test_truncation_keeps_a_long_last_line_that_starts_with_hash",
            T + "test_truncation_still_drops_a_short_cut_heading",
        ],
    ),
    (
        "4a raw length after the post-processing",
        SERVER,
        [
            (
                "        chars_out_raw=len(result.text) if result.ok else None,\r\n",
                "        chars_out_raw=len(text) if result.ok else None,\r\n",
            )
        ],
        [T + "test_the_log_keeps_the_raw_length_before_the_post_processing"],
    ),
    (
        "4b map-reduce does not add the raw length",
        SERVER,
        [("        raw_chars += len(result.text)\r\n", "        raw_chars += 0\r\n")],
        [T + "test_the_chunked_log_sums_the_raw_length_of_every_call"],
    ),
    (
        "5 always add the introduction",
        SECTIONS,
        [
            (
                "    own_introduction = any(_is_introduction(t.text) for t in top_level)\n",
                "    own_introduction = False\n",
            )
        ],
        [
            T + "test_a_document_with_its_own_introduction_gets_only_one",
            T + "test_a_document_without_it_still_gets_the_products",
        ],
    ),
    (
        "6 the counter does not look at the log",
        FID,
        [
            ("    facts = log_facts(log)\n", "    facts = log_facts(answer)\n"),
            ("    log_norm = _norm_path(log)\n", "    log_norm = _norm_path(answer)\n"),
        ],
        [
            T + "test_the_counter_finds_an_invented_number_file_and_repetition",
            T + "test_a_faithful_answer_scores_0",
        ],
    ),
    (
        "7 summarize order without the labels rule",
        SERVER,
        [
            (
                (
                    '        f" También van en {name} las etiquetas en negrita, también las que nombran una "\r\n'
                    '        "subsección: tradúcelas aunque en el contenido aparezcan en otro idioma. Solo se quedan "\r\n'
                ),
                '        " Solo se quedan "\r\n',
            )
        ],
        [T + "test_the_summarize_order_names_the_bold_labels"],
    ),
    (
        "8 judge in strict UTF-8 again",
        JUDGE,
        [
            (
                '    document = args.document.read_text(encoding="utf-8", errors="replace")\n',
                '    document = args.document.read_text(encoding="utf-8")\n',
            )
        ],
        [T + "test_the_judge_reads_a_cp1252_document_without_an_exception"],
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

print(json.dumps(report, ensure_ascii=False, indent=1))
