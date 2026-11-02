"""What a lint/test log names: files and rule codes (front B, wave B2e).

One definition for two readers. `local_lint_summary` builds with these the inventory it puts in
front of the partial summaries when the log is chunked (`server._lint_inventory`), and
`scripts/score_lint_fidelity.py` uses the same ones to tell an invented file from a copied one.
Before B2e they lived only in the script; two copies would drift, and the measurement of the
inventory would then check something the tool does not compute.
"""

from __future__ import annotations

import json
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
    return [code for code, _ in code_counts(log)]


def code_counts(log: str) -> list[tuple[str, int]]:
    """The rule codes of `codes_by_frequency` with how many times the log names each one.

    The count is of mentions outside a file token, in the whole log: one per diagnostic in the
    usual formats (`path:line:col: E501 ...`, the full format of ruff, tsc), and also a code named
    in a warning line (`D203` in "D203 and D211 are incompatible"). Wave lint-counts gives these
    figures to the model of the single `long` call so that it copies them instead of counting.
    """
    found = RULE.findall(FILE.sub(" ", log))
    counts = Counter(found)
    order: dict[str, int] = {}
    for match in found:
        order.setdefault(match, len(order))
    return [(c, counts[c]) for c in sorted(counts, key=lambda c: (-counts[c], order[c]))]


#: Diagnostic lines that carry the file and the rule code together, so the program can count per
#: file (wave lint-large-logs): ruff concise / flake8 `path:line:col: CODE`, the full format of
#: ruff (`CODE message` and `--> path:line:col` on the next line) and tsc `path(line,col): error
#: TS1234:`. Other formats (biome, eslint stylish, pytest) put the file on another line or carry no
#: code: no per-file counts for them.
_PER_FILE_FORMATS = (
    re.compile(r"(?m)^(?P<file>[^\s:]+\.\w+):\d+:\d+: (?P<code>[A-Z]{1,5}\d{2,5})\b"),
    re.compile(r"(?m)^(?P<code>[A-Z]{1,5}\d{2,5}) [^\n]*\n\s*--> (?P<file>[^\s:]+\.\w+):\d+"),
    re.compile(r"(?m)^(?P<file>[^\s(]+\.\w+)\(\d+,\d+\): error (?P<code>TS\d+):"),
)


def per_file_code_counts(log: str) -> dict[str, Counter[str]] | None:
    """How many diagnostics of each rule code each file has, or `None` if the format does not say.

    Only for the formats of `_PER_FILE_FORMATS`, the first one that matches; files in order of
    their number of diagnostics (most first, ties in order of first appearance), codes the same.
    """
    for pattern in _PER_FILE_FORMATS:
        found = [(m["file"].replace("\\", "/"), m["code"]) for m in pattern.finditer(log)]
        if found:
            break
    else:
        return None
    per: dict[str, Counter[str]] = {}
    for file, code in found:
        per.setdefault(file, Counter())[code] += 1
    order = {file: index for index, file in enumerate(per)}
    ranked = sorted(per, key=lambda f: (-sum(per[f].values()), order[f]))
    return {f: Counter(dict(per[f].most_common())) for f in ranked}


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


def invented_files(answer: str, log: str, limit: int = 10) -> list[str]:
    """The files `answer` names that `log` never names (up to `limit`), most named first.

    The reverse of `not_mentioned` (issue #525): a summary that names a file the log does not
    carry made it up. Matched as `mentions` does, by path or by basename.
    """
    named = files_by_frequency(MARKDOWN_ESCAPE.sub(r"\1", answer))
    return [file for file in named if not mentions(file, log)][:limit]


# --- Input with nothing to summarize (issue #525) ---------------------------------------------
# A clean linter run gives `[]` (ruff, pylint), an empty output (tsc) or one summary line ("All
# checks passed!"). With such an input the small model of the `mechanical` role wrote errors in
# files that do not exist (`src/main.js`, `tests/main.test.js`): it got a "summarize these errors"
# order and an empty body, and filled it with a typical example. The program now tells these
# inputs apart BEFORE the model, so there is no prompt to fill.

#: An ANSI colour sequence, which a CLI writes around "✔ No problems" when it thinks it is a tty.
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

#: One line that says a run found nothing, as the usual tools write it: ESLint/Biome "No problems
#: found" or "0 problems", ruff "All checks passed!", tsc/pyright "Found 0 errors" or "0 errors,
#: 0 warnings, 0 informations", mypy "Success: no issues found in N source files", Biome
#: "Checked N files in Xms. No fixes applied.". A line with a non-zero figure never matches.
CLEAN_LINE = re.compile(
    r"(?i)\s*(?:[✔✓√]\s*)?(?:"
    r"no problems(?: found)?"
    r"|0 problems?(?: \(0 errors?, 0 warnings?\))?"
    r"|all checks passed"
    r"|(?:found )?0 errors?(?:,? (?:and )?0 warnings?)?"
    r"(?:,? (?:and )?0 (?:informations?|infos?|notes?))?(?: in \d+ files?)?"
    r"|success: no issues found in \d+ source files?"
    r"|no issues found"
    r"|checked \d+ files? in [\d.]+\s*m?s\.? no fixes (?:applied|needed)"
    r")[.!]?\s*"
)

#: The summary line of a pytest run where everything passed (`=== 42 passed in 3.21s ===`, or the
#: bare `42 passed in 3.21s` of `-q`). Skipped and deselected tests are not findings; warnings,
#: failures, errors and xfail/xpass are, so a summary that names them does not match.
_PYTEST_ALL_PASSED = re.compile(
    r"(?m)^(?:=+ )?(\d+ passed(?:, \d+ (?:skipped|deselected))*"
    r"(?: in [\d.]+s(?: \([^)\n]*\))?)?)(?: =+)?[ \t]*$"
)

#: What makes a pytest log not clean even with a "passed" line: a failure, an error, a traceback,
#: a section of failures, errors or warnings, or a count of any of them.
_PYTEST_PROBLEM = re.compile(
    r"(?m)^(?:FAILED|ERROR)\b|^E\s|Traceback \(most recent call last\)"
    r"|^=+ (?:FAILURES|ERRORS|warnings summary)\b"
    r"|\b\d+ (?:failed|errors?|warnings?|xfailed|xpassed)\b"
)

#: The keys under which a JSON report lists its diagnostics (ESLint `messages`, stylelint
#: `warnings`, Biome `diagnostics`, Semgrep/Bandit `results` and `errors`, RuboCop `files` and
#: `offenses`). A JSON object with none of them is not recognised: it goes to the model.
_DIAGNOSTIC_KEYS = frozenset(
    {
        "messages",
        "warnings",
        "errors",
        "diagnostics",
        "issues",
        "results",
        "violations",
        "offenses",
        "problems",
        "findings",
        "files",
    }
)

#: A counter of findings in a JSON report (`errorCount`, `fatalErrorCount`, `offense_count`).
_FINDING_COUNT = re.compile(r"(?i).*(?:error|warning|offense|issue|problem|violation).*count")


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _json_list_is_clean(items: list) -> bool:
    """Whether every item of a JSON list is a report entry with no diagnostics (`[]` is)."""
    return all(isinstance(item, dict) and _json_object_is_clean(item) for item in items)


def _json_object_is_clean(obj: dict) -> bool:
    """Whether a JSON object is a report entry with no diagnostics.

    It must carry at least one key of `_DIAGNOSTIC_KEYS`, each one empty, a list of entries that
    are clean themselves, or the number 0; no finding counter above 0 and no `errored: true`.
    Anything else (a string, a list with one message) counts as content.
    """
    if obj.get("errored") is True:
        return False
    if any(_FINDING_COUNT.fullmatch(k) and _is_number(v) and v for k, v in obj.items()):
        return False
    present = [key for key in obj if key in _DIAGNOSTIC_KEYS]
    if not present:
        return False
    for key in present:
        value = obj[key]
        if isinstance(value, list):
            clean = _json_list_is_clean(value)
        elif isinstance(value, dict):
            clean = not value or _json_object_is_clean(value)
        else:
            clean = _is_number(value) and value == 0
        if not clean:
            return False
    return True


def _json_is_clean(text: str) -> bool:
    """Whether `text` is a JSON report with nothing in it: `[]`, `{}`, `null`, or entries with no
    diagnostics (`[{"filePath": ..., "messages": []}]`, `{"results": [], "errors": []}`)."""
    try:
        data = json.loads(text)
    except ValueError:
        return False
    if data is None:
        return True
    if isinstance(data, list):
        return _json_list_is_clean(data)
    if isinstance(data, dict):
        return not data or _json_object_is_clean(data)
    return False


def clean_verdict(log: str) -> str | None:
    """Whether `log` carries nothing to summarize, decided by the program (issue #525).

    `None` when the log may carry diagnostics: it goes to the model as always. Otherwise the
    line(s) of the log that say the run was clean (`"All checks passed!"`, `"42 passed in
    3.21s"`), or `""` when the log says nothing at all (empty, only whitespace, or a JSON report
    with no diagnostics). Conservative on purpose: a line it does not know, or any figure above
    zero, sends the log to the model.
    """
    text = _ANSI.sub("", log).strip()
    if not text:
        return ""
    if text[0] in "[{" or text == "null":
        return "" if _json_is_clean(text) else None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if all(CLEAN_LINE.fullmatch(line) for line in lines):
        return "; ".join(lines)
    passed = _PYTEST_ALL_PASSED.findall(text)
    if len(passed) == 1 and not _PYTEST_PROBLEM.search(text):
        return passed[0]
    return None
