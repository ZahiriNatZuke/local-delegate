"""Paridad entre idiomas del catálogo y de los textos de los hooks (REQ-031, REQ-030).

Un texto que existe en un idioma y no en el otro, una traducción vacía, un marcador de
interpolación distinto o un identificador entre comillas invertidas que no coincide son fallos
que en ejecución se ven como una frase rota o en el idioma equivocado. Las comprobaciones son
funciones puras y tienen sus propios tests sobre catálogos sintéticos: así el guardián está probado
aunque `HOOK_TEXTS` siga vacío hasta B3.
"""

from __future__ import annotations

import ast
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from local_delegate import config, i18n
from local_delegate.resources.hooks import hook_common

PACKAGE = Path(config.__file__).parent
CATALOG_DIR = PACKAGE / "resources" / "i18n"
# `{n}`, `{0}`, `{name!r}` (format) y `%s`, `%(prog)s` (los msgid de argparse).
_PLACEHOLDER = re.compile(
    r"\{[A-Za-z0-9_]*(?:![rsa])?(?::[^{}]*)?\}|%\([A-Za-z0-9_]+\)[sdr]|%[sdr]"
)
_BACKTICKED = re.compile(r"`([^`]+)`")


def _load(lang: str) -> dict[str, dict[str, str]]:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((CATALOG_DIR / lang).glob("*.json"))
    }


def check_pair(es: dict[str, str], en: dict[str, str], *, ascii_only: bool = False) -> list[str]:
    """Los problemas de paridad entre dos diccionarios `clave → texto`, uno por línea."""
    problems = []
    for key in sorted(es.keys() - en.keys()):
        problems.append(f"{key}: falta en en")
    for key in sorted(en.keys() - es.keys()):
        problems.append(f"{key}: falta en es")
    for key in sorted(es.keys() & en.keys()):
        a, b = es[key], en[key]
        for lang, text in (("es", a), ("en", b)):
            if not isinstance(text, str) or not text.strip():
                problems.append(f"{key}: vacía en {lang}")
            elif ascii_only and not text.isascii():
                problems.append(f"{key}: no es ASCII en {lang}")
        if not (isinstance(a, str) and isinstance(b, str)):
            continue
        if Counter(_PLACEHOLDER.findall(a)) != Counter(_PLACEHOLDER.findall(b)):
            problems.append(
                f"{key}: marcadores distintos {sorted(_PLACEHOLDER.findall(a))} "
                f"!= {sorted(_PLACEHOLDER.findall(b))}"
            )
        if Counter(_BACKTICKED.findall(a)) != Counter(_BACKTICKED.findall(b)):
            problems.append(
                f"{key}: identificadores distintos {sorted(_BACKTICKED.findall(a))} "
                f"!= {sorted(_BACKTICKED.findall(b))}"
            )
    return problems


def check_surfaces(catalog: dict[str, dict[str, str]]) -> list[str]:
    """Cada clave empieza por el nombre de su fichero, y ninguna está en dos ficheros (plan D5)."""
    problems = []
    seen: dict[str, str] = {}
    for surface, entries in catalog.items():
        for key in entries:
            if not key.startswith(f"{surface}."):
                problems.append(f"{key}: está en {surface}.json y no empieza por «{surface}.»")
            if key in seen:
                problems.append(f"{key}: repetida en {seen[key]}.json y {surface}.json")
            seen[key] = surface
    return problems


# --- El catálogo real ------------------------------------------------------------------------------


def test_both_languages_have_the_same_files():
    assert sorted(_load("es")) == sorted(_load("en"))


def test_the_catalog_is_not_empty():
    """Guarda de no vacío: sin ficheros, todos los tests de abajo pasarían sobre nada."""
    assert "common" in _load("es")
    assert len(i18n.catalog("es")) >= 10
    assert set(i18n.LANGUAGES) == {path.name for path in CATALOG_DIR.iterdir() if path.is_dir()}


@pytest.mark.parametrize("surface", sorted(_load("es")))
def test_each_surface_has_parity(surface):
    problems = check_pair(_load("es")[surface], _load("en")[surface])
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("lang", ["es", "en"])
def test_each_key_lives_in_its_surface_file(lang):
    problems = check_surfaces(_load(lang))
    assert problems == [], "\n".join(problems)


def test_the_hook_texts_have_parity_and_are_ascii():
    """Los hooks no importan el paquete y llevan sus textos dentro (REQ-030), en ASCII (i18n §1 e)."""
    assert set(hook_common.HOOK_TEXTS) == set(i18n.LANGUAGES)
    problems = check_pair(
        hook_common.HOOK_TEXTS["es"], hook_common.HOOK_TEXTS["en"], ascii_only=True
    )
    assert problems == [], "\n".join(problems)


def _literal_keys_used() -> list[tuple[str, int, str]]:
    """(fichero, línea, clave) de cada `t("…")` y `t_lang(lang, "…")` con clave literal."""
    found = []
    for file in sorted(PACKAGE.rglob("*.py")):
        if "vendor" in file.parts or "__pycache__" in file.parts:
            continue
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            position = {"t": 0, "t_lang": 1}.get(name)
            if position is None or len(node.args) <= position:
                continue
            arg = node.args[position]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.append((file.relative_to(PACKAGE).as_posix(), node.lineno, arg.value))
    return found


def test_every_literal_key_used_by_the_code_exists():
    """Una clave que no existe se mostraría tal cual en ejecución (`common.algo`)."""
    known = i18n.catalog("es").keys() | i18n.catalog("en").keys()
    missing = [f"{f}:{line} {key}" for f, line, key in _literal_keys_used() if key not in known]
    assert missing == []


# --- Las comprobaciones, sobre catálogos sintéticos (control positivo permanente) -----------------

_ES = {"x.files": "Hay {n} ficheros en `local_extract`.", "x.title": "Título"}
_EN = {"x.files": "There are {n} files in `local_extract`.", "x.title": "Title"}


def test_a_clean_pair_has_no_problems():
    assert check_pair(_ES, _EN) == []


def test_a_missing_translation_is_caught():
    en = {k: v for k, v in _EN.items() if k != "x.title"}
    assert check_pair(_ES, en) == ["x.title: falta en en"]


def test_an_empty_translation_is_caught():
    assert check_pair(_ES, {**_EN, "x.title": "  "}) == ["x.title: vacía en en"]


def test_a_changed_placeholder_is_caught():
    problems = check_pair(_ES, {**_EN, "x.files": "There are {m} files in `local_extract`."})
    assert len(problems) == 1 and "marcadores distintos" in problems[0]


def test_an_argparse_placeholder_is_compared_too():
    assert check_pair({"a.b": "uso: %(prog)s"}, {"a.b": "usage: %s"}) != []


def test_a_changed_identifier_is_caught():
    problems = check_pair(_ES, {**_EN, "x.files": "There are {n} files in `local_extrac`."})
    assert len(problems) == 1 and "identificadores distintos" in problems[0]


def test_a_non_ascii_hook_text_is_caught():
    problems = check_pair({"h.x": "Pásalo"}, {"h.x": "Pass it"}, ascii_only=True)
    assert problems == ["h.x: no es ASCII en es"]


def test_a_key_outside_its_surface_and_a_repeated_key_are_caught():
    problems = check_surfaces({"common": {"cli.x": "a"}, "cli": {"cli.x": "b"}})
    assert problems == [
        "cli.x: está en common.json y no empieza por «common.»",
        "cli.x: repetida en common.json y cli.json",
    ]
