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
    python scripts/sesiones_de_prueba.py --dia 2026-09-22
    python scripts/sesiones_de_prueba.py --dia 2026-09-22 --salida benchmarks/ventanas-excluidas.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SALIDA_POR_DEFECTO = Path(__file__).parents[1] / "benchmarks" / "ventanas-excluidas.json"


def sesiones_sdk(proyectos: Path, dia: str) -> list[dict]:
    """Sesiones del hilo principal con `entrypoint == "sdk-cli"` que tocaron ese día (UTC)."""
    encontradas: dict[str, dict] = {}
    for transcript in sorted(proyectos.glob("*/*.jsonl")):
        try:
            lineas = transcript.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for linea in lineas:
            try:
                evento = json.loads(linea)
            except json.JSONDecodeError:
                continue
            ts = str(evento.get("timestamp") or "")
            if evento.get("entrypoint") != "sdk-cli" or not ts.startswith(dia):
                continue
            sid = str(evento.get("sessionId") or "")
            if not sid:
                continue
            franja = encontradas.setdefault(sid, {"session_id": sid, "inicio": ts, "fin": ts})
            franja["inicio"] = min(franja["inicio"], ts)
            franja["fin"] = max(franja["fin"], ts)
    return sorted(encontradas.values(), key=lambda f: f["inicio"])


def fusionar(salida: Path, nuevas: list[dict], motivo: str) -> dict:
    datos = {"sesiones": [], "ventanas": []}
    if salida.is_file():
        datos = json.loads(salida.read_text(encoding="utf-8"))
    conocidas = {s["session_id"] for s in datos.get("sesiones", [])}
    for sesion in nuevas:
        if sesion["session_id"] not in conocidas:
            datos.setdefault("sesiones", []).append({**sesion, "motivo": motivo})
    return datos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--dia", required=True, help="AAAA-MM-DD (UTC)")
    parser.add_argument("--proyectos", type=Path, default=Path.home() / ".claude" / "projects")
    parser.add_argument("--salida", type=Path, default=SALIDA_POR_DEFECTO)
    parser.add_argument("--motivo", default="prueba con claude -p en el entorno global")
    args = parser.parse_args(argv)

    nuevas = sesiones_sdk(args.proyectos, args.dia)
    datos = fusionar(args.salida, nuevas, args.motivo)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"{len(nuevas)} sesión(es) sdk-cli el {args.dia}; {len(datos['sesiones'])} en {args.salida}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
