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

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "site"
DESTINATION = ROOT / "_site"
MARKER = "__LD_VERSION__"

# Ficheros que viven en `site/` pero NO se publican: son la fuente revisable de un artefacto
# (hoy, el HTML del que sale `og-image.png`), no una página del sitio. Es el mismo criterio por
# el que se publica `site/` y no `docs/`: nada llega a una URL pública sin que se haya decidido.
SOURCE_SUFFIX = ".src.html"


def declared_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def build(dest: Path, version: str) -> list[Path]:
    """Copia `site/` sustituyendo el marcador. Devuelve los ficheros escritos."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(SOURCE_DIR, dest, ignore=shutil.ignore_patterns(f"*{SOURCE_SUFFIX}"))

    written: list[Path] = []
    for path in sorted(dest.rglob("*")):
        # `.webmanifest` es JSON con otra extensión. Entra en la lista aunque hoy no traiga el
        # marcador: si algún día lo trae, `comprobar()` lo vería pendiente y tumbaría el deploy.
        replaceable = {".html", ".css", ".js", ".json", ".webmanifest"}
        if not path.is_file() or path.suffix.lower() not in replaceable:
            continue
        text = path.read_text(encoding="utf-8")
        if MARKER in text:
            # newline="\n" a propósito: lo sirve un servidor web, no lo edita nadie, y en
            # Windows `write_text` a secas lo pasaría a CRLF.
            path.write_text(text.replace(MARKER, version), encoding="utf-8", newline="\n")
            written.append(path)
    return written


def check(dest: Path) -> list[Path]:
    """Ficheros del build que TODAVÍA tienen el marcador: si hay alguno, el build miente."""
    return [
        r
        for r in sorted(dest.rglob("*"))
        if r.is_file() and MARKER in r.read_text(encoding="utf-8", errors="ignore")
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Construye site/ para GitHub Pages.")
    parser.add_argument("--check", action="store_true", help="solo comprueba, no escribe")
    parser.add_argument(
        "--out", default=str(DESTINATION), help=f"directorio de salida (default: {DESTINATION})"
    )
    args = parser.parse_args()

    dest = Path(args.out)
    version = declared_version()

    if args.check:
        if not dest.exists():
            print(f"error: no existe {dest}; construye antes", file=sys.stderr)
            return 1
        pending = check(dest)
        if pending:
            for r in pending:
                print(f"error: {r} conserva {MARKER}", file=sys.stderr)
            return 1
        print(f"OK: sin marcadores pendientes en {dest}")
        return 0

    written = build(dest, version)
    print(f"site -> {dest} (versión {version})")
    for r in written:
        print(f"  {r.relative_to(dest)}: {MARKER} -> {version}")
    if not written:
        print(f"aviso: ningún fichero traía {MARKER}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
