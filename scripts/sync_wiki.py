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
    python scripts/sync_wiki.py <destino>            # escribe las páginas convertidas
    python scripts/sync_wiki.py --check              # solo informa de los enlaces que se convertirían
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

RAIZ = Path(__file__).resolve().parent.parent
ORIGEN = RAIZ / "docs" / "wiki"
REPO_URL = "https://github.com/ZahiriNatZuke/local-delegate"
RAMA = "main"

# `[texto](destino)`. El destino se captura aparte para poder reescribirlo sin tocar el texto.
ENLACE_RE = re.compile(r"(\[[^\]]*\]\()([^)]+)(\))")


def _es_externo(destino: str) -> bool:
    """URLs absolutas, anclas puras y `mailto:` se dejan intactas."""
    return bool(urlsplit(destino).scheme) or destino.startswith(("#", "mailto:"))


def convertir_destino(destino: str) -> str | None:
    """Devuelve la URL absoluta si el enlace se rompería en la wiki, o ``None`` si vale tal cual.

    Solo se tocan los que **salen** de `docs/wiki/`. Un enlace a una página hermana
    (`Daemon.md`) es exactamente lo que la wiki espera y convertirlo a URL absoluta sacaría al
    lector de la wiki en cada clic.
    """
    if _es_externo(destino) or not destino.startswith(".."):
        return None

    ruta, _, ancla = destino.partition("#")
    # La ruta se resuelve contra el directorio de origen y se vuelve relativa a la raíz del repo,
    # que es lo que espera la URL de GitHub. `..` de más saldría del repo: eso es un enlace roto ya
    # en el fuente, y se deja intacto para que se vea en vez de convertirlo en una URL plausible.
    try:
        destino_abs = (ORIGEN / ruta).resolve()
        relativa = destino_abs.relative_to(RAIZ)
    except ValueError:
        return None

    return f"{REPO_URL}/blob/{RAMA}/{relativa.as_posix()}" + (f"#{ancla}" if ancla else "")


def convertir(texto: str) -> tuple[str, list[tuple[str, str]]]:
    """Reescribe los enlaces que se romperían. Devuelve (texto nuevo, [(antes, después)])."""
    cambios: list[tuple[str, str]] = []

    def _sustituir(match: re.Match) -> str:
        destino = match.group(2)
        nuevo = convertir_destino(destino)
        if nuevo is None:
            return match.group(0)
        cambios.append((destino, nuevo))
        return f"{match.group(1)}{nuevo}{match.group(3)}"

    return ENLACE_RE.sub(_sustituir, texto), cambios


def paginas() -> list[Path]:
    return sorted(ORIGEN.glob("*.md"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destino", nargs="?", help="directorio donde escribir las páginas")
    parser.add_argument(
        "--check", action="store_true", help="no escribe: enumera los enlaces que se convertirían"
    )
    args = parser.parse_args(argv)

    if not args.check and not args.destino:
        parser.error("falta el directorio destino (o usa --check)")

    encontradas = paginas()
    if not encontradas:
        print(f"error: no hay páginas en {ORIGEN}", file=sys.stderr)
        return 1

    destino = Path(args.destino) if args.destino else None
    if destino is not None:
        destino.mkdir(parents=True, exist_ok=True)

    total = 0
    for pagina in encontradas:
        texto, cambios = convertir(pagina.read_text(encoding="utf-8"))
        total += len(cambios)
        if cambios:
            print(f"{pagina.name}: {len(cambios)} enlace(s) convertido(s)")
            for antes, despues in cambios:
                print(f"    {antes}  ->  {despues}")
        if destino is not None:
            (destino / pagina.name).write_text(texto, encoding="utf-8")

    print(f"\n{len(encontradas)} páginas, {total} enlaces convertidos.")
    if destino is not None:
        print(f"Escritas en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
