"""Latencia de los hooks por subcomando (REQ-003: p95 <= 300 ms, 20 invocaciones en Windows).

Lanza cada hook como lo lanza el plugin, `<python> -I -m local_delegate.hook <nombre>`, con el
intérprete que se le pase (por defecto, el del `.venv` del árbol: ni `uv run`, que suma su propio
arranque, ni el `uv tool` instalado). Todo en un directorio temporal: la telemetría, el estado del
interruptor y las notas no tocan los del usuario, y el backend no se sondea (bloqueo apagado).

    uv run python scripts/measure_hook_latency.py [--python RUTA] [--runs 20] [--json]

Sale con 1 si algún p95 pasa del umbral.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THRESHOLD_MS = 300.0


def _default_python() -> Path:
    venv = ROOT / ".venv"
    windows = venv / "Scripts" / "python.exe"
    return windows if windows.exists() else venv / "bin" / "python"


def _percentile(values: list[float], fraction: float) -> float:
    """Percentil por rango más cercano (con 20 muestras, el p95 es la 19.ª)."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _cases(base: Path) -> list[tuple[str, str, dict, bool]]:
    """(etiqueta, hook, entrada, ¿capa «activo» encendida?)."""
    docs = base / "docs"
    docs.mkdir()
    prose = docs / "report.md"
    prose.write_text("Texto de prosa para resumir.\n" * 800, encoding="utf-8")
    read = {"tool_name": "Read", "tool_input": {"file_path": str(prose)}}
    return [
        ("prompt", "prompt", {"prompt": "resume este texto"}, False),
        ("record-call", "record-call", {"tool_use_id": "toolu_latency01"}, False),
        ("read (inactive)", "read", read, False),
        ("read", "read", read, True),
        (
            "mcp-read",
            "mcp-read",
            {"tool_name": "mcp__fs__read_text_file", "tool_input": {"path": str(prose)}},
            True,
        ),
        ("shell", "shell", {"tool_input": {"command": f'cat "{prose}"'}, "cwd": str(base)}, True),
    ]


def measure(python: Path, runs: int) -> list[dict]:
    results = []
    with tempfile.TemporaryDirectory(prefix="ld-hook-latency-") as raw:
        base = Path(raw)
        data, tmp = base / "data", base / "tmp"
        data.mkdir()
        tmp.mkdir()
        env = {
            **os.environ,
            "LOCAL_DELEGATE_LOG_DIR": str(data),
            "LD_HOOK_TELEMETRY_LOG": str(base / "telemetry.jsonl"),
            "LD_HOOK_READ_SWITCH_FILE": str(base / "block-off"),
            "LD_HOOK_READ_BLOCK": "0",
            "TMP": str(tmp),
            "TEMP": str(tmp),
            "TMPDIR": str(tmp),
        }
        env.pop("LD_HOOK_READ_ENABLED", None)
        state = data / "read-hook.json"
        for label, hook, payload, active in _cases(base):
            state.write_text(json.dumps({"active": active, "since": "2026-10-21T00:00:00Z"}))
            stdin = json.dumps({"session_id": "latency", **payload}).encode("utf-8")
            command = [str(python), "-I", "-m", "local_delegate.hook", hook]
            # Una pasada de calentamiento: la primera paga la caché de disco y los .pyc.
            subprocess.run(command, input=stdin, capture_output=True, env=env, timeout=60)
            samples, codes = [], set()
            for _ in range(runs):
                start = time.perf_counter()
                done = subprocess.run(
                    command, input=stdin, capture_output=True, env=env, timeout=60
                )
                samples.append((time.perf_counter() - start) * 1000)
                codes.add(done.returncode)
            results.append(
                {
                    "hook": label,
                    "runs": runs,
                    "p50_ms": round(_percentile(samples, 0.50), 1),
                    "p95_ms": round(_percentile(samples, 0.95), 1),
                    "max_ms": round(max(samples), 1),
                    "exit_codes": sorted(codes),
                }
            )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--python", type=Path, default=_default_python())
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    results = measure(args.python, args.runs)
    if args.json:
        print(json.dumps({"python": str(args.python), "results": results}, indent=2))
    else:
        print(f"python: {args.python}  (umbral p95: {THRESHOLD_MS:.0f} ms)")
        print(f"{'hook':<18}{'p50 ms':>9}{'p95 ms':>9}{'max ms':>9}  exit")
        for row in results:
            print(
                f"{row['hook']:<18}{row['p50_ms']:>9}{row['p95_ms']:>9}{row['max_ms']:>9}  "
                f"{row['exit_codes']}"
            )
    over = [r for r in results if r["p95_ms"] > THRESHOLD_MS or r["exit_codes"] != [0]]
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
