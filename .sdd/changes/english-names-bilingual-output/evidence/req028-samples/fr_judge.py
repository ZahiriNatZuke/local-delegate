"""French language judge for the REQ-028 `fr` sample (evidence only, not a product detector).

`scripts/judge_response_language.py` and `scripts/detect_language.py` only know `es` and `en`
(spec, amendment of 2026-10-14). For the `LOCAL_DELEGATE_OUTPUT_LANGUAGE=fr` sample this judge
keeps EVERYTHING the prose judge does (`judge_response_language.prose`, rules R1-R8, same
document headings) and only adds a third closed list of French function words, written by hand.
A French word that is also in the es or en list is dropped from ALL lists (version 2), as the
detector already does with the words es and en share; the product judge is not touched.

Verdict, with the detector's own thresholds (20 tokens, margin 0.15):
- `not_judgeable`: fewer than 20 tokens left after the prose rules;
- otherwise the language with the highest ratio if it beats the second by >= 0.15, else
  `unknown`; `requested` when that language is `fr`, `other` when it is `es` or `en`.

Controls (`fr_judge_controls.md`): negative, the B2d-2 es/en answers must never come out `fr`;
positive, French translations made by `local_translate` must come out `fr`.

    python fr_judge.py --document DOC RESPONSE [RESPONSE ...]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[4]
for _path in (ROOT / "scripts", ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import detect_language
import judge_response_language

VERSION = 2
MIN_TOKENS = detect_language.MIN_TOKENS
MIN_MARGIN = detect_language.MIN_MARGIN
TOKEN = re.compile(r"[a-záàâäçéèêëíîïñóôöúùûüÿœæ]+")
FRENCH = frozenset(
    [
        "le",
        "la",
        "les",
        "un",
        "une",
        "des",
        "du",
        "au",
        "aux",
        "et",
        "ou",
        "mais",
        "donc",
        "car",
        "ni",
        "que",
        "qui",
        "quoi",
        "dont",
        "où",
        "ce",
        "cet",
        "cette",
        "ces",
        "celui",
        "celle",
        "ceux",
        "celles",
        "ceci",
        "cela",
        "ça",
        "il",
        "elle",
        "ils",
        "elles",
        "on",
        "nous",
        "vous",
        "leur",
        "leurs",
        "lui",
        "eux",
        "se",
        "sa",
        "son",
        "ses",
        "mon",
        "ma",
        "mes",
        "ton",
        "ta",
        "tes",
        "notre",
        "nos",
        "votre",
        "vos",
        "ne",
        "pas",
        "plus",
        "jamais",
        "rien",
        "aucun",
        "aucune",
        "très",
        "est",
        "sont",
        "était",
        "étaient",
        "être",
        "été",
        "avoir",
        "avez",
        "avons",
        "ont",
        "fait",
        "faire",
        "peut",
        "peuvent",
        "doit",
        "doivent",
        "dans",
        "sur",
        "sous",
        "avec",
        "sans",
        "pour",
        "par",
        "chez",
        "vers",
        "entre",
        "depuis",
        "pendant",
        "avant",
        "après",
        "selon",
        "contre",
        "chaque",
        "tout",
        "tous",
        "toute",
        "toutes",
        "aussi",
        "ainsi",
        "alors",
        "puis",
        "lorsque",
        "quand",
        "comme",
        "si",
        "déjà",
        "encore",
        "toujours",
        "souvent",
        "ici",
        "là",
        "cependant",
        "également",
        "plutôt",
        "afin",
        "autre",
        "autres",
        "même",
        "mêmes",
        "quel",
        "quelle",
        "quels",
        "quelles",
        "lequel",
        "laquelle",
        "lesquels",
        "sont-ils",
        "elle-même",
        "c'est",
        "qu'il",
        "d'un",
        "d'une",
        "l'image",
        "utilise",
        "permet",
        "affiche",
        "indique",
        "contient",
        "fichier",
        "fonction",
        "lorsqu",
        "puisque",
        "tandis",
        "selon",
        "de",
        "en",
        "me",
        "te",
        "y",
        "non",
        "mi",
        "tu",
        "si",
    ]
)


def load_words() -> dict[str, frozenset[str]]:
    """Three disjoint lists: a word that French shares with es or en counts for nobody.

    Version 1 only dropped the shared words from the French list, so French `de`, `la`, `le`,
    `en`, `que`, `un`, `les` counted as Spanish and the positive control came out `unknown`
    (fr-control-positive-v1.jsonl). The detector does the same with the words es and en share.
    """
    words = detect_language.load_function_words()
    french = frozenset(w for w in FRENCH if TOKEN.fullmatch(w))
    shared = french & (words["es"] | words["en"])
    return {"es": words["es"] - shared, "en": words["en"] - shared, "fr": french - shared}


def judge(response: str, document: str, words: dict[str, frozenset[str]]) -> dict:
    text = judge_response_language.prose(response, document)
    tokens = TOKEN.findall(text.lower().replace("’", " ").replace("'", " "))
    n = len(tokens)
    ratios = {
        lang: (round(sum(t in lst for t in tokens) / n, 4) if n else 0.0)
        for lang, lst in words.items()
    }
    ranked = sorted(ratios.items(), key=lambda kv: kv[1], reverse=True)
    margin = round(ranked[0][1] - ranked[1][1], 4)
    if n < MIN_TOKENS:
        verdict, lang = "not_judgeable", "not_judged"
    elif margin < MIN_MARGIN:
        verdict, lang = "unknown", "unknown"
    else:
        lang = ranked[0][0]
        verdict = "requested" if lang == "fr" else "other"
    return {
        "verdict": verdict,
        "lang": lang,
        "tokens": n,
        **{f"{k}_ratio": v for k, v in ratios.items()},
        "margin": margin,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="French prose judge (requested/other/unknown/not_judgeable)."
    )
    parser.add_argument("responses", nargs="+", type=Path)
    parser.add_argument("--document", type=Path, required=True)
    args = parser.parse_args(argv)
    document = (
        args.document.read_text(encoding="utf-8", errors="replace")
        if args.document.suffix != ".png"
        else ""
    )
    words = load_words()
    for path in args.responses:
        response = path.read_text(encoding="utf-8", errors="replace")
        print(
            json.dumps(
                {"path": str(path), "judge_version": VERSION, **judge(response, document, words)},
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
