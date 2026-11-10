"""#630: check, by program, a `local_summarize` answer against its input.

The mechanical model summarized short Markdown files with tables and wrote data the file does not
hold: an acronym expansion of its own («SDD (Sistema de Diagnóstico Dinámico)»), a word of another
language («deviações» in a Spanish summary, where the file says «Deviations») and, in a case of the
same family (#586), a figure the table does not hold. None of that came with a warning.

So, after the answer, with the whole input at hand, three things are looked for in the summary:

- an acronym written next to an expansion in parentheses (`ACR (Words)` or `Words (ACR)`), whose
  words spell the acronym, when the input does not hold that expansion;
- a figure (a run of digits, with decimals or thousands groups) that the input does not hold in
  any spelling: `2 862`, `2862`, `2,5`, `2.5` and the small numbers written as words (`tres`)
  count as the same figure; digits glued to a letter or a hyphen (`gemma3-4b`, `M1`, `E501`, a
  date) are names, not figures, and a list marker (`1.` at the start of a line) is not one;
- a word with a letter outside the alphabet of the summary's language (`ç`, `ã`, `ê`… in a Spanish
  summary; any accent in an English one) that the input does not hold.

Text in backticks is left out: it is copied code. Only a warning comes from this: the summary is
not changed, because a figure may be computed (a percentage) and an expansion may be right; the
caller is told what to check against the source.

Pure functions over strings, linear in the length of the text: the input is not trusted, so no
pattern here can backtrack on it.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field

__all__ = ["Findings", "check"]

#: Items named per kind in the warning; the rest are counted out.
MAX_ITEMS = 5

#: Words an expansion may hold that do not give a letter to the acronym.
_CONNECTORS = frozenset(
    {"de", "del", "la", "las", "los", "el", "y", "e", "en", "para", "por", "con", "a", "al"}
    | {"of", "the", "and", "for", "to", "on", "in"}
)

#: The letters each summary language writes with. A language not here is not judged.
_ALPHABETS: dict[str, frozenset[str]] = {
    "es": frozenset("abcdefghijklmnopqrstuvwxyzáéíóúüñ"),
    "en": frozenset("abcdefghijklmnopqrstuvwxyz"),
}

#: The small numbers written as words, in the two languages, so «tres fixtures» holds a 3.
_SPANISH_NUMBERS = (
    "cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince "
    "dieciséis diecisiete dieciocho diecinueve veinte"
)
_ENGLISH_NUMBERS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty"
)
_NUMBER_WORDS: dict[str, str] = {
    word: str(value)
    for words in (_SPANISH_NUMBERS, _ENGLISH_NUMBERS)
    for value, word in enumerate(words.split())
}
_NUMBER_WORDS.update({"una": "1", "un": "1"})

_CODE_SPAN = re.compile(r"`[^`\n]*`")
_LIST_MARKER = re.compile(r"^[ \t]*\d+[.)][ \t]", re.MULTILINE)
#: A figure: digits with decimals or groups, not glued to a letter, a digit, `_` or `-`.
_FIGURE = re.compile(r"(?<![\w.,-])\d+(?:[.,]\d+)*(?![\w-])")
#: Digits grouped by thousands with a blank (`2 862`, also the narrow no-break space).
_GROUPED = re.compile(r"(?<![\w.,])\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?![\w.,])")
_BLANKS = re.compile(r"[ \u00a0\u202f]")
#: Any run of digits in the input, glued to a name or not (`v0.2`, `gemma3`): what it holds.
_DIGITS = re.compile(r"\d+(?:[.,]\d+)*")
_WORD = re.compile(r"[^\W\d_]+")
#: `ACR (words)`: the acronym, then its expansion in parentheses.
_ACRONYM_FIRST = re.compile(r"\b([A-Z][A-Z0-9]{1,7})s?[ \t]*\(([^()\n]{3,120})\)")
#: `words (ACR)`: the expansion before, the acronym in parentheses.
_ACRONYM_LAST = re.compile(r"\(([A-Z][A-Z0-9]{1,7})s?\)")
#: Characters before `(ACR)` looked at for its expansion.
_LOOKBACK_CHARS = 200


@dataclass
class Findings:
    """What a summary holds that its input does not, in the order of the summary."""

    acronyms: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    foreign_words: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.acronyms or self.numbers or self.foreign_words)


def check(summary: str, source: str, *, language: str, figures: bool = True) -> Findings:
    """The acronym expansions, figures and foreign words of `summary` that `source` does not hold.

    `language` is the language the summary is written in (`es`, `en`); for another one the word
    check is skipped, since its alphabet is not known here. `figures=False` skips the figures: the
    tool judges them only on an input with a table (see `local_summarize`).
    """
    text = _CODE_SPAN.sub(" ", summary)
    source_words = [w.lower() for w in _WORD.findall(source)]
    return Findings(
        acronyms=_ungrounded_acronyms(text, " " + " ".join(source_words) + " "),
        numbers=_ungrounded_figures(text, source, source_words) if figures else [],
        foreign_words=_foreign_words(text, set(source_words), language),
    )


def _spells(acronym: str, words: list[str]) -> bool:
    """Whether the words that are not connectors start with the letters of `acronym`, in order."""
    letters = [w[0].upper() for w in words if w.lower() not in _CONNECTORS]
    return len(letters) == len(acronym) and "".join(letters) == acronym


def _ungrounded_acronyms(text: str, source_joined: str) -> list[str]:
    found: list[str] = []

    def _judge(acronym: str, words: list[str], shown: str) -> None:
        if not words or not _spells(acronym, words):
            return
        expansion = " " + " ".join(w.lower() for w in words) + " "
        if expansion not in source_joined and shown not in found:
            found.append(shown)

    for match in _ACRONYM_FIRST.finditer(text):
        acronym, inner = match.group(1), match.group(2)
        words = _WORD.findall(inner)
        _judge(acronym, words, f"{acronym} ({inner.strip()})")
    for match in _ACRONYM_LAST.finditer(text):
        acronym = match.group(1)
        if not acronym.isalpha():
            continue
        before = _WORD.findall(text[max(0, match.start() - _LOOKBACK_CHARS) : match.start()])
        # The shortest tail of the words before that spells the acronym, connectors aside.
        for start in range(len(before) - 1, max(-1, len(before) - 3 * len(acronym) - 1), -1):
            tail = before[start:]
            if tail[0].lower() in _CONNECTORS:
                continue
            if _spells(acronym, tail):
                _judge(acronym, tail, f"{' '.join(tail)} ({acronym})")
                break
    return found


def _figure_forms(raw: str) -> set[str]:
    """The spellings a figure is the same figure in: `2,5` and `2.5`; `2 862`, `2.862`, `2862`."""
    compact = _BLANKS.sub("", raw)
    forms = {compact, compact.replace(",", ".")}
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", compact):
        forms.add(re.sub(r"[.,]", "", compact))
    return forms


def _ungrounded_figures(text: str, source: str, source_words: list[str]) -> list[str]:
    held: set[str] = set()
    for pattern in (_DIGITS, _GROUPED):
        for match in pattern.finditer(source):
            held |= _figure_forms(match.group())
    held.update(_NUMBER_WORDS[w] for w in source_words if w in _NUMBER_WORDS)
    text = _LIST_MARKER.sub(" ", text)
    grouped = [(m.start(), m.end(), m.group()) for m in _GROUPED.finditer(text)]
    starts = [start for start, _end, _raw in grouped]
    figures = list(grouped)
    for match in _FIGURE.finditer(text):
        # A figure inside a grouped one (`862` of `2 862`) is judged with it, not on its own.
        i = bisect.bisect_right(starts, match.start()) - 1
        if i >= 0 and grouped[i][1] >= match.end():
            continue
        figures.append((match.start(), match.end(), match.group()))
    found: list[str] = []
    for _start, _end, raw in sorted(figures):
        if not _figure_forms(raw) & held and raw not in found:
            found.append(raw)
    return found


def _foreign_words(text: str, source_words: set[str], language: str) -> list[str]:
    alphabet = _ALPHABETS.get(language)
    if alphabet is None:
        return []
    found: list[str] = []
    for word in _WORD.findall(text):
        low = word.lower()
        if all(ch in alphabet for ch in low) or low in source_words:
            continue
        if word not in found:
            found.append(word)
    return found
