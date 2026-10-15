#!/usr/bin/env python3
"""Prose-only language judge for the live samples of REQ-028 (front B, wave B2d).

`scripts/detect_language.py` judges a whole text. On the responses of `local_summarize` and
`local_lint_summary` that text also carries what the output format forces the model to copy
(the document's headings, paths, code, rule codes) and that is not language at all, so a short
summary of a ruff log can come out "unknown" or even "es" because `I001`/`E501` count as words.
This judge removes ONLY that, and leaves the detector and its threshold untouched.

Rules, applied in this order (each one has a unit test and a mutant in
`tests/test_judge_response_language.py`):

R1. Product lines: a whole line that is the product's own wrapper is dropped:
    "(leído server-side: ...)" / "(read server-side: ...)", "[local-delegate warning: ...]"
    and "(sin resumir)" / "(not summarized)".
R2. Document headings: a Markdown ATX heading line (`#` to `######`) whose text, normalized with
    `sections.normalize_heading`, equals the normalized text of a heading of the ORIGINAL
    document (`sections.markdown_headings`) is dropped. A heading the model translated or
    invented stays and is judged.
R3. Code: fenced blocks (``` or ~~~) and inline spans `...` are dropped.
R4. URLs: `http://...`, `https://...` and `www....` are dropped (only the URL, not the text of
    a Markdown link around it).
R5. Paths: a whitespace-separated run that contains `/` or `\\` is dropped.
R6. Rule names in kebab case (`no-unused-vars`, `no-console`). Rule and error codes with digits
    (`I001`, `UP006`, `E501`, `TS2345`, `PLR2004`) go by R8.
R7. Identifiers: snake_case (has `_`), camelCase/PascalCase with an inner capital
    (`useState`, `AuditMetadata`), dotted names (`sections.detect`), `--flags` and `name()`.
R8. Numbers and coded names: any token that contains a digit (`57`, `0.75s`, `12ms`, `v255`,
    `E501`, `TS2345`).

What is NOT removed: bold labels `**...**`, section and check names, headings that do not match
the document, list text. Those must be written in the requested language.

Verdict: if what is left has fewer than `MIN_TOKENS` detector tokens (the detector's own
`min_tokens`, 20), the response is `not_judgeable` (not a pass, not a failure). Otherwise
`detect(text, min_tokens=20, min_margin=0.15)` decides: `requested`, `opposite` or `unknown`.

Usage:
    python scripts/judge_response_language.py --document DOC --requested en RESPONSE [...]

Prints one JSON line per response: verdict, detected language, tokens, ratios and margin.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple

_ROOT = Path(__file__).resolve().parents[1]
for _path in (_ROOT / "scripts", _ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import detect_language

from local_delegate import sections

MIN_TOKENS = detect_language.MIN_TOKENS
MIN_MARGIN = detect_language.MIN_MARGIN
LANGUAGES = ("es", "en")
VERDICTS = ("requested", "opposite", "unknown", "not_judgeable")

PRODUCT_LINE = re.compile(
    r"^\s*(\((leído|read) server-side:.*\)|\[local-delegate warning:.*\]"
    r"|\((sin resumir|not summarized)\))\s*$"
)
ATX_LINE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"`[^`\n]+`")
URL = re.compile(r"(?:https?://|www\.)[^\s)\]>»\"']+")
KEBAB = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$")
CAMEL = re.compile(r"[a-z0-9][A-Z]")
DOTTED = re.compile(r"\w\.\w")
EDGE_PUNCTUATION = "()[]{}<>,.;:!?¡¿\"'«»*`|"


class Judgement(NamedTuple):
    verdict: str  # one of VERDICTS
    lang: str  # what the detector said ("not_judged" when not_judgeable)
    tokens: int
    es_ratio: float
    en_ratio: float
    margin: float
    judged_text: str


def document_headings(document: str) -> frozenset[str]:
    """The normalized headings of the original document (R2)."""
    return frozenset(
        sections.normalize_heading(h.text) for h in sections.markdown_headings(document)
    )


def _keep_token(token: str) -> bool:
    if "/" in token or "\\" in token:  # R5
        return False
    bare = token.strip(EDGE_PUNCTUATION)
    if not bare:
        return True
    if KEBAB.match(bare):  # R6
        return False
    if (  # R7
        "_" in bare
        or CAMEL.search(bare)
        or DOTTED.search(bare)
        or bare.startswith("--")
        or bare.endswith("()")
    ):
        return False
    return not any(c.isdigit() for c in bare)  # R8


def prose(response: str, document: str) -> str:
    """What is left of `response` once R1-R8 have removed what the format forces to copy."""
    headings = document_headings(document)
    kept: list[str] = []
    fence: str | None = None
    for line in response.split("\n"):
        opening = FENCE.match(line)
        if fence is not None:  # R3, inside a fenced block
            if opening and opening.group(1)[0] == fence[0] and len(opening.group(1)) >= len(fence):
                fence = None
            continue
        if opening:  # R3, a fence opens
            fence = opening.group(1)
            continue
        if PRODUCT_LINE.match(line):  # R1
            continue
        atx = ATX_LINE.match(line)
        if atx and sections.normalize_heading(atx.group(1)) in headings:  # R2
            continue
        line = INLINE_CODE.sub(" ", line)  # R3
        line = URL.sub(" ", line)  # R4
        kept.append(" ".join(token for token in line.split() if _keep_token(token)))
    return "\n".join(kept).strip()


def judge(
    response: str,
    document: str,
    requested: str,
    *,
    words: dict[str, frozenset[str]] | None = None,
) -> Judgement:
    """Judge the language of the prose of `response` against the `requested` one ("es"/"en")."""
    if requested not in LANGUAGES:
        raise ValueError(f"requested must be one of {LANGUAGES}: {requested!r}")
    text = prose(response, document)
    words = words or detect_language.load_function_words()
    detection = detect_language.detect(
        text, min_tokens=MIN_TOKENS, min_margin=MIN_MARGIN, words=words
    )
    margin = round(abs(detection.es_ratio - detection.en_ratio), 4)
    if detection.tokens < MIN_TOKENS:
        verdict, lang = "not_judgeable", "not_judged"
    else:
        lang = detection.lang
        if lang == requested:
            verdict = "requested"
        elif lang in LANGUAGES:
            verdict = "opposite"
        else:
            verdict = "unknown"
    return Judgement(
        verdict, lang, detection.tokens, detection.es_ratio, detection.en_ratio, margin, text
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Juez de idioma solo de prosa (requested, opposite, unknown o not_judgeable)."
    )
    parser.add_argument("responses", nargs="+", type=Path, help="respuestas literales a juzgar")
    parser.add_argument("--document", type=Path, required=True, help="documento original")
    parser.add_argument("--requested", choices=LANGUAGES, required=True, help="idioma pedido")
    args = parser.parse_args(argv)
    # As the server reads (`server._read_input`): a cp1252 log such as
    # `docs-3/es-log-B2c_corpus-f2-check.txt` gets U+FFFD, not a UnicodeDecodeError (B2d-2).
    document = args.document.read_text(encoding="utf-8", errors="replace")
    words = detect_language.load_function_words()
    for path in args.responses:
        response = path.read_text(encoding="utf-8", errors="replace")
        result = judge(response, document, args.requested, words=words)
        row = {"path": str(path), **result._asdict()}
        row.pop("judged_text")
        print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
