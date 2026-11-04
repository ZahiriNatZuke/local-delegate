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
import unicodedata
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


#: A line of a numbered piece: `N| code` (`server.LINE_PREFIX_SEP`), N the absolute file line.
_NUMBERED_LINE = re.compile(r"(\d{1,7})\| ?(.*)")


def piece_hits(piece: str, question: str) -> list[tuple[str, list[int]]]:
    """#527: (identifier, absolute lines) of the question's identifiers inside a numbered piece.

    Only lines that carry the `N| ` prefix count, so a piece of notes (the regroup) gives nothing.
    Identifiers that do not appear in the piece are left out; the order is the question's.
    """
    names = identifiers(question)[:MAX_IDENTIFIERS]
    if not names:
        return []
    numbered: list[tuple[int, str]] = []
    for line in piece.split("\n"):
        m = _NUMBERED_LINE.fullmatch(line.rstrip("\r"))
        if m:
            numbered.append((int(m.group(1)), m.group(2)))
    hits: list[tuple[str, list[int]]] = []
    for name in names:
        pattern = _whole_word(name)
        lines = [n for n, code in numbered if pattern.search(code)]
        if lines:
            hits.append((name, lines))
    return hits


#: #531: the `N| ` prefix at the start of an answer line, with its indentation.
_LEADING_PREFIX = re.compile(r"^(\s*)(\d{1,7})\| ?")
#: A Markdown fence line (``` or ~~~), which opens or closes a code block.
_FENCE = re.compile(r"^\s*(?:```|~~~)")


def strip_line_prefixes(answer: str, content: str) -> str:
    """#531: `answer` without the `N| ` prefix the model copied from its input onto prose lines.

    The model sees every line as `N| line` and sometimes starts a line of prose with one
    (`98| Sí, la función…`): it is the input's format, not part of the answer. Two cases keep it,
    because there it is a citation the check verifies (`_PREFIX_FORM`): any line inside a fenced
    code block, and a line outside one whose rest is the file's line N itself (an echoed line of
    code, `233| this.focus();`). Without a prefix to drop, `answer` comes back byte for byte.
    """
    if "|" not in answer:
        return answer
    lines = content.split("\n")
    out: list[str] = []
    in_fence = False
    changed = False
    for line in answer.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence:
            m = _LEADING_PREFIX.match(line)
            if m:
                number, rest = int(m.group(2)), line[m.end() :]
                copied = 1 <= number <= len(lines) and rest.strip() == lines[number - 1].strip()
                if not copied:
                    line = m.group(1) + rest
                    changed = True
        out.append(line)
    return "\n".join(out) if changed else answer


#: #527: an answer that says the code (or the notes) is not enough to answer. Spanish and
#: English, the languages of the prompts; worded narrowly, so a partial "cannot verify X" in an
#: otherwise real answer does not count.
_NO_INFORMATION = re.compile(
    r"(?i)(?:\bsin\b|\bno\b)[^.\n]{0,60}?informaci[o\u00f3]n\s+suficiente"
    r"|\bnada\s+relevante\b"
    r"|\bno\s+bastan?\b"
    r"|\b(?:not\s+enough|insufficient)\b[^.\n]{0,30}?\binformation\b"
    r"|\bnothing\s+relevant\b"
    r"|\b(?:do|does)\s+not\s+suffice\b"
)


def claims_no_information(answer: str) -> bool:
    """#527: whether `answer` says there is not enough information (or nothing relevant)."""
    return bool(_NO_INFORMATION.search(answer))


# --- #538: a premise of the question confirmed with nothing in the code behind it -------------
# Asked «how does it handle the backups and their retention?» about a module that never deletes a
# backup, the model answered there was an «implicit retention». The word came from the question,
# the file has nothing like it, and the sentence that asserts it neither negates it nor cites code
# that backs it. Those three facts are checked here, by program; the prose is not judged.

#: Letters of a word compared with the file: «retención» and «retention» share `reten`, and a
#: Spanish word that shares its first five letters with the code (`config`, `concurrent`) counts.
PREMISE_STEM_LEN = 5
#: Only nominalizations are compared: the abstract nouns of a feature or a process (retención,
#: rotación, expiración, caducidad, persistencia, limpieza; retention, rotation, consistency).
#: They are what a question presupposes («and its retention?»), and they keep their first letters
#: across Spanish and English, so a Spanish question can be checked against English code. Any
#: other word is not: «entrada», «copias», «pulsar» never appear in English code even when the
#: answer that echoes them is right (5 false warnings out of 6 correct answers without this
#: filter). Endings after folding accents and dropping a plural `s`/`es`.
_NOMINALIZATION = re.compile(r"(?:cion|sion|tion|idad|ity|ncia|ncy|nce|eza)$")
#: Nominalizations of asking, not of the domain, and cognates whose first letters differ between
#: the two languages (opción/option, sección/section). Stems of PREMISE_STEM_LEN letters. The
#: domain words (retention, rotation, expiration) are never listed: the check works for any.
_QUESTION_STEMS = frozenset(
    {
        "funci", "funct", "infor", "expli", "expla", "descr", "imple", "ejecu", "execu",
        "opcio", "optio", "secci", "secti", "versi", "condi", "situa", "canti", "difer",
        "relac", "relat", "posib", "possi", "neces",
    }
)  # fmt: skip
#: A plain word of the question long enough to compare, not glued to a backtick (`name`).
_PREMISE_WORD = re.compile(r"(?<![\w`])([^\W\d_]{" + str(PREMISE_STEM_LEN) + r",})(?![\w`])")
#: A negation in the sentence: the answer denies the premise, which is what it should do.
_NEGATION = re.compile(
    r"(?i)\b(?:no|ni|nunca|jam[a\xe1]s|ning[u\xfa]n[oa]?|nada|sin|tampoco|carece|"
    r"not|never|none|nothing|without|neither|nor|lacks?|no\s+longer)\b|n't\b"
)
#: Sentence boundaries: a full stop, `!` or `?` before a space or the end, `;` or a new line. Not
#: a bare `.` (`this.first.focus()`) nor `:` («retención implícita: se acumulan» is one claim).
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)|[;\n]")


def _fold(text: str) -> str:
    """`text` in lower case without accents: «Retención» and «retencion» compare equal."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _without_fences(answer: str) -> str:
    out: list[str] = []
    in_fence = False
    for line in answer.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence:
            out.append(line)
    return "\n".join(out)


def premise_terms(question: str, content: str) -> list[str]:
    """#538: the nominalizations of `question` whose stem the file does not hold, in order.

    Plain words (not code identifiers: those get their exact occurrences) ending as a
    nominalization (`_NOMINALIZATION`) and not words of asking. The file is searched as a whole,
    comments and strings included, without accents and ignoring case.
    """
    folded = _fold(content)
    names = {_fold(name) for name in identifiers(question)}
    terms: list[str] = []
    stems: set[str] = set()
    for word in _PREMISE_WORD.findall(question):
        folded_word = _fold(word)
        singular = re.sub(r"(?:(?<=[cs]ion)|(?<=dad))es$|(?<=[^s])s$", "", folded_word)
        stem = folded_word[:PREMISE_STEM_LEN]
        if (
            not _NOMINALIZATION.search(singular)
            or stem in stems
            or stem in _QUESTION_STEMS
            or folded_word in names
        ):
            continue
        stems.add(stem)
        if not _held(folded_word, folded):
            terms.append(word)
    return terms


#: A Spanish `c` before `i` that English writes `t`: rotación/rotation, acción/action,
#: inicialización/initialization. Only a variant is added, so it can only remove warnings.
_SOFT_C = re.compile(r"c(?=i)")


def _held(folded_word: str, folded: str) -> bool:
    """Whether the folded file holds the folded word by its first letters, in either language.

    The stem as written (`reten` of retención and retention), the stem with its `ci` written `ti`
    (`rotac` → `rotat`, for `TimedRotatingFileHandler`) and, of that English form, its first four
    letters at the start of a word (`init` of `__init__`, `crea` of `createBackup`).
    """
    english = _SOFT_C.sub("t", folded_word)
    if folded_word[:PREMISE_STEM_LEN] in folded or english[:PREMISE_STEM_LEN] in folded:
        return True
    if english == folded_word:
        return False
    return re.search(r"(?<![^\W\d_])" + re.escape(english[:4]), folded) is not None


def _anchored(sentence: str, question: str, content: str, lines: list[str]) -> bool:
    """Whether `sentence` stands on the code: a cited line that holds what it cites, or a code
    identifier of the sentence that is in the file."""
    result = check(sentence, question, content)
    if result.checked and not result.mismatched:
        return True
    return any(occurrences(lines, name) for name in identifiers(sentence))


def unsupported_premises(
    answer: str, question: str, content: str, truncated: bool = False
) -> list[str]:
    """#538: the words of the question the answer asserts with nothing in the file behind them.

    A word counts when the file does not hold it (`premise_terms`), no sentence of the answer
    that names it denies (`_denies`), and some sentence names it without standing on the code
    (`_anchored`). #553: the denial is judged per word, not per sentence: «no implementa ninguna
    política de retención… La retención es ilimitada» already answers the premise, and its second
    sentence is not a fresh claim. «La retención es implícita» alone asserts it. The word is
    matched by its stem as written or as its English cognate (`rotac`/`rotat`). Fenced code is not
    prose. With `truncated`, as in `check`, the last line is not judged: its citation may be cut
    in half.
    """
    terms = premise_terms(question, content)
    if not terms:
        return []
    if truncated:
        answer = answer.rstrip("\n").rpartition("\n")[0]
    lines = content.split("\n")
    sentences = [s for s in _SENTENCE_END.split(_without_fences(answer)) if s.strip()]
    out: list[str] = []
    for term in terms:
        folded_term = _fold(term)
        stems = {folded_term[:PREMISE_STEM_LEN], _SOFT_C.sub("t", folded_term)[:PREMISE_STEM_LEN]}
        stem = re.compile(r"(?<![^\W\d_])(?:" + "|".join(map(re.escape, sorted(stems))) + ")")
        naming = [s for s in sentences if stem.search(_fold(s))]
        if any(_denies(s) for s in naming):
            continue
        if any(not _anchored(s, question, content, lines) for s in naming):
            out.append(term)
    return out


#: #553: words after «no»/«not» that limit instead of deny: «no solo aplica retención, sino…».
_NOT_ONLY = re.compile(
    r"(?i)\s+(?:s[o\xf3]lo|solamente|[u\xfa]nicamente|only|just|merely|simply)\b"
)
#: Connectors that carry a negation word and deny nothing: «sin embargo», «no obstante».
_CONNECTOR = re.compile(r"(?i)\b(?:sin\s+embargo|no\s+obstante|nonetheless|nevertheless)\b")


def _denies(sentence: str) -> bool:
    """Whether `sentence` holds a negation that denies: not «no solo…» nor «sin embargo».

    The negation may fall anywhere in the sentence that names the word («Respecto a la retención,
    el código no implementa ninguna política de eliminación»): what it denies is not parsed.
    """
    text = _CONNECTOR.sub(" ", sentence)
    return any(not _NOT_ONLY.match(text, m.end()) for m in _NEGATION.finditer(text))


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


# --- #568: line numbers in `local_extract` -----------------------------------------------------
# `local_extract` had no way to answer "which lines": the model never saw a line number. With
# `path` and a field that asks for lines, it now sees `N| line` like `local_explain_code` (#460);
# these helpers decide when (by the field names), give a Markdown outline the model can filter,
# and check the lines the model cites in those fields.

#: Words of a field name that ask for file lines by themselves (plural, or the `lineno` of code).
_LINES_WORDS = frozenset({"lines", "lineas", "lineno", "linenos"})
#: The singular asks for file lines only next to one of `_LINE_QUALIFIERS` (`line_number`,
#: `start_line`, `lineRange`): alone it is ordinary data (`line_items`, `address_line`).
_LINE_WORDS = frozenset({"line", "linea"})
_LINE_QUALIFIERS = frozenset(
    {
        "number", "numbers", "numero", "numeros", "num", "no", "nr",
        "start", "end", "inicio", "fin", "range", "ranges", "rango", "rangos",
    }
)  # fmt: skip
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_FIELD_WORD = re.compile(r"[a-z0-9]+")


def is_location_field(name: str) -> bool:
    """Whether the field `name` asks for file lines: `sections_with_lines`, `lineRange`.

    Deterministic, on the name only: it is split into words (camelCase, `_`, `-`, spaces and any
    other non-alphanumeric) and folded (lower case, no accents, so `líneas` is `lineas`). It asks
    for lines if a word is in `_LINES_WORDS`, or if `line`/`linea` comes with a word of
    `_LINE_QUALIFIERS`. Narrow on purpose: `location`, `position`, `offset`, `price_range`,
    `line_items` or `pipeline` are ordinary data fields, and a false positive changes their prompt.
    """
    words = set(_FIELD_WORD.findall(_fold(_CAMEL_BOUNDARY.sub(" ", name))))
    return bool(words & _LINES_WORDS) or bool(words & _LINE_WORDS and words & _LINE_QUALIFIERS)


#: An ATX heading: up to 3 spaces, 1 to 6 `#`, then a blank and some text. No trailing group: the
#: heading is the stripped line, so nothing can backtrack on a long line.
_ATX_HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+\S")


def markdown_outline(content: str) -> list[tuple[int, str]]:
    """(line, heading) of each ATX heading of `content` outside fenced code blocks.

    Lines counted from 1 and split only on `\\n`, like `_number_lines` and `Read`; the heading is
    the stripped line, `#` included, so its level shows.
    """
    out: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(content.split("\n"), 1):
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and _ATX_HEADING.match(line):
            out.append((number, line.strip()))
    return out


#: Keys of an extracted object whose number is a line bound: `{"heading": ..., "start": 12}`.
_BOUND_KEYS = frozenset(
    {
        "start", "end", "from", "to", "first", "last", "begin", "inicio", "fin", "desde", "hasta",
        "line", "linea", "lines", "lineas",
    }
)  # fmt: skip
#: A bare range in a value: `120-160`, `120 – 160`. The lookarounds leave out the parts of a
#: longer dashed form (a date `2026-11-04`).
_VALUE_RANGE = re.compile(r"(?<![\w.\-–])(\d{1,6})\s*[-–]\s*(\d{1,6})(?![\w.\-–])")
#: `Name: 120` in a value, the "name: line" form.
_VALUE_COLON = re.compile(r":\s*(\d{1,6})(?![\w.:\-–])")

_Span = tuple[int, int]


def _text_spans(text: str) -> list[_Span]:
    spans: list[_Span] = []
    for m in _KEYWORD.finditer(text):
        spans.extend(_ranges(m.group(1)))
    for m in _L_FORM.finditer(text):
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        spans.append((min(start, end), max(start, end)))
    spans.extend((int(m.group(1)),) * 2 for m in _PREFIX_FORM.finditer(text))
    for m in _VALUE_RANGE.finditer(text):
        start, end = int(m.group(1)), int(m.group(2))
        spans.append((min(start, end), max(start, end)))
    spans.extend((int(m.group(1)),) * 2 for m in _VALUE_COLON.finditer(text))
    bare = text.strip()
    if not spans and bare.isascii() and bare.isdecimal() and len(bare) <= 6:  # not `²`
        spans.append((int(bare),) * 2)
    return list(dict.fromkeys(spans))


def _words(text: str) -> tuple[str, ...]:
    """What an item names: its plain words of 4+ letters and its code-like identifiers."""
    found = [*_PLAIN_WORD.findall(text), *identifiers(text)]
    return tuple(
        w
        for w in dict.fromkeys(found)
        if w.lower() not in _COMMON
        and not _CITATION_WORD.fullmatch(w)
        and _fold(w) not in _BOUND_KEYS  # "desde 120 hasta 160" names nothing
    )


def _is_number(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _items(value: object, context: str = "") -> list[tuple[str, list[_Span]]]:
    """(what the item names, the line spans it cites) of each item of an extracted value."""
    if _is_number(value):
        return [(context, [(value, value)])]  # type: ignore[list-item]
    if isinstance(value, str):
        return [(f"{context} {line}", _text_spans(line)) for line in value.split("\n")]
    if isinstance(value, list):
        if len(value) == 2 and all(_is_number(v) for v in value):  # `[start, end]`
            return [(context, [(min(value), max(value))])]  # type: ignore[type-var]
        return [item for element in value for item in _items(element, context)]
    if not isinstance(value, dict):
        return []
    bounds = {k: v for k, v in value.items() if isinstance(k, str) and _is_bound_key(k)}
    if not bounds:
        # A map name -> lines (`{"Button": "120-160"}`): each pair is an item named by its key.
        return [item for k, v in value.items() for item in _items(v, f"{context} {k}")]
    # An object with line keys is one item; its other scalar values say what it names.
    names = " ".join(str(v) for k, v in value.items() if k not in bounds and isinstance(v, str))
    numbers = [v for v in bounds.values() if _is_number(v)]
    numbers += [n for v in bounds.values() if isinstance(v, list) for n in v if _is_number(n)]
    spans = [span for v in bounds.values() if isinstance(v, str) for span in _text_spans(v)]
    if numbers:
        spans.append((min(numbers), max(numbers)))
    return [(f"{context} {names}", spans)]


def _is_bound_key(key: str) -> bool:
    return _fold(key) in _BOUND_KEYS or is_location_field(key)


def check_values(value: object, content: str) -> list[Citation]:
    """#568: the line citations of an extracted location value that do not hold in `content`.

    Each item of the value (a line of a string, an element of a list, an object with line keys,
    a pair of a name -> lines map) cites spans (`líneas 120-160`, `L120`, `120| …`, `name: 120`,
    `120-160`, `{"start": 120, "end": 160}`). A span outside the file never holds; one inside
    holds if its lines, or one around them (`TOLERANCE`), contain, ignoring case and accents, a
    word the item names. An item that names nothing is checked only against the file length.
    """
    lines = content.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    total = len(lines)
    mismatched: list[Citation] = []
    seen: set[tuple[_Span, tuple[str, ...]]] = set()
    for text, spans in _items(value):
        words = _words(text)
        folded_words = [_fold(w) for w in words]
        for start, end in spans:
            if ((start, end), words) in seen:
                continue
            seen.add(((start, end), words))
            citation = Citation(start, end, (), words)
            if start < 1 or end > total:
                mismatched.append(citation)
                continue
            if not folded_words:
                continue
            low = max(start - TOLERANCE, 1)
            window = _fold("\n".join(lines[low - 1 : min(end + TOLERANCE, total)]))
            if not any(w in window for w in folded_words):
                mismatched.append(citation)
    return mismatched
