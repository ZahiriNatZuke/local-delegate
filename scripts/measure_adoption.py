#!/usr/bin/env python3
"""Responde, sin cruzar nada a mano, si la regla de delegacion esta funcionando.

Las cuatro mediciones anteriores se hicieron leyendo dos logs por separado y atandolos a ojo, y
por eso la pregunta central —«de los avisos que se dieron, cuantos acabaron en delegacion»— no
tenia respuesta: los dos lados son procesos distintos que escriben en ficheros distintos. Desde
F1 cada aviso y cada bloqueo llevan un identificador que el evento de la tool recoge, asi que el
cruce lo hace el programa.

Cuando la pregunta es «cuantos sitios hay», que la conteste el programa: contar a ojo ya salio
mal una vez en este repo, catorce contra treinta y cuatro.

Las pruebas no cuentan: los eventos de hooks dentro de una ventana de prueba
(`LOG_DIR/test-windows.json`) y las filas del log de uso que la regla comun
(`attribution.test_reason`, con la ventana estampada) marca como prueba se quitan, y la salida dice
cuantas. `--include-tests` las deja.

Uso:
    uv run python scripts/measure_adoption.py                    # desde que arranco el experimento
    uv run python scripts/measure_adoption.py --since 2026-09-12 # una ventana concreta
    uv run python scripts/measure_adoption.py --json             # para pegarlo en una nota
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from local_delegate import attribution, config, cost, legacy_names, test_windows


def hook_telemetry() -> Path:
    dest = os.environ.get("LD_HOOK_TELEMETRY_LOG", "").strip()
    return Path(dest) if dest else Path.home() / ".claude" / "hooks" / "telemetry.jsonl"


def logs_dir() -> Path:
    """`config.LOG_DIR`: el mismo directorio que leen el panel y el daemon, y por tanto el mismo
    `test-windows.json` (test-windows-out-of-metrics, REQ-022). Lo usa tambien
    `measure_cooldown.py`."""
    return config.LOG_DIR


def usage_logs() -> list[Path]:
    return sorted(logs_dir().glob("usage-*.jsonl"))


def read(path: Path, since: str | None) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if since and str(event.get("ts", "")) < since:
            continue
        events.append(event)
    return events


def merged_usages(since: str | None) -> list[dict]:
    """Las filas del log de uso FUNDIDAS como las ve el panel (`cost.merge`): con el `banco` del
    relleno y el `test_window` estampado. Se funde el fichero entero y se filtra despues, porque la
    clave de una fila sin `tool_use_id` depende de su posicion en el fichero."""
    usages = []
    for path in usage_logs():
        # Filas viejas y nuevas al mismo formato (REQ-006): `bloqueo_id` se lee como `block_id`.
        rows = [legacy_names.normalize("usage", e) for e in read(path, None)]
        for e in cost.merge(rows, log_dir=logs_dir()):
            if since and str(e.get("ts", "")) < since:
                continue
            usages.append(e)
    return usages


def measure(since: str | None, include_tests: bool = False) -> dict:
    # Claves y valores viejos (`motivo`, `bloqueo`, `camino`…) y nuevos dan lo mismo (REQ-006).
    hooks = [legacy_names.normalize("hook_telemetry", e) for e in read(hook_telemetry(), since)]
    usages = merged_usages(since)
    outside = {"hooks": 0, "usage": 0}
    applied: list[dict] = []
    if not include_tests:
        windows = test_windows.load(logs_dir())
        applied = [w.to_json() for w in windows.windows]
        before = len(hooks)
        hooks = [e for e in hooks if windows.find(e.get("ts")) is None]
        outside["hooks"] = before - len(hooks)
        before = len(usages)
        usages = [e for e in usages if not attribution.test_reason(e)]
        outside["usage"] = before - len(usages)

    reads = [e for e in hooks if e.get("category") in {"read", "shell"}]
    offered = [e for e in reads if e.get("suggested")]
    blocks = [e for e in offered if e.get("blocked")]

    # «Aceptado» = el identificador del bloqueo aparece en un evento de tool. Sin esto, lo unico
    # medible era «hubo delegaciones», que no dice si las provoco el aviso.
    delegated_ids = {e["block_id"] for e in usages if e.get("block_id")}
    accepted = [b for b in blocks if b.get("id") in delegated_ids]

    # De las lecturas acotadas, cuantas eran de un fichero que en la misma sesion acabo leyendose
    # entero: el criterio escrito ANTES de mirar el dato (REQ-F1-8).
    whole_per_session: dict[tuple, set] = defaultdict(set)
    bands_per_session: dict[tuple, int] = Counter()
    for event in reads:
        key = (event.get("session_id", ""), event.get("path_sha", ""))
        if not key[1]:
            continue  # eventos viejos, sin huella: no se pueden agrupar
        if event.get("reason") == "bounded":
            bands_per_session[key] += 1
        else:
            whole_per_session[key].add(event.get("reason") or "aviso")

    bounded = [c for c, n in bands_per_session.items() if n]
    worth_delegating = [c for c in bounded if c in whole_per_session or bands_per_session[c] >= 3]

    return {
        "window_since": since or "(todo)",
        "sessions": len({e.get("session_id") for e in reads if e.get("session_id")}),
        "script_versions": sorted({e.get("version", "?") for e in reads}),
        "reads": len(reads),
        "by_reason": dict(
            Counter(
                e.get("reason") or ("(ofrecido)" if e.get("suggested") else "(sin motivo)")
                for e in reads
            )
        ),
        "by_path": dict(Counter(e.get("route", "read") for e in reads)),
        "offered": len(offered),
        "blocks": len(blocks),
        "accepted": len(accepted),
        "acceptance_rate": round(len(accepted) / len(blocks), 3) if blocks else None,
        "total_delegations": len([e for e in usages if e.get("tool", "").startswith("local_")]),
        "spontaneous_delegations": len(
            [e for e in usages if e.get("tool", "").startswith("local_") and not e.get("block_id")]
        ),
        "bounded_with_footprint": len(bounded),
        "bounded_worth_delegating": len(worth_delegating),
        "excluded_tests": outside,
        "test_windows": applied,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # `--desde` es el nombre de antes: sigue valiendo, porque así está escrito el comando en la wiki
    # y en el `verification.md` de `delegacion-precisa-y-fiable`.
    parser.add_argument(
        "--since", "--desde", help="fecha ISO; se compara contra el `ts` del evento"
    )
    parser.add_argument("--json", action="store_true", help="salida cruda")
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="no quitar las pruebas (ventanas y regla comun)",
    )
    args = parser.parse_args()

    result = measure(args.since, include_tests=args.include_tests)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"Ventana: {result['window_since']}  ({datetime.now(UTC):%Y-%m-%d %H:%M} UTC)")
    print(f"Sesiones: {result['sessions']} | versiones de script: {result['script_versions']}")
    outside = result["excluded_tests"]
    if args.include_tests:
        print("Pruebas: incluidas (--include-tests)")
    else:
        print(
            f"Pruebas fuera: {outside['hooks']} eventos de hooks y {outside['usage']} filas del log de "
            f"uso ({len(result['test_windows'])} ventanas de prueba en el fichero)"
        )
    print()
    print(f"Lecturas vistas:        {result['reads']}")
    for reason, how_many in sorted(result["by_reason"].items(), key=lambda x: -x[1]):
        print(f"    {reason:20} {how_many}")
    print(f"Por camino:             {result['by_path']}")
    print()
    print(f"Ofrecidos:              {result['offered']}")
    print(f"  de ellos, bloqueos:   {result['blocks']}")
    print(f"  aceptados:            {result['accepted']}  (tasa: {result['acceptance_rate']})")
    print()
    print(f"Delegaciones totales:   {result['total_delegations']}")
    print(f"  espontaneas:          {result['spontaneous_delegations']}")
    print()
    print("Guarda de lectura acotada (REQ-F1-8):")
    print(f"  agrupables por fichero: {result['bounded_with_footprint']}")
    print(f"  convenia delegarlas:    {result['bounded_worth_delegating']}")

    versions = result["script_versions"]
    if "?" in versions:
        print()
        print("AVISO: hay eventos SIN version de script, o sea anteriores a que se registrara.")
        print("Esos no se pueden atribuir a una politica concreta; acota la ventana con --since.")
    if len([v for v in versions if v != "?"]) > 1:
        print()
        print("AVISO: hay mas de una version de script en la ventana. Una sesion abierta hereda")
        print("el entorno del lanzador, asi que la muestra puede mezclar dos politicas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
