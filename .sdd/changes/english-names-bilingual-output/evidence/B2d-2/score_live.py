#!/usr/bin/env python3
"""Scoring of the B2d-2 live measurement, fixed BEFORE measuring (see `live-plan.md`).

Subcommands (all print JSON):

- `log`: the rows of the usage log in a time window, per tool and model: calls, `finish_reason`
  = `length`, chunked calls (`chunks` > 1) and `chars_out_raw` against `chars_out`.
- `labels`: bold labels of an answer copied from the document (the label rule of set 3).
- `intro`: how many introduction sections an answer has (Introduction/Introducción).
- `answers`: the three above over a manifest of the measurement (`manifest.json`, see
  `live-plan.md`), plus the fidelity counter (`scripts/score_lint_fidelity.py`) for the lint
  answers whose log is in `fidelity-set.json`.
- `control-set3`: the label rule over the literal answers of set 3, to compare with the counts
  reviewed by hand (5 in batch 1, 4 in batch 2 by the automatic rule of then). A rule that does not
  find them is not a measuring rule.

Run from the repository root with `uv run python <this file> ...`.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from local_delegate import sections

BOLD = re.compile(r"\*\*(.+?)\*\*")
MIN_LABEL_WORDS = 2
IDENTIFIER = re.compile(r"[\w./-]+")


def _fidelity():
    spec = importlib.util.spec_from_file_location(
        "score_lint_fidelity", ROOT / "scripts" / "score_lint_fidelity.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["score_lint_fidelity"] = module
    spec.loader.exec_module(module)
    return module


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def copied_labels(answer: str, document: str, *, cross_language: bool = True) -> list[str]:
    """Bold labels copied from a document written in the OTHER language than the answer's.

    A label (trailing colon out) counts when it has 2+ words and appears verbatim, normalized, in
    the document. Left out: labels with code (a backtick) or made of one identifier-like token
    (`check-llamaswap`, `local_translate`): they stay as they are in any language. When the
    document is in the requested language (`cross_language=False`) a copied label is not in the
    other language, so nothing counts.
    """
    if not cross_language:
        return []
    doc = " " + sections.normalize_heading(document) + " "
    found = []
    for raw in BOLD.findall(answer):
        label = raw.strip().rstrip(":").strip()
        if "`" in label or IDENTIFIER.fullmatch(label):
            continue
        norm = sections.normalize_heading(label)
        if len(norm.split()) >= MIN_LABEL_WORDS and f" {norm} " in doc:
            found.append(label)
    return found


def introductions(answer: str) -> int:
    forms = {sections.normalize_heading(f) for f in sections.INTRODUCTION_FORMS}
    return sum(1 for _i, text in sections.heading_lines(answer) if text in forms)


def log_rows(paths: list[Path], since: str, until: str) -> list[dict]:
    rows = []
    for path in paths:
        for line in _read(path).splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if since <= row.get("ts", "") <= until:
                rows.append(row)
    return rows


def log_summary(rows: list[dict]) -> dict:
    out: dict = defaultdict(lambda: {"calls": 0, "length": 0, "chunked": 0, "raw_gt_out": 0})
    for row in rows:
        cell = out[f"{row['tool']}|{row['model']}"]
        cell["calls"] += 1
        cell["length"] += row.get("finish_reason") == "length"
        cell["chunked"] += (row.get("chunks") or 1) > 1
        raw = row.get("chars_out_raw")
        cell["raw_gt_out"] += raw is not None and raw > row["chars_out"]
    return {
        k: {**v, "pct_length": round(100 * v["length"] / v["calls"], 1)} for k, v in out.items()
    }


def score_answers(manifest: dict) -> dict:
    fidelity = _fidelity()
    frozen = json.loads(_read(HERE / "fidelity-set.json"))
    by_path = {entry["path"]: entry for entry in frozen["logs"]}
    rows = []
    for call in manifest["calls"]:
        answer = _read(ROOT / call["answer"])
        document = _read(ROOT / call["document"])
        row = {"id": call["id"], "tool": call["tool"], "document": call["document"]}
        if call["tool"] == "local_summarize":
            cross = call["input_language"] != call["requested"]
            row["copied_labels"] = copied_labels(answer, document, cross_language=cross)
            row["introductions"] = introductions(answer)
        else:
            entry = by_path.get(call["document"])
            if entry is not None:
                extra = tuple(entry.get("extra_allowed_numbers", ()))
                row["fidelity"] = fidelity.count_inventions(answer, document, extra)
        rows.append(row)
    summ = [r for r in rows if r["tool"] == "local_summarize"]
    lint = [r for r in rows if "fidelity" in r]
    return {
        "rows": rows,
        "copied_labels": sum(len(r["copied_labels"]) for r in summ),
        "duplicate_introductions": sum(1 for r in summ if r["introductions"] > 1),
        "fidelity_total": sum(r["fidelity"]["total"] for r in lint),
        "fidelity_answers": len(lint),
    }


def control_set3() -> dict:
    evidence = HERE.parent / "B2d-fix"
    rows = []
    for name, key in (
        ("lang-sample-set3-batch1.json", "spanish_bold_labels_copied"),
        ("lang-sample-set3-batch2.json", "english_bold_labels_copied"),
    ):
        data = json.loads(_read(evidence / name))
        requested = data["combination"]["output_language"]
        for sample in data["samples"]:
            if sample["tool"] != "local_summarize":
                continue
            document = _read(ROOT / sample["document"])
            cross = sample["input_language"] != requested
            found = copied_labels(sample["response_literal"], document, cross_language=cross)
            rows.append(
                {
                    "batch": name,
                    "document": Path(sample["document"]).name,
                    "rule_now": found,
                    "rule_then": sample[key],
                    "reviewed": sample.get(key + "_reviewed"),
                    "introductions": introductions(sample["response_literal"]),
                }
            )
    return {
        "rows": rows,
        "rule_now": sum(len(r["rule_now"]) for r in rows),
        "rule_then": sum(len(r["rule_then"]) for r in rows),
        "reviewed": sum(len(r["reviewed"] or []) for r in rows),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="B2d-2 live scoring")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("log")
    p.add_argument("--usage-log", type=Path, nargs="+", required=True)
    p.add_argument("--since", required=True, help="ISO timestamp, e.g. 2026-10-16T10:00:00")
    p.add_argument("--until", required=True)
    p = sub.add_parser("labels")
    p.add_argument("--document", type=Path, required=True)
    p.add_argument("--answer", type=Path, required=True)
    p.add_argument("--same-language", action="store_true", help="document in the answer's language")
    p = sub.add_parser("intro")
    p.add_argument("--answer", type=Path, required=True)
    p = sub.add_parser("answers")
    p.add_argument("--manifest", type=Path, required=True)
    sub.add_parser("control-set3")
    args = parser.parse_args(argv)
    if args.command == "log":
        result = log_summary(log_rows(args.usage_log, args.since, args.until))
    elif args.command == "labels":
        result = copied_labels(
            _read(args.answer), _read(args.document), cross_language=not args.same_language
        )
    elif args.command == "intro":
        result = introductions(_read(args.answer))
    elif args.command == "answers":
        result = score_answers(json.loads(_read(args.manifest)))
    else:
        result = control_set3()
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
