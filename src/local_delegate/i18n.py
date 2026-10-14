"""Textos de salida en español e inglés: el idioma del proceso y el catálogo (REQ-018, REQ-030).

El idioma lo decide `hook_common.resolve_language`, la única implementación de la regla (plan D7);
este módulo la llama con `config.LOG_DIR` y la cachea por proceso: el daemon y el servidor por
stdio resuelven una vez y sirven con ese idioma.

El catálogo son ficheros JSON planos por idioma y superficie,
`resources/i18n/<lang>/<surface>.json` (plan D5), con claves con puntos cuyo primer segmento es la
superficie (`common.language.source.system`). Si a un idioma le falta una clave en ejecución, se
muestra la española; si falta en los dos, la propia clave (los guardianes de paridad y de textos
fuera del catálogo lo impiden antes de llegar ahí).

`argparse_gettext` y `argparse_ngettext` son las piezas de D8: el CLI (ola B1) las instala en el
módulo `argparse` de su proceso para traducir el armazón de `--help` y de los errores.
"""

from __future__ import annotations

import functools
import json
from importlib.resources import files

from . import config
from .resources.hooks import hook_common

LANGUAGES = hook_common.LANGUAGES
#: Idioma que se muestra si a otro le falta una traducción en ejecución (plan D5).
CATALOG_FALLBACK = "es"
_ARGPARSE_PREFIX = "argparse."


@functools.cache
def current() -> hook_common.LanguageResolution:
    """El idioma vigente de este proceso (REQ-018), con su origen, su `language.json` y avisos."""
    return hook_common.resolve_language(config.LOG_DIR)


def lang() -> str:
    return current().lang


@functools.cache
def catalog(language: str) -> dict[str, str]:
    """Une todos los `resources/i18n/<language>/*.json` en un solo diccionario plano."""
    merged: dict[str, str] = {}
    folder = files("local_delegate").joinpath("resources", "i18n", language)
    if not folder.is_dir():
        return merged
    for entry in sorted(folder.iterdir(), key=lambda item: item.name):
        if entry.name.endswith(".json"):
            merged.update(json.loads(entry.read_text(encoding="utf-8")))
    return merged


def reset() -> None:
    """Olvida el idioma y el catálogo cacheados (la suite lo llama en cada test)."""
    current.cache_clear()
    catalog.cache_clear()
    _argparse_index.cache_clear()


def t_lang(language: str, key: str, /, **values: object) -> str:
    """El texto de `key` en `language`, interpolado con nombre (`{n}`) si se pasan valores."""
    text = catalog(language).get(key)
    if text is None:
        text = catalog(CATALOG_FALLBACK).get(key, key)
    return text.format(**values) if values else text


def t(key: str, /, **values: object) -> str:
    """El texto de `key` en el idioma vigente del proceso."""
    return t_lang(lang(), key, **values)


@functools.cache
def _argparse_index() -> dict[str, str]:
    """msgid inglés de argparse → su clave `argparse.*` del catálogo."""
    return {text: key for key, text in catalog("en").items() if key.startswith(_ARGPARSE_PREFIX)}


def argparse_gettext(msgid: str) -> str:
    """Sustituto de `argparse._`: en inglés, el msgid; en español, su traducción si existe."""
    if lang() == "en":
        return msgid
    key = _argparse_index().get(msgid)
    if key is None:
        return msgid
    return catalog(lang()).get(key, msgid)


def argparse_ngettext(singular: str, plural: str, n: int) -> str:
    """Sustituto de `argparse.ngettext`: español e inglés tienen las mismas dos formas."""
    return argparse_gettext(singular if n == 1 else plural)
