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
de línea. `tests/test_vigilante.py` comprueba con `restos()` que las copias del repo están limpias.

Uso:
    python scripts/limpiar_fixtures_vigilante.py            # limpia las copias del repo
    python scripts/limpiar_fixtures_vigilante.py otra.html  # o las que se le pasen
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures" / "vigilante"

UUID_NEUTRO = "00000000-0000-0000-0000-000000000000"
NONCE_NEUTRO = "nonce-neutro"
PAIS_NEUTRO = "ZZ"  # código ISO 3166 de uso privado: no es ningún país

# Cada clave admite todas las formas en que la sirve la página: atributo HTML (`clave="v"` o
# `clave='v'`), JSON (`"clave":"v"`), JSON escapado dentro de una cadena (`\"clave\":\"v\"`, con
# una o más barras), argumento de una llamada (`["clave", "v"]`), con o sin espacios alrededor del
# separador y con o sin comillas en el valor.
_ANTES = r"(?<![\w-])"  # la clave empieza aquí: no es la cola de otro nombre
_COMILLA = r"""(?:\\*["'])?"""  # comilla simple o doble, tal cual o escapada, u omitida
_SEPARADOR = rf"{_COMILLA}\s*[:=,]\s*{_COMILLA}"
_VALOR = r"""([^"'\\\s<>,;{}\[\]()]+)"""


def _clave(nombre: str) -> re.Pattern[str]:
    return re.compile(rf"{_ANTES}(?:{nombre}){_SEPARADOR}{_VALOR}", re.IGNORECASE)


# (patrón que captura el valor de la visita, valor neutro). Un valor largo se sustituye en TODO el
# fichero, sea cual sea la forma en que aparezca; uno corto, solo donde lo captura el patrón.
PATRONES: tuple[tuple[re.Pattern[str], str], ...] = (
    # Ids de la analítica y del antifraude: cualquier valor, tenga o no forma de UUID.
    (
        _clave(r"anonymous[-_]?id|stable[-_]?id|_?set[-_]?session[-_]?id|session[-_]?id"),
        UUID_NEUTRO,
    ),
    (_clave(r"nonce"), NONCE_NEUTRO),
    # El país de la IP: `ipCountry`, `ip_country`, `data-consent-ip-country`...
    (_clave(r"(?:[\w-]*[-_])?ip[-_]?country"), PAIS_NEUTRO),
)


def restos(texto: str) -> list[str]:
    """Los valores de la visita que siguen en el texto (vacío si está limpio)."""
    vistos: list[str] = []
    for patron, neutro in PATRONES:
        for valor in patron.findall(texto):
            if valor != neutro and valor not in vistos:
                vistos.append(valor)
    return vistos


def limpiar(texto: str) -> str:
    for patron, neutro in PATRONES:
        for valor in set(patron.findall(texto)):
            if valor == neutro:
                continue
            if len(valor) >= 16:  # un id largo: todas sus apariciones son de la visita
                texto = texto.replace(valor, neutro)
            else:  # uno corto («UY») podría estar en otra parte: solo donde lo captó el patrón
                texto = patron.sub(lambda m, n=neutro: m.group(0).replace(m.group(1), n), texto)
    return texto


def main(argv: list[str]) -> int:
    rutas = [Path(a) for a in argv] or sorted(FIXTURES.glob("*.html"))
    for ruta in rutas:
        original = ruta.read_bytes().decode("utf-8")
        limpio = limpiar(original)
        if limpio != original:
            ruta.write_bytes(limpio.encode("utf-8"))
        print(f"{ruta.name}: {len(restos(original))} valores sustituidos")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
