"""#460: check, by program, the line numbers a `local_explain_code` answer cites.

The model sees every line as `N| line` and still cites lines that are off by a few (228/236 for
calls really at 233/270/328/336). So, after the answer, with the whole file at hand:

- every cited line (or range) is checked against what the answer line that cites it names (its
  code-like identifiers, its words of 4 letters or more, its numbers of 2 digits or more) and the
  code-like identifiers of the question: a citation that finds none of them on its lines, or one
  line around them, is reported;
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
#: Shortest plain word of the answer that can confirm a citation ("llama a dispatch").
MIN_WORD_LEN = 4
#: Occurrences listed per identifier before "and N more".
MAX_OCCURRENCES = 20
#: Identifiers of the question that get an occurrences line.
MAX_IDENTIFIERS = 5
#: A citation holds if what it refers to is on its lines or this many lines around them: the
#: decorator above a `def`, the `if` that opens the block, the comment above a function.
TOLERANCE = 1

#: Code-like words so common that a whole-word match proves nothing.
_COMMON = frozenset(
    {
        "this", "self", "that", "the", "and", "for", "not", "null", "none", "true", "false",
        "return", "function", "const", "let", "var", "class", "def", "new", "void", "async",
        "await", "import", "export", "from", "if", "else", "while", "string", "number",
        "with",
    }
)  # fmt: skip

#: Backticked names that are files (`App.tsx`, `package.json`): their last part is an extension,
#: not an identifier.
_FILE_EXTENSIONS = frozenset(
    {
        "py", "pyi", "ts", "tsx", "js", "jsx", "mjs", "cjs", "json", "md", "yaml", "yml",
        "toml", "html", "css", "scss", "txt", "lock", "cfg", "ini", "sh", "ps1", "go", "rs",
        "java", "kt", "rb", "php", "vue", "svelte", "xml", "csv", "sql", "env",
    }
)  # fmt: skip

_WORD = r"[A-Za-z_$][\w$]*"
#: `name` between backticks (a dotted path keeps its last part), `name(`, camelCase, snake_case.
_BACKTICKED = re.compile(r"`([^`\n]{1,80})`")
_CALLED = re.compile(r"(?<![\w$.])(" + _WORD + r")\s*\(")
_CAMEL = re.compile(r"(?<![\w$])([a-z][a-z0-9]*[A-Z][\w$]*)")
_SNAKE = re.compile(r"(?<![\w$])([A-Za-z][A-Za-z0-9]*_[\w$]*[A-Za-z0-9])")
#: What else of an answer line can confirm a citation: plain words and numbers like 404 or 9393.
_PLAIN_WORD = re.compile(r"(?<!\w)([^\W\d_]{" + str(MIN_WORD_LEN) + r",})(?!\w)")
_NUMBER = re.compile(r"(?<![\w.])(\d{2,})(?![\w.])")
#: The citation keywords themselves never confirm: `// line 12` would confirm any "line 12".
_CITATION_WORD = re.compile(r"(?i)l[i\xed]neas?|lines?")

#: "line 12", "lines 12-20", Spanish "linea/lineas" with or without accent, "l. 12", followed by
#: a list: "lineas 228, 233 y 236", "228/233/236", "120-130". A later item followed by a word is
#: not a line ("linea 4, 2 veces", "linea 4 y 3 modulos").
_NUM = r"\d{1,6}(?:\s*[-–]\s*\d{1,6})?"
_SEPARATOR_WORD = r"(?:y|e|and)\b"
_NEXT = (
    r"(?:\s*(?:,|/|\b" + _SEPARATOR_WORD + r")\s*" + _NUM
    + r"(?![\d–-])(?!\s+(?!" + _SEPARATOR_WORD + r")[^\W\d_]))"
)  # fmt: skip
_LIST = _NUM + _NEXT + "*"
_KEYWORD = re.compile(
    r"(?i)\b(?:l[i\xed]neas?|lines?|l\.)\s*(?:n[o\xba\xb0.]*\s*)?(" + _LIST + r")"
)
#: `L123` or `L120-L130`.
_L_FORM = re.compile(r"\bL(\d{1,6})(?:\s*[-–]\s*L?(\d{1,6}))?\b")
#: `name: 123`, `name():123`, `file.ts:123` (the "name: line" the prompt asks for). The
#: lookbehind anchors the name at a word start: without it a long word was retried from each of
#: its letters (quadratic: 32 000 chars took 21 s).
_COLON_FORM = re.compile(r"(?<![\w$])(" + _WORD + r")(?:\(\))?`?\s*:\s*(\d{1,6})(?![\d:.,]\d)")
#: The prefix echoed back: `233| this.focus()`.
_PREFIX_FORM = re.compile(r"(?m)^\s*(\d{1,6})\|")
#: A bare list of three or more numbers of 2 digits or more: `228/233/236/270` (not `1/2/3`).
_SLASH_LIST = re.compile(r"(?<![\w/])(\d{2,6}(?:/\d{2,6}){2,})(?![\w/])")
_RANGE = re.compile(r"(\d{1,6})(?:\s*[-–]\s*(\d{1,6}))?")


def _is_code_like(word: str) -> bool:
    return len(word) >= MIN_IDENTIFIER_LEN and word.lower() not in _COMMON


def identifiers(text: str) -> list[str]:
    """The code-like identifiers of `text`, in order of appearance and without repeats.

    Code-like means: between backticks, followed by `(`, camelCase or snake_case; plain words of
    the language ("handlers", "the") never count, and short or common ones neither. A backticked
    file name (`App.tsx`) gives nothing: its extension is not an identifier.
    """
    found: list[tuple[int, str]] = []
    for m in _BACKTICKED.finditer(text):
        inner = m.group(1).strip().rstrip("()").strip()
        parts = re.split(r"[.:#]", inner) if inner else [""]
        if len(parts) > 1 and parts[-1].lower() in _FILE_EXTENSIONS:
            continue
        if re.fullmatch(_WORD, parts[-1]):
            found.append((m.start(), parts[-1]))
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
    #: Code-like identifiers of the answer line and of the question.
    names: tuple[str, ...]
    #: Plain words and numbers of the answer line: they confirm a citation, never list one.
    words: tuple[str, ...] = ()

    def label(self) -> str:
        return str(self.start) if self.start == self.end else f"{self.start}-{self.end}"


def _ranges(listing: str) -> list[tuple[int, int]]:
    out = []
    for m in _RANGE.finditer(listing):
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        out.append((min(start, end), max(start, end)))
    return out


def _spans(text_line: str, names: tuple[str, ...], total_lines: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for m in _KEYWORD.finditer(text_line):
        spans.extend(_ranges(m.group(1)))
    for m in _L_FORM.finditer(text_line):
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        spans.append((min(start, end), max(start, end)))
    for m in _COLON_FORM.finditer(text_line):
        # A named identifier (`focus: 233`) or a file extension (`dialog.ts:233`); never a plain
        # word of the prose (`Note: 3 calls`), nor a number the file cannot have (`port: 9393`,
        # `example.com:8080`).
        number = int(m.group(2))
        if number > total_lines:
            continue
        if m.group(1) in names or text_line[max(0, m.start() - 1) : m.start()] == ".":
            spans.append((number, number))
    spans.extend((int(m.group(1)),) * 2 for m in _PREFIX_FORM.finditer(text_line))
    for m in _SLASH_LIST.finditer(text_line):
        numbers = [int(n) for n in m.group(1).split("/")]
        if all(1 <= n <= total_lines for n in numbers):  # 30/10/2026 is a date, not lines
            spans.extend((n, n) for n in numbers)
    return spans


def citations(answer: str, question_names: list[str], total_lines: int) -> list[Citation]:
    """The line citations of `answer`, each with what it can be checked against.

    That is the code-like identifiers of the same answer line plus the ones of the question
    (`names`), and the plain words and numbers of that line (`words`). A citation with no
    code-like name to check against is left out: it is neither right nor wrong.
    """
    out: list[Citation] = []
    seen: set[tuple[int, int]] = set()
    for text_line in answer.split("\n"):
        names = tuple(dict.fromkeys([*identifiers(text_line), *question_names]))
        if not names:
            continue
        spans = _spans(text_line, names, total_lines)
        if not spans:
            continue
        cited = {str(n) for span in spans for n in span}  # a cited number confirms nothing
        words = tuple(
            dict.fromkeys(
                w
                for w in [*_PLAIN_WORD.findall(text_line), *_NUMBER.findall(text_line)]
                if w not in cited
                and w.lower() not in _COMMON
                and w not in names
                and not _CITATION_WORD.fullmatch(w)
            )
        )
        for span in spans:
            if span[0] < 1 or span in seen:
                continue
            seen.add(span)
            out.append(Citation(span[0], span[1], names, words))
    return out


@dataclass
class LineCheck:
    checked: list[Citation] = field(default_factory=list)
    mismatched: list[Citation] = field(default_factory=list)
    #: (identifier, its lines) for each code-like identifier of the question.
    found: list[tuple[str, list[int]]] = field(default_factory=list)


def check(answer: str, question: str, content: str, truncated: bool = False) -> LineCheck:
    """Check the citations of `answer` against `content` and find the question's identifiers.

    `content` is the whole file, split only on `\\n` like `_number_lines` (and `Read`). With
    `truncated` (the answer was cut by `max_tokens`) its last line is not checked: it may end in
    the middle of a number.
    """
    lines = content.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    question_names = identifiers(question)
    if truncated:
        answer = answer.rstrip("\n").rpartition("\n")[0]
    result = LineCheck()
    patterns: dict[str, re.Pattern[str]] = {}
    for citation in citations(answer, question_names, len(lines)):
        result.checked.append(citation)
        low = max(citation.start - TOLERANCE, 1)
        window = lines[low - 1 : min(citation.end + TOLERANCE, len(lines))]
        hit = any(
            patterns.setdefault(name, _whole_word(name)).search(line)
            for line in window
            for name in (*citation.names, *citation.words)
        )
        if not hit:
            result.mismatched.append(citation)
    result.found = [(name, occurrences(lines, name)) for name in question_names[:MAX_IDENTIFIERS]]
    return result
