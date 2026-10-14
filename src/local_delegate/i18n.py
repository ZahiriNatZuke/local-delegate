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
from dataclasses import dataclass
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
            # `read_bytes` y no `read_text`: un test que dobla `Path.read_text` no rompe el catálogo.
            merged.update(json.loads(entry.read_bytes().decode("utf-8")))
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


#: Orígenes del idioma (REQ-018) → su rótulo del catálogo común (B0a).
_LANGUAGE_SOURCES = {
    "variable": "common.language.source.variable",
    "preference": "common.language.source.preference",
    "system": "common.language.source.system",
    "fallback": "common.language.source.fallback",
}
#: Avisos de la regla del idioma (`hook_common.resolve_language`) → su texto y su marcador.
_LANGUAGE_WARNINGS = {
    "invalid_variable": ("common.language.warning.invalid_variable", "value"),
    "invalid_preference": ("common.language.warning.invalid_preference", "path"),
    "unreadable_preference": ("common.language.warning.unreadable_preference", "path"),
}


@dataclass(frozen=True)
class LanguageReport:
    """El idioma de este proceso tal como lo cuentan `doctor` y `local_status` (REQ-019, D11).

    Los datos son los mismos para las dos superficies; cada una los formatea con sus claves.
    """

    lang: str
    source: str  # rótulo del origen, ya en el idioma vigente
    path: str  # el `language.json` que se leyó o se leería
    warnings: tuple[str, ...]  # avisos ya redactados
    follow_system: bool  # lo guardado vino de la variable: decir cómo volver a seguir al sistema


def language_report() -> LanguageReport:
    resolution = current()
    warnings = []
    for code, detail in resolution.warnings:
        if code in _LANGUAGE_WARNINGS:
            text_key, field_name = _LANGUAGE_WARNINGS[code]
            warnings.append(t(text_key, **{field_name: detail}))
    return LanguageReport(
        lang=resolution.lang,
        source=t(_LANGUAGE_SOURCES[resolution.source]),
        path=str(resolution.pref_path),
        warnings=tuple(warnings),
        follow_system=(
            resolution.source == "preference" and resolution.stored_source == "variable"
        ),
    )


#: Separadores de miles y decimal por idioma (REQ-026): `20.027` y `1,5` en español, `20,027` y
#: `1.5` en inglés.
_SEPARATORS = {"es": (".", ","), "en": (",", ".")}


def format_number(
    value: float, decimals: int | None = 0, *, language: str | None = None, machine: bool = False
) -> str:
    """Un número para una persona, con los separadores del idioma (REQ-026).

    `decimals=None` deja los decimales que hagan falta (como `:g`). Con `machine=True` sale sin
    separador de miles y con punto decimal, sea cual sea el idioma: es el formato de las salidas
    que lee un modelo (REQ-026, ola B2) y de todo lo que se escribe en un fichero.
    """
    if machine:
        return f"{value:g}" if decimals is None else f"{value:.{decimals}f}"
    text = f"{value:,g}" if decimals is None else f"{value:,.{decimals}f}"
    thousands, point = _SEPARATORS.get(language or lang(), _SEPARATORS["en"])
    return text.replace(",", "\0").replace(".", point).replace("\0", thousands)


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
