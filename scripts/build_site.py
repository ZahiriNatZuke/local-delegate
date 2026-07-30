#!/usr/bin/env python3
"""Prepara `site/` para publicar en GitHub Pages, con la versión ya inyectada.

La versión aparece en la landing (el eyebrow del hero y la salida de `doctor` del bloque de
terminal), y escribirla a mano ahí sería una **quinta** copia de un número que ya vive en
`pyproject.toml`, `server.json` (dos veces) y `uv.lock`. Este repo ya sabe cómo acaba eso: en
la 0.8.1 el lock se quedó en 0.7.0. Así que la página trae un marcador `__LD_VERSION__` y este
script lo sustituye por lo que declare `pyproject.toml` en el momento de desplegar.

Solo stdlib, igual que `check_vendor.py`: lo corre un workflow y no debe arrastrar dependencias.

Uso:
    python scripts/build_site.py            # escribe en _site/
    python scripts/build_site.py --check    # ¿queda algún marcador sin sustituir? (sale 1 si sí)
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ORIGEN = RAIZ / "site"
DESTINO = RAIZ / "_site"
MARCADOR = "__LD_VERSION__"


def version_declarada() -> str:
    datos = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    return datos["project"]["version"]


def construir(destino: Path, version: str) -> list[Path]:
    """Copia `site/` sustituyendo el marcador. Devuelve los ficheros escritos."""
    if destino.exists():
        shutil.rmtree(destino)
    shutil.copytree(ORIGEN, destino)

    escritos: list[Path] = []
    for ruta in sorted(destino.rglob("*")):
        if not ruta.is_file() or ruta.suffix.lower() not in {".html", ".css", ".js", ".json"}:
            continue
        texto = ruta.read_text(encoding="utf-8")
        if MARCADOR in texto:
            # newline="\n" a propósito: lo sirve un servidor web, no lo edita nadie, y en
            # Windows `write_text` a secas lo pasaría a CRLF.
            ruta.write_text(texto.replace(MARCADOR, version), encoding="utf-8", newline="\n")
            escritos.append(ruta)
    return escritos


def comprobar(destino: Path) -> list[Path]:
    """Ficheros del build que TODAVÍA tienen el marcador: si hay alguno, el build miente."""
    return [
        r
        for r in sorted(destino.rglob("*"))
        if r.is_file() and MARCADOR in r.read_text(encoding="utf-8", errors="ignore")
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Construye site/ para GitHub Pages.")
    parser.add_argument("--check", action="store_true", help="solo comprueba, no escribe")
    parser.add_argument(
        "--out", default=str(DESTINO), help=f"directorio de salida (default: {DESTINO})"
    )
    args = parser.parse_args()

    destino = Path(args.out)
    version = version_declarada()

    if args.check:
        if not destino.exists():
            print(f"error: no existe {destino}; construye antes", file=sys.stderr)
            return 1
        pendientes = comprobar(destino)
        if pendientes:
            for r in pendientes:
                print(f"error: {r} conserva {MARCADOR}", file=sys.stderr)
            return 1
        print(f"OK: sin marcadores pendientes en {destino}")
        return 0

    escritos = construir(destino, version)
    print(f"site -> {destino} (versión {version})")
    for r in escritos:
        print(f"  {r.relative_to(destino)}: {MARCADOR} -> {version}")
    if not escritos:
        print(f"aviso: ningún fichero traía {MARCADOR}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
