#!/usr/bin/env python3
"""Mide la ventana entre «decidir» y «llegar» que usa el margen de «cargado con margen» (REQ-013).

Con la afinidad al modelo cargado, el daemon decide con una foto de llama-swap (las tres consultas de
REQ-013, con tope de 1 s) y, al acabar el cálculo, manda la petición. Entre una cosa y otra el TTL
sigue corriendo: si la petición llega tarde, el modelo pudo descargarse. El margen
(`LOCAL_DELEGATE_AFINIDAD_MARGEN_S`, 5 s) tiene que cubrir esa ventana **más** el tope de 1 s.

El script lanza un llama-swap v255 de prueba (con un servidor falso como modelo, su propio `store` y
un puerto libre; nunca el real), hace N decisiones simuladas y apunta, para cada una, el tiempo entre
el fin del cálculo (`time.time()`) y la hora a la que la petición **llegó al servidor falso**.

    uv run python scripts/dev/medir_carrera_ttl.py
    uv run python scripts/dev/medir_carrera_ttl.py --decisiones 200 --concurrencia 8

Sale con 0 si `p99 + 1 s` cabe en el margen y con 1 si no (entonces hay que subir el margen antes de
implementar la afinidad). Los números van a stdout; el registro, a stderr.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx2

log = logging.getLogger("medir_carrera_ttl")

MODELO = "m-carrera"
TOPE_CONSULTA_S = 1.0  # el tope de REQ-013 para cada consulta
MARGEN_POR_DEFECTO_S = 5.0  # LOCAL_DELEGATE_AFINIDAD_MARGEN_S según REQ-013


def percentil(valores: list[float], p: float) -> float:
    """Percentil `p` (0-100) por interpolación lineal; `valores` no puede estar vacío."""
    ordenados = sorted(valores)
    if len(ordenados) == 1:
        return ordenados[0]
    posicion = (len(ordenados) - 1) * p / 100
    bajo = int(posicion)
    alto = min(bajo + 1, len(ordenados) - 1)
    return ordenados[bajo] + (ordenados[alto] - ordenados[bajo]) * (posicion - bajo)


def una_decision(cliente: httpx2.Client, url: str, marca: int) -> tuple[float, float]:
    """Las tres consultas de REQ-013 y, al acabar, la petición.

    Devuelve (hora a la que acabó el cálculo, duración del cálculo en s).
    """
    inicio = time.time()
    cliente.get(f"{url}/running", timeout=TOPE_CONSULTA_S).raise_for_status()
    with cliente.stream("GET", f"{url}/api/events", timeout=TOPE_CONSULTA_S) as eventos:
        for linea in eventos.iter_lines():
            if linea.startswith("data:") and json.loads(linea[5:])["type"] == "inflight":
                break  # la foto de peticiones en vuelo; se cierra la conexión
    cliente.get(
        f"{url}/api/metrics/activity", params={"model": MODELO, "limit": 1}, timeout=TOPE_CONSULTA_S
    ).raise_for_status()
    fin_del_calculo = time.time()
    cuerpo = {"model": MODELO, "messages": [], "marca": marca}
    cliente.post(f"{url}/v1/chat/completions", json=cuerpo, timeout=30).raise_for_status()
    return fin_del_calculo, fin_del_calculo - inicio


def medir(decisiones: int, concurrencia: int, margen: float, directorio: Path) -> dict[str, object]:
    from llamaswap_de_prueba import ModeloPrueba, llamaswap_de_prueba

    with llamaswap_de_prueba(directorio, [ModeloPrueba(MODELO, ttl=0)]) as ls:
        assert ls.chat(MODELO).status_code == 200  # carga el modelo: se mide con él ya cargado
        decididas: dict[int, tuple[float, float]] = {}

        def trabajador(marcas: list[int]) -> None:
            with httpx2.Client() as cliente:
                for marca in marcas:
                    decididas[marca] = una_decision(cliente, ls.url, marca)

        marcas = list(range(decisiones))
        with ThreadPoolExecutor(max_workers=concurrencia) as pool:
            # Cada trabajador toma las marcas que le tocan; así `concurrencia` decisiones se solapan.
            futuros = [
                pool.submit(trabajador, marcas[i::concurrencia]) for i in range(concurrencia)
            ]
            for futuro in futuros:
                futuro.result()
        llegadas = {
            int(str(x["marca"])): float(str(x["ts"]))
            for x in ls.llegadas(MODELO)
            if x.get("marca") is not None
        }
    ventanas = [llegadas[m] - decididas[m][0] for m in marcas]
    calculos = [decididas[m][1] for m in marcas]
    p99 = percentil(ventanas, 99)
    return {
        "decisiones": decisiones,
        "concurrencia": concurrencia,
        "ventana_s": {
            "min": round(min(ventanas), 4),
            "mediana": round(statistics.median(ventanas), 4),
            "p99": round(p99, 4),
            "max": round(max(ventanas), 4),
        },
        "calculo_s": {
            "mediana": round(statistics.median(calculos), 4),
            "p99": round(percentil(calculos, 99), 4),
            "max": round(max(calculos), 4),
        },
        "margen_s": margen,
        "p99_mas_tope_s": round(p99 + TOPE_CONSULTA_S, 4),
        "cabe_en_el_margen": p99 + TOPE_CONSULTA_S <= margen,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisiones", type=int, default=200)
    parser.add_argument(
        "--concurrencia", type=int, default=1, help="decisiones que se solapan (el pico real es 8)"
    )
    parser.add_argument("--margen", type=float, default=MARGEN_POR_DEFECTO_S)
    parser.add_argument("--directorio", type=Path, default=None, help="por defecto, uno temporal")
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )
    # La fixture vive en `tests/`, que no es un paquete: se añade a la ruta de importación.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
    from llamaswap_de_prueba import binario_disponible

    if not binario_disponible():
        log.error("Falta el llama-swap v255 de prueba")
        return 2
    with tempfile.TemporaryDirectory(prefix="carrera-ttl-") as temporal:
        directorio = args.directorio or Path(temporal)
        resultado = medir(args.decisiones, args.concurrencia, args.margen, directorio)
    print(json.dumps(resultado, indent=2))
    if not resultado["cabe_en_el_margen"]:
        log.error(
            "p99 + %s s = %s s supera el margen de %s s: hay que subirlo antes de implementar",
            TOPE_CONSULTA_S,
            resultado["p99_mas_tope_s"],
            args.margen,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
