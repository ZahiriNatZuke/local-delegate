#!/usr/bin/env python3
"""Mide la RAM y la VRAM de un proceso mientras corre un comando: el envoltorio de llama-bench.

`llama-bench` no pasa por el runner de `local-delegate benchmark`, asi que aqui se reutiliza la
misma sonda (`ProcessProbe`) en vez de escribir otra. El proceso se busca por NOMBRE, no por el PID
del comando lanzado: un lanzador intermedio tiene otro PID que el proceso que carga la memoria.

Uso (Windows):

    python scripts/sonda_recursos.py --process llama-bench.exe --output medida.json -- \
        llama-bench.exe -m modelo.gguf -ngl 99

Exit code: el del comando si fallo; 3 si el comando fue bien pero la medida quedo anulada (por
ejemplo, cero muestras); 2 si la sonda no se puede montar; 0 si todo fue bien.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from local_delegate import benchmark


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--process", required=True, help="nombre de imagen, p. ej. llama-bench.exe")
    parser.add_argument("--gpu-luid", default=None, help="sin el, se resuelve contra nvidia-smi")
    parser.add_argument("--interval", type=float, default=0.5, help="segundos entre lecturas")
    parser.add_argument("--output", required=True, help="JSON de salida")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="-- comando a medir")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    probe_factory: Callable[[str, str | None], Any] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        print("error: falta el comando a medir despues de --")
        return 2

    if probe_factory is None:
        if not benchmark.probe_supported():
            print("error: la sonda solo funciona en Windows")
            return 2
        luid = args.gpu_luid or benchmark.resolve_gpu_luid()
        if not luid:
            print("error: LUID de la GPU ambiguo; pasalo con --gpu-luid")
            return 2
        probe = benchmark.ProcessProbe(args.process, luid)
    else:
        probe = probe_factory(args.process, args.gpu_luid)

    started_at = datetime.now(UTC).isoformat()
    started = time.perf_counter()
    try:
        with benchmark.ResourceSampler(probe, args.interval) as sampler:
            returncode = subprocess.run(command, check=False).returncode
    finally:
        probe.close()
    summary = sampler.summary()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "started": started_at,
                "elapsed_s": round(time.perf_counter() - started, 3),
                "process": args.process,
                "gpu_luid": probe.gpu_luid,
                "command": command,
                "exit_code": returncode,
                "resources": summary,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"exit={returncode} muestras={summary['samples']} ram={summary['ram_samples']} "
        f"vram={summary['vram_samples']} annul={summary['annul']}"
    )
    if returncode != 0:
        return returncode
    return 3 if summary["annul"] else 0


if __name__ == "__main__":
    sys.exit(main())
