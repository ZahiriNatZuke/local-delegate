#!/usr/bin/env python3
"""Hoja de revision humana a ciegas de la tanda de F2 (protocolo-f2.md §4.8).

La puntuacion automatica no decide sola, y la revision es el unico juez que ve lo que el puntuador
no. Si sabe de quien es la respuesta, puntua la expectativa: por eso la hoja sale **barajada y con
el modelo oculto**, y la correspondencia va a un fichero de clave aparte que no se abre hasta haber
puntuado.

- `generar` lee el JSONL (hace falta `--save-responses` en el runner) y escribe la hoja en Markdown
  y la clave en JSON. Entran las corridas de calidad validas: `ok`, no descartadas y sin control de
  entrada. El orden se baraja y los numeros de item se asignan DESPUES, asi que no codifican nada.
- `destapar` lee la hoja puntuada y la clave, y da la puntuacion media por modelo y caso. Un item
  sin puntuar no se ignora: el exit code es 1 y se listan, porque una media sobre la hoja a medias
  parece una medida.

Uso:
    python scripts/hoja_revision.py generar --hoja hoja.md --clave clave.json resultados/*.jsonl
    python scripts/hoja_revision.py destapar --hoja hoja.md --clave clave.json
"""

from __future__ import annotations

import argparse
import json
import random
import re
import secrets
import statistics
import sys
from pathlib import Path
from typing import Any

_ITEM_RE = re.compile(r"^## Item (\d+)\s*$")
_NOTA_RE = re.compile(r"^Puntuacion \(0/1/2\):[ \t]*(\S*)[ \t]*$")


def _registros(rutas: list[Path]) -> list[dict[str, Any]]:
    registros = []
    for ruta in rutas:
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                registros.append(json.loads(linea))
    return registros


def _revisables(registros: list[dict[str, Any]]) -> list[dict[str, Any]]:
    elegidos = [
        r
        for r in registros
        if r.get("kind") == "calidad"
        and r.get("outcome") == "ok"
        and not r.get("descartada")
        and r.get("input_variant") is None
    ]
    sin_respuesta = sorted(
        {f"{r.get('label')}:{r.get('case')}" for r in elegidos if "response" not in r}
    )
    if sin_respuesta:
        raise ValueError(
            "corridas sin respuesta guardada (el runner necesita --save-responses): "
            + ", ".join(sin_respuesta)
        )
    return elegidos


def _valla(texto: str) -> str:
    """Una valla mas larga que cualquier racha de acentos graves de la respuesta."""
    rachas = [len(m) for m in re.findall(r"`+", texto)]
    return "`" * max(3, max(rachas, default=0) + 1)


def generar(
    registros: list[dict[str, Any]], corpus: dict[str, dict[str, Any]] | None, semilla: int
) -> tuple[str, dict[str, Any]]:
    elegidos = _revisables(registros)
    random.Random(semilla).shuffle(elegidos)
    lineas = [
        "# Revision a ciegas",
        "",
        "Puntua cada respuesta con 0 (mal), 1 (a medias) o 2 (bien) contra su fuente, sin abrir la",
        "clave. Escribe el numero detras de «Puntuacion (0/1/2):».",
        "",
    ]
    clave: dict[str, Any] = {"semilla": semilla, "items": {}}
    for numero, registro in enumerate(elegidos, 1):
        item = f"{numero:03d}"
        caso = registro["case"]
        fuente = ((corpus or {}).get(caso) or {}).get("source_file")
        respuesta = str(registro["response"])
        valla = _valla(respuesta)
        lineas += [
            f"## Item {item}",
            "",
            f"Caso: `{caso}`" + (f" · fuente: `fuentes/{fuente}`" if fuente else ""),
            "",
            valla,
            respuesta,
            valla,
            "",
            "Puntuacion (0/1/2): ",
            "",
        ]
        clave["items"][item] = {
            "label": registro.get("label"),
            "model": registro.get("model"),
            "case": caso,
            "role": registro.get("role"),
            "run": registro.get("run"),
            "response_sha256": registro.get("response_sha256"),
        }
    return "\n".join(lineas), clave


def leer_notas(hoja: str) -> dict[str, int | None]:
    """Lee las notas saltandose lo que va dentro de la valla.

    La respuesta la escribio el modelo: si trae una linea «Puntuacion (0/1/2): 2» o «## Item 001»,
    leerla como nota dejaria que un modelo se puntuara a si mismo.
    """
    notas: dict[str, int | None] = {}
    actual: str | None = None
    valla: str | None = None
    for linea in hoja.splitlines():
        if valla is not None:
            if linea == valla:
                valla = None
            continue
        if re.fullmatch(r"`{3,}", linea):
            valla = linea
            continue
        if m := _ITEM_RE.match(linea):
            actual = m.group(1)
            notas[actual] = None
        elif actual is not None and (m := _NOTA_RE.match(linea)):
            valor = m.group(1)
            if valor == "":
                notas[actual] = None
            elif valor in {"0", "1", "2"}:
                notas[actual] = int(valor)
            else:
                raise ValueError(f"item {actual}: puntuacion {valor!r} no es 0, 1 ni 2")
            actual = None
    return notas


def destapar(hoja: str, clave: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    notas = leer_notas(hoja)
    items = clave["items"]
    if set(notas) != set(items):
        raise ValueError(
            "la hoja y la clave no tienen los mismos items: ¿son de la misma generacion?"
        )
    faltan = sorted(item for item, nota in notas.items() if nota is None)
    por_modelo_caso: dict[tuple[str, str], list[int]] = {}
    for item, nota in notas.items():
        if nota is None:
            continue
        meta = items[item]
        por_modelo_caso.setdefault((meta["label"], meta["case"]), []).append(nota)
    resultado = {
        f"{label}|{caso}": {
            "label": label,
            "case": caso,
            "n": len(valores),
            "media": statistics.fmean(valores),
        }
        for (label, caso), valores in sorted(por_modelo_caso.items())
    }
    return resultado, faltan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    sub = parser.add_subparsers(dest="modo", required=True)
    gen = sub.add_parser("generar")
    gen.add_argument("--hoja", type=Path, required=True)
    gen.add_argument("--clave", type=Path, required=True)
    gen.add_argument("--cases", type=Path, default=None, help="cases.json, para citar la fuente")
    gen.add_argument(
        "--semilla", type=int, default=None, help="solo para pruebas; por defecto aleatoria"
    )
    gen.add_argument("jsonl", nargs="+", type=Path)
    des = sub.add_parser("destapar")
    des.add_argument("--hoja", type=Path, required=True)
    des.add_argument("--clave", type=Path, required=True)
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    try:
        if args.modo == "generar":
            if args.clave.exists() or args.hoja.exists():
                # Regenerar baraja otra vez: una hoja ya puntuada quedaria emparejada con otra clave.
                raise ValueError("la hoja o la clave ya existen; elige otras rutas")
            corpus = None
            if args.cases:
                data = json.loads(args.cases.read_text(encoding="utf-8"))
                corpus = {c["id"]: c for c in data["cases"]}
            semilla = args.semilla if args.semilla is not None else secrets.randbits(32)
            hoja, clave = generar(_registros(args.jsonl), corpus, semilla)
            args.hoja.write_text(hoja, encoding="utf-8")
            args.clave.write_text(
                json.dumps(clave, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(
                f"{len(clave['items'])} items en {args.hoja}; la clave en {args.clave} no se abre hasta puntuar"
            )
            return 0
        resultado, faltan = destapar(
            args.hoja.read_text(encoding="utf-8"),
            json.loads(args.clave.read_text(encoding="utf-8")),
        )
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("| Modelo | Caso | Items | Media (0-2) |")
    print("| --- | --- | --- | --- |")
    for fila in resultado.values():
        print(f"| {fila['label']} | {fila['case']} | {fila['n']} | {fila['media']:.2f} |")
    if faltan:
        print(f"\nfaltan por puntuar {len(faltan)} items: {', '.join(faltan)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
