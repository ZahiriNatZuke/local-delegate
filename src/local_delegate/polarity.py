"""Polarity flips in a `local_extract` answer (#667).

The model sometimes turns an instruction around while it rewrites or translates it: the source
says «revisar el código real del mod, no inferir la respuesta desde las skills» and the field
comes back as «Do not review code real of the mod, do not infer response from the skills». The
negation of the second clause leaked into the first. Nothing in the program adds or removes a
word of a value: the flip is the model's. This module finds it deterministically, from the source
and the answer only, so `local_extract` can WARN about it. It never changes a value.

How a clause of the answer is checked:

- source and value are first cut into blocks: a blank line, a list item (`-`, `*`, `+`, `1.`), a
  heading (`#`), a table cell (`|`, a tab) or a markup tag starts a new one; a single line break
  inside a paragraph does not (a text wrapped at a fixed width keeps «no» with its verb). Blocks
  are cut into sentences at `. ; ! ?` and sentences into clauses at `,` and `:`;
- a clause is reduced to its stems: the first four letters of each content word, folded (no
  accents, lower case), without stopwords or negation words. Four letters is what Spanish and
  English cognates share (`revisar`/`review`, `adaptadores`/`adapters`, `clientes`/`clients`), so
  a translation by the model still finds its source clause;
- the word a negation denies is the first content word after it, compared by its first three
  letters with `qu`/`gu`/`z` folded (`toques`/`toca`, `falla`/`falle`);
- a clause of the answer with at least three stems matches a source clause that holds at least
  60 % of its stems, and at least two that are not the denied word (so «no hay errores en los
  tests» does not match «hay errores en el build»);
- a negation ADDED is flagged when the clause of the answer carries one and no matching source
  clause is under one: its own, one earlier in its sentence («no revises X, los adaptadores»), or
  a heading or a `...:` line with a negation over the list that follows («## No hacer»). The denied
  word must sit in the matched clause, and no negated clause of the same source sentence may hold
  it («revisar el código del mod, no el código de los hooks» is the source of «review the code of
  the mod and not the code of the hooks»);
- a negation REMOVED is flagged when the clause of the answer carries none and every matching
  source clause carries one of its own, whose denied word sits in the answer's clause, and no
  `sin`/`without` after it (a double negation: «no mezclar sin CI verde»).

A clause with no match, or with matches of both polarities, stays quiet: the warning is for a
clear contradiction, never for a doubt. A key whose name carries a negation or a ban
(`no_reintentar`, `do_not_retry`, `forbidden_actions`) is not checked: its values may drop the
negation on purpose. `sin`/`without` are not counted as negations (they are prepositions as often
as not).

Deterministic, standard library only, linear in the input; the regular expressions have no nested
quantifiers.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

#: A source longer than this is not scanned: the warning is a cheap check, never a cost.
MAX_SOURCE_CHARS = 400_000

#: Clause pairs (answer x source) the check may compare before it gives up on the remaining keys.
_BUDGET = 5_000_000

#: Letters of a word that make its stem.
_STEM_LETTERS = 4

#: Letters of the word a negation denies, matched across the two clauses (conjugations differ).
_TARGET_LETTERS = 3

#: A clause of the answer with fewer stems is not checked: too little to tell its source apart.
_MIN_STEMS = 3

#: A source clause matches when it holds at least this many of the answer clause's stems that are
#: not the denied word...
_MIN_SHARED = 2

#: ...and at least this share of all of them.
_MIN_RATIO = 0.6

#: A clause longer than this is cut in the warning: it is text, not the program's.
_LABEL_CHARS = 120

_NEGATIONS = frozenset(
    {
        "no", "not", "never", "nor", "dont", "doesnt", "didnt", "cannot", "cant", "wont",
        "shouldnt", "mustnt", "isnt", "arent", "wasnt", "werent", "neither", "avoid", "avoids",
        "none", "nothing", "nobody", "nunca", "jamas", "ni", "tampoco", "ningun", "ninguno",
        "ninguna", "nadie", "evita", "evitar", "evite", "eviten", "evites",
    }
)  # fmt: skip

#: Words after a negation that turn it into a double one («no mezclar sin CI verde»).
_DOUBLE = frozenset({"sin", "without"})

#: A key name with one of these words (or a word starting with a ban) is not checked.
_BAN_PREFIXES = ("prohib", "forbid", "avoid", "evit", "never", "nunca")

_STOPWORDS = frozenset(
    {
        "a", "al", "de", "del", "el", "la", "las", "los", "lo", "y", "o", "u", "e", "en", "por",
        "para", "con", "sin", "un", "una", "unos", "unas", "que", "se", "su", "sus", "es", "son",
        "desde", "este", "esta", "estos", "estas", "ese", "esa", "como", "mas", "pero", "sino",
        "the", "of", "and", "or", "in", "on", "per", "for", "with", "without", "to", "an", "by",
        "at", "is", "are", "be", "from", "this", "that", "these", "those", "it", "its", "as",
        "do", "does", "did", "but", "into", "any",
    }
)  # fmt: skip

_APOSTROPHES = re.compile(r"['’]")
_WORD = re.compile(r"[a-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
#: A markup tag ends a block: `<td>No incluido</td><td>Incluido</td>` are two cells.
_TAG = re.compile(r"<[^<>]{0,200}>")
#: A table cell ends a block too: «No incluido» and «Incluido» share a row.
_CELL = re.compile(r"[|\t]")
#: A line that starts a block of its own: a list item or a heading.
_BLOCK_START = re.compile(r"\s{0,12}(?:[-*+]\s|\d{1,3}[.)]\s|#)")
_HEADING = re.compile(r"\s{0,3}#")
_SENTENCE = re.compile(r"[.;!?]")
_CLAUSE = re.compile(r"[,:]")


def _words(text: str) -> list[str]:
    """Folded words: no accents, lower case, `don't` as `dont`."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return _WORD.findall(_APOSTROPHES.sub("", text.lower()))


def _content(word: str) -> bool:
    return word not in _NEGATIONS and word not in _STOPWORDS and len(word) > 2


def _prefix(word: str) -> str:
    """The short prefix of a denied word, with the spelling changes of a Spanish conjugation
    folded (`toca`/`toques`, `llega`/`llegues`, `empieza`/`empieces`)."""
    return word.replace("qu", "c").replace("gu", "g").replace("z", "c")[:_TARGET_LETTERS]


class _Clause:
    __slots__ = (
        "denied_stems", "double", "negated", "prefixes", "scoped", "sentence", "stems", "targets",
        "text",
    )  # fmt: skip

    def __init__(self, text: str, scoped: bool = False, sentence: int = 0) -> None:
        words = _words(text)
        self.text = text.strip()
        self.sentence = sentence
        self.negated = any(word in _NEGATIONS for word in words)
        # A negation here, earlier in the same sentence or over the block (source clauses only).
        self.scoped = scoped or self.negated
        self.stems = frozenset(word[:_STEM_LETTERS] for word in words if _content(word))
        self.prefixes = frozenset(_prefix(word) for word in words if _content(word))
        # What each negation denies: the next content word. One pass from the right keeps it
        # linear however many negations the clause has.
        targets: set[str] = set()
        denied: set[str] = set()
        double = False
        following: str | None = None
        seen_double = False
        for word in reversed(words):
            if word in _NEGATIONS:
                if following is not None:
                    targets.add(_prefix(following))
                    denied.add(following[:_STEM_LETTERS])
                double = double or seen_double
            elif word in _DOUBLE:
                seen_double = True
            elif _content(word):
                following = word
        self.targets = frozenset(targets)
        self.denied_stems = frozenset(denied)
        self.double = double


def _blocks(text: str) -> list[tuple[str, bool]]:
    """`(block, under a negated heading or `...:` line)`; see the module docstring."""
    text = _TAG.sub("\n\n", text.replace("\\n", "\n"))
    blocks: list[tuple[str, bool]] = []
    current: list[str] = []
    heading_scope = False
    list_scope = False

    def close() -> None:
        if current:
            blocks.append((" ".join(current), heading_scope or list_scope))
            current.clear()

    for line in text.split("\n"):
        cells = _CELL.split(line)
        if len(cells) > 1:
            close()
            blocks.extend((cell, heading_scope or list_scope) for cell in cells if cell.strip())
            continue
        if not line.strip():
            close()
            continue
        if _BLOCK_START.match(line):
            close()
            if _HEADING.match(line):
                list_scope = False
                negated = any(word in _NEGATIONS for word in _words(line))
                blocks.append((line, negated))
                heading_scope = negated
                continue
        elif not current:
            # A plain paragraph after the list ends the scope of its `...:` line.
            list_scope = False
        current.append(line.strip())
        if line.rstrip().endswith(":"):
            close()
            # The `...:` line itself keeps its own polarity; its negation covers what follows.
            list_scope = any(word in _NEGATIONS for word in _words(line))
    close()
    return blocks


def _clauses(text: str) -> list[_Clause]:
    out: list[_Clause] = []
    sentence = 0
    for block, block_scoped in _blocks(text):
        for piece in _SENTENCE.split(block):
            sentence += 1
            scoped = block_scoped
            for part in _CLAUSE.split(piece):
                if not part.strip():
                    continue
                clause = _Clause(part, scoped, sentence)
                scoped = clause.scoped
                if clause.stems:
                    out.append(clause)
    return out


def _leaves(value: Any) -> list[str]:
    """The strings of a value, also inside lists and objects."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [leaf for item in value for leaf in _leaves(item)]
    if isinstance(value, dict):
        return [leaf for item in value.values() for leaf in _leaves(item)]
    return []


def _banned_key(name: str) -> bool:
    words = _words(_CAMEL.sub(" ", name).replace("_", " ").replace("-", " "))
    return any(word in _NEGATIONS or word.startswith(_BAN_PREFIXES) for word in words)


def _cut(text: str) -> str:
    return text if len(text) <= _LABEL_CHARS else text[: _LABEL_CHARS - 1] + "…"


def _matches(clause: _Clause, source: list[_Clause], denied: frozenset[str]) -> list[_Clause]:
    need = _MIN_RATIO * len(clause.stems)
    out = []
    for candidate in source:
        shared = clause.stems & candidate.stems
        if len(shared) >= need and len(shared - denied - candidate.denied_stems) >= _MIN_SHARED:
            out.append(candidate)
    return out


def _flip(clause: _Clause, source: list[_Clause]) -> tuple[str, _Clause] | None:
    """`("added"|"removed", source clause)` when the clause contradicts every source clause it
    matches; None when it matches none, or matches one of its own polarity."""
    matches = _matches(clause, source, clause.denied_stems)
    if not matches:
        return None
    if clause.negated:
        if any(c.scoped for c in matches):
            return None
        # The denied word must be in the source clause, and in no negated clause of its sentence.
        sentences = {c.sentence for c in matches}
        negated_near = [c for c in source if c.sentence in sentences and c.scoped]
        if any(clause.targets & c.prefixes for c in negated_near):
            return None
        matches = [c for c in matches if clause.targets & c.prefixes]
        kind = "added"
    elif clause.scoped:
        # A negation earlier in the answer's own sentence covers this clause.
        return None
    else:
        if not all(c.negated for c in matches):
            return None
        matches = [c for c in matches if c.targets & clause.prefixes and not c.double]
        kind = "removed"
    if not matches:
        return None
    best = max(matches, key=lambda c: len(clause.stems & c.stems))
    return kind, best


def flipped(
    source: str, fields: list[str], data: dict, skip: list[str] | tuple[str, ...] = ()
) -> dict[str, dict]:
    """`{key: {"value": clause, "source": clause, "flip": "added"|"removed"}}` for each requested
    key with a clause whose negation the source does not carry, or whose source negation it
    lost (the first such clause). `skip` are keys not to check (the location fields). Empty when
    nothing is flagged, the source is too big, or anything fails: a warning never breaks the
    answer."""
    if not source or len(source) > MAX_SOURCE_CHARS:
        return {}
    try:
        return _scan(source, fields, data, frozenset(skip))
    except Exception:
        # The boundary: whatever the source or the answer, a warning never breaks the answer.
        return {}


def _scan(source: str, fields: list[str], data: dict, skip: frozenset[str]) -> dict[str, dict]:
    clauses = _clauses(source)
    if not clauses:
        return {}
    budget = _BUDGET
    flagged: dict[str, dict] = {}
    for name in dict.fromkeys(fields):
        if not isinstance(name, str) or name in skip or _banned_key(name):
            continue
        for leaf in _leaves(data.get(name)):
            for clause in _clauses(leaf):
                if len(clause.stems) < _MIN_STEMS:
                    continue
                budget -= len(clauses)
                if budget < 0:
                    return flagged
                found = _flip(clause, clauses)
                if found is not None:
                    kind, match = found
                    flagged[name] = {
                        "value": _cut(clause.text),
                        "source": _cut(match.text),
                        "flip": kind,
                    }
                    break
            if name in flagged:
                break
    return flagged
