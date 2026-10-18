#!/usr/bin/env python3
"""B2-affinity: the verdict of the lint cell re-evaluation, with the T6 evaluator untouched.

For each language and each repetition k, the rows of run k of the three models are evaluated by
`analyze_benchmark.evaluate_mechanical_cell` (the same six criteria that approved the cell in T6),
with `qwen35-2b` as the weak control and the median cold load of the role from a fresh copy of
llama-swap's `metrics.db`. The criterion fixed in the plan before measuring: the cell of a language
is approved if the state is `approved` in EVERY repetition.

Writes `benchmarks/afinidad-2026-10/reevaluation-0.36.0/verdict.json` and the evidence table
`evidence/B2-affinity/verdict.md`. The footprints are computed here with `footprint.footprint`, the
real llama-swap config (read only) and the production prompt of each language (a subprocess per
language, so the language is the one of the process).

    uv run python evaluate_reevaluation.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_benchmark as ab

CORPUS = ROOT / "benchmarks" / "afinidad-2026-10"
TARGET = CORPUS / "reevaluation-0.36.0"
TOOL = "local_lint_summary"
ROLE = "gemma3-4b"
ALTERNATIVE = "gemma4-26b-a4b"
#: The T6 alternative and, by rule (1) of the plan, the other one REQ-011 allows.
ALTERNATIVES = (ALTERNATIVE, "qwen36-35b-a3b")
WEAK = "qwen35-2b"
LANGUAGES = ("es", "en")
METRICS_DB = Path(r"D:\Projects\llms\llama-swap\metrics.db")
LLAMASWAP_CONFIG = Path(r"D:\Projects\llms\llama-swap\config.yaml")
#: The T6 cell this verdict replaces (`benchmarks/afinidad-2026-10/veredicto.json`).
SUPERSEDES = [{"tool": TOOL, "alternative": ALTERNATIVE, "compared_role": ROLE}]

_FOOTPRINT_CODE = """
import json, sys
from local_delegate import footprint, server
snap = server._topology()
prompt = server._affinity_prompt(sys.argv[1])
out = {m: footprint.footprint(server._model_config(snap, m), prompt) for m in sys.argv[2:]}
print(json.dumps(out))
"""


_T6_RULES_WITH_WRONG_COUNT = ab.rules_with_wrong_count
_T6_SCORE_AFFINITY = ab.score_affinity
_FOOTER = re.compile(r"\n*\((?:leído|read) server-side:[^\n]*\)\s*$")
_LINE_NUMBERS = re.compile(
    # The list ends as "4, 5, 6, and 7" / "20, 31 y 32" / "12-40": the separator may be a comma
    # followed by "and"/"y" (first version left ", and 7" and counted the 7: scorer-v3-check.md).
    r"(?i)\b(?:l[ií]neas?|lines?)\b[\s:]*\d+(?:\s*(?:,\s*(?:and\b|y\b)?|\by\b|\band\b|&|-)\s*\d+)*"
)
_COORDINATES = re.compile(r":\d+(?::\d+)?")
_WORDS = {
    # v3: not `un`/`una`, which are articles far more often than counts ("un solo bloque").
    **{
        w: i
        for i, w in enumerate(
            ["uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez"], 1
        )
    },
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    **{
        w: i
        for i, w in enumerate(
            [
                "one",
                "two",
                "three",
                "four",
                "five",
                "six",
                "seven",
                "eight",
                "nine",
                "ten",
                "eleven",
                "twelve",
                "thirteen",
                "fourteen",
                "fifteen",
            ],
            1,
        )
    },
}
_NUMBER_WORD = re.compile(r"(?i)\b(" + "|".join(_WORDS) + r")\b")
_SENTENCE = re.compile(r"\.\s+|;\s*")


def strip_footer(text: str) -> str:
    """Point 1 of lint v2: the program's `(read server-side: ...)` line is not the model's."""
    return _FOOTER.sub("", text)


def _clean(sentence: str) -> str:
    """Points 2 and 3: line numbers and coordinates out, number words as digits."""
    sentence = _COORDINATES.sub(" ", _LINE_NUMBERS.sub(" ", sentence))
    return _NUMBER_WORD.sub(lambda m: str(_WORDS[m.group(1).lower()]), sentence)


def rules_with_wrong_count_v2(text: str, counts: dict[str, list[int]]) -> list[str]:
    """Lint v2 (plan, B2-affinity): T6's reading plus points 2-4, fixed before the second run."""
    numbers: dict[str, list[int]] = {rule: [] for rule in counts}
    for line in strip_footer(text).splitlines():
        for sentence in _SENTENCE.split(line):
            sentence = _clean(sentence)
            codes = [c for c in ab._RULE_CODE.finditer(sentence) if c.group() in numbers]
            if len(codes) == 1:
                rest = sentence[: codes[0].start()] + " " + sentence[codes[0].end() :]
                numbers[codes[0].group()] += [int(n) for n in ab._BARE_INTEGER.findall(rest)]
                continue
            numbers_t6 = {rule: [] for rule in counts}
            all_codes = list(ab._RULE_CODE.finditer(sentence))
            for i, code in enumerate(all_codes):
                if code.group() not in numbers_t6:
                    continue
                end = all_codes[i + 1].start() if i + 1 < len(all_codes) else len(sentence)
                found = ab._BARE_INTEGER.findall(sentence[code.end() : end])
                numbers_t6[code.group()] += [int(n) for n in found]
            for rule, found in numbers_t6.items():
                numbers[rule] += found
    return [
        rule
        for rule, valid in counts.items()
        if not numbers[rule] or not set(numbers[rule]) <= set(valid)
    ]


def score_affinity_v2(case, text, record=None):
    """T6's `score_affinity` with the footer out (point 1) and `rules_with_wrong_count_v2`."""
    return _T6_SCORE_AFFINITY(case, strip_footer(text), record)


def use_scorer(name: str) -> None:
    if name == "v2":
        ab.rules_with_wrong_count = rules_with_wrong_count_v2
        ab.score_affinity = score_affinity_v2
    else:
        ab.rules_with_wrong_count = _T6_RULES_WITH_WRONG_COUNT
        ab.score_affinity = _T6_SCORE_AFFINITY


def footprints(lang: str, alternatives: list[str]) -> dict:
    env = {**os.environ, "LOCAL_DELEGATE_LANG": lang, "LLAMASWAP_CONFIG": str(LLAMASWAP_CONFIG)}
    env.pop("LOCAL_DELEGATE_OUTPUT_LANGUAGE", None)
    out = subprocess.run(
        [sys.executable, "-c", _FOOTPRINT_CODE, TOOL, *alternatives, ROLE],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=True,
    ).stdout
    return json.loads(out)


def cold_load() -> float | None:
    with tempfile.TemporaryDirectory() as tmp:
        for suffix in ("", "-wal", "-shm"):
            source = Path(str(METRICS_DB) + suffix)
            if source.exists():
                shutil.copy2(source, Path(tmp) / source.name)
        return ab.median_cold_load(Path(tmp) / METRICS_DB.name, ROLE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scorer", choices=("v1", "v2"), default="v2")
    parser.add_argument("--results", type=Path, default=TARGET / "results")
    parser.add_argument("--output", type=Path, default=TARGET / "verdict.json")
    parser.add_argument("--table", type=Path, default=HERE / "verdict.md")
    args = parser.parse_args()
    use_scorer(args.scorer)
    data = json.loads((CORPUS / "cases.json").read_text(encoding="utf-8"))
    cases = [c for c in data["cases"] if c.get("tool") == TOOL]
    cold = cold_load()
    verdict: dict = {
        "schema_version": 1,
        "method": "B2-affinity (plan.md): T6 criteria per repetition, approved in every one",
        "scorer": args.scorer,
        "supersedes": SUPERSEDES,
        "cold_load_role_s": cold,
        "cells": [],
    }
    table = [
        (
            "| Alternativo | Idioma | Rep. | Estado | Criterios que fallan "
            "| Calidad por caso (rol / 2B / alternativo) | Latencia mediana alternativo / rol (ms) |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for lang in LANGUAGES:
        rows = ab.read_jsonl(sorted((args.results / lang).glob("*.jsonl")))
        reps = sorted({int(r["run"]) for r in rows})
        present = [m for m in ALTERNATIVES if any(r["label"] == m for r in rows)]
        fp = footprints(lang, present)
        for alternative in present:
            per_rep = []
            for k in reps:
                runs = ab.group_runs([{**r, "run": 1} for r in rows if int(r["run"]) == k])
                cell = ab.evaluate_mechanical_cell(
                    TOOL, alternative, ROLE, cases, runs, cold, weak=WEAK
                )
                scores = {
                    c["id"]: [ab.result_of(runs, m, c).quality for m in (ROLE, WEAK, alternative)]
                    for c in cases
                }
                failing = [name for name, v in cell["criteria"].items() if not v["ok"]]
                latency = cell["criteria"]["latency"]
                per_rep.append({"run": k, **cell, "scores": scores})
                quality = "; ".join(
                    f"{cid.removeprefix('resume-ruff-')} {' / '.join(f'{q:.2f}' for q in qs)}"
                    for cid, qs in scores.items()
                )
                table.append(
                    f"| {alternative} | {lang} | {k} | {cell['state']} | "
                    f"{', '.join(failing) or '—'} | {quality} "
                    f"| {latency['alternative_median_ms']} / {latency['role_median_ms']} |"
                )
            distinct = {
                m: len({r["response_sha256"] for r in rows if r["label"] == m})
                for m in (ROLE, WEAK, alternative)
            }
            approved = all(r["state"] == "approved" for r in per_rep)
            verdict["cells"].append(
                {
                    "tool": TOOL,
                    "alternative": alternative,
                    "compared_role": ROLE,
                    "language": lang,
                    "state": "approved" if approved else "rejected",
                    "repetitions": per_rep,
                    "distinct_responses_of_12": distinct,
                    "latency_ms_all_runs": {
                        m: statistics.median(r["latency_ms"] for r in rows if r["label"] == m)
                        for m in (ROLE, WEAK, alternative)
                    },
                    "footprint": fp[alternative],
                    "role_footprint": fp[ROLE],
                }
            )
            table.append(
                f"| {alternative} | {lang} | — | **{'aprobada' if approved else 'rechazada'}** "
                f"| respuestas distintas de 12: {distinct} | | |"
            )
    cases_bytes = (CORPUS / "cases.json").read_bytes()
    verdict["cases_sha256"] = hashlib.sha256(cases_bytes).hexdigest()
    args.output.write_text(
        json.dumps(verdict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    text = "\n".join(table) + f"\n\nCarga en frío mediana del rol: {cold} s\n"
    args.table.write_text(text, encoding="utf-8", newline="\n")
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
