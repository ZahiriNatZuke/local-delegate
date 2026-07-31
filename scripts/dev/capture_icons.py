#!/usr/bin/env python3
"""Regenera los PNG de la marca desde `site/icon.src.html` y deja constancia de con qué SVG.

`icon.src.html` no dibuja la marca: **carga** `favicon.svg`, el fichero canónico que también
sirven el dashboard y la landing. Así los PNG son una rasterización del icono y no una tercera
copia. Lo que faltaba es lo otro: **nada obligaba a regenerarlos cuando el SVG cambia**. Los tests
comprobaban que existen, que la cabecera es la de un PNG y que están declarados en el HTML —
ninguno miraba si su contenido seguía correspondiéndose con el icono.

Este script cierra ese hueco por procedencia, no rasterizando en el CI: junto a los PNG escribe
`site/icons.json` con el **sha256 del SVG con el que se generaron**, y `tests/test_site.py`
compara ese hash con el del SVG actual. Si alguien toca el icono y no regenera, el PR falla.

Mismo trato que el manifiesto de la captura del README: **lo escribe quien captura, nunca se toca
a mano**. Un manifiesto actualizado a mano cumpliría el check sin que nadie regenerara nada, que
es justo lo que se quiere evitar.

Requiere playwright, que **no es dependencia del proyecto** (y `uv sync` lo desinstala):

    uv pip install playwright && uv run python -m playwright install chromium

Uso:

    uv run python scripts/dev/capture_icons.py

Códigos de salida:

    0  PNG y manifiesto escritos
    1  falta playwright, o la captura falló
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import http.server
import json
import socketserver
import sys
import threading
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SITIO = RAIZ / "site"
SVG = SITIO / "favicon.svg"
FUENTE = "icon.src.html"
MANIFIESTO = SITIO / "icons.json"

# (fichero, lado en px). Los tamaños los declaran el `<link sizes>` y el manifest de la landing,
# y hay tests que leen la cabecera de cada PNG: cambiarlos aquí sin cambiarlos allí rompe el CI.
ICONOS = ((SITIO / "apple-touch-icon.png", 180), (SITIO / "favicon-32x32.png", 32))


def _servir(directorio: Path) -> tuple[socketserver.TCPServer, int]:
    """Sirve el directorio en un puerto libre. Playwright no abre `file://`."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directorio))
    servidor = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor, servidor.server_address[1]


def _escribir_manifiesto(sha_svg: str) -> Path:
    """Deja junto a los PNG el manifiesto que dice de qué SVG salieron."""
    MANIFIESTO.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "_acerca_de": [
                    "Manifiesto de los PNG de la marca. Es la FUENTE DE VERDAD de con qué",
                    "favicon.svg se generaron.",
                    "Lo escribe `scripts/dev/capture_icons.py` al capturar, NUNCA a mano: un",
                    "manifiesto actualizado a mano cumpliría el check sin que nadie regenerara",
                    "los PNG, que es justo lo que se quiere evitar.",
                    "Lo comprueba `tests/test_site.py`.",
                ],
                "source": SVG.name,
                "source_sha256": sha_svg,
                "icons": [
                    {
                        "file": png.name,
                        "size": lado,
                        "sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
                        "bytes": png.stat().st_size,
                    }
                    for png, lado in ICONOS
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return MANIFIESTO


async def capturar() -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "falta playwright: uv pip install playwright && "
            "uv run python -m playwright install chromium",
            file=sys.stderr,
        )
        return 1

    if not SVG.is_file():
        print(f"no existe {SVG}", file=sys.stderr)
        return 1

    servidor, puerto = _servir(SITIO)
    try:
        async with async_playwright() as p:
            navegador = await p.chromium.launch()
            pagina = await navegador.new_page()
            for png, lado in ICONOS:
                # `scale="css"` y no `device`: con `device` el PNG sale al doble en una pantalla
                # retina y deja de medir lo que declaran el `sizes` del <link> y el manifest.
                await pagina.set_viewport_size({"width": lado, "height": lado})
                await pagina.goto(f"http://127.0.0.1:{puerto}/{FUENTE}")
                await pagina.screenshot(path=str(png), scale="css")
                print(f"{png.relative_to(RAIZ).as_posix()} — {lado}x{lado}")
            await navegador.close()
    finally:
        # Sin esto queda un servidor escuchando: el repo ya pagó ese descuido una vez.
        servidor.shutdown()
        servidor.server_close()

    manifiesto = _escribir_manifiesto(hashlib.sha256(SVG.read_bytes()).hexdigest())
    print(f"{manifiesto.relative_to(RAIZ).as_posix()} — sha del SVG registrado")
    return 0


def main() -> int:
    return asyncio.run(capturar())


if __name__ == "__main__":
    raise SystemExit(main())
