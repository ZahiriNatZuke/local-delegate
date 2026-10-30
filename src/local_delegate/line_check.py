"""#460: check, by program, the line numbers a `local_explain_code` answer cites.

The model sees every line as `N| line` and still cites lines that are off by a few (228/236 for
calls really at 233/270/328/336). So, after the answer, with the whole file at hand:

- every cited line (or range) is checked against the code-like identifiers of the question and of
  the answer line that cites it: a citation whose line contains none of them is reported;
- every code-like identifier of the question is searched in the file as a whole word, and its
  real lines are listed, which is exact and is what "locate, then Read only that range" needs.

Pure functions over strings; the tool decides when to apply them (only with `path` and a
question) and how to word the result (`i18n`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Shortest identifier worth checking: `i`, `x`, `id` match almost any line.
MIN_IDENTIFIER_LEN = 3
#: Occurrences listed per identifier before "and N more".
MAX_OCCURRENCES = 20
#: Identifiers of the question that get an occurrences line.
MAX_IDENTIFIERS = 5

#: Code-like words so common that a whole-word match proves nothing.
_COMMON = frozenset(
    {
        "this", "self", "that", "the", "and", "for", "not", "null", "none", "true", "false",
        "return", "function", "const", "let", "var", "class", "def", "new", "void", "async",
        "await", "import", "export", "from", "if", "else", "while", "string", "number",
    }
)  # fmt: skip

_WORD = r"[A-Za-z_$][\w$]*"
#: `name` between backticks (a dotted path keeps its last part), `name(`, camelCase, snake_case.
_BACKTICKED = re.compile(r"`([^`\n]{1,80})`")
_CALLED = re.compile(r"(?<![\w$.])(" + _WORD + r")\s*\(")
_CAMEL = re.compile(r"(?<![\w$])([a-z][a-z0-9]*[A-Z][\w$]*)")
_SNAKE = re.compile(r"(?<![\w$])([A-Za-z][A-Za-z0-9]*_[\w$]*[A-Za-z0-9])")

#: "line 12", "lines 12-20", Spanish "linea/lineas" with or without accent, "l. 12", followed by
#: a list: "lineas 228, 233 y 236", "228/233/236", "120-130".
_NUM = r"\d{1,6}(?:\s*[-–]\s*\d{1,6})?"
_LIST = _NUM + r"(?:\s*(?:,|/|\by\b|\band\b|\be\b)\s*" + _NUM + r")*"
_KEYWORD = re.compile(
    r"(?i)\b(?:l[i\xed]neas?|lines?|l\.)\s*(?:n[o\xba\xb0.]*\s*)?(" + _LIST + r")"
)
#: `L123` or `L120-L130`.
_L_FORM = re.compile(r"\bL(\d{1,6})(?:\s*[-–]\s*L?(\d{1,6}))?\b")
#: `name: 123`, `name():123`, `file.ts:123` (the "name: line" the prompt asks for).
_COLON_FORM = re.compile(r"(" + _WORD + r")(?:\(\))?`?\s*:\s*(\d{1,6})(?![\d:.,]\d)")
#: The prefix echoed back: `233| this.focus()`.
_PREFIX_FORM = re.compile(r"(?m)^\s*(\d{1,6})\|")
#: A bare list of three or more numbers: `228/233/236/270`.
_SLASH_LIST = re.compile(r"(?<![\w/])(\d{1,6}(?:/\d{1,6}){2,})(?![\w/])")
_RANGE = re.compile(r"(\d{1,6})(?:\s*[-–]\s*(\d{1,6}))?")


def _is_code_like(word: str) -> bool:
    return len(word) >= MIN_IDENTIFIER_LEN and word.lower() not in _COMMON


def identifiers(text: str) -> list[str]:
    """The code-like identifiers of `text`, in order of appearance and without repeats.

    Code-like means: between backticks, followed by `(`, camelCase or snake_case; plain words of
    the language ("handlers", "the") never count, and short or common ones neither.
    """
    found: list[tuple[int, str]] = []
    for m in _BACKTICKED.finditer(text):
        inner = m.group(1).strip().rstrip("()").strip()
        last = re.split(r"[.:#]", inner)[-1] if inner else ""
        if re.fullmatch(_WORD, last):
            found.append((m.start(), last))
    for pattern in (_CALLED, _CAMEL, _SNAKE):
        found.extend((m.start(), m.group(1)) for m in pattern.finditer(text))
    out: list[str] = []
    for _pos, word in sorted(found):
        if _is_code_like(word) and word not in out:
            out.append(word)
    return out


def _whole_word(name: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w$])" + re.escape(name) + r"(?![\w$])")


def occurrences(lines: list[str], name: str) -> list[int]:
    """The 1-based lines of `lines` where `name` appears as a whole word."""
    pattern = _whole_word(name)
    return [n for n, line in enumerate(lines, 1) if pattern.search(line)]


@dataclass(frozen=True)
class Citation:
    start: int
    end: int
    names: tuple[str, ...]

    def label(self) -> str:
        return str(self.start) if self.start == self.end else f"{self.start}-{self.end}"


def _ranges(listing: str) -> list[tuple[int, int]]:
    out = []
    for m in _RANGE.finditer(listing):
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        out.append((min(start, end), max(start, end)))
    return out


def citations(answer: str, question_names: list[str], total_lines: int) -> list[Citation]:
    """The line citations of `answer`, each with the identifiers it can be checked against.

    Those are the code-like identifiers of the same answer line plus the ones of the question.
    A citation with nothing to check against is left out: it is neither right nor wrong.
    """
    out: list[Citation] = []
    seen: set[tuple[int, int]] = set()
    for text_line in answer.split("\n"):
        line_names = identifiers(text_line)
        names = tuple(dict.fromkeys([*line_names, *question_names]))
        spans: list[tuple[int, int]] = []
        for m in _KEYWORD.finditer(text_line):
            spans.extend(_ranges(m.group(1)))
        for m in _L_FORM.finditer(text_line):
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else start
            spans.append((min(start, end), max(start, end)))
        for m in _COLON_FORM.finditer(text_line):
            # A named identifier (`focus: 233`) or a file extension (`dialog.ts:233`); never a
            # plain word of the prose (`Note: 3 calls`).
            if m.group(1) in names or text_line[max(0, m.start() - 1) : m.start()] == ".":
                spans.append((int(m.group(2)),) * 2)
        spans.extend((int(m.group(1)),) * 2 for m in _PREFIX_FORM.finditer(text_line))
        for m in _SLASH_LIST.finditer(text_line):
            numbers = [int(n) for n in m.group(1).split("/")]
            if all(1 <= n <= total_lines for n in numbers):  # 30/10/2026 is a date, not lines
                spans.extend((n, n) for n in numbers)
        if not names:
            continue
        for span in spans:
            if span[0] < 1 or span in seen:
                continue
            seen.add(span)
            out.append(Citation(span[0], span[1], names))
    return out


@dataclass
class LineCheck:
    checked: list[Citation] = field(default_factory=list)
    mismatched: list[Citation] = field(default_factory=list)
    #: (identifier, its lines) for each code-like identifier of the question.
    found: list[tuple[str, list[int]]] = field(default_factory=list)


def check(answer: str, question: str, content: str) -> LineCheck:
    """Check the citations of `answer` against `content` and find the question's identifiers.

    `content` is the whole file, split only on `\\n` like `_number_lines` (and `Read`).
    """
    lines = content.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    question_names = identifiers(question)
    result = LineCheck()
    patterns: dict[str, re.Pattern[str]] = {}
    for citation in citations(answer, question_names, len(lines)):
        result.checked.append(citation)
        window = lines[citation.start - 1 : min(citation.end, len(lines))]
        hit = any(
            patterns.setdefault(name, _whole_word(name)).search(line)
            for line in window
            for name in citation.names
        )
        if not hit:
            result.mismatched.append(citation)
    result.found = [(name, occurrences(lines, name)) for name in question_names[:MAX_IDENTIFIERS]]
    return result
