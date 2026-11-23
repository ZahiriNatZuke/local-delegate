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

and three categories are kept, failures (failed and errors), errors alone (#714) and skips
(skipped, ignored). Then each
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

__all__ = [
    "ERRORS",
    "FAILURES",
    "SKIPS",
    "Totals",
    "denied",
    "pytest_header",
    "python_versions",
    "totals",
]

#: Failed tests and errors together: what «fallos»/«failures» of a summary talk about.
FAILURES = "failures"
#: #714: errors alone (`1 error`): what «errores»/«errors» talk about («1 falló, sin errores» over
#: `1 failed` is faithful).
ERRORS = "errors"
SKIPS = "skips"

#: Lines longer than this are not a runner's totals line (and are not scanned).
_MAX_LINE = 400

#: Input or summary longer than this is not checked (the check stays cheap on any input).
_MAX_TEXT = 2_000_000

#: A runner's word for a counted outcome, and the category it falls in (None: counted, not kept).
_OUTCOMES: dict[str, str | None] = {
    "passed": None,
    "failed": FAILURES,
    "error": ERRORS,
    "errors": ERRORS,
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
    #: #714: the `N outcome` parts of each totals line, as the runner wrote them
    #: (`216 passed, 3 skipped`), for the line the program adds to the answer.
    parts: list[str] = field(default_factory=list)
    #: #714 (F3 of #684): the first line that counts each category above zero, to cite it.
    line_for: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.lines)


def _parts(body: str, separator: str) -> tuple[dict[str, int], list[str]] | None:
    """`body` as `N outcome` parts split on `separator`, or None if one part is not that.

    The kept counts per category (failures count the errors too), and the parts as written."""
    found: dict[str, int] = {}
    written: list[str] = []
    pieces = [piece.strip() for piece in body.split(separator)]
    if not pieces or not any(pieces):
        return None
    for piece in pieces:
        if not piece:
            continue
        match = _PART.fullmatch(piece)
        if match is None:
            return None
        written.append(piece)
        category = _OUTCOMES[match.group(2)]
        count = int(match.group(1))
        if category == ERRORS:
            found[FAILURES] = found.get(FAILURES, 0) + count
        if category is not None:
            found[category] = found.get(category, 0) + count
    return found, written


def _totals_line(line: str) -> tuple[dict[str, int], list[str]] | None:
    """The kept counts and the parts of `line` if it is a totals line of pytest, jest or cargo."""
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
        parsed = _totals_line(line)
        if parsed is not None:
            counts, written = parsed
            found.lines.append(line.strip())
            found.parts.append(", ".join(written))
            for category, count in counts.items():
                found.counts[category] = found.counts.get(category, 0) + count
                if count > 0:
                    found.line_for.setdefault(category, line.strip())
            continue
        if len(line) <= _MAX_LINE:
            go_match = _GO_LINE.match(line)
            if go_match is not None:
                category = FAILURES if go_match.group(1) == "FAIL" else SKIPS
                go[category] += 1
                go_lines.append(line.strip())
                found.line_for.setdefault(category, line.strip())
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
            "failure",
            "failures",
            "failed",
            "fail",
            "fails",
            "failing",
        ],
        FAILURES,
    ),
    **dict.fromkeys(["error", "errores", "errors"], ERRORS),
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

#: #714: figures written in words (folded). Between a negation and a category word they count the
#: category, like a figure in digits («No hubo fallos salvo dos omitidas»). «un», «una», «uno»,
#: «one» are left out: they are also the article («No hubo ni un salto»).
_FIGURE_WORDS = frozenset(
    [
        "dos",
        "tres",
        "cuatro",
        "cinco",
        "seis",
        "siete",
        "ocho",
        "nueve",
        "diez",
        "once",
        "doce",
        "trece",
        "catorce",
        "quince",
        "dieciseis",
        "diecisiete",
        "dieciocho",
        "diecinueve",
        "veinte",
        "veintiuno",
        "veintidos",
        "veintitres",
        "veinticuatro",
        "veinticinco",
        "veintiseis",
        "veintisiete",
        "veintiocho",
        "veintinueve",
        "treinta",
        "cuarenta",
        "cincuenta",
        "sesenta",
        "setenta",
        "ochenta",
        "noventa",
        "cien",
        "ciento",
        "cientos",
        "mil",
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
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
        "hundred",
        "hundreds",
        "thousand",
        "thousands",
    ]
)

#: How many words back from a category word a negation may be.
_REACH = 6

#: A word, a figure or a clause mark: one class per alternative, no nesting, no backtracking.
#: #714: the comma is a clause mark too («Sin fallos, cuatro pruebas omitidas»); a decimal comma
#: stays inside its figure (second alternative).
_TOKEN = re.compile(r"[^\W\d_]+|\d+(?:[.,]\d+)?|[.,;:!?()\[\]\n]")


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
            if (
                word[0].isdigit()
                or not word[0].isalpha()
                or word in _CLAUSE_WORDS
                or word in _FIGURE_WORDS
            ):
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


#: #714: the session header of pytest (`platform win32 -- Python 3.11.15, pytest-8.3.4, …`). Read
#: per line of at most `_MAX_LINE` characters; bounded runs and no nesting: no backtracking.
_PYTEST_HEADER = re.compile(
    r"platform \S{1,40} -- Python (\d{1,3}\.\d{1,3}(?:\.\d{1,3})?)\S{0,20}, "
    r"pytest-(\d{1,3}(?:\.\d{1,3}){0,3})"
)

#: A Python version named in a summary (`Python 3.11.5`, `python 3.12`), not cut in the middle.
_PYTHON_IN_TEXT = re.compile(r"\b[Pp]ython\s{1,3}v?(\d{1,3}\.\d{1,3}(?:\.\d{1,3})?)(?![.\d]?\d)")


def pytest_header(source: str) -> tuple[str, str] | None:
    """(Python, pytest) versions of the first pytest session header in `source`, or None."""
    if not source or len(source) > _MAX_TEXT:
        return None
    for line in source.splitlines():
        if len(line) > _MAX_LINE or "-- Python " not in line:
            continue
        match = _PYTEST_HEADER.search(line)
        if match is not None:
            return match.group(1), match.group(2)
    return None


def python_versions(summary: str, source: str) -> list[str]:
    """The Python versions `summary` names that are not the one of the pytest header of `source`.

    A shorter form of the same version (`Python 3.11` for 3.11.15) is not another one. Empty
    without a header: then there is nothing to compare with."""
    if not summary or len(summary) > _MAX_TEXT:
        return []
    header = pytest_header(source)
    if header is None:
        return []
    real = header[0]
    other: list[str] = []
    for match in _PYTHON_IN_TEXT.finditer(summary):
        written = match.group(1)
        if written == real or real.startswith(written + "."):
            continue
        if written not in other:
            other.append(written)
    return other
