#!/usr/bin/env python3
"""Mide la ventana entre «decidir» y «llegar» que usa el margen de «cargado con margen» (REQ-013).

Con la afinidad al modelo cargado, el daemon decide con una foto de llama-swap (las tres consultas de
REQ-013, con tope de 1 s) y, al acabar el cálculo, manda la petición. Entre una cosa y otra el TTL
sigue corriendo: si la petición llega tarde, el modelo pudo descargarse. El margen
(`LOCAL_DELEGATE_AFFINITY_MARGIN_S`, 5 s) tiene que cubrir esa ventana **más** el tope de 1 s.

El script lanza un llama-swap v255 de prueba (con un servidor falso como modelo, su propio `store` y
un puerto libre; nunca el real), hace N decisiones simuladas y apunta, para cada una, el tiempo entre
el fin del cálculo (`time.time()`) y la hora a la que la petición **llegó al servidor falso**.

    uv run python scripts/dev/measure_ttl_race.py
    uv run python scripts/dev/measure_ttl_race.py --decisions 200 --concurrency 8

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

log = logging.getLogger("measure_ttl_race")

MODEL = "m-carrera"
QUERY_CAP_S = 1.0  # el tope de REQ-013 para cada consulta
DEFAULT_MARGIN_S = 5.0  # LOCAL_DELEGATE_AFFINITY_MARGIN_S según REQ-013


def percentile(values: list[float], p: float) -> float:
    """Percentil `p` (0-100) por interpolación lineal; `values` no puede estar vacío."""
    sorted_ones = sorted(values)
    if len(sorted_ones) == 1:
        return sorted_ones[0]
    position = (len(sorted_ones) - 1) * p / 100
    low = int(position)
    high = min(low + 1, len(sorted_ones) - 1)
    return sorted_ones[low] + (sorted_ones[high] - sorted_ones[low]) * (position - low)


def one_decision(client: httpx2.Client, url: str, mark: int) -> tuple[float, float]:
    """Las tres consultas de REQ-013 y, al acabar, la petición.

    Devuelve (hora a la que acabó el cálculo, duración del cálculo en s).
    """
    start_ts = time.time()
    client.get(f"{url}/running", timeout=QUERY_CAP_S).raise_for_status()
    with client.stream("GET", f"{url}/api/events", timeout=QUERY_CAP_S) as events:
        for line in events.iter_lines():
            if line.startswith("data:") and json.loads(line[5:])["type"] == "inflight":
                break  # la foto de peticiones en vuelo; se cierra la conexión
    client.get(
        f"{url}/api/metrics/activity", params={"model": MODEL, "limit": 1}, timeout=QUERY_CAP_S
    ).raise_for_status()
    calc_end = time.time()
    body = {"model": MODEL, "messages": [], "mark": mark}
    client.post(f"{url}/v1/chat/completions", json=body, timeout=30).raise_for_status()
    return calc_end, calc_end - start_ts


def measure(decisions: int, concurrency: int, margin: float, directory: Path) -> dict[str, object]:
    from fake_llamaswap import FakeModel, fake_llamaswap

    with fake_llamaswap(directory, [FakeModel(MODEL, ttl=0)]) as ls:
        assert ls.chat(MODEL).status_code == 200  # carga el modelo: se mide con él ya cargado
        decided: dict[int, tuple[float, float]] = {}

        def worker(marks: list[int]) -> None:
            with httpx2.Client() as client:
                for mark in marks:
                    decided[mark] = one_decision(client, ls.url, mark)

        marks = list(range(decisions))
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            # Cada trabajador toma las marcas que le tocan; así `concurrency` decisiones se solapan.
            futures_list = [pool.submit(worker, marks[i::concurrency]) for i in range(concurrency)]
            for future in futures_list:
                future.result()
        arrivals = {
            int(str(x["mark"])): float(str(x["ts"]))
            for x in ls.arrivals(MODEL)
            if x.get("mark") is not None
        }
    windows = [arrivals[m] - decided[m][0] for m in marks]
    calcs = [decided[m][1] for m in marks]
    p99 = percentile(windows, 99)
    return {
        "decisiones": decisions,
        "concurrencia": concurrency,
        "ventana_s": {
            "min": round(min(windows), 4),
            "mediana": round(statistics.median(windows), 4),
            "p99": round(p99, 4),
            "max": round(max(windows), 4),
        },
        "calculo_s": {
            "mediana": round(statistics.median(calcs), 4),
            "p99": round(percentile(calcs, 99), 4),
            "max": round(max(calcs), 4),
        },
        "margen_s": margin,
        "p99_mas_tope_s": round(p99 + QUERY_CAP_S, 4),
        "cabe_en_el_margen": p99 + QUERY_CAP_S <= margin,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", type=int, default=200)
    parser.add_argument(
        "--concurrency", type=int, default=1, help="decisiones que se solapan (el pico real es 8)"
    )
    parser.add_argument("--margin", type=float, default=DEFAULT_MARGIN_S)
    parser.add_argument("--directory", type=Path, default=None, help="por defecto, uno temporal")
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
    from fake_llamaswap import binary_available

    if not binary_available():
        log.error("Falta el llama-swap v255 de prueba")
        return 2
    with tempfile.TemporaryDirectory(prefix="carrera-ttl-") as tmp_dir:
        directory = args.directory or Path(tmp_dir)
        result = measure(args.decisions, args.concurrency, args.margin, directory)
    print(json.dumps(result, indent=2))
    if not result["cabe_en_el_margen"]:
        log.error(
            "p99 + %s s = %s s supera el margen de %s s: hay que subirlo antes de implementar",
            QUERY_CAP_S,
            result["p99_mas_tope_s"],
            args.margin,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
