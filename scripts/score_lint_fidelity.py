#!/usr/bin/env python3
"""Fidelity counter for `local_lint_summary` answers (front B, wave B2d-2).

In set 3 of the B2d live sample the lint summaries carried figures and claims that are not in the
log ("Missing MCP Credentials (2)", "4 errores", "72 errores"), repeated sentences, and a list of
~30 hashes in `corpus-affinity-check`. This script counts, per answer and against ITS log:

- **invented numbers**: a number of the answer that is not in the log and is not a count the log
  supports (see `log_facts`);
- **invented files**: a file name or path of the answer that does not appear in the log;
- **repeated sentences**: a sentence (5 words or more, normalized) that appears again.

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
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
MIN_SENTENCE_WORDS = 5


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
    file, code and status mark, lines that name a file, distinct files and codes, and non-empty
    lines. `extra_allowed_numbers` in the frozen set is for what a person reviews by hand.
    """
    numbers = {_norm_number(n) for n in NUMBER.findall(log)}
    files = Counter(_norm_path(f) for f in FILE.findall(log))
    codes = Counter(CODE.findall(log))
    statuses = Counter(s.strip("[] ").upper() for s in STATUS.findall(log))
    lines = [line for line in log.splitlines() if line.strip()]
    with_file = sum(1 for line in lines if FILE.search(line))
    derived = {len(lines), with_file, len(files), len(codes)}
    derived |= set(files.values()) | set(codes.values()) | set(statuses.values())
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
    invented_files = [f for f in FILE.findall(text) if _norm_path(f) not in log_norm]
    sentences = [
        " ".join(re.findall(r"\w+", s.lower()))
        for s in SENTENCE_SPLIT.split(text)
        if len(re.findall(r"\w+", s)) >= MIN_SENTENCE_WORDS
    ]
    repeated = [s for s, n in Counter(sentences).items() for _ in range(n - 1)]
    return {
        "invented_numbers": invented_numbers,
        "invented_files": invented_files,
        "repeated_sentences": repeated,
        "total": len(invented_numbers) + len(invented_files) + len(repeated),
    }


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
