"""El catálogo de textos del paquete para los scripts que no pueden importarlo (frente B, ola B1d).

`pair_sheet.py` y `analyze_benchmark.py` no importan `local_delegate` a propósito: importar el
paquete carga `entrypoint` y con él `server`, y la tarea que recoge el juicio del usuario corre
mientras otras editan `server.py`. Este módulo, solo con la biblioteca estándar, les da lo mismo que
`local_delegate.i18n`:

- el idioma, con la única regla que existe (`hook_common.resolve_language`, cargado por ruta como
  hacen los hooks) sobre el `LOG_DIR` de `hook_common.log_dir()`;
- `t(key, **values)` sobre los mismos `resources/i18n/<idioma>/*.json`, con el español de reserva;
- `format_number`, con los separadores de REQ-026;
- `argparse_in_language()`, el armazón de argparse («usage:», «options:») en el idioma vigente, como
  `cli._argparse_in_language` (D8), con los mismos `argparse.*` del catálogo.

`tests/test_script_i18n.py` comprueba que da lo mismo que `local_delegate.i18n`.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import importlib.util
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

_PACKAGE = Path(__file__).resolve().parents[1] / "src" / "local_delegate"
_CATALOG_DIR = _PACKAGE / "resources" / "i18n"
_FALLBACK = "es"
_SEPARATORS = {"es": (".", ","), "en": (",", ".")}


def _load_hook_common() -> Any:
    path = _PACKAGE / "resources" / "hooks" / "hook_common.py"
    spec = importlib.util.spec_from_file_location("_script_hook_common", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@functools.cache
def lang() -> str:
    """El idioma vigente del proceso (REQ-018), con la regla de `hook_common`."""
    hook_common = _load_hook_common()
    return hook_common.resolve_language(hook_common.log_dir()).lang


@functools.cache
def catalog(language: str) -> dict[str, str]:
    merged: dict[str, str] = {}
    folder = _CATALOG_DIR / language
    for path in sorted(folder.glob("*.json")):
        merged.update(json.loads(path.read_bytes().decode("utf-8")))
    return merged


def reset() -> None:
    """Olvida el idioma y el catálogo cacheados (para los tests)."""
    lang.cache_clear()
    catalog.cache_clear()
    _argparse_index.cache_clear()


def t_lang(language: str, key: str, /, **values: object) -> str:
    text = catalog(language).get(key)
    if text is None:
        text = catalog(_FALLBACK).get(key, key)
    return text.format(**values) if values else text


def t(key: str, /, **values: object) -> str:
    """El texto de `key` en el idioma vigente, interpolado con nombre."""
    return t_lang(lang(), key, **values)


def format_number(value: float, decimals: int | None = 0, *, language: str | None = None) -> str:
    """Un número para una persona, con los separadores del idioma (como `i18n.format_number`)."""
    text = f"{value:,g}" if decimals is None else f"{value:,.{decimals}f}"
    thousands, point = _SEPARATORS.get(language or lang(), _SEPARATORS["en"])
    return text.replace(",", "\0").replace(".", point).replace("\0", thousands)


@functools.cache
def _argparse_index() -> dict[str, str]:
    """msgid inglés de argparse → su clave `argparse.*` del catálogo."""
    return {text: key for key, text in catalog("en").items() if key.startswith("argparse.")}


def argparse_gettext(msgid: str) -> str:
    """Como `i18n.argparse_gettext`: en inglés, el msgid; en español, su traducción si existe."""
    if lang() == "en":
        return msgid
    key = _argparse_index().get(msgid)
    return msgid if key is None else catalog(lang()).get(key, msgid)


def argparse_ngettext(singular: str, plural: str, n: int) -> str:
    return argparse_gettext(singular if n == 1 else plural)


@contextlib.contextmanager
def argparse_in_language(
    gettext: Callable[[str], str] = argparse_gettext,
    ngettext: Callable[[str, str, int], str] = argparse_ngettext,
) -> Iterator[None]:
    """Cambia `argparse._` y `argparse.ngettext` mientras dura el bloque y los devuelve al salir,
    pase lo que pase (la suite corre en un solo proceso). `measure_cooldown`, que sí importa el
    paquete, pasa las de `local_delegate.i18n`."""
    saved = (argparse._, argparse.ngettext)
    argparse._, argparse.ngettext = gettext, ngettext  # type: ignore[assignment]
    try:
        yield
    finally:
        argparse._, argparse.ngettext = saved
