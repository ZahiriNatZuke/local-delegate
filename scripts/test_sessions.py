#!/usr/bin/env python3
"""Anota las sesiones `claude -p` de un día para que las mediciones de adopción las excluyan.

Las pruebas con `claude -p` corren con el entorno global del usuario: sus lecturas pasan por los
mismos hooks, escriben en la misma telemetría y sus delegaciones van al mismo log de uso del
daemon. Y casi todas **pedían delegar**, así que meterlas en una línea base inflaría la tasa.
Claude Code marca esas sesiones con `entrypoint == "sdk-cli"` en el transcript; las interactivas
llevan `"cli"`.

Guarda solo `session_id` y la franja horaria de cada sesión, nunca rutas ni contenido. El
resultado se fusiona con lo que ya hubiera en el JSON: el banco de pruebas añade ahí también las
ventanas de sus tandas.

Uso:
    python scripts/test_sessions.py --day 2026-09-22
    python scripts/test_sessions.py --day 2026-09-22 --output benchmarks/excluded-windows.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from local_delegate import legacy_names

DEFAULT_OUTPUT = (
    Path(__file__).parents[1] / "benchmarks" / legacy_names.EXCLUDED_WINDOWS_FILE_NAMES[1]
)
#: El nombre de antes del fichero. Se lee si el nuevo aún no existe; nunca se escribe.
LEGACY_OUTPUT_NAME = legacy_names.EXCLUDED_WINDOWS_FILE_NAMES[0]


def sdk_sessions(projects: Path, day: str) -> list[dict]:
    """Sesiones del hilo principal con `entrypoint == "sdk-cli"` que tocaron ese día (UTC)."""
    found: dict[str, dict] = {}
    for transcript in sorted(projects.glob("*/*.jsonl")):
        try:
            lines = transcript.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = str(event.get("timestamp") or "")
            if event.get("entrypoint") != "sdk-cli" or not ts.startswith(day):
                continue
            sid = str(event.get("sessionId") or "")
            if not sid:
                continue
            band = found.setdefault(sid, {"session_id": sid, "start": ts, "end": ts})
            band["start"] = min(band["start"], ts)
            band["end"] = max(band["end"], ts)
    return sorted(found.values(), key=lambda f: f["start"])


def _load(output: Path) -> dict:
    """Lo que ya hubiera en `output` o, si no existe, en el fichero de antes a su lado, con las
    claves viejas (`sesiones`, `ventanas`, `inicio`, `fin`, `motivo`…) leídas como las nuevas."""
    source = output if output.is_file() else output.with_name(LEGACY_OUTPUT_NAME)
    if not source.is_file():
        return {"sessions": [], "windows": []}
    return legacy_names.normalize_excluded_windows(json.loads(source.read_text(encoding="utf-8")))


def merge(output: Path, new_ones: list[dict], reason: str) -> dict:
    data = _load(output)
    known = {s["session_id"] for s in data.get("sessions", [])}
    for session in new_ones:
        if session["session_id"] not in known:
            data.setdefault("sessions", []).append({**session, "reason": reason})
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--day", required=True, help="AAAA-MM-DD (UTC)")
    parser.add_argument("--projects", type=Path, default=Path.home() / ".claude" / "projects")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--reason", default="prueba con claude -p en el entorno global")
    args = parser.parse_args(argv)

    new_ones = sdk_sessions(args.projects, args.day)
    data = merge(args.output, new_ones, args.reason)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"{len(new_ones)} sesión(es) sdk-cli el {args.day}; {len(data['sessions'])} en {args.output}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
