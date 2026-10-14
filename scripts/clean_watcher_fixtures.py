#!/usr/bin/env python3
"""Quita de las páginas guardadas del vigilante los datos de la visita que las descargó.

`tests/fixtures/vigilante/*.html` son copias tal cual de dos páginas públicas. Además del contenido
traen lo que el sitio sirve **a cada visitante**: el id anónimo de la analítica (`anonymousId` y
`stableId`), el id de sesión del antifraude (`_setSessionId`), el país deducido de la IP
(`data-consent-ip-country`, `ipCountry`) y el `nonce` de la CSP de esa respuesta. Ninguno hace falta para
extraer la tabla de precios ni el texto de límites, así que se sustituyen por valores neutros.

El resto de UUID de la página (términos legales, claves de sitio de hCaptcha, ids de cliente de
las extensiones) es configuración pública del sitio, igual para cualquiera, y se deja.

Es idempotente: sobre una página ya limpia no cambia nada. Escribe en bytes para conservar el fin
de línea. `tests/test_price_watcher.py` comprueba con `leftovers()` que las copias del repo están limpias.

Uso:
    python scripts/clean_watcher_fixtures.py            # limpia las copias del repo
    python scripts/clean_watcher_fixtures.py otra.html  # o las que se le pasen
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures" / "vigilante"

NEUTRAL_UUID = "00000000-0000-0000-0000-000000000000"
NEUTRAL_NONCE = "nonce-neutro"
NEUTRAL_COUNTRY = "ZZ"  # código ISO 3166 de uso privado: no es ningún país

# Cada clave admite todas las formas en que la sirve la página: atributo HTML (`clave="v"` o
# `clave='v'`), JSON (`"clave":"v"`), JSON escapado dentro de una cadena (`\"clave\":\"v\"`, con
# una o más barras), argumento de una llamada (`["clave", "v"]`), con o sin espacios alrededor del
# separador y con o sin comillas en el valor.
_BEFORE = r"(?<![\w-])"  # la clave empieza aquí: no es la cola de otro nombre
_QUOTE = r"""(?:\\*["'])?"""  # comilla simple o doble, tal cual o escapada, u omitida
_SEPARATOR = rf"{_QUOTE}\s*[:=,]\s*{_QUOTE}"
_VALUE = r"""([^"'\\\s<>,;{}\[\]()]+)"""


def _key(name: str) -> re.Pattern[str]:
    return re.compile(rf"{_BEFORE}(?:{name}){_SEPARATOR}{_VALUE}", re.IGNORECASE)


# (patrón que captura el valor de la visita, valor neutro). Un valor largo se sustituye en TODO el
# fichero, sea cual sea la forma en que aparezca; uno corto, solo donde lo captura el patrón.
PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Ids de la analítica y del antifraude: cualquier valor, tenga o no forma de UUID.
    (
        _key(r"anonymous[-_]?id|stable[-_]?id|_?set[-_]?session[-_]?id|session[-_]?id"),
        NEUTRAL_UUID,
    ),
    (_key(r"nonce"), NEUTRAL_NONCE),
    # El país de la IP: `ipCountry`, `ip_country`, `data-consent-ip-country`...
    (_key(r"(?:[\w-]*[-_])?ip[-_]?country"), NEUTRAL_COUNTRY),
)


def leftovers(text: str) -> list[str]:
    """Los valores de la visita que siguen en el texto (vacío si está limpio)."""
    seen: list[str] = []
    for pattern, neutral in PATTERNS:
        for value in pattern.findall(text):
            if value != neutral and value not in seen:
                seen.append(value)
    return seen


def clean(text: str) -> str:
    for pattern, neutral in PATTERNS:
        for value in set(pattern.findall(text)):
            if value == neutral:
                continue
            if len(value) >= 16:  # un id largo: todas sus apariciones son de la visita
                text = text.replace(value, neutral)
            else:  # uno corto («UY») podría estar en otra parte: solo donde lo captó el patrón
                text = pattern.sub(lambda m, n=neutral: m.group(0).replace(m.group(1), n), text)
    return text


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv] or sorted(FIXTURES.glob("*.html"))
    for path in paths:
        original = path.read_bytes().decode("utf-8")
        cleaned = clean(original)
        if cleaned != original:
            path.write_bytes(cleaned.encode("utf-8"))
        print(f"{path.name}: {len(leftovers(original))} valores sustituidos")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
