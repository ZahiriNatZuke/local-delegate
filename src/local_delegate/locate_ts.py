"""Index of a TS/JS file for `locate` (REQ-004): its declarations and their exact lines.

A small lexer and a shallow parser, no dependency and no execution: the lexer skips strings,
template literals with nested `${}`, comments and regex literals, so a brace inside any of them
never moves an end; the parser reads, at module level, `function`, `class`, `interface`, `enum`,
`type X =` and `const|let|var x =` (with `export`, `export default`, `declare`, decorators), and
the members of each class (methods, accessors, properties). A range starts at the declaration or
its first decorator, never at the JSDoc or any comment before it, and ends at the brace or the
semicolon that closes it. If the braces do not balance (or a comment or template never ends), the
file gets no index: `index_typescript` says `"unbalanced"`.

Every regular expression here is linear: its alternatives start with different characters.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

#: One entry: (name, kind, first line, last line, top_level). `locate` turns it into a `Block`.
Entry = tuple[str, str, int, int, bool]

_STRING = {
    "'": re.compile(r"'(?:[^'\\\n]|\\[\s\S])*'"),
    '"': re.compile(r'"(?:[^"\\\n]|\\[\s\S])*"'),
}
#: The body of a template literal up to its closing backtick or its next `${`.
_TEMPLATE_BODY = re.compile(r"(?:[^`\\$]|\\[\s\S]|\$(?!\{))*")
_REGEX = re.compile(r"/(?![*/])(?:[^\\/\[\n]|\\.|\[(?:[^\]\\\n]|\\.)*\])+/[A-Za-z]*")
#: After one of these words an expression starts, so a `/` opens a regex.
_EXPRESSION_KEYWORDS = frozenset(
    {
        "return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case",
        "do", "else", "yield", "await",
    }
)  # fmt: skip


#: One match for the common tokens with the blanks before them (1): (2) a word, (3) a number or
#: (4) a punctuator other than the ones the lexer reads by hand (`/`, quotes, backtick, braces);
#: or (5) only blanks, before one of those. The blanks are possessive (`\s*+`): a word may start
#: with a Unicode blank such as U+00A0, and giving one back would read it as a word, where the
#: lexer must skip it as a blank. The token alternatives start with different characters, so it
#: stays linear.
_SIMPLE = re.compile(
    r"(\s*+)(?:"
    r"([A-Za-z_$\u00a0-\uffff][\w$\u00a0-\uffff]*)"
    r"|(\.?\d[\w.]*)"
    r"|(===|!==|\.\.\.|=>|==|!=|<=|>=|\?\.|\?\?|&&|\|\||[^\s/'\"`{}])"
    r")|(\s+)"
)
_SIMPLE_KINDS = {2: "id", 3: "num", 4: "p"}


@dataclass(slots=True)
class _Token:
    kind: str  # "id" | "num" | "str" | "tpl" | "re" | "p"
    text: str
    start: int
    end: int
    newline_before: bool


class _Unbalanced(Exception):
    pass


def _regex_allowed(tokens: list[_Token]) -> bool:
    if not tokens:
        return True
    prev = tokens[-1]
    if prev.kind == "p":
        # `<` before `/` is a JSX closing tag (`</div>`), not a regex.
        return prev.text not in (")", "]", "}", "<")
    if prev.kind == "id":
        return prev.text in _EXPRESSION_KEYWORDS
    if prev.kind == "tpl":
        return prev.text.endswith("${")
    return False


def _tokenize(src: str) -> tuple[list[_Token], list[tuple[int, int]]]:
    """Tokens of `src` (no comments) and the (start, end) offsets of its comments."""
    tokens: list[_Token] = []
    comments: list[tuple[int, int]] = []
    braces: list[str] = []  # "{" for a brace, "${" for the expression of a template
    n = len(src)
    i = 0
    newline = False

    def add(kind: str, start: int, end: int) -> None:
        nonlocal newline
        tokens.append(_Token(kind, src[start:end], start, end, newline))
        newline = False

    def template(start: int, body_from: int) -> int:
        """Scan a template chunk from `body_from`; returns where the lexer goes on."""
        m = _TEMPLATE_BODY.match(src, body_from)
        j = m.end()
        if j >= n:
            raise _Unbalanced
        if src[j] == "`":
            add("tpl", start, j + 1)
            return j + 1
        add("tpl", start, j + 2)  # ends with "${"
        braces.append("${")
        return j + 2

    simple = _SIMPLE.match
    append = tokens.append
    while i < n:
        m = simple(src, i)
        if m:  # the common tokens in one match, with the blanks before them
            group = m.lastindex
            j = m.end()
            if group == 5:
                if "\n" in m.group(5):
                    newline = True
            else:
                blanks = m.group(1)
                if blanks and "\n" in blanks:
                    newline = True
                append(_Token(_SIMPLE_KINDS[group], m.group(group), m.start(group), j, newline))
                newline = False
            i = j
            continue
        c = src[i]
        if c == "/":
            nxt = src[i + 1 : i + 2]
            if nxt == "/":
                j = src.find("\n", i)
                j = n if j < 0 else j
                comments.append((i, j))
                i = j
                continue
            if nxt == "*":
                j = src.find("*/", i + 2)
                if j < 0:
                    raise _Unbalanced
                comments.append((i, j + 2))
                if "\n" in src[i:j]:
                    newline = True
                i = j + 2
                continue
            if _regex_allowed(tokens):
                m = _REGEX.match(src, i)
                if m:
                    add("re", i, m.end())
                    i = m.end()
                    continue
            add("p", i, i + 1)
            i += 1
            continue
        if c in _STRING:
            m = _STRING[c].match(src, i)
            if m:
                add("str", i, m.end())
                i = m.end()
            else:  # a quote that does not close on its line (JSX text: «don't»): one mark
                add("p", i, i + 1)
                i += 1
            continue
        if c == "`":
            i = template(i, i + 1)
            continue
        if c == "{":
            braces.append("{")
            add("p", i, i + 1)
            i += 1
            continue
        if c == "}":
            if not braces:
                raise _Unbalanced
            if braces.pop() == "${":
                i = template(i, i + 1)
                continue
            add("p", i, i + 1)
            i += 1
            continue
        add("p", i, i + 1)  # not reached: `_SIMPLE` takes any other character
        i += 1
    if braces:
        raise _Unbalanced
    return tokens, comments


_OPEN = {"(": ")", "[": "]", "{": "}"}
_CLOSE = frozenset(_OPEN.values())
#: A `{` right after one of these opens a type (`): { a: number } {`), not a body.
_TYPE_BEFORE_BRACE = frozenset(
    {":", "|", "&", "<", ",", "=>", "=", "?", "keyof", "typeof", "extends"}
)
#: A line that ends with one of these goes on in the next line.
_GOES_ON = frozenset(
    {
        "=", "=>", ",", "(", "[", "{", "+", "-", "*", "/", "%", "&", "|", "^", "!", "~", "?", ":",
        "<", "&&", "||", "??", ".", "?.", "==", "===", "!=", "!==", "<=", ">=", "extends",
        "instanceof", "in", "of", "typeof", "keyof", "new", "as", "satisfies",
    }
)  # fmt: skip
#: A line that starts with one of these continues the line before.
_CONTINUES = frozenset(
    {
        ".", "?.", ")", "]", "}", ",", "=>", "*", "/", "%", "&&", "||", "??", "|", "&", "?", ":",
        "=", "==", "===", "!=", "!==", "<=", ">=", "as", "satisfies", "extends", "instanceof",
        "in", "implements",
    }
)  # fmt: skip
#: A word that starts a declaration on its line, so the one before has ended.
_STARTS_DECLARATION = frozenset(
    {
        "export", "import", "const", "let", "var", "function", "class", "interface", "type",
        "enum", "declare", "abstract", "async", "@", "public", "private", "protected", "static",
        "readonly", "namespace", "module",
    }
)  # fmt: skip
_MODULE_MODIFIERS = frozenset({"export", "default", "declare", "abstract"})
_MEMBER_MODIFIERS = frozenset(
    {
        "public", "private", "protected", "static", "readonly", "abstract", "override", "declare",
        "async", "get", "set", "accessor",
    }
)  # fmt: skip
#: After a member name, one of these says the name is the member, not a modifier.
_AFTER_MEMBER_NAME = frozenset({"(", "=", ":", ";", "?", "!", "<", "}"})
_FUNCTION_CALLS = frozenset({"computed", "signal", "effect"})


class _Parser:
    def __init__(self, src: str, tokens: list[_Token]) -> None:
        self.tokens = tokens
        self.texts = [tok.text for tok in tokens]
        self.count = len(tokens)
        self.line_starts = [0] + [m.end() for m in re.finditer("\n", src)]
        self.match = self._match_brackets()
        self.entries: list[Entry] = []

    def _match_brackets(self) -> dict[int, int]:
        out: dict[int, int] = {}
        stack: list[int] = []
        for k, tok in enumerate(self.tokens):
            if tok.kind != "p":
                continue
            if tok.text in _OPEN:
                stack.append(k)
            elif tok.text in _CLOSE:
                if not stack or _OPEN[self.tokens[stack[-1]].text] != tok.text:
                    raise _Unbalanced
                out[stack.pop()] = k
        if stack:
            raise _Unbalanced
        return out

    # --- lines and token helpers -------------------------------------------------------------

    def line_of(self, offset: int) -> int:
        return bisect.bisect_right(self.line_starts, offset)

    def first_line(self, k: int) -> int:
        return self.line_of(self.tokens[k].start)

    def last_line(self, k: int) -> int:
        tok = self.tokens[k]
        return self.line_of(max(tok.end - 1, tok.start))

    def text(self, k: int) -> str:
        return self.texts[k] if 0 <= k < self.count else ""

    def kind(self, k: int) -> str:
        return self.tokens[k].kind if 0 <= k < self.count else ""

    def is_open(self, k: int) -> bool:
        tok = self.tokens[k]
        return tok.kind == "p" and tok.text in _OPEN

    def is_close(self, k: int) -> bool:
        tok = self.tokens[k]
        return tok.kind == "p" and tok.text in _CLOSE

    # --- ends ----------------------------------------------------------------------------------

    def statement_end(self, k: int, limit: int) -> int:
        """The last token of the statement or member that goes on at `k` (before `limit`)."""
        last = k
        while k < limit:
            if self.is_close(k):  # the group that holds the statement closes
                return last
            if self.kind(k) == "p" and self.text(k) == ";":
                return k
            current = self.match[k] if self.is_open(k) else k
            last = current
            nxt = current + 1
            if nxt >= limit:
                return last
            if self.tokens[nxt].newline_before:
                ends = self.text(current) not in _GOES_ON or self.text(nxt) in _STARTS_DECLARATION
                if ends and self.text(nxt) not in _CONTINUES:
                    return last
            k = nxt
        return last

    def body_or_end(self, k: int, limit: int) -> tuple[int | None, int]:
        """From `k`, the body `{` of a declaration (or None) and its last token."""
        while k < limit:
            tok = self.tokens[k]
            if tok.kind == "p" and tok.text == "{":
                if self.text(k - 1) in _TYPE_BEFORE_BRACE:
                    k = self.match[k] + 1
                    continue
                return k, self.match[k]
            if self.is_open(k):
                k = self.match[k] + 1
                continue
            if self.is_close(k):
                return None, k - 1
            if tok.kind == "p" and tok.text == ";":
                return None, k
            k += 1
        return None, limit - 1

    def skip_decorator(self, k: int) -> int:
        k += 1  # "@"
        if self.kind(k) == "id":
            k += 1
            while self.text(k) == "." and self.kind(k + 1) == "id":
                k += 2
            if self.kind(k) == "p" and self.text(k) == "(":
                k = self.match[k] + 1
        return k

    def initializer_kind(self, k: int, end: int, function_kind: str, other_kind: str) -> str:
        """The kind of a declaration whose initializer starts at token `k` (after `=`)."""
        if self.text(k) == "async":
            k += 1
        if self.text(k) == "function":
            return function_kind
        if self.text(k) in _FUNCTION_CALLS and self.text(k + 1) in ("(", "<"):
            return "function_property" if function_kind == "function_property" else other_kind
        j = k
        while j <= end:
            if self.is_open(j):
                j = self.match[j] + 1
                continue
            if self.text(j) == "=>":
                return function_kind
            j += 1
        return other_kind

    def params_then_body(self, k: int, limit: int) -> int:
        """From a name, past its generics and parameters to the end of its body or `;`."""
        while k < limit and not (self.text(k) == "(" and self.tokens[k].kind == "p"):
            if self.text(k) in ("{", ";", "}"):
                break
            if self.is_open(k):
                k = self.match[k] + 1
                continue
            k += 1
        if k < limit and self.text(k) == "(":
            k = self.match[k] + 1
        _body, end = self.body_or_end(k, limit)
        return end

    # --- module ------------------------------------------------------------------------------

    def parse_module(self) -> None:
        tokens = self.tokens
        k = 0
        n = len(tokens)
        while k < n:
            starts = k == 0 or self.text(k - 1) in (";", "}") or tokens[k].newline_before
            if starts:
                nxt = self.declaration(k, n)
                if nxt is not None:
                    k = nxt
                    continue
            if self.is_open(k):
                k = self.match[k] + 1
                continue
            k += 1

    def declaration(self, k: int, limit: int) -> int | None:
        """Parse a module-level declaration at `k`; the next token, or None if it is not one."""
        first = k
        while self.text(k) == "@" and k < limit:
            k = self.skip_decorator(k)
        while self.text(k) in _MODULE_MODIFIERS and k < limit:
            k += 1
        word = self.text(k)
        if word == "async" and self.text(k + 1) == "function":
            k += 1
            word = "function"
        start_line = self.first_line(first)
        if word == "function":
            k += 1
            if self.text(k) == "*":
                k += 1
            name = self.text(k) if self.kind(k) == "id" else "default"
            end = self.params_then_body(k, limit)
            self.entries.append((name, "function", start_line, self.last_line(end), True))
            return end + 1
        if word == "class":
            k += 1
            name = self.text(k) if self.kind(k) == "id" else "default"
            if name in ("extends", "implements"):
                name = "default"
            body, end = self.body_or_end(k, limit)
            self.entries.append((name, "class", start_line, self.last_line(end), True))
            if body is not None:
                self.class_members(name, body + 1, end)
            return end + 1
        if word in ("interface", "enum") or (word == "const" and self.text(k + 1) == "enum"):
            if word == "const":
                k += 1
            k += 1
            if self.kind(k) != "id":
                return None
            name = self.text(k)
            _body, end = self.body_or_end(k + 1, limit)
            self.entries.append((name, "type", start_line, self.last_line(end), True))
            return end + 1
        if word == "type" and self.kind(k + 1) == "id" and self.text(k + 2) in ("=", "<"):
            name = self.text(k + 1)
            end = self.statement_end(k + 2, limit)
            self.entries.append((name, "type", start_line, self.last_line(end), True))
            return end + 1
        if word in ("const", "let", "var"):
            if self.kind(k + 1) != "id":
                return None  # destructuring
            name = self.text(k + 1)
            end = self.statement_end(k + 1, limit)
            kind = "variable"
            j = k + 2
            while j <= end and self.text(j) != "=":
                j = self.match[j] + 1 if self.is_open(j) else j + 1
            if j <= end:
                kind = self.initializer_kind(j + 1, end, "function", "variable")
            self.entries.append((name, kind, start_line, self.last_line(end), True))
            return end + 1
        return None

    # --- class members -----------------------------------------------------------------------

    def class_members(self, class_name: str, k: int, close: int) -> None:
        while k < close:
            if self.text(k) == ";":
                k += 1
                continue
            first = k
            while self.text(k) == "@" and k < close:
                k = self.skip_decorator(k)
            while (
                k + 1 < close
                and self.text(k) in _MEMBER_MODIFIERS
                and self.text(k + 1) not in _AFTER_MEMBER_NAME
            ):
                k += 1
            if k >= close:
                break
            tok = self.tokens[k]
            name_at = k
            if tok.kind == "p" and tok.text == "{":  # `static { ... }`
                k = self.match[k] + 1
                continue
            if tok.kind == "p" and tok.text == "#" and k + 1 < close:
                name = "#" + self.text(k + 1)
                k += 2
            elif tok.kind == "p" and tok.text == "[":
                name = "[computed]"
                k = self.match[k] + 1
            elif tok.kind in ("id", "str", "num"):
                name = tok.text.strip("'\"")
                k += 1
            else:
                k = max(k + 1, first + 1)
                continue
            while self.text(k) in ("?", "!") and k < close:
                k += 1
            start_line = self.first_line(first)
            full = f"{class_name}.{name}"
            if self.text(k) in ("(", "<"):
                end = self.params_then_body(k, close)
                self.entries.append((full, "method", start_line, self.last_line(end), False))
            else:
                end = self.statement_end(name_at, close)
                kind = "property"
                j = k
                while j <= end and self.text(j) != "=":
                    j = self.match[j] + 1 if self.is_open(j) else j + 1
                if j <= end:
                    kind = self.initializer_kind(j + 1, end, "function_property", "property")
                self.entries.append((full, kind, start_line, self.last_line(end), False))
            k = max(end + 1, first + 1)


def index_typescript(content: str) -> tuple[list[Entry], frozenset[int], str | None]:
    """REQ-004: (entries, whole comment lines, unavailable reason) of a TS/JS `content`."""
    try:
        tokens, comments = _tokenize(content)
        parser = _Parser(content, tokens)
        parser.parse_module()
    except (_Unbalanced, IndexError, KeyError):
        return [], frozenset(), "unbalanced"
    return parser.entries, _comment_lines(content, comments, parser), None


def _comment_lines(
    content: str, comments: list[tuple[int, int]], parser: _Parser
) -> frozenset[int]:
    """The lines a comment covers that hold nothing else but blanks (only those lines are read,
    so the cost follows the comments, not the file)."""
    covered: dict[int, list[tuple[int, int]]] = {}
    for start, end in comments:
        for line in range(parser.line_of(start), parser.line_of(max(end - 1, start)) + 1):
            covered.setdefault(line, []).append((start, end))
    starts = parser.line_starts
    out: set[int] = set()
    for line, spans in covered.items():
        begin = starts[line - 1]
        finish = starts[line] - 1 if line < len(starts) else len(content)
        at = begin
        rest = []
        for start, end in sorted(spans):
            rest.append(content[at : max(at, start)])
            at = max(at, end)
        rest.append(content[at:finish] if at < finish else "")
        if not "".join(rest).strip():
            out.add(line)
    return frozenset(out)
