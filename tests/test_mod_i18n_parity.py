"""Paridad de los catálogos del mod (`<plugin>/mod/i18n/{es,en}.json`, REQ-014).

El mod no lee los catálogos de Python: tiene los suyos, planos (`clave → texto`). Mismas reglas que
`test_i18n_parity.py` (mismas claves, nada vacío, mismos marcadores e identificadores entre comillas
invertidas), más una que solo tiene sentido aquí: cada clave que una pieza del mod pide con
`t('…')` existe en los dos idiomas.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from local_delegate import config

MOD_DIR = Path(config.__file__).parent / "resources" / "claude-plugin" / "local-delegate" / "mod"
CATALOG_DIR = MOD_DIR / "i18n"
_PLACEHOLDER = re.compile(r"\{[A-Za-z0-9_]+\}")
_BACKTICKED = re.compile(r"`([^`]+)`")
# `t('commands.lint.usage')`, `common.t("x.y", {...})`
_T_CALL = re.compile(r"""\bt\(\s*['"]([A-Za-z0-9_.]+)['"]""")


def _catalog(lang: str) -> dict[str, str]:
    return json.loads((CATALOG_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def check_pair(es: dict[str, str], en: dict[str, str]) -> list[str]:
    """Los problemas de paridad entre dos catálogos planos, uno por línea."""
    problems = [f"{k}: falta en en" for k in sorted(es.keys() - en.keys())]
    problems += [f"{k}: falta en es" for k in sorted(en.keys() - es.keys())]
    for key in sorted(es.keys() & en.keys()):
        a, b = es[key], en[key]
        if not (isinstance(a, str) and a.strip() and isinstance(b, str) and b.strip()):
            problems.append(f"{key}: vacía o no es texto")
            continue
        if sorted(_PLACEHOLDER.findall(a)) != sorted(_PLACEHOLDER.findall(b)):
            problems.append(f"{key}: marcadores distintos")
        if sorted(_BACKTICKED.findall(a)) != sorted(_BACKTICKED.findall(b)):
            problems.append(f"{key}: identificadores distintos")
    return problems


def test_check_pair_detects_each_problem():
    # Control positivo: el guardián sí puede fallar.
    es = {"a.x": "hola {n} `x`", "a.y": "solo es", "a.z": " "}
    en = {"a.x": "hi {m} `y`", "a.w": "only en", "a.z": "z"}
    problems = check_pair(es, en)
    assert "a.y: falta en en" in problems
    assert "a.w: falta en es" in problems
    assert "a.z: vacía o no es texto" in problems
    assert "a.x: marcadores distintos" in problems
    assert "a.x: identificadores distintos" in problems
    assert check_pair({"a.x": "{n} `x`"}, {"a.x": "`x` {n}"}) == []


def test_mod_catalogs_have_same_keys():
    es, en = _catalog("es"), _catalog("en")
    assert es, "el catálogo del mod está vacío"
    assert check_pair(es, en) == []


def test_every_key_a_piece_asks_for_exists():
    es, en = _catalog("es"), _catalog("en")
    pieces = sorted(p for p in MOD_DIR.glob("*.js") if not p.name.endswith(".test.js"))
    assert any(p.name == "commands.js" for p in pieces)
    asked = {key for p in pieces for key in _T_CALL.findall(p.read_text(encoding="utf-8"))}
    assert "commands.lint.usage" in asked  # guarda: el patrón sí encuentra las llamadas
    missing = sorted(k for k in asked if k not in es or k not in en)
    assert missing == []
