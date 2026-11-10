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
from array import array
from collections import Counter
from typing import NamedTuple

_EXTENSIONS = (
    r"\.(?:py|pyi|ts|tsx|js|jsx|mjs|cjs|json|jsonl|md|txt|toml|ya?ml|"
    r"ps1|sh|cfg|ini|lock|html|css|scss|rs|go|java|exe|log|spec\.ts)\b"
)
#: A file name or path with a known extension. The definition; search a log with `file_spans`,
#: which gives the same matches in linear time (`findall` of this is quadratic on a long run).
FILE = re.compile(r"(?:[\w.~-]+[/\\])*[\w.-]+" + _EXTENSIONS, re.IGNORECASE)
#: The extension of `FILE` at a dot, with the alternative and the `\b` the full pattern would take.
_EXT = re.compile(_EXTENSIONS, re.IGNORECASE)
#: The characters a match of `FILE` is made of: a run of them holds every match whole.
_PATH_RUN = re.compile(r"[\w.~/\\-]+")
_SLASHES = "/\\"


def _run_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """The spans of `FILE.finditer(text)` inside the run `text[start:end]`, in O(end - start).

    `FILE` is `D* F`, `D` = `[\\w.~-]+[/\\\\]` and `F` = `[\\w.-]+` plus an extension. A `D` is
    deterministic: `[\\w.~-]+` cannot take a slash, so it always runs to the next one, and backing
    off never makes a slash follow it. `F` from `x` takes the RIGHTMOST dot `q > x` of the `[\\w.-]`
    stretch of `x` where an extension matches (greedy backtracking tries the longest first) and
    ends where that extension ends. `D*` is greedy: the most segments first, one fewer when that
    fails. So the match from each position is computed once, scanning from the right.
    """
    # Nothing at or after the end of the last extension can be part of a match.
    last_dot = text.rfind(".", start, end)
    while last_dot != -1 and not _EXT.match(text, last_dot, end):
        last_dot = text.rfind(".", start, last_dot)
    if last_dot == -1:
        return []
    end = _EXT.match(text, last_dot, end).end()
    # Match end from each position of the run, -1 if none: 8 bytes per character.
    best = array("q", [-1]) * (end - start + 1)
    f_end = -1  # where `F` ends from left of here in the current `[\w.-]` stretch, -1 if none
    slash = -1  # the slash that ends the current `[\w.~-]` stretch, -1 if none
    for x in range(end - 1, start - 1, -1):
        char = text[x]
        if char in _SLASHES:
            f_end = -1
            slash = x
            continue
        here = -1
        if char == "~":
            f_end = -1
        else:
            here = f_end
            if f_end == -1 and char == ".":
                found = _EXT.match(text, x, end)
                if found:
                    f_end = found.end()
        deeper = best[slash + 1 - start] if slash != -1 else -1
        best[x - start] = deeper if deeper != -1 else here
    spans: list[tuple[int, int]] = []
    x = start
    while x < end:
        stop = best[x - start]
        if stop != -1:
            spans.append((x, stop))
            x = stop
        else:
            x += 1
    return spans


def file_spans(text: str) -> list[tuple[int, int]]:
    """The spans of `FILE.finditer(text)`, in linear time: run by run of path characters."""
    spans: list[tuple[int, int]] = []
    for run in _PATH_RUN.finditer(text):
        spans += _run_spans(text, run.start(), run.end())
    return spans


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
    for begin, end in file_spans(log):
        match = log[begin:end]
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
    pieces, last = [], 0
    for begin, end in file_spans(log):
        pieces += [log[last:begin], " "]
        last = end
    pieces.append(log[last:])
    found = RULE.findall("".join(pieces))
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


def not_mentioned(
    answer: str, log: str, limit: int = 10, files: list[str] | None = None
) -> list[str]:
    """The most named files and rule codes of `log` (up to `limit` of each) that `answer` omits.

    B2e, fallback decided by the user on 2026-10-17: in the chunked `local_lint_summary` the
    program, not the model, lists what of the inventory the summary left out. With `files` (issue
    #641: the files with failures of a pytest log) only those files are checked, not every file
    the log names: a clean file a summary leaves out is left out on purpose.
    """
    named = files_by_frequency(log) if files is None else files
    items = named[:limit] + codes_by_frequency(log)[:limit]
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

_FINDING_WORD = re.compile(r"error|warning|offense|issue|problem|violation", re.IGNORECASE)
_COUNT_SUFFIX = re.compile(r"count", re.IGNORECASE)


def is_finding_counter(key: str) -> bool:
    """A counter of findings in a JSON report (`errorCount`, `fatalErrorCount`, `offense_count`).

    Same verdict as `re.fullmatch(r"(?i).*(?:error|warning|offense|issue|problem|violation).*count",
    key)` (the reference regex lives in the tests), in linear time: a JSON key is untrusted input.

    The `.*` of the pattern takes no line break, so the key holds none; it ends in `count`, and a
    word of the list comes before that suffix. The fullmatch backtracked in quadratic time.
    """
    size = len(key) - 5
    return (
        size >= 0
        and "\n" not in key
        and _COUNT_SUFFIX.fullmatch(key, size) is not None
        and _FINDING_WORD.search(key, 0, size) is not None
    )


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
    if any(is_finding_counter(k) and _is_number(v) and v for k, v in obj.items()):
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


# --- The failures of a pytest log (issue #641) --------------------------------------------------
# With the output of a pytest run of 24 files (1 failed, 660 passed) the summary gave a second
# failure in a file that only appears CITED in the assertion message of the one failure, and one
# "no errors" line per clean file until `max_tokens` cut it. The model got the list of every file
# the log names, the cited one first (it is the most named). The program now reads the failures
# from the log, so that the model gets them as facts and its answer is checked against them.
# Line by line with `str` methods: the input is not trusted, and no pattern here backtracks.


class PytestFailure(NamedTuple):
    """One failing test of a pytest log: a `FAILED` or `ERROR` line of its short summary."""

    #: `"FAILED"` or `"ERROR"`.
    kind: str
    #: The node id, with forward slashes (`tests/test_api.py::TestUsers::test_create`).
    node: str
    #: The file of the node (`tests/test_api.py`).
    file: str
    #: The `file:line` of its traceback, in the node's file when the traceback passes through it,
    #: else where the exception was raised; `None` when the log has no traceback for it.
    location: str | None


#: What may come before `FAILED`/`ERROR` on a line of `pytest -v -n N`: `[gw0] [ 50%] `.
_XDIST_PREFIX_CHARS = frozenset("[]gw0123456789% ")
#: The words of the results line of pytest (`2 failed, 36 passed, 2 errors in 1.92s`).
_RESULT_WORDS = frozenset(
    {
        "failed",
        "passed",
        "skipped",
        "deselected",
        "xfailed",
        "xpassed",
        "error",
        "errors",
        "warning",
        "warnings",
        "rerun",
    }
)


def _node_file(node: str) -> str | None:
    """The file of a node id, when the part before `::` is one whole file token."""
    path = node.split("::", 1)[0]
    return path if path and file_spans(path) == [(0, len(path))] else None


def _summary_entry(line: str) -> tuple[str, str, str] | None:
    """`(kind, node, file)` of a `FAILED <node> - <message>` (or `ERROR`) line, else `None`."""
    for kind in ("FAILED", "ERROR"):
        at = line.find(kind + " ")
        if at == -1:
            continue
        if at > 0 and (line[at - 1] != " " or not set(line[:at]) <= _XDIST_PREFIX_CHARS):
            continue
        node = line[at + len(kind) + 1 :].split(" - ", 1)[0].strip().replace("\\", "/")
        file = _node_file(node)
        if file is not None:
            return kind, node, file
    return None


def _pytest_counts(lines: list[str]) -> dict[str, int] | None:
    """The figures of the last results line of pytest (`1 failed, 660 passed in 48.17s`)."""
    for line in reversed(lines):
        head, sep, tail = line.strip().strip("=").strip().rpartition(" in ")
        if not sep or not tail[:1].isdigit():
            continue
        counts: dict[str, int] = {}
        for part in head.split(", "):
            figure, _, word = part.partition(" ")
            if not figure.isdigit() or word not in _RESULT_WORDS:
                break
            counts["error" if word == "errors" else word] = int(figure)
        else:
            if counts:
                return counts
    return None


def _same_file(a: str, b: str) -> bool:
    """Whether two spellings name the same file: equal, or one a path suffix of the other."""
    a, b = norm_path(a).removeprefix("./"), norm_path(b).removeprefix("./")
    return a == b or a.endswith("/" + b) or b.endswith("/" + a)


def _sections(lines: list[str]) -> dict[str, tuple[int, int]]:
    """The failure sections of the log by title (`____ test_x ____`): `title -> (start, end)`."""
    found: dict[str, tuple[int, int]] = {}
    title, start = None, 0
    for index, line in enumerate(lines):
        text = line.strip()
        header = len(text) > 2 and text[0] == "_" and text[-1] == "_" and " " in text
        if header or text.startswith("="):
            if title is not None:
                found.setdefault(title, (start, index))
            title = text.strip("_").strip().replace("\\", "/") if header else None
            start = index + 1
    if title is not None:
        found.setdefault(title, (start, len(lines)))
    return found


def _locations(lines: list[str]) -> list[tuple[str, str]]:
    """The `(path, line)` of the traceback lines that start a line: `tests/x.py:31: in test_x`."""
    found = []
    for line in lines:
        if not line or line[0] in " \t>" or line.startswith("E "):
            continue
        path, sep, figure = line.split(": ", 1)[0].rpartition(":")
        if sep and path and figure.isdigit():
            found.append((path.replace("\\", "/"), figure))
    return found


def _section_titles(kind: str, node: str, file: str) -> list[str]:
    """The titles pytest gives the section of a failure (`TestUsers.test_create`)."""
    if "::" not in node:
        return [f"ERROR collecting {file}"]
    name = ".".join(node.split("::")[1:])
    if kind == "ERROR":
        return [f"ERROR at setup of {name}", f"ERROR at teardown of {name}", name]
    return [name]


def _location(
    lines: list[str], sections: dict[str, tuple[int, int]], kind: str, node: str, file: str
) -> str | None:
    """The `file:line` of the traceback of one failure (`PytestFailure.location`)."""
    for title in _section_titles(kind, node, file):
        if title in sections:
            start, end = sections[title]
            found = _locations(lines[start:end])
            own = [figure for path, figure in found if _same_file(path, file)]
            if own:
                return f"{file}:{own[-1]}"
            if found:
                return f"{found[-1][0]}:{found[-1][1]}"
            return None
    return None


def pytest_failures(log: str) -> list[PytestFailure]:
    """The failing tests of a pytest log, read by the program (issue #641), or `[]`.

    From the `FAILED`/`ERROR` lines of the short test summary (also the per-test lines of
    `pytest -v -n N`), each node once, in order. Only a log with a results line of pytest or a
    short test summary counts, and when the results line gives figures the lines must add up to
    them: a cut summary is not the list of failures, and it gives `[]` (the model then goes as
    before). Linear in the size of the log.
    """
    lines = _ANSI.sub("", log).splitlines()
    counts = _pytest_counts(lines)
    if counts is None and not any("short test summary info" in line for line in lines):
        return []
    entries: dict[str, tuple[str, str, str]] = {}
    for line in lines:
        entry = _summary_entry(line)
        if entry is not None and entry[1] not in entries:
            entries[entry[1]] = entry
    if counts is not None:
        failed = sum(1 for kind, _, _ in entries.values() if kind == "FAILED")
        errors = len(entries) - failed
        if failed != counts.get("failed", 0) or errors != counts.get("error", 0):
            return []
    sections = _sections(lines)
    return [
        PytestFailure(kind, node, file, _location(lines, sections, kind, node, file))
        for kind, node, file in entries.values()
    ]


class FailureMismatch(NamedTuple):
    """Where a summary of a pytest log does not match its failures (`failure_mismatch`)."""

    #: Files the summary gives an entry to that have no failure (a cited file, a clean one).
    phantom: list[str]
    #: Files with failures the summary does not name.
    missing: list[str]
    #: Files with failures whose entry gives another number of failures (its first figure).
    miscounted: list[str]


#: A figure of failures in an entry: `6 errores`, `2 fallos`, `1 failed`, `3 tests fallidos`. One
#: start per run of digits (`\b`), and each part is bounded: linear on a line.
_FAILURE_FIGURE = re.compile(
    r"\b(\d+)\s+(?:(?:tests?|pruebas?)\s+)?(?:fall|error|fail)", re.IGNORECASE
)
_ENTRY_LABELS = ("archivo:", "fichero:", "file:")


def _entry_file(line: str) -> str | None:
    """The file a line of a summary is the entry of, or `None`.

    A top-level line (not indented) whose text, past the bullet, numbering, emphasis and an
    "Archivo:" label, starts with a file. A file followed by `:<line>` is a cited location, not an
    entry; a file further along the line, or on an indented sub-item, is context of the entry.
    """
    if not line or line[0] in " \t":
        return None
    text = line.lstrip("#>|-*+• ")
    digits = len(text) - len(text.lstrip("0123456789"))
    if digits and text[digits : digits + 1] in (".", ")"):
        text = text[digits + 1 :]
    text = text.lstrip("*` ")
    for label in _ENTRY_LABELS:
        if text[: len(label)].lower() == label:
            text = text[len(label) :].lstrip("*` ")
            break
    spans = file_spans(text[:512])
    if not spans or spans[0][0] != 0:
        return None
    end = spans[0][1]
    if text[end : end + 1] == ":" and text[end + 1 : end + 2].isdigit():
        return None
    return text[:end].replace("\\", "/")


def failure_mismatch(answer: str, failures: list[PytestFailure]) -> FailureMismatch:
    """Where `answer` does not match `failures`, the failures the program read (issue #641)."""
    answer = MARKDOWN_ESCAPE.sub(r"\1", answer)
    failing: list[str] = []
    for failure in failures:
        if not any(_same_file(failure.file, f) for f in failing):
            failing.append(failure.file)
    phantom: list[str] = []
    miscounted: list[str] = []
    for line in answer.splitlines():
        entry = _entry_file(line)
        if entry is None:
            continue
        own = [f for f in failing if _same_file(entry, f)]
        if not own:
            if not any(_same_file(entry, p) for p in phantom):
                phantom.append(entry)
            continue
        # The first figure of the entry is its count of failures; a later one is part of the
        # description ("1 fallo ... Se identificaron 3 errores: propias, ..." live, 2026-11-10).
        real = sum(1 for failure in failures if _same_file(failure.file, own[0]))
        first = _FAILURE_FIGURE.search(line)
        if first is not None and int(first.group(1)) != real and own[0] not in miscounted:
            miscounted.append(own[0])
    missing = [file for file in failing if not mentions(file, answer)]
    return FailureMismatch(phantom, missing, miscounted)
