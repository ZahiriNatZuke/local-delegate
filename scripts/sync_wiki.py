#!/usr/bin/env python3
"""Prepara `docs/wiki/` para publicarse como wiki nativa de GitHub.

La wiki de GitHub sirve los `.md` **planos y en otro repositorio**: no hay `docs/`, ni `src/`, ni
un árbol al que subir con `../`. Un enlace como `../recipes/ollama.md` se ve perfecto navegando el
repo y es un **404** en la wiki publicada — la peor combinación, porque el fichero fuente parece
correcto.

Copiar tal cual no vale, entonces. Y cambiar los fuentes a URLs absolutas tampoco: `docs/wiki/`
existe sobre todo para leerse **dentro del repo**, donde los enlaces relativos son lo correcto.
Así que la conversión se hace aquí, al publicar: la fuente queda navegable y la wiki, enlazada.

Medido el 2026-07-31: 18 enlaces en 6 páginas se rompían al publicar.

Solo stdlib, igual que `build_site.py` y `check_vendor.py`: el workflow lo corre sin instalar nada.

Uso:
    python scripts/sync_wiki.py <destination>        # escribe las páginas convertidas
    python scripts/sync_wiki.py --check              # solo informa de los enlaces que se convertirían
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "docs" / "wiki"
REPO_URL = "https://github.com/ZahiriNatZuke/local-delegate"
BRANCH = "main"

# `[texto](destino)`. El destino se captura aparte para poder reescribirlo sin tocar el texto.
LINK_RE = re.compile(r"(\[[^\]]*\]\()([^)]+)(\))")


def _is_external(dest: str) -> bool:
    """URLs absolutas, anclas puras y `mailto:` se dejan intactas."""
    return bool(urlsplit(dest).scheme) or dest.startswith(("#", "mailto:"))


def convert_destination(dest: str) -> str | None:
    """Devuelve la URL absoluta si el enlace se rompería en la wiki, o ``None`` si vale tal cual.

    Solo se tocan los que **salen** de `docs/wiki/`. Un enlace a una página hermana
    (`Daemon.md`) es exactamente lo que la wiki espera y convertirlo a URL absoluta sacaría al
    lector de la wiki en cada clic.
    """
    if _is_external(dest) or not dest.startswith(".."):
        return None

    path, _, anchor = dest.partition("#")
    # La ruta se resuelve contra el directorio de origen y se vuelve relativa a la raíz del repo,
    # que es lo que espera la URL de GitHub. `..` de más saldría del repo: eso es un enlace roto ya
    # en el fuente, y se deja intacto para que se vea en vez de convertirlo en una URL plausible.
    try:
        destination_abs = (SOURCE_DIR / path).resolve()
        relative = destination_abs.relative_to(ROOT)
    except ValueError:
        return None

    return f"{REPO_URL}/blob/{BRANCH}/{relative.as_posix()}" + (f"#{anchor}" if anchor else "")


def convert(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Reescribe los enlaces que se romperían. Devuelve (texto nuevo, [(antes, después)])."""
    changes: list[tuple[str, str]] = []

    def _replace(match: re.Match) -> str:
        dest = match.group(2)
        new = convert_destination(dest)
        if new is None:
            return match.group(0)
        changes.append((dest, new))
        return f"{match.group(1)}{new}{match.group(3)}"

    return LINK_RE.sub(_replace, text), changes


def pages() -> list[Path]:
    return sorted(SOURCE_DIR.glob("*.md"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", nargs="?", help="directorio donde escribir las páginas")
    parser.add_argument(
        "--check", action="store_true", help="no escribe: enumera los enlaces que se convertirían"
    )
    args = parser.parse_args(argv)

    if not args.check and not args.destination:
        parser.error("falta el directorio destino (o usa --check)")

    found = pages()
    if not found:
        print(f"error: no hay páginas en {SOURCE_DIR}", file=sys.stderr)
        return 1

    dest = Path(args.destination) if args.destination else None
    if dest is not None:
        dest.mkdir(parents=True, exist_ok=True)

    total = 0
    for page in found:
        text, changes = convert(page.read_text(encoding="utf-8"))
        total += len(changes)
        if changes:
            print(f"{page.name}: {len(changes)} enlace(s) convertido(s)")
            for before, after in changes:
                print(f"    {before}  ->  {after}")
        if dest is not None:
            (dest / page.name).write_text(text, encoding="utf-8")

    print(f"\n{len(found)} páginas, {total} enlaces convertidos.")
    if dest is not None:
        print(f"Escritas en {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
