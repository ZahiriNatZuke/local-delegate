"""#684: check, by program, a `local_summarize` answer against the totals of a test runner.

The mechanical model summarized a short `pytest -q` output that ends in `750 passed, 2 skipped`
and wrote «omitiendo 2» and, one sentence later, «No se reportaron fallos ni saltos», with no
warning. The figure is in the input, so the #630 check (`grounding`) has nothing to flag: the
mistake is a category the summary denies while the runner counted it.

So the totals line of the common runners is read from the input:

- pytest: `=== 3 failed, 750 passed, 2 skipped, 1 error in 81.33s ===` (with or without the `=`);
- jest: `Tests:       1 failed, 2 skipped, 10 passed, 13 total`;
- cargo test: `test result: FAILED. 5 passed; 1 failed; 2 ignored; 0 measured; 0 filtered out`;
- go test -v: one `--- FAIL:` or `--- SKIP:` line per test.

and two categories are kept, failures (failed, errors) and skips (skipped, ignored). Then each
mention of a category in the summary («fallos», «saltos», «skipped», «errors»…) is looked at: if a
negation («no», «sin», «ni», «ningún», «cero», «without», «none», «0»…) comes before it in the same
clause, with no figure in between, and the runner counted that category above zero, a warning
names it, with the runner's own line. The summary is not changed: the caller is told what to
check, and pointed to `local_lint_summary`, made for test output.

Pure functions over strings, linear in the length of the text: the input is not trusted, so no
pattern here can backtrack on it (fixed alternations and bounded digit runs, matched per line or
per word).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

__all__ = ["FAILURES", "SKIPS", "Totals", "denied", "totals"]

FAILURES = "failures"
SKIPS = "skips"

#: Lines longer than this are not a runner's totals line (and are not scanned).
_MAX_LINE = 400

#: Input or summary longer than this is not checked (the check stays cheap on any input).
_MAX_TEXT = 2_000_000

#: A runner's word for a counted outcome, and the category it falls in (None: counted, not kept).
_OUTCOMES: dict[str, str | None] = {
    "passed": None,
    "failed": FAILURES,
    "error": FAILURES,
    "errors": FAILURES,
    "skipped": SKIPS,
    "ignored": SKIPS,
    "xfailed": None,
    "xpassed": None,
    "deselected": None,
    "warning": None,
    "warnings": None,
    "rerun": None,
    "measured": None,
    "filtered out": None,
    "total": None,
    "pending": None,
}

#: One `N outcome` part of a totals line. Anchored at both ends, one run of digits and a closed
#: alternation: no backtracking.
_PART = re.compile(r"(\d{1,9}) (" + "|".join(re.escape(k) for k in _OUTCOMES) + r")")

#: The ` in 81.33s` (pytest) or `; finished in 0.00s` (cargo) that ends a totals line.
_DURATION = re.compile(r"\s+in\s+[\d.]{1,20}m?s\b.*$|;\s*finished in .*$")

_CARGO_PREFIX = re.compile(r"test result: (?:ok|FAILED)\.\s")
_JEST_PREFIX = re.compile(r"Tests:\s+")
_GO_LINE = re.compile(r"\s{0,40}--- (FAIL|SKIP):")


@dataclass
class Totals:
    """What the runner counted per kept category, and its own lines, as found."""

    counts: dict[str, int] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.lines)


def _parts(body: str, separator: str) -> dict[str, int] | None:
    """`body` as `N outcome` parts split on `separator`, or None if one part is not that."""
    found: dict[str, int] = {}
    pieces = [piece.strip() for piece in body.split(separator)]
    if not pieces or not any(pieces):
        return None
    for piece in pieces:
        if not piece:
            continue
        match = _PART.fullmatch(piece)
        if match is None:
            return None
        category = _OUTCOMES[match.group(2)]
        if category is not None:
            found[category] = found.get(category, 0) + int(match.group(1))
    return found


def _totals_line(line: str) -> dict[str, int] | None:
    """The kept counts of `line` if it is the totals line of pytest, jest or cargo."""
    stripped = line.strip()
    if len(stripped) > _MAX_LINE or not stripped:
        return None
    cargo = _CARGO_PREFIX.match(stripped)
    if cargo is not None:
        return _parts(_DURATION.sub("", stripped[cargo.end() :]), ";")
    jest = _JEST_PREFIX.match(stripped)
    if jest is not None:
        return _parts(stripped[jest.end() :], ",")
    # pytest: the line may come framed in `=` and ends in ` in 81.33s` (also `-q`).
    body = stripped.strip("=").strip()
    without_duration = _DURATION.sub("", body)
    if without_duration == body:
        return None  # a pytest totals line always says how long it took
    return _parts(without_duration, ",")


def totals(source: str) -> Totals:
    """The totals the runners in `source` counted, summed over every totals line found."""
    found = Totals()
    if not source or len(source) > _MAX_TEXT:
        return found
    go = {FAILURES: 0, SKIPS: 0}
    go_lines: list[str] = []
    for line in source.splitlines():
        counts = _totals_line(line)
        if counts is not None:
            found.lines.append(line.strip())
            for category, count in counts.items():
                found.counts[category] = found.counts.get(category, 0) + count
            continue
        if len(line) <= _MAX_LINE:
            go_match = _GO_LINE.match(line)
            if go_match is not None:
                go[FAILURES if go_match.group(1) == "FAIL" else SKIPS] += 1
                go_lines.append(line.strip())
    if go_lines:
        for category, count in go.items():
            found.counts[category] = found.counts.get(category, 0) + count
        found.lines.extend(go_lines[:3])
    return found


def _fold(word: str) -> str:
    """`word` casefolded and without accents (`Ningún` -> `ningun`)."""
    decomposed = unicodedata.normalize("NFD", word.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


#: Words of the summary that name a category (folded), Spanish and English.
_CATEGORY_WORDS: dict[str, str] = {
    **dict.fromkeys(
        [
            "fallo",
            "fallos",
            "falla",
            "fallas",
            "fallido",
            "fallidos",
            "fallida",
            "fallidas",
            "fallaron",
            "fallo",
            "error",
            "errores",
            "fallos",
            "failure",
            "failures",
            "failed",
            "fail",
            "fails",
            "failing",
            "errors",
        ],
        FAILURES,
    ),
    **dict.fromkeys(
        [
            "salto",
            "saltos",
            "saltado",
            "saltados",
            "saltada",
            "saltadas",
            "omitido",
            "omitidos",
            "omitida",
            "omitidas",
            "omision",
            "omisiones",
            "ignorado",
            "ignorados",
            "ignorada",
            "ignoradas",
            "skip",
            "skips",
            "skipped",
            "ignored",
        ],
        SKIPS,
    ),
}

#: Words that negate what follows in their clause (folded), Spanish and English.
_NEGATIONS = frozenset(
    [
        "no",
        "sin",
        "ni",
        "ningun",
        "ninguna",
        "ninguno",
        "ningunos",
        "ningunas",
        "nada",
        "cero",
        "jamas",
        "nunca",
        "tampoco",
        "not",
        "without",
        "none",
        "nor",
        "zero",
        "never",
        "neither",
        "0",
    ]
)

#: Words that end the reach of a negation: a new clause starts with them.
_CLAUSE_WORDS = frozenset(
    ["y", "pero", "aunque", "mientras", "and", "but", "while", "whereas", "although"]
)

#: How many words back from a category word a negation may be.
_REACH = 6

#: A word, a figure or a clause mark: one class per alternative, no nesting, no backtracking.
_TOKEN = re.compile(r"[^\W\d_]+|\d+(?:[.,]\d+)?|[.;:!?()\[\]\n]")


def _negated_categories(summary: str) -> list[tuple[str, str]]:
    """(category, clause) for each mention of a category that a negation of its clause denies."""
    tokens = [(m.group(0), m.start(), m.end()) for m in _TOKEN.finditer(summary)]
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, (token, _start, end) in enumerate(tokens):
        category = _CATEGORY_WORDS.get(_fold(token))
        if category is None or category in seen:
            continue
        for back in range(index - 1, max(-1, index - 1 - _REACH), -1):
            word = _fold(tokens[back][0])
            if word in _NEGATIONS:
                start = tokens[back][1]
                found.append((category, summary[start:end]))
                seen.add(category)
                break
            if word[0].isdigit() or not word[0].isalpha() or word in _CLAUSE_WORDS:
                break  # a figure counts the category; a mark or a conjunction ends the clause
    return found


def denied(summary: str, source: str) -> list[tuple[str, str, int]]:
    """(category, clause of the summary, runner's count) for each category the summary denies
    while a test runner's totals in `source` count it above zero. Empty when nothing to say."""
    if not summary or len(summary) > _MAX_TEXT:
        return []
    found = totals(source)
    if not found:
        return []
    return [
        (category, clause, found.counts[category])
        for category, clause in _negated_categories(summary)
        if found.counts.get(category, 0) > 0
    ]
