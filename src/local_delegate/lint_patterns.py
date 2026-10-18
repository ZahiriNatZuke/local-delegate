"""What a lint/test log names: files and rule codes (front B, wave B2e).

One definition for two readers. `local_lint_summary` builds with these the inventory it puts in
front of the partial summaries when the log is chunked (`server._lint_inventory`), and
`scripts/score_lint_fidelity.py` uses the same ones to tell an invented file from a copied one.
Before B2e they lived only in the script; two copies would drift, and the measurement of the
inventory would then check something the tool does not compute.
"""

from __future__ import annotations

import re
from collections import Counter

#: A file name or path with a known extension.
FILE = re.compile(
    r"(?:[\w.~-]+[/\\])*[\w.-]+\.(?:py|pyi|ts|tsx|js|jsx|mjs|cjs|json|jsonl|md|txt|toml|ya?ml|"
    r"ps1|sh|cfg|ini|lock|html|css|scss|rs|go|java|exe|log|spec\.ts)\b",
    re.IGNORECASE,
)
#: A rule or error code (`E501`, `TS2345`, `PLR2004`) or a kebab/slash rule name.
CODE = re.compile(r"\b[A-Z]{1,5}\d{2,5}\b|\b[a-z]+(?:[/-][a-z]+){1,4}\b")
#: A rule of the inventory: a code with letters and digits (`E501`, `TS2345`), the first
#: alternative of `CODE`, or a Biome rule path (`lint/style/noMagicNumbers`), which the kebab
#: alternative of `CODE` cuts at the first capital (`lint/style`).
RULE = re.compile(r"\b[A-Z]{1,5}\d{2,5}\b|\blint/[a-z]+/[A-Za-z]+\b")


def norm_path(text: str) -> str:
    """A path as it is compared: forward slashes, lower case."""
    return text.replace("\\", "/").lower()


def files_by_frequency(log: str) -> list[str]:
    """The files the log names, most named first (ties in order of first appearance)."""
    seen: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for match in FILE.findall(log):
        key = norm_path(match)
        seen.setdefault(key, match.replace("\\", "/"))
        counts[key] += 1
    order = {key: index for index, key in enumerate(seen)}
    return [seen[k] for k in sorted(counts, key=lambda k: (-counts[k], order[k]))]


def codes_by_frequency(log: str) -> list[str]:
    """The rule codes the log names (`RULE`), most named first.

    Outside a file token: `test_E501.py` is a file, not the code `E501`. The kebab alternative of
    `CODE` is left out here on purpose: in a log it also matches plain words of a path or a
    command (`local-delegate`, `build-site`), and an inventory of those would tell the model
    nothing about the rules.
    """
    text = FILE.sub(" ", log)
    counts = Counter(RULE.findall(text))
    order: dict[str, int] = {}
    for match in RULE.findall(text):
        order.setdefault(match, len(order))
    return sorted(counts, key=lambda c: (-counts[c], order[c]))
