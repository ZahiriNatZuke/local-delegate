#!/usr/bin/env python3
"""Fidelity counter for `local_lint_summary` answers (front B, waves B2d-2 and B2d-3).

In set 3 of the B2d live sample the lint summaries carried figures and claims that are not in the
log ("Missing MCP Credentials (2)", "4 errores", "72 errores"), repeated sentences, and a list of
~30 hashes in `corpus-affinity-check`. This script counts, per answer and against ITS log:

- **invented numbers**: a number of the answer that is not in the log and is not a count the log
  supports (see `log_facts`). Since B2d-3 a number written in words from zero to twenty, in English
  or Spanish ("eight", "ocho"), is a number too and follows the same rule: it is supported when its
  figure is (8 written in the log, or 8 lines with the same code). Left out on purpose: "one",
  "un", "una", "uno" (articles more often than counts) and "once" (eleven in Spanish, "one time"
  in English). The live answer of B2d-3 that said "eight instances of the print statement (T201)"
  over a log with 6 T201 went unseen before;
- **invented files**: a file name or path of the answer that does not appear in the log;
- **repeated sentences**: a sentence (5 words or more, normalized) that appears again under the
  same heading. The same bullet under two different file headings (`**a.ts**`, `**b.ts**`) is the
  same rule in two files, not a repetition (B2d-3, answer A14); under the same heading, or with no
  heading at all, it counts.

It looks at the log, never at the answer alone: a counter that does not look at the log cannot
tell an invented figure from a copied one (the mutant of `tests/test_score_lint_fidelity.py`).

What it does NOT see: a real file or figure attributed to the wrong thing (`scripts/
build_corpus.py` presented as a file with errors when the log only names it in a command line).
That stays for the manual review column of `evidence/B2d-2/live.md`.

Usage:
    # Freeze the set BEFORE measuring (sha256 and facts of each log):
    python scripts/score_lint_fidelity.py build --out SET.json LOG [LOG ...]
    # Score the answers (one file per log, named <log stem>.txt) against the frozen set:
    python scripts/score_lint_fidelity.py score --set SET.json --answers DIR

Output is JSON (machine values, no prose for people): it is a measurement script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

from local_delegate.server import LINT_REPEAT_KEEP, compact_repeated_lines

#: The product's own lines around an answer (receipts, notices): not the model's content.
PRODUCT_LINE = re.compile(
    r"^\s*(\(.*(server-side|local-delegate).*\)|\[local-delegate (warning|fallback): .*\])\s*$"
)
#: A number: an integer, a decimal or a dotted version, not glued to letters (`E501` is a code).
NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?![\w])")
#: A file name or path with a known extension.
FILE = re.compile(
    r"(?:[\w.~-]+[/\\])*[\w.-]+\.(?:py|pyi|ts|tsx|js|jsx|mjs|cjs|json|jsonl|md|txt|toml|ya?ml|"
    r"ps1|sh|cfg|ini|lock|html|css|scss|rs|go|java|exe|log|spec\.ts)\b",
    re.IGNORECASE,
)
#: A rule or error code (`E501`, `TS2345`, `PLR2004`) or a kebab/slash rule name.
CODE = re.compile(r"\b[A-Z]{1,5}\d{2,5}\b|\b[a-z]+(?:[/-][a-z]+){1,4}\b")
#: A status mark of a report (`[ OK ]`, `[WARN]`, `[FALT]`, `[ -- ]`).
STATUS = re.compile(r"\[[^\]\n]{1,6}\]")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
MIN_SENTENCE_WORDS = 5
#: A heading line of the answer: Markdown `#` or a line that is all bold (`**src/a.ts**`, `**X**:`).
HEADING = re.compile(r"\s*(?:#{1,6}\s+\S.*|\*\*[^*\n]+\*\*\s*:?|__[^_\n]+__\s*:?)\s*")
#: Numbers in words from zero to twenty (B2d-3), without "one"/"un"/"una"/"uno" and "once".
NUMBER_WORDS: dict[str, int] = {
    "zero": 0, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "cero": 0, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
    "nueve": 9, "diez": 10, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciséis": 16, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19,
    "veinte": 20,
}  # fmt: skip
#: A number word on its own: not inside an identifier or a kebab name (`two-pass`, `no_two`).
NUMBER_WORD = re.compile(
    r"(?<![\w-])(" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")(?![\w-])",
    re.IGNORECASE,
)
#: The same words in the log, where a kebab or snake name may carry them (`resume-ruff-tres-reglas`).
LOG_NUMBER_WORD = re.compile(
    r"(?<![^\W_])(" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")(?![^\W_])",
    re.IGNORECASE,
)


def _norm_path(text: str) -> str:
    return text.replace("\\", "/").lower()


def _norm_number(text: str) -> str:
    """`8,00` and `8` are the same figure, and so are `1,50` and `1.5` (a Spanish log, B2d-2)."""
    number = text.replace(",", ".")
    if number.count(".") == 1:
        number = number.rstrip("0").rstrip(".") or "0"
    return number


def model_text(answer: str) -> str:
    """The answer without the product's own lines."""
    return "\n".join(line for line in answer.splitlines() if not PRODUCT_LINE.match(line))


def log_facts(log: str) -> dict:
    """What the log supports: its literal numbers and files, and the counts it backs.

    A summary that says "3 E501" over a log with three E501 lines is faithful even though "3" is
    not written in the log, so the counts the log supports are allowed too: occurrences of each
    file, code and status mark, lines that name a file, distinct files and codes, non-empty
    lines, and the size of each block that `local_lint_summary` compacts and its "N more"
    (B2d-4). `extra_allowed_numbers` in the frozen set is for what a person reviews by hand.
    """
    numbers = {_norm_number(n) for n in NUMBER.findall(log)}
    # A number word of the log writes its figure too, also inside a name (`resume-ruff-tres-reglas`
    # turned "Tres reglas" in a live answer of B2d-3): "tres" or "3" in the answer is supported.
    numbers |= {str(NUMBER_WORDS[w.lower()]) for w in LOG_NUMBER_WORD.findall(log)}
    files = Counter(_norm_path(f) for f in FILE.findall(log))
    codes = Counter(CODE.findall(log))
    statuses = Counter(s.strip("[] ").upper() for s in STATUS.findall(log))
    lines = [line for line in log.splitlines() if line.strip()]
    with_file = sum(1 for line in lines if FILE.search(line))
    derived = {len(lines), with_file, len(files), len(codes)}
    derived |= set(files.values()) | set(codes.values()) | set(statuses.values())
    # B2d-4: the tool compacts a dense block of lines equal but for one token and tells the model
    # how many more there are ("… y N líneas más"); that N and the block size are counted by the
    # program from this same log (`tests/test_lint_count_rule.py` checks them against the log).
    for size in compact_repeated_lines(log)[1]:
        derived |= {size, size - LINT_REPEAT_KEEP}
    return {
        "numbers": sorted(numbers),
        "derived_counts": sorted(derived),
        "files": sorted(files),
    }


def count_inventions(answer: str, log: str, extra_allowed: tuple[str, ...] = ()) -> dict:
    """Invented numbers, invented files and repeated sentences of `answer` against `log`."""
    text = model_text(answer)
    facts = log_facts(log)
    log_norm = _norm_path(log)
    # Numbers inside a file token (`x.py:12`) are checked as part of the path, not alone.
    without_files = FILE.sub(" ", text)
    allowed = set(facts["numbers"]) | {str(n) for n in facts["derived_counts"]}
    allowed |= {_norm_number(n) for n in extra_allowed}
    invented_numbers = [n for n in NUMBER.findall(without_files) if _norm_number(n) not in allowed]
    invented_numbers += [
        w for w in NUMBER_WORD.findall(without_files) if str(NUMBER_WORDS[w.lower()]) not in allowed
    ]
    invented_files = [f for f in FILE.findall(text) if _norm_path(f) not in log_norm]
    repeated = [s for (_h, s), n in Counter(_sentences(text)).items() for _ in range(n - 1)]
    return {
        "invented_numbers": invented_numbers,
        "invented_files": invented_files,
        "repeated_sentences": repeated,
        "total": len(invented_numbers) + len(invented_files) + len(repeated),
    }


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _sentences(text: str) -> list[tuple[str | None, str]]:
    """(heading, sentence) of every sentence with 5+ words; a heading line is its own sentence.

    A heading long enough to be a sentence is keyed without a heading, so a whole block repeated
    with its heading still counts.
    """
    out: list[tuple[str | None, str]] = []
    heading: str | None = None
    for line in text.splitlines():
        if HEADING.fullmatch(line):
            heading = " ".join(_words(line))
            if len(_words(line)) >= MIN_SENTENCE_WORDS:
                out.append((None, heading))
            continue
        for sentence in SENTENCE_SPLIT.split(line):
            if len(_words(sentence)) >= MIN_SENTENCE_WORDS:
                out.append((heading, " ".join(_words(sentence))))
    return out


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> str:
    # As the server reads (`server._read_input`): a cp1252 log gets U+FFFD, not an exception.
    return path.read_text(encoding="utf-8", errors="replace")


def build(logs: list[Path], root: Path) -> dict:
    entries = []
    for log in logs:
        facts = log_facts(_read(log))
        try:
            shown = log.resolve().relative_to(root).as_posix()
        except ValueError:
            shown = str(log)
        entries.append(
            {
                "id": log.stem,
                "path": shown,
                "sha256": _sha256(log),
                "numbers": facts["numbers"],
                "derived_counts": facts["derived_counts"],
                "files": facts["files"],
                "extra_allowed_numbers": [],
            }
        )
    return {"logs": entries}


def score(frozen: dict, answers: Path, root: Path) -> dict:
    rows = []
    for entry in frozen["logs"]:
        log_path = root / entry["path"]
        if _sha256(log_path) != entry["sha256"]:
            rows.append({"id": entry["id"], "error": "log_changed"})
            continue
        answer_path = answers / f"{entry['id']}.txt"
        if not answer_path.is_file():
            rows.append({"id": entry["id"], "error": "no_answer"})
            continue
        result = count_inventions(
            _read(answer_path), _read(log_path), tuple(entry.get("extra_allowed_numbers", ()))
        )
        rows.append({"id": entry["id"], **result})
    scored = [r for r in rows if "error" not in r]
    return {
        "rows": rows,
        "answers": len(scored),
        "invented_numbers": sum(len(r["invented_numbers"]) for r in scored),
        "invented_files": sum(len(r["invented_files"]) for r in scored),
        "repeated_sentences": sum(len(r["repeated_sentences"]) for r in scored),
        "total": sum(r["total"] for r in scored),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("logs", nargs="+", type=Path)
    s = sub.add_parser("score")
    s.add_argument("--set", type=Path, required=True, dest="frozen")
    s.add_argument("--answers", type=Path, required=True)
    for p in (b, s):
        p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command == "build":
        data = build(args.logs, root)
        args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
        print(json.dumps({"logs": len(data["logs"]), "out": str(args.out)}))
        return 0
    frozen = json.loads(args.frozen.read_text(encoding="utf-8"))
    print(json.dumps(score(frozen, args.answers, root), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
