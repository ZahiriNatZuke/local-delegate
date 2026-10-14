#!/usr/bin/env python3
"""Detector de idioma de D10: dice si un texto está en español, en inglés o no se sabe.

Es el juez versionado de REQ-028 (la muestra en vivo de B2) y se controla en
`tests/test_detect_language.py`. No necesita red ni dependencias: cuenta qué proporción de las
palabras del texto está en cada una de dos listas cerradas de palabras funcionales
(`scripts/data/function_words.json`, escritas a mano y disjuntas) y responde:

- `unknown` si el texto tiene menos de `min_tokens` palabras (por defecto 20) o si la diferencia
  entre las dos proporciones es menor que `min_margin` (por defecto 0,15);
- si no, el idioma con la proporción mayor (`es` o `en`).

Uso:
    python scripts/detect_language.py FICHERO [FICHERO ...]
    python scripts/detect_language.py --min-tokens 8 FICHERO

Imprime una línea JSON por fichero: `{"path", "lang", "tokens", "es_ratio", "en_ratio"}`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple

FUNCTION_WORDS_PATH = Path(__file__).resolve().parent / "data" / "function_words.json"
MIN_TOKENS = 20
MIN_MARGIN = 0.15
_TOKEN = re.compile(r"[a-záéíóúüñ]+")


class Detection(NamedTuple):
    lang: str  # "es" | "en" | "unknown"
    tokens: int
    es_ratio: float
    en_ratio: float


def load_function_words(path: Path = FUNCTION_WORDS_PATH) -> dict[str, frozenset[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"es": frozenset(data["es"]), "en": frozenset(data["en"])}


def detect(
    text: str,
    *,
    min_tokens: int = MIN_TOKENS,
    min_margin: float = MIN_MARGIN,
    words: dict[str, frozenset[str]] | None = None,
) -> Detection:
    words = words or load_function_words()
    tokens = _TOKEN.findall(text.lower())
    if not tokens:
        return Detection("unknown", 0, 0.0, 0.0)
    es_ratio = sum(token in words["es"] for token in tokens) / len(tokens)
    en_ratio = sum(token in words["en"] for token in tokens) / len(tokens)
    if len(tokens) < min_tokens or abs(es_ratio - en_ratio) < min_margin:
        lang = "unknown"
    else:
        lang = "es" if es_ratio > en_ratio else "en"
    return Detection(lang, len(tokens), round(es_ratio, 4), round(en_ratio, 4))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detector de idioma de D10 (es, en o unknown).")
    parser.add_argument("paths", nargs="+", type=Path, help="ficheros de texto a clasificar")
    parser.add_argument("--min-tokens", type=int, default=MIN_TOKENS)
    parser.add_argument("--min-margin", type=float, default=MIN_MARGIN)
    args = parser.parse_args(argv)
    words = load_function_words()
    for path in args.paths:
        result = detect(
            path.read_text(encoding="utf-8"),
            min_tokens=args.min_tokens,
            min_margin=args.min_margin,
            words=words,
        )
        print(json.dumps({"path": str(path), **result._asdict()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
