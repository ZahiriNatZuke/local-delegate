#!/usr/bin/env python3
"""Hoja por pares, a ciegas, para validar la puntuacion automatica contra juicio humano (P-15).

La cobertura de terminos puede medir vocabulario y no correccion: el cuarto piloto de CP-3 vio al
mismo modelo pasar de 1,0 a 0 segun nombrara o describiera, y al 2B puntuar tras contradecir la
fuente. Antes de fiarse de ella en la tanda, se contrasta con la pregunta que §7 decide de verdad:
¿cual de estas dos respuestas es mejor?

- `generar` empareja, por caso, la corrida i de dos configuraciones (solo si las dos son validas y
  puntuadas), sortea que respuesta va como A y cual como B, baraja los pares y numera DESPUES. La
  clave, con los modelos y las puntuaciones automaticas, va a un fichero aparte.
- `destapar` lee las elecciones (A, B o =) y dice, por caso, en cuantos pares la metrica prefiere a
  uno y en cuantos de esos coincide la persona. Un empate humano donde la metrica ve diferencia NO es
  acuerdo: la metrica afirmo algo que la persona no ve. Un caso es valido con al menos
  `MIN_PREFERENCIAS` preferencias de la metrica y `UMBRAL_ACUERDO` de acuerdo; con menos, «sin base».

Uso:
    python scripts/hoja_pares.py generar --hoja pares.md --clave pares-clave.json \\
        --cases benchmarks/catalogo-2026-09/cases.json --pequeno cp3-qwen35-2b \\
        --grande cp3-qwen25-coder-14b --caso resumen-changelog-7k ... resultados/cp3d-*.jsonl
    python scripts/hoja_pares.py destapar --hoja pares.md --clave pares-clave.json
"""

from __future__ import annotations

import argparse
import json
import random
import re
import secrets
import sys
from pathlib import Path
from typing import Any

UMBRAL_ACUERDO = 0.8
MIN_PREFERENCIAS = 3

_PAR_RE = re.compile(r"^## Par (\d+)\s*$")
_ELECCION_RE = re.compile(r"^Mejor \(A/B/=\):[ \t]*(\S*)[ \t]*$")


def _registros(rutas: list[Path]) -> list[dict[str, Any]]:
    registros = []
    for ruta in rutas:
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                registros.append(json.loads(linea))
    return registros


def _valla(texto: str) -> str:
    """Una valla mas larga que cualquier racha de acentos graves de la respuesta."""
    rachas = [len(m) for m in re.findall(r"`+", texto)]
    return "`" * max(3, max(rachas, default=0) + 1)


def _corridas_validas(
    registros: list[dict[str, Any]], label: str, caso: str
) -> dict[int, dict[str, Any]]:
    """El ultimo intento de cada corrida, si es valido y tiene puntuacion automatica."""
    ultimos: dict[int, dict[str, Any]] = {}
    for r in registros:
        if r.get("label") == label and r.get("case") == caso and r.get("input_variant") is None:
            ultimos[int(r["run"])] = r  # el fichero va en orden: el ultimo intento pisa a los otros
    validas = {}
    for run, r in ultimos.items():
        calidad = (r.get("score") or {}).get("quality")
        if r.get("descartada") or calidad is None:
            continue
        if "response" not in r:
            raise ValueError(
                f"{label}:{caso} run {run} sin respuesta guardada (el runner necesita --save-responses)"
            )
        validas[run] = r
    return validas


def generar(
    registros: list[dict[str, Any]],
    corpus: dict[str, dict[str, Any]],
    casos: list[str],
    pequeno: str,
    grande: str,
    semilla: int,
) -> tuple[str, dict[str, Any]]:
    azar = random.Random(semilla)
    pares = []
    for caso in casos:
        a, b = (
            _corridas_validas(registros, pequeno, caso),
            _corridas_validas(registros, grande, caso),
        )
        for run in sorted(set(a) & set(b)):
            pares.append((caso, run, a[run], b[run]))
    if not pares:
        raise ValueError("ningun par valido: ¿etiquetas o casos equivocados?")
    azar.shuffle(pares)
    lineas = [
        "# Comparacion por pares, a ciegas",
        "",
        "En cada par, lee la tarea y las dos respuestas (abre la fuente si hace falta) y escribe detras",
        "de «Mejor (A/B/=):» cual responde MEJOR a la tarea: A, B, o = si no ves diferencia real.",
        "Juzga si es correcta y util para quien la pidio, no si nombra mas cosas. No abras la clave.",
        "",
    ]
    clave: dict[str, Any] = {"semilla": semilla, "pequeno": pequeno, "grande": grande, "pares": {}}
    for numero, (caso, run, reg_p, reg_g) in enumerate(pares, 1):
        par = f"{numero:02d}"
        meta = corpus.get(caso) or {}
        lados = [(pequeno, reg_p), (grande, reg_g)]
        azar.shuffle(lados)
        lineas += [
            f"## Par {par}",
            "",
            f"Tarea: `{meta.get('tool', '?')}` sobre `fuentes/{meta.get('source_file', '?')}`",
            "",
            f"> {meta.get('system') or ''}",
            "",
        ]
        for letra, (_label, reg) in zip("AB", lados, strict=True):
            respuesta = str(reg["response"])
            valla = _valla(respuesta)
            lineas += [f"### Respuesta {letra}", "", valla, respuesta, valla, ""]
        lineas += ["Mejor (A/B/=): ", ""]
        clave["pares"][par] = {
            "case": caso,
            "run": run,
            "A": {"label": lados[0][0], "quality": lados[0][1]["score"]["quality"]},
            "B": {"label": lados[1][0], "quality": lados[1][1]["score"]["quality"]},
        }
    return "\n".join(lineas), clave


def leer_elecciones(hoja: str) -> dict[str, str | None]:
    """Lee las elecciones saltandose lo que va dentro de la valla: la respuesta la escribio un
    modelo, y una linea «Mejor (A/B/=): A» dentro de ella no puede votar por el."""
    elecciones: dict[str, str | None] = {}
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
        if m := _PAR_RE.match(linea):
            actual = m.group(1)
            elecciones[actual] = None
        elif actual is not None and (m := _ELECCION_RE.match(linea)):
            valor = m.group(1).upper()
            if valor == "":
                elecciones[actual] = None
            elif valor in {"A", "B", "="}:
                elecciones[actual] = valor
            else:
                raise ValueError(f"par {actual}: eleccion {m.group(1)!r} no es A, B ni =")
            actual = None
    return elecciones


def destapar(hoja: str, clave: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    elecciones = leer_elecciones(hoja)
    pares = clave["pares"]
    if set(elecciones) != set(pares):
        raise ValueError(
            "la hoja y la clave no tienen los mismos pares: ¿son de la misma generacion?"
        )
    faltan = sorted(par for par, eleccion in elecciones.items() if eleccion is None)
    por_caso: dict[str, dict[str, Any]] = {}
    for par, eleccion in sorted(elecciones.items()):
        if eleccion is None:
            continue
        meta = pares[par]
        fila = por_caso.setdefault(
            meta["case"],
            {"pares": 0, "metrica_prefiere": 0, "acuerdos": 0, "humano": {}},
        )
        fila["pares"] += 1
        ganador_humano = "empate" if eleccion == "=" else meta[eleccion]["label"]
        fila["humano"][ganador_humano] = fila["humano"].get(ganador_humano, 0) + 1
        qa, qb = meta["A"]["quality"], meta["B"]["quality"]
        if qa == qb:
            continue  # la metrica no prefiere: nada que validar en este par
        fila["metrica_prefiere"] += 1
        preferida = "A" if qa > qb else "B"
        if eleccion == preferida:
            fila["acuerdos"] += 1
    for fila in por_caso.values():
        n = fila["metrica_prefiere"]
        fila["acuerdo"] = fila["acuerdos"] / n if n else None
        if n < MIN_PREFERENCIAS:
            fila["veredicto"] = "sin base"
        elif fila["acuerdo"] >= UMBRAL_ACUERDO:
            fila["veredicto"] = "valida"
        else:
            fila["veredicto"] = "no valida"
    return por_caso, faltan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    sub = parser.add_subparsers(dest="modo", required=True)
    gen = sub.add_parser("generar")
    gen.add_argument("--hoja", type=Path, required=True)
    gen.add_argument("--clave", type=Path, required=True)
    gen.add_argument("--cases", type=Path, required=True)
    gen.add_argument("--pequeno", required=True)
    gen.add_argument("--grande", required=True)
    gen.add_argument("--caso", action="append", required=True)
    gen.add_argument("--semilla", type=int, default=None, help="solo para pruebas")
    gen.add_argument("jsonl", nargs="+", type=Path)
    des = sub.add_parser("destapar")
    des.add_argument("--hoja", type=Path, required=True)
    des.add_argument("--clave", type=Path, required=True)
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    try:
        if args.modo == "generar":
            if args.clave.exists() or args.hoja.exists():
                # Regenerar sortea otra vez: una hoja ya elegida quedaria emparejada con otra clave.
                raise ValueError("la hoja o la clave ya existen; elige otras rutas")
            data = json.loads(args.cases.read_text(encoding="utf-8"))
            corpus = {c["id"]: c for c in data["cases"]}
            semilla = args.semilla if args.semilla is not None else secrets.randbits(32)
            hoja, clave = generar(
                _registros(args.jsonl), corpus, args.caso, args.pequeno, args.grande, semilla
            )
            args.hoja.write_text(hoja, encoding="utf-8")
            args.clave.write_text(
                json.dumps(clave, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(f"{len(clave['pares'])} pares en {args.hoja}; la clave no se abre hasta elegir")
            return 0
        resultado, faltan = destapar(
            args.hoja.read_text(encoding="utf-8"),
            json.loads(args.clave.read_text(encoding="utf-8")),
        )
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        "| Caso | Pares | Metrica prefiere | Acuerdos | Acuerdo | Veredicto | Elegido por la persona |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for caso, fila in resultado.items():
        acuerdo = "—" if fila["acuerdo"] is None else f"{fila['acuerdo']:.0%}"
        humano = ", ".join(f"{k}: {v}" for k, v in sorted(fila["humano"].items()))
        print(
            f"| {caso} | {fila['pares']} | {fila['metrica_prefiere']} | {fila['acuerdos']} | "
            f"{acuerdo} | {fila['veredicto']} | {humano} |"
        )
    if faltan:
        print(f"\nfaltan por elegir {len(faltan)} pares: {', '.join(faltan)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
