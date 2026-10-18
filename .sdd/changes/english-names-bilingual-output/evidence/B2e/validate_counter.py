"""B2e: every figure and file of the chunked lint answers, with the verdict of both counters.

For the manual review of `counter-validation.md` (rule of B2d-4: NEW figures, reviewed by hand
against the log BEFORE the corrected counter is used to measure). Prints JSON: per answer, each
number (digits or words) and each file with its context, and whether the counter of `main`
(`score_lint_fidelity_main.py`) and the corrected one (`scripts/score_lint_fidelity.py`) call it
invented. The person decides; this only lays the cases out.

    uv run --frozen python validate_counter.py ANSWER=LOG [ANSWER=LOG ...]
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


def _cases(answer: str, log: str) -> list[dict]:
    old = OLD.count_inventions(answer, log)
    new = NEW.count_inventions(answer, log)
    text = NEW.model_text(answer)
    out = []
    seen: set[tuple[str, str]] = set()
    bare = NEW.FILE.sub(" ", text)
    tokens = [("number", m.group(0), m.start()) for m in NEW.NUMBER.finditer(bare)]
    tokens += [("word", m.group(0), m.start()) for m in NEW.NUMBER_WORD.finditer(bare)]
    tokens += [("file", m.group(0), m.start()) for m in NEW.FILE.finditer(text)]
    for kind, token, start in sorted(tokens, key=lambda t: t[2]):
        if (kind, token) in seen:
            continue
        seen.add((kind, token))
        source = text if kind == "file" else bare
        context = source[max(0, start - 50) : start + len(token) + 30].replace("\n", " ")
        key = "invented_files" if kind == "file" else "invented_numbers"
        old_key = token.replace("\\", "") if kind == "file" else token
        out.append(
            {
                "kind": kind,
                "token": token,
                "context": context,
                "old_invented": token in old[key] or old_key in old[key],
                "new_invented": token in new[key] or old_key in new[key],
            }
        )
    return out


def main(pairs: list[str]) -> None:
    report = {}
    for pair in pairs:
        answer, log = pair.split("=", 1)
        report[answer] = _cases(
            Path(answer).read_text(encoding="utf-8"),
            Path(log).read_text(encoding="utf-8", errors="replace"),
        )
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
