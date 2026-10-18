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


#: A Markdown escape (`build\_corpus.py`): the model writes it, the reader sees `_`.
MARKDOWN_ESCAPE = re.compile(r"\\([_*`-])")


def mentions(item: str, text: str) -> bool:
    r"""Whether `text` names `item`, a file (by its path or its basename) or a rule code.

    As a whole token, after removing Markdown escapes: `E501` is not named by `E5011`, and
    `build\_corpus.py` names `scripts/build_corpus.py`.
    """
    text = MARKDOWN_ESCAPE.sub(r"\1", text)
    if FILE.fullmatch(item):
        norm, path = norm_path(text), norm_path(item).removeprefix("./")
        base = path.rsplit("/", 1)[-1]
        return (
            path in norm
            or re.search(r"(?<![\w.-])" + re.escape(base) + r"(?!\w)", norm) is not None
        )
    return re.search(r"(?<![\w-])" + re.escape(item) + r"(?![\w-])", text) is not None


def not_mentioned(answer: str, log: str, limit: int = 10) -> list[str]:
    """The most named files and rule codes of `log` (up to `limit` of each) that `answer` omits.

    B2e, fallback decided by the user on 2026-10-17: in the chunked `local_lint_summary` the
    program, not the model, lists what of the inventory the summary left out.
    """
    items = files_by_frequency(log)[:limit] + codes_by_frequency(log)[:limit]
    return [item for item in items if not mentions(item, answer)]
